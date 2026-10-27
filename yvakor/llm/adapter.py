"""Interface única para qualquer provider de LLM (OpenAI-compatible)."""
from __future__ import annotations
import os
import re
import json
import urllib.error
import urllib.request


class ProviderErro(RuntimeError):
    """Falha de um provider. `fatal` = não adianta tentar de novo agora
    (sem saldo/credencial inválida: HTTP 401/402/403) — o roteador usa isso
    para pular o provider por um bom tempo em vez de errar a cada passo."""

    def __init__(self, msg: str, codigo: int | None = None,
                 fatal: bool = False):
        super().__init__(msg)
        self.codigo = codigo
        self.fatal = fatal


class LLMProvider:
    """Provider genérico estilo OpenAI chat/completions.
    Funciona com DeepSeek (api.deepseek.com) e Ollama (modo /v1)."""

    def __init__(self, name: str, base_url: str, model: str,
                 api_key: str | None = None,
                 temperature: float = 0.3, max_tokens: int = 4096,
                 timeout: float = 120, num_thread: int | None = None,
                 keep_alive: str = "5m"):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        # Só para o Ollama: limita as threads de inferência (deixa núcleo(s)
        # livre(s) p/ a interface). O endpoint /v1 compatível com OpenAI ignora
        # `num_thread`, então com isso definido usamos a API nativa /api/chat.
        self.num_thread = num_thread
        self.keep_alive = keep_alive

    def _url(self) -> str:
        return (f"{self.base_url}/v1/chat/completions"
                if "ollama" in self.name or "11434" in self.base_url
                else f"{self.base_url}/chat/completions")

    def _post_bruto(self, url: str, payload: dict,
                    timeout: float | None = None) -> dict:
        """POST + parse. Levanta ERRO em qualquer falha (HTTP, rede, payload de
        erro com 200) para que o roteador caia no próximo provider (ex.: o
        local). Antes, HTTPError perdia o corpo e {"error":...} com 200 não
        disparava o fallback."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                bruto = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            corpo = ""
            try:
                corpo = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise ProviderErro(
                f"{self.name} HTTP {exc.code}: {corpo or exc.reason}",
                codigo=exc.code, fatal=exc.code in (401, 402, 403)) from exc
        except urllib.error.URLError as exc:
            raise ProviderErro(f"{self.name} indisponível: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderErro(
                f"{self.name} não respondeu em {timeout or self.timeout:.0f}s") from exc
        try:
            data = json.loads(bruto)
        except Exception as exc:
            raise RuntimeError(f"{self.name}: resposta não-JSON") from exc
        # Alguns provedores devolvem erro com HTTP 200 (ex.: saldo esgotado).
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise ProviderErro(
                f"{self.name}: {msg}",
                fatal=bool(re.search(
                    r"insufficient|balance|quota|payment|saldo|credit",
                    str(msg), re.I)))
        return data

    def _post(self, payload: dict, timeout: float | None = None) -> dict:
        """Endpoint OpenAI-compatível (DeepSeek e Ollama /v1)."""
        data = self._post_bruto(self._url(), payload, timeout)
        if not (data.get("choices")):
            raise ProviderErro(f"{self.name}: resposta sem 'choices'")
        return data

    def _chat_ollama_nativo(self, messages: list[dict], timeout: float | None,
                            max_tokens: int | None) -> str:
        """API nativa do Ollama (/api/chat): aceita `num_thread` e `keep_alive`.
        Medido neste PC (4 núcleos): 4 threads = 7,7 tok/s; 3 threads = 7,2
        tok/s (-6%) — deixar um núcleo livre custa pouco e evita que a máquina
        inteira engasgue enquanto o modelo gera."""
        data = self._post_bruto(f"{self.base_url}/api/chat", {
            "model": self.model, "messages": messages, "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature,
                        "num_predict": max_tokens or self.max_tokens,
                        "num_thread": self.num_thread}}, timeout)
        return (data.get("message") or {}).get("content") or ""

    def chat(self, system: str, user: str) -> str:
        return self.chat_messages([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])

    def chat_tools(self, messages: list[dict], tools: list[dict],
                   tool_choice: str = "auto") -> dict:
        """Chamada com function calling nativo; devolve a mensagem do modelo."""
        data = self._post({"model": self.model, "temperature": self.temperature,
                           "max_tokens": self.max_tokens, "messages": messages,
                           "tools": tools, "tool_choice": tool_choice})
        return data["choices"][0]["message"]

    def chat_messages(self, messages: list[dict], timeout: float | None = None,
                      max_tokens: int | None = None) -> str:
        """Completa a partir de uma lista de mensagens (multi-turno).
        `timeout`/`max_tokens` sobrescrevem o padrão do provider só nesta chamada
        (ex.: o agente local precisa de muito mais tempo que a resposta rápida)."""
        if self.num_thread:
            conteudo = self._chat_ollama_nativo(messages, timeout, max_tokens)
        else:
            data = self._post({
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": max_tokens or self.max_tokens,
                "messages": messages,
            }, timeout=timeout)
            conteudo = (data["choices"][0].get("message") or {}).get("content")
        if not (conteudo and conteudo.strip()):
            # Resposta vazia conta como falha → o roteador tenta o próximo
            # provider (o local), em vez de devolver "" ao agente.
            raise ProviderErro(f"{self.name}: resposta vazia")
        return conteudo


def build_provider(name: str, cfg: dict) -> LLMProvider:
    api_key = None
    if "api_key_env" in cfg:
        api_key = os.environ.get(cfg["api_key_env"])
    return LLMProvider(
        name=name,
        base_url=cfg["base_url"],
        model=cfg["model"],
        api_key=api_key,
        temperature=cfg.get("temperature", 0.3),
        max_tokens=cfg.get("max_tokens", 4096),
        timeout=float(cfg.get("timeout_s", 120)),
        num_thread=(_threads_ollama(cfg) if _eh_ollama(name, cfg) else None),
        keep_alive=str(cfg.get("keep_alive", "5m")),
    )


def _eh_ollama(name: str, cfg: dict) -> bool:
    return "ollama" in name or "11434" in str(cfg.get("base_url", ""))


def _threads_ollama(cfg: dict) -> int | None:
    """num_thread do modelo local: "auto" = núcleos-1 (em máquinas com 4+),
    número = fixo, 0/false = desligado (usa o endpoint /v1 e as threads padrão)."""
    valor = cfg.get("num_thread", "auto")
    if valor in (0, False, None, "0", "off"):
        return None
    if isinstance(valor, int) or str(valor).isdigit():
        return max(1, int(valor))
    nucleos = os.cpu_count() or 1
    return nucleos - 1 if nucleos >= 4 else None
