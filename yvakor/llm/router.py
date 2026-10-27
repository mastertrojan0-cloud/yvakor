"""Roteador: decide qual provider atende cada tipo de tarefa.
É aqui que a independência de IA externa acontece gradualmente:
mova categorias de 'external' para 'local' no settings.yaml."""
from __future__ import annotations
import json
import logging
import re
import threading
import time

from yvakor.config import ROOT
from yvakor.llm.adapter import build_provider

# Modos de uso do modelo (escolhidos pelo usuário, salvos em preferencias.json).
MODOS = {
    "local": {
        "rotulo": "Local",
        "descricao": "Só o modelo local (Ollama). Nunca chama a nuvem."},
    "auto": {
        "rotulo": "Automático",
        "descricao": "Local primeiro; DeepSeek nas tarefas mais profundas."},
    "deepseek": {
        "rotulo": "DeepSeek",
        "descricao": "DeepSeek primeiro; o local entra se ele falhar."},
}
MODO_PADRAO = "local"
ARQ_PREFS = ROOT / "data" / "preferencias.json"

_log = logging.getLogger("yvakor.llm")
# Erros em que insistir não adianta (sem saldo / credencial inválida).
_FATAL = re.compile(
    r"\b(401|402|403)\b|payment|insufficient|balance|quota|saldo|credit|"
    r"unauthorized|invalid api key|authentication", re.I)

KEYWORDS = {    "codigo": ["código", "codigo", "script", "função", "bug", "erro", "python",
               "javascript", "api", "sql", "implementa"],
    "prospeccao": ["cliente", "prospec", "proposta", "lead", "orçamento", "venda"],
    "pesquisa_sintese": ["pesquise", "pesquisa", "compare", "mercado", "tendência"],
    "analise_complexa": ["analise", "análise", "arquitetura", "planeje", "estratégia"],
    "resumo_curto": ["resuma", "resumo", "tldr"],
    "classificacao": ["classifique", "categorize"],
    "geracao_imagem": ["imagem", "imagens", "foto", "ilustração", "arte", "desenho",
                       "gerar imagem", "cria imagem", "gera imagem", "criar imagem",
                       "faça uma imagem", "gerar foto", "criar arte", "renderizar",
                       "image", "generate image", "picture", "draw"],
}


# Verbos de ação: exigem modelo forte (ferramentas, navegador, arquivos).
# Mensagens curtas sem ação vão para o modelo local (economia de API).
ACOES = ("abra", "abrir", "crie", "criar", "list", "edit", "apag", "mova",
         "mover", "copi", "baix", "instal", "execut", "rodar", "rode",
         "grav", "tire", "tirar", "ligu", "ligar", "deslig", "envi", "salv",
         "pesquis", "naveg", "clic", "preench", "analis", "compare",
         "organiz", "corrija", "refator", "implement")


