"""Roteador: decide qual provider atende cada tipo de tarefa.
É aqui que a independência de IA externa acontece gradualmente:
mova categorias de 'external' para 'local' no settings.yaml."""
from __future__ import annotations
import inspect
import logging
import re
import threading
import time

from yvakor import seguro
from yvakor.config import ROOT
from yvakor.llm import economia
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
    "gemini": {
        "rotulo": "Gemini",
        "descricao": "Gemini (Google AI Studio) primeiro; DeepSeek e o local "
                     "entram se ele falhar."},
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
         "organiz", "corrija", "refator", "implement",
         # faltavam na conversa 71: "deleta", "verifica", "procede"…
         "delet", "limp", "remov", "exclu", "verific", "atualiz", "proced",
         "prossig", "autoriz", "configur", "consert", "repar", "diagnost",
         "desinstal", "escane", "reinici", "mostr", "busc", "procur")


class _SemProvedor(Exception):
    """Reservada: sinaliza falha total que não deve cair no caminho original."""


class LLMRouter:
    def __init__(self, settings: dict):
        self.settings = settings
        llm = settings["llm"]
        self.providers = {name: build_provider(name, cfg)
                          for name, cfg in llm["providers"].items()}
        self.routing = llm["routing"]
        self.default = llm["default_provider"]
        # Otimizador de consumo (cache, compressão, cascata local→nuvem, orçamento).
        # Se não puder iniciar, o roteador segue no caminho original.
        self.otim = None
        try:
            cfg_otim = llm.get("otimizacao") or {}
            if cfg_otim.get("ativo", True):
                self.otim = economia.Otimizador(cfg_otim, self.providers)
        except Exception as exc:                         # pragma: no cover
            _log.warning("otimizador de consumo desativado: %s", exc)
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
        dados = seguro.ler_json(ARQ_PREFS, {})
        return dados.get(chave) if isinstance(dados, dict) else None

    def _gravar_pref(self, chave: str, valor) -> None:
        with self._lock:
            dados = seguro.ler_json(ARQ_PREFS, {})
            if not isinstance(dados, dict):
                dados = {}
            dados[chave] = valor
            seguro.gravar_json(ARQ_PREFS, dados)

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
        gm = self._cooldown.get("gemini", 0.0) - time.time()
        return {
            "modo": self.modo,
            "modos": [{"id": k, **v} for k, v in MODOS.items()],
            "efetivo": ("ollama" if self.sem_externos()
                        else self.pick_provider("analise_complexa").name),
            "local": {"modelo": getattr(self.providers.get("ollama"), "model", "")},
            "deepseek": {
                "modelo": getattr(self.providers.get("deepseek"), "model", ""),
                "indisponivel_s": max(0, round(ds)) if ds > 0 else 0},
            "gemini": {
                "modelo": getattr(self.providers.get("gemini"), "model", ""),
                "com_chave": bool(getattr(self.providers.get("gemini"), "api_key", None)),
                "indisponivel_s": max(0, round(gm)) if gm > 0 else 0},
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
        if self.modo == "gemini":
            order = ["gemini"] + [n for n in self.routing["fallback_order"]
                                  if n != "gemini"]           # gemini primeiro
        elif self.modo == "deepseek" or task_type in profundas:
            order = self.routing["fallback_order"]            # deepseek primeiro
        else:
            resto = [n for n in self.routing["fallback_order"] if n != "ollama"]
            order = ["ollama"] + resto                        # local primeiro
        for name in order:
            if name in self.providers and self._tem_chave(self.providers[name]):
                return self.providers[name]
        return self.providers[self.default]

    @staticmethod
    def _tem_chave(p) -> bool:
        """Provedor de nuvem sem chave configurada fica fora da rota."""
        return not getattr(p, "precisa_chave", False) or bool(getattr(p, "api_key", None))

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
        if getattr(exc, "fatal", False):
            return True
        # 429 por minuto traz "quota" no texto mas volta em segundos: não é
        # fatal (o adaptador já marca fatal a cota do DIA esgotada).
        if getattr(exc, "codigo", None) == 429:
            return False
        return bool(_FATAL.search(str(exc)))

    def _falhou(self, nome: str, exc: Exception) -> None:
        fatal = self._fatal(exc)
        espera = getattr(exc, "espera_s", None)      # Retry-After da própria API
        ate = time.time() + (self.COOLDOWN_FATAL if fatal else
                             max(self.COOLDOWN_TRANSITORIO, min(float(espera), 300))
                             if espera else self.COOLDOWN_TRANSITORIO)
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
                _log.debug("exceção ignorada", exc_info=True)

    def _ok(self, nome: str) -> None:
        with self._lock:
            self._cooldown.pop(nome, None)

    def externos(self) -> list[str]:
        """Providers de nuvem (tudo que não é o local 'ollama')."""
        return [n for n in self.providers
                if n != "ollama" and self._tem_chave(self.providers[n])]

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
                p = self.providers[nome]
                if hasattr(p, "ping"):
                    p.ping(timeout=10)
                else:
                    p.chat_messages([{"role": "user", "content": "ok"}],
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
        ordem = [p for p in ordem if self._tem_chave(p)] or ordem
        vivos = [p for p in ordem if not self._em_cooldown(p.name)]
        return vivos or ordem      # todos em cooldown: tenta mesmo assim

    def complete(self, task_type: str, system: str, user: str) -> str:
        if self.otim is not None and self.otim.ativo:
            return self.complete_messages(task_type, [
                {"role": "system", "content": system},
                {"role": "user", "content": user}])
        return self._dispatch(task_type, lambda p: p.chat(system, user))

    def complete_messages(self, task_type: str, messages: list[dict],
                          forcar: str | None = None,
                          timeout: float | None = None) -> str:
        if self.otim is not None and self.otim.ativo:
            try:
                return self._completar_otimizado(task_type, messages, forcar, timeout)
            except _SemProvedor:
                raise
            except Exception as exc:                     # otimizador falhou: caminho original
                if isinstance(exc, RuntimeError) and "Todos os provedores" in str(exc):
                    raise
                _log.warning("otimizador falhou (%s) — caminho original", exc)
        if timeout is None:
            call = lambda p: p.chat_messages(messages)
        else:
            call = lambda p: p.chat_messages(messages, timeout=timeout)
        return self._dispatch(task_type, call, forcar=forcar)

    def complete_tools(self, task_type: str, messages: list[dict],
                       tools: list[dict], forcar: str | None = None):
        """Function calling nativo; devolve (provider, mensagem)."""
        ultimo = None
        plano = None
        ordem = self._ordem(task_type, forcar)
        # Loop de ferramentas: o 3B em CPU leva ~110 s por passo com o prompt
        # completo e estoura o timeout de 50 s — cair nele no meio da tarefa
        # só atrasava o erro. Com nuvem na fila, falha rápido e o agente segue
        # o próprio fallback (protocolo compacto) se nada rodou ainda.
        nuvem = [p for p in ordem if p.name != "ollama"]
        ordem = nuvem or ordem
        if self.otim is not None and self.otim.ativo:
            try:
                # Ferramentas seguem a prioridade declarada (fallback_order /
                # modo): trocar de nuvem por custo a cada passo esbarrava no
                # limite por minuto do Gemini grátis no meio da tarefa.
                plano = self.otim.planejar(task_type, messages, ordem, self.modo, forcar,
                                           ranquear=False)
                ordem = plano.ordem
            except Exception as exc:
                _log.warning("otimizador (tools) falhou: %s", exc)
                plano = None
        for p in ordem:
            try:
                msgs = (plano.mensagens.get(p.name) if plano else None) or messages
                kw = ({"max_tokens": plano.max_tokens[p.name]}
                      if plano and p.name in plano.max_tokens
                      and "max_tokens" in inspect.signature(p.chat_tools).parameters else {})
                t0 = time.time()
                msg = p.chat_tools(msgs, tools, **kw)
                self._ok(p.name)
                if plano is not None:
                    try:
                        q = 0.9 if (msg or {}).get("tool_calls") else economia.avaliar(
                            (msg or {}).get("content") or "", task_type)
                        self.otim.registrar_chamada(plano, p, msgs, str((msg or {}).get("content") or ""),
                                                    (time.time() - t0) * 1000,
                                                    getattr(p, "ultimo_uso", None), q)
                    except Exception:
                        _log.debug("exceção ignorada", exc_info=True)
                return p.name, msg
            except Exception as exc:
                self._falhou(p.name, exc)
                ultimo = exc
        raise ultimo or RuntimeError("nenhum provider disponível")

    @staticmethod
    def _chamar(p, msgs: list[dict], timeout: float | None, max_tokens: int | None) -> str:
        kw = {}
        if timeout is not None:
            kw["timeout"] = timeout
        if max_tokens and "max_tokens" in inspect.signature(p.chat_messages).parameters:
            kw["max_tokens"] = max_tokens
        return p.chat_messages(msgs, **kw)

    def _completar_otimizado(self, task_type: str, messages: list[dict],
                             forcar: str | None, timeout: float | None) -> str:
        o = self.otim
        plano = o.planejar(task_type, messages, self._ordem(task_type, forcar),
                           self.modo, forcar)
        hit = o.cache_buscar(plano)
        if hit:
            o.registrar_cache(plano, hit)
            return hit["resposta"]
        chave = plano.cache_chave if plano.cacheavel else None
        ev, dono = o.voo_unico(chave)
        try:
            if not dono:                                  # outra thread já pagou por isto
                hit = o.cache_buscar(plano)
                if hit:
                    o.registrar_cache(plano, hit)
                    return hit["resposta"]
            return self._percorrer(plano, messages, timeout)
        finally:
            if dono:
                o.voo_fim(chave, ev)

    def _percorrer(self, plano, messages: list[dict], timeout: float | None) -> str:
        o = self.otim
        erros, fatais = [], 0
        melhor: tuple[float, str] | None = None
        ordem = plano.ordem
        for i, p in enumerate(ordem):
            msgs = plano.mensagens.get(p.name) or messages
            t0 = time.time()
            try:
                r = self._chamar(p, msgs, timeout, plano.max_tokens.get(p.name))
            except Exception as exc:
                # "resposta vazia" é falha de QUALIDADE (o modelo não deu conta), não queda do
                # provedor: não o põe em cooldown — só escalona para o próximo.
                if "resposta vazia" not in str(exc):
                    self._falhou(p.name, exc)
                erros.append(f"{p.name}: {exc}")
                fatais += 1 if self._fatal(exc) else 0
                try:
                    o.registrar_chamada(plano, p, msgs, "", (time.time() - t0) * 1000,
                                        getattr(p, "ultimo_uso", None), 0.0, ok=False,
                                        detalhe=str(exc)[:120])
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
                continue
            if not (r or "").strip():                    # vazio = falha (como no adapter)
                erros.append(f"{p.name}: resposta vazia")
                try:
                    o.registrar_chamada(plano, p, msgs, "", (time.time() - t0) * 1000,
                                        getattr(p, "ultimo_uso", None), 0.0, ok=False,
                                        detalhe="resposta vazia")
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
                continue
            uso = getattr(p, "ultimo_uso", None)
            q = economia.avaliar(r, plano.tarefa, (uso or {}).get("finish"))
            info = o.registrar_chamada(plano, p, msgs, r, (time.time() - t0) * 1000, uso, q)
            self._ok(p.name)
            proximo = ordem[i + 1] if i + 1 < len(ordem) else None
            if o.deve_escalar(q, p, proximo):             # o local não convenceu: sobe para a nuvem
                if melhor is None or q > melhor[0]:
                    melhor = (q, r)
                continue
            o.cache_guardar(plano, r, info["tok_in"], info["tok_out"], q)
            return r
        if melhor is not None:                            # a nuvem falhou depois: fica o melhor que houve
            return melhor[1]
        dica = (" — recarregue o saldo do provedor externo (HTTP 402) ou "
                "confira a chave" if fatais else "")
        if getattr(plano, "zona", "") == "bloqueado":
            dica += (" — o orçamento de nuvem do dia/mês foi atingido; aumente em "
                     "Ajustes → Consumo ou abra o Ollama para usar o modelo local")
        raise RuntimeError("Todos os provedores de IA falharam — "
                           + " | ".join(erros) + dica)

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
