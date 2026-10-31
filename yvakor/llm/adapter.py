"""Interface única para qualquer provider de LLM (OpenAI-compatible)."""
from __future__ import annotations
import os
import re
import json
import urllib.error
import threading
import urllib.request
import logging

_log = logging.getLogger(__name__)


class ProviderErro(RuntimeError):
    """Falha de um provider. `fatal` = não adianta tentar de novo agora
    (sem saldo/credencial inválida: HTTP 401/402/403) — o roteador usa isso
    para pular o provider por um bom tempo em vez de errar a cada passo."""

    def __init__(self, msg: str, codigo: int | None = None,
                 fatal: bool = False, espera_s: float | None = None):
        super().__init__(msg)
        self.codigo = codigo
        self.fatal = fatal
        self.espera_s = espera_s      # Retry-After do HTTP 429/503, se a API informou


class LLMProvider:
    """Provider genérico estilo OpenAI chat/completions.
    Funciona com DeepSeek (api.deepseek.com) e Ollama (modo /v1)."""

    def __init__(self, name: str, base_url: str, model: str,
                 api_key: str | None = None,
                 temperature: float = 0.3, max_tokens: int = 4096,
                 timeout: float = 120, num_thread: int | None = None,
                 keep_alive: str = "5m", num_ctx: int | None = None,
                 extra: dict | None = None, precisa_chave: bool = False,
                 modelos_reserva: list[str] | None = None):
        self.name = name
        # Campos a mais no corpo da requisição, específicos do provedor (ex.:
        # Gemini: reasoning_effort, para o "pensamento" não comer o teto de saída).
        self.extra = dict(extra or {})
        # Provedor de nuvem que só funciona com chave: sem ela fica fora da
        # rota (senão cada tarefa levava um 401 e 30 min de cooldown).
        self.precisa_chave = precisa_chave
        self.modelos_reserva: list[str] = list(modelos_reserva or [])
        self.modelo_usado = model
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
        # Janela de contexto do Ollama: o padrão (2048/4096) CORTA o começo do
        # prompt em silêncio (some o system). Fixar evita isso.
        self.num_ctx = num_ctx
        self._tl = threading.local()

    @property
    def ultimo_uso(self) -> dict | None:
        """Tokens REAIS da última chamada desta thread: {prompt, saida, cache, finish}."""
        return getattr(self._tl, "uso", None)

    def _anotar_uso(self, data: dict) -> None:
        u = data.get("usage") or {}
        if not u and "prompt_eval_count" in data:          # Ollama nativo
            self._tl.uso = {"prompt": int(data.get("prompt_eval_count") or 0),
                            "saida": int(data.get("eval_count") or 0), "cache": 0,
                            "finish": data.get("done_reason")}
            return
        ch = (data.get("choices") or [{}])[0]
        self._tl.uso = {
            "prompt": int(u.get("prompt_tokens") or 0),
            "saida": int(u.get("completion_tokens") or 0),
            # DeepSeek: prompt_cache_hit_tokens; OpenAI: prompt_tokens_details.cached_tokens
            "cache": int(u.get("prompt_cache_hit_tokens")
                         or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            "finish": ch.get("finish_reason")}

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
            inteiro = ""
            try:
                inteiro = exc.read().decode("utf-8", "replace")
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            corpo = inteiro[:300]
            espera = None
            try:
                ra = exc.headers.get("Retry-After") if exc.headers else None
                espera = float(ra) if ra else None
            except (TypeError, ValueError):
                espera = None
            fatal = exc.code in (401, 402, 403)
            if exc.code == 429:
                # Gemini (plano grátis): limite por minuto vem com "retryDelay"
                # no corpo, depois dos 300 primeiros caracteres; a cota do DIA
                # esgotada ("PerDay") não volta em segundos.
                m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', inteiro)
                if m and espera is None:
                    espera = float(m.group(1))
                fatal = "PerDay" in inteiro
            raise ProviderErro(
                f"{self.name} HTTP {exc.code}: {corpo or exc.reason}",
                codigo=exc.code, fatal=fatal, espera_s=espera) from exc
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

    # O Gemini 3 devolve cada chamada de ferramenta com uma "thought_signature"
    # (em extra_content.google) e exige que ela volte no histórico. Quando a
    # tarefa começou em outro provedor (fallback DeepSeek → Gemini no meio),
    # as chamadas antigas não têm assinatura: o Google aceita este valor
    # neutro para histórico vindo de outro modelo.
    ASSINATURA_NEUTRA = "skip_thought_signature_validator"

    def _eh_google(self) -> bool:
        return "googleapis.com" in self.base_url

    def _mensagens_para_o_provedor(self, messages: list[dict]) -> list[dict]:
        """Ajusta as chamadas de ferramenta do histórico para este provedor:
        no Gemini, completa a assinatura que falta; nos outros, tira o campo
        extra_content que só o Google entende."""
        google = self._eh_google()
        saida = []
        for m in messages:
            chamadas = m.get("tool_calls") if isinstance(m, dict) else None
            if not chamadas:
                saida.append(m)
                continue
            novas = []
            for tc in chamadas:
                if not isinstance(tc, dict):
                    novas.append(tc)
                elif google and not ((tc.get("extra_content") or {}).get("google") or {}).get(
                        "thought_signature"):
                    novas.append({**tc, "extra_content": {"google": {
                        "thought_signature": self.ASSINATURA_NEUTRA}}})
                elif not google and "extra_content" in tc:
                    novas.append({k: v for k, v in tc.items() if k != "extra_content"})
                else:
                    novas.append(tc)
            saida.append({**m, "tool_calls": novas})
        return saida

    def _post(self, payload: dict, timeout: float | None = None) -> dict:
        """Endpoint OpenAI-compatível (DeepSeek, Gemini e Ollama /v1).
        Com `modelos_reserva`, um modelo sobrecarregado (503) ou desativado
        (404) cede a vez ao próximo do MESMO provedor (no Gemini, em 28/10,
        quase todos os Flash davam 503 e só os "lite" respondiam)."""
        if isinstance(payload.get("messages"), list):
            payload = {**payload, "messages": self._mensagens_para_o_provedor(payload["messages"])}
        modelos = [payload.get("model") or self.model] + [
            m for m in self.modelos_reserva if m != payload.get("model")]
        for i, modelo in enumerate(modelos):
            try:
                data = self._post_bruto(self._url(), {**payload, "model": modelo}, timeout)
                break
            except ProviderErro as exc:
                if exc.codigo not in (404, 503) or i == len(modelos) - 1:
                    raise
        self.modelo_usado = modelo
        if not (data.get("choices")):
            raise ProviderErro(f"{self.name}: resposta sem 'choices'")
        self._anotar_uso(data)
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
            "options": {k: v for k, v in {
                "temperature": self.temperature,
                "num_predict": max_tokens or self.max_tokens,
                "num_thread": self.num_thread,
                "num_ctx": self.num_ctx}.items() if v is not None}}, timeout)
        self._anotar_uso(data)
        return (data.get("message") or {}).get("content") or ""

    def chat(self, system: str, user: str) -> str:
        return self.chat_messages([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])

    # ------------------------------------------------------------------ #
    # Guarda contra resposta cortada (finish_reason "length"): o usuário via
    # a resposta parar no meio da frase e chamadas de ferramenta chegavam com
    # os argumentos truncados. 1) refaz com o teto do provedor; 2) se ainda
    # assim cortar, pede a continuação e emenda (no máximo MAX_CONTINUACOES).
    # ------------------------------------------------------------------ #
    MAX_CONTINUACOES = 2
    PEDIDO_CONTINUAR = ("Sua resposta anterior foi cortada pelo limite de tamanho. "
                        "Continue EXATAMENTE de onde parou (mesmo no meio da "
                        "palavra), sem repetir nada e sem introdução.")

    def _cortada(self) -> bool:
        # Só na nuvem: no modelo local o teto curto é proposital (cada token
        # custa segundos) e refazer travaria a máquina.
        local = bool(self.num_thread) or "ollama" in self.name or "11434" in self.base_url
        return not local and (self.ultimo_uso or {}).get("finish") in ("length", "max_tokens")

    def ping(self, timeout: float = 10) -> None:
        """Teste barato de que o provedor responde (chave, saldo, rede).
        Não passa pela guarda de resposta cortada nem exige conteúdo: com
        max_tokens=1 a resposta é sempre "cortada" (e o Gemini, que pensa
        antes, devolve texto vazio) — antes isso refazia o teste com o teto
        cheio ou punha o provedor em cooldown por "resposta vazia"."""
        if self.num_thread:
            self._chat_ollama_nativo([{"role": "user", "content": "ok"}], timeout, 1)
            return
        self._post({**self.extra, "model": self.model, "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ok"}]}, timeout=timeout)

    def _acumular(self, antes: dict | None) -> None:
        """Soma o uso das chamadas extras ao da primeira (custo real)."""
        agora = self._tl.uso or {}
        if antes:
            self._tl.uso = {**agora, **{k: int(antes.get(k) or 0) + int(agora.get(k) or 0)
                                        for k in ("prompt", "saida", "cache")}}

    def _gerar(self, messages: list[dict], timeout: float | None,
               max_tokens: int | None) -> str:
        if self.num_thread:
            return self._chat_ollama_nativo(messages, timeout, max_tokens)
        data = self._post({
            **self.extra,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": messages,
        }, timeout=timeout)
        return (data["choices"][0].get("message") or {}).get("content") or ""

    def _continuar(self, messages: list[dict], parcial: str,
                   timeout: float | None) -> str:
        texto = parcial
        for _ in range(self.MAX_CONTINUACOES):
            if not self._cortada():
                break
            antes = self._tl.uso
            resto = self._gerar(messages + [
                {"role": "assistant", "content": texto},
                {"role": "user", "content": self.PEDIDO_CONTINUAR}], timeout, self.max_tokens)
            self._acumular(antes)
            if not resto.strip():
                break
            texto += resto
        return texto

    def chat_tools(self, messages: list[dict], tools: list[dict],
                   tool_choice: str = "auto", max_tokens: int | None = None) -> dict:
        """Chamada com function calling nativo; devolve a mensagem do modelo."""
        self._tl.uso = None
        payload = {**self.extra, "model": self.model, "temperature": self.temperature,
                   "max_tokens": max_tokens or self.max_tokens, "messages": messages,
                   "tools": tools, "tool_choice": tool_choice}
        data = self._post(payload)
        if self._cortada() and payload["max_tokens"] < self.max_tokens:
            antes = self._tl.uso
            data = self._post({**payload, "max_tokens": self.max_tokens})
            self._acumular(antes)
        msg = data["choices"][0]["message"]
        if self._cortada() and not msg.get("tool_calls") and (msg.get("content") or "").strip():
            msg = {**msg, "content": self._continuar(messages, msg["content"], None)}
        return msg

    def chat_messages(self, messages: list[dict], timeout: float | None = None,
                      max_tokens: int | None = None) -> str:
        """Completa a partir de uma lista de mensagens (multi-turno).
        `timeout`/`max_tokens` sobrescrevem o padrão do provider só nesta chamada
        (ex.: o agente local precisa de muito mais tempo que a resposta rápida)."""
        self._tl.uso = None
        conteudo = self._gerar(messages, timeout, max_tokens)
        if self._cortada() and max_tokens and max_tokens < self.max_tokens:
            antes = self._tl.uso
            conteudo = self._gerar(messages, timeout, self.max_tokens)
            self._acumular(antes)
        if self._cortada() and conteudo.strip():
            conteudo = self._continuar(messages, conteudo, timeout)
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
        num_ctx=(int(cfg["num_ctx"]) if cfg.get("num_ctx") else None),
        extra=cfg.get("extra") if isinstance(cfg.get("extra"), dict) else None,
        precisa_chave="api_key_env" in cfg,
        modelos_reserva=[str(m) for m in cfg.get("modelos_reserva") or []],
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