class LLMRouter:
    def __init__(self, settings: dict):
        self.settings = settings
        llm = settings["llm"]
        self.providers = {name: build_provider(name, cfg)
                          for name, cfg in llm["providers"].items()}
        self.routing = llm["routing"]
        self.default = llm["default_provider"]
        # Circuit breaker por provider: nome -> instante até o qual é pulado.
        self._cooldown: dict[str, float] = {}
        self._probe_ok_ate = 0.0
        self._lock = threading.Lock()
        # Modo escolhido pelo usuário (preferência salva) > settings > padrão.
        padrao = str(llm.get("modo_padrao") or MODO_PADRAO).lower()
        self.modo = padrao if padrao in MODOS else MODO_PADRAO
        salvo = str(self._ler_pref("modelo_modo") or "").lower()
        if salvo in MODOS:
            self.modo = salvo
        local = self._ler_pref("modelo_local")
        if local and "ollama" in self.providers:
            self.providers["ollama"].model = str(local)

    # ------------------------------------------------------------------ #
    # Escolha do modelo (persistida)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _ler_pref(chave: str):
        try:
            return json.loads(ARQ_PREFS.read_text(encoding="utf-8")).get(chave)
        except Exception:
            return None

    def _gravar_pref(self, chave: str, valor) -> None:
        with self._lock:
            try:
                dados = json.loads(ARQ_PREFS.read_text(encoding="utf-8"))
                if not isinstance(dados, dict):
                    dados = {}
            except Exception:
                dados = {}
            dados[chave] = valor
            ARQ_PREFS.parent.mkdir(parents=True, exist_ok=True)
            ARQ_PREFS.write_text(
                json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    def definir_modo(self, modo: str) -> None:
        modo = str(modo or "").lower()
        if modo not in MODOS:
            raise ValueError(f"modo inválido: {modo!r} "
                             f"(use: {', '.join(MODOS)})")
        self.modo = modo
        self._gravar_pref("modelo_modo", modo)
        # Trocar de modo é um "tentar de novo": o usuário pode ter recarregado
        # o saldo do DeepSeek, então zera o breaker e o cache do probe.
        with self._lock:
            self._cooldown.clear()
            self._probe_ok_ate = 0.0

    def definir_modelo_local(self, nome: str) -> None:
        nome = str(nome or "").strip()
        if not nome or "ollama" not in self.providers:
            raise ValueError("modelo local inválido")
        self.providers["ollama"].model = nome
        self._gravar_pref("modelo_local", nome)

    def info(self) -> dict:
        ds = self._cooldown.get("deepseek", 0.0) - time.time()
        return {
            "modo": self.modo,
            "modos": [{"id": k, **v} for k, v in MODOS.items()],
            "efetivo": ("ollama" if self.sem_externos()
                        else self.pick_provider("analise_complexa").name),
            "local": {"modelo": getattr(self.providers.get("ollama"), "model", "")},
            "deepseek": {
                "modelo": getattr(self.providers.get("deepseek"), "model", ""),
                "indisponivel_s": max(0, round(ds)) if ds > 0 else 0},
        }

    def classify(self, message: str) -> str:
        """Classificação leve por keywords (zero custo).
        Regra de ouro: tarefa com AÇÃO ou longa vai para o modelo forte (API);
        conversa curta e pergunta simples vai para o local (fallback barato)."""
        low = message.lower()
        if any(a in low for a in ACOES):
            return "analise_complexa"
        for task_type, kws in KEYWORDS.items():
            if any(k in low for k in kws):
                return task_type
        if len(message) > 160:
            return "analise_complexa"
        return "resposta_simples"

    def pick_provider(self, task_type: str):
        # Política: LOCAL primeiro; DeepSeek só para tarefas mais profundas
        # (código, arquitetura, análise complexa, pesquisa, prospecção — e o
        # loop de ferramentas do agente, que usa 'analise_complexa'). Em ambos
        # os casos o outro provider entra como fallback.
        if self.modo == "local" and "ollama" in self.providers:
            return self.providers["ollama"]
        profundas = set(self.routing.get("external", []))
        if self.modo == "deepseek" or task_type in profundas:
            order = self.routing["fallback_order"]            # deepseek primeiro
        else:
            resto = [n for n in self.routing["fallback_order"] if n != "ollama"]
            order = ["ollama"] + resto                        # local primeiro
        for name in order:
            if name in self.providers:
                return self.providers[name]
        return self.providers[self.default]

    # ------------------------------------------------------------------ #
    # Circuit breaker: provider que falhou é pulado por um tempo
    # ------------------------------------------------------------------ #
    COOLDOWN_FATAL = 1800.0     # sem saldo/credencial: 30 min
    COOLDOWN_TRANSITORIO = 60.0  # timeout/5xx/rede: 1 min
    PROBE_TTL = 600.0           # reaproveita um probe bem-sucedido por 10 min

    def _em_cooldown(self, nome: str) -> bool:
        return self._cooldown.get(nome, 0.0) > time.time()

    @staticmethod
    def _fatal(exc: Exception) -> bool:
        return bool(getattr(exc, "fatal", False)) or bool(_FATAL.search(str(exc)))

    def _falhou(self, nome: str, exc: Exception) -> None:
        fatal = self._fatal(exc)
        ate = time.time() + (self.COOLDOWN_FATAL if fatal
                             else self.COOLDOWN_TRANSITORIO)
        with self._lock:
            era_novo = not self._em_cooldown(nome)
            self._cooldown[nome] = ate
            self._probe_ok_ate = 0.0
        if era_novo:
            _log.warning("provider %s indisponível (%s) — usando o próximo",
                         nome, "sem saldo/credencial" if fatal
                         else str(exc)[:90])
            try:   # aviso na API/GUI, sem falar em voz alta
                from yvakor.notificacoes import emitir
                emitir(f"{nome} indisponível"
                       + (" (sem saldo ou credencial)" if fatal else "")
                       + " — usando o modelo local.", "sistema", 1, falar=False)
            except Exception:
                pass

    def _ok(self, nome: str) -> None:
        with self._lock:
            self._cooldown.pop(nome, None)

    def externos(self) -> list[str]:
        """Providers de nuvem (tudo que não é o local 'ollama')."""
        return [n for n in self.providers if n != "ollama"]

    def sem_externos(self) -> bool:
        """True se há provider externo configurado e TODOS estão em cooldown
        (ex.: DeepSeek sem saldo). Não faz chamada de rede."""
        if self.modo == "local":
            return True            # escolha do usuário: só o modelo local
        ext = self.externos()
        return bool(ext) and all(self._em_cooldown(n) for n in ext)

    def verificar_externos(self, forcar: bool = False) -> bool:
        """Algum provider externo está respondendo? Faz um probe BARATO
        (1 token) só quando o resultado anterior expirou. Evita gastar o 1º
        passo do agente, com prompt pesado, num provider que está sem saldo."""
        if self.modo == "local":
            return False           # modo local: nem tenta a nuvem
        ext = self.externos()
        if not ext:
            return False
        if not forcar and time.time() < self._probe_ok_ate:
            return True
        for nome in ext:
            if self._em_cooldown(nome) and not forcar:
                continue
            try:
                self.providers[nome].chat_messages(
                    [{"role": "user", "content": "ok"}],
                    timeout=10, max_tokens=1)
                self._ok(nome)
                self._probe_ok_ate = time.time() + self.PROBE_TTL
                return True
            except Exception as exc:
                self._falhou(nome, exc)
        return False

    def _ordem(self, task_type: str, forcar: str | None) -> list:
        if self.modo == "local" and "ollama" in self.providers:
            # Estrito: mesmo um `forcar="deepseek"` explícito (absorção etc.)
            # fica no local — o usuário escolheu não usar a nuvem.
            return [self.providers["ollama"]]
        primeiro = self.providers.get(forcar) if forcar else None
        primeiro = primeiro or self.pick_provider(task_type)
        resto = [self.providers[n] for n in self.routing["fallback_order"]
                 if n in self.providers and self.providers[n] is not primeiro]
        ordem = [primeiro] + resto
        vivos = [p for p in ordem if not self._em_cooldown(p.name)]
        return vivos or ordem      # todos em cooldown: tenta mesmo assim

    def complete(self, task_type: str, system: str, user: str) -> str:
        return self._dispatch(task_type, lambda p: p.chat(system, user))

    def complete_messages(self, task_type: str, messages: list[dict],
                          forcar: str | None = None,
                          timeout: float | None = None) -> str:
        if timeout is None:
            call = lambda p: p.chat_messages(messages)
        else:
            call = lambda p: p.chat_messages(messages, timeout=timeout)
        return self._dispatch(task_type, call, forcar=forcar)

    def complete_tools(self, task_type: str, messages: list[dict],
                       tools: list[dict], forcar: str | None = None):
        """Function calling nativo; devolve (provider, mensagem)."""
        ultimo = None
        for p in self._ordem(task_type, forcar):
            try:
                msg = p.chat_tools(messages, tools)
                self._ok(p.name)
                return p.name, msg
            except Exception as exc:
                self._falhou(p.name, exc)
                ultimo = exc
        raise ultimo or RuntimeError("nenhum provider disponível")

    def _dispatch(self, task_type: str, call, forcar: str | None = None) -> str:
        erros = []
        fatais = 0
        for p in self._ordem(task_type, forcar):
            try:
                r = call(p)
                self._ok(p.name)
                return r
            except Exception as exc:
                self._falhou(p.name, exc)
                erros.append(f"{p.name}: {exc}")
                fatais += 1 if self._fatal(exc) else 0
        dica = (" — recarregue o saldo do provedor externo (HTTP 402) ou "
                "confira a chave" if fatais else "")
        raise RuntimeError("Todos os provedores de IA falharam — "
                           + " | ".join(erros) + dica)
