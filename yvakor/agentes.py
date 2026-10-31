"""
YVAKOR — Subagentes com ferramentas (agents/*.md), como no Claude Code

Um subagente é um especialista com prompt próprio, uma LISTA FECHADA de
ferramentas e contexto isolado: recebe a tarefa, trabalha sozinho (navega,
lê arquivos, roda código, conforme as ferramentas dele) e devolve só o
resultado. O histórico da conversa principal não entra nem sai.

  agents/<nome>.md                      ← seus agentes
  plugins/<plugin>/agents/<nome>.md     ← agentes de plugins ligados ("plugin:nome")

    ---
    name: pesquisador
    description: Pesquisa na web e devolve fontes com resumo. Use para…
    tools: pesquisa_web, web_ler, navegador_*     # vazio = todas
    model: deepseek                               # local | deepseek | gemini | inherit
    max_passos: 8
    ---
    Você é um pesquisador… (o prompt de sistema do agente)

Há um agente embutido, "geral", com todas as ferramentas. Nenhum subagente
pode delegar de novo nem perguntar ao usuário (não tem com quem falar).
A diferença para a ferramenta antiga `subagentes`: aquela só conversa com o
modelo (texto puro); esta executa ferramentas.
"""
from __future__ import annotations

import copy
import fnmatch
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from yvakor import injecao
from yvakor.config import ROOT
from yvakor.memory.procedural import _lista, front_matter

_log = logging.getLogger(__name__)

PASTA = ROOT / "agents"
NUNCA = ("agente_delegar", "agentes_listar", "subagentes", "perguntar_usuario")
MAX_PARALELO = 4
_MODELOS = {"local": "ollama", "ollama": "ollama", "deepseek": "deepseek",
            "gemini": "gemini"}


@dataclass
class Definicao:
    nome: str
    descricao: str
    prompt: str
    ferramentas: list[str] = field(default_factory=list)   # padrões (aceita *)
    modelo: str = ""
    max_passos: int = 8
    origem: str = ""


GERAL = Definicao(
    nome="geral", origem="embutido",
    descricao="Agente de uso geral com todas as ferramentas. Use para uma parte "
              "independente de uma tarefa maior (pesquisar, levantar dados, "
              "preparar um arquivo) sem encher a conversa principal.",
    prompt="Você é um subagente do YVAKOR. Execute a tarefa recebida até o fim "
           "com as ferramentas, sem pedir confirmação para o óbvio. No final, "
           "devolva só o resultado: o que encontrou/fez, com caminhos, links e "
           "números exatos. Não invente; se não conseguir, diga o que faltou.")


def ler_definicao(arq: Path, prefixo: str = "") -> Definicao | None:
    texto = arq.read_text(encoding="utf-8", errors="replace")
    meta, corpo = front_matter(texto)
    motivos = injecao.varrer(corpo)
    if motivos:
        _log.warning("agente bloqueado (%s): %s", ", ".join(motivos), arq)
        return None
    nome = re.sub(r"[^a-z0-9-]+", "-", str(meta.get("name") or arq.stem).lower()).strip("-")
    if not nome or not corpo.strip():
        return None
    try:
        passos = max(1, min(int(meta.get("max_passos") or 8), 30))
    except (TypeError, ValueError):
        passos = 8
    return Definicao(
        nome=f"{prefixo}:{nome}" if prefixo else nome,
        descricao=" ".join(str(meta.get("description") or "").split())[:600],
        prompt=corpo.strip()[:12000], ferramentas=_lista(meta.get("tools")),
        modelo=str(meta.get("model") or "").lower().strip(), max_passos=passos,
        origem=str(arq))


class Agentes:
    def __init__(self, router, registry, pasta: Path | None = None, extras=None,
                 nativo: bool = False, timeout_s: int = 300, criar_loop=None):
        self.router = router
        self.registry = registry
        self.pasta = Path(pasta or PASTA)
        self.extras = extras          # callable → {"plugin:nome": Path} (plugins ligados)
        self.nativo = nativo
        self.timeout_s = timeout_s
        self._criar_loop = criar_loop or self._loop_padrao

    # ------------------------------------------------------------------ #
    def definicoes(self) -> dict[str, Definicao]:
        defs = {GERAL.nome: GERAL}
        if self.pasta.is_dir():
            for arq in sorted(self.pasta.glob("*.md")):
                if arq.name.lower() == "readme.md":
                    continue
                d = ler_definicao(arq)
                if d:
                    defs[d.nome] = d
        if self.extras is not None:
            try:
                for chave, arq in self.extras().items():
                    d = ler_definicao(arq, prefixo=chave.split(":", 1)[0])
                    if d:
                        defs[d.nome] = d
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        return defs

    def _resolver(self, nome: str) -> Definicao | None:
        defs = self.definicoes()
        nome = (nome or "geral").strip().lower()
        if nome in defs:
            return defs[nome]
        curtos = [d for n, d in defs.items() if ":" in n and n.split(":", 1)[1] == nome]
        return curtos[0] if len(curtos) == 1 else None

    def ferramentas_de(self, d: Definicao) -> list[str]:
        todas = [n for n in self.registry.tools if n not in NUNCA]
        if not d.ferramentas:
            return todas
        return [n for n in todas if any(fnmatch.fnmatchcase(n, p) for p in d.ferramentas)]

    def listar(self) -> dict:
        return {"ok": True, "agentes": [
            {"nome": d.nome, "descricao": d.descricao,
             "ferramentas": d.ferramentas or ["(todas)"], "modelo": d.modelo or "padrão"}
            for d in self.definicoes().values()],
            "dica": "agente_delegar(agente, tarefa) — ou tarefas=[{agente,tarefa},…] em paralelo"}

    # ------------------------------------------------------------------ #
    def _registro_restrito(self, nomes: list[str]):
        """Cópia rasa do registro só com as ferramentas permitidas: guard,
        hooks e validação de argumentos continuam valendo."""
        restrito = copy.copy(self.registry)
        restrito.tools = {n: self.registry.tools[n] for n in nomes}
        restrito.specs = {n: self.registry.specs[n] for n in nomes if n in self.registry.specs}
        return restrito

    def _loop_padrao(self, registro, d: Definicao):
        from yvakor.agent import AgentLoop
        return AgentLoop(self.router, registro, max_iterations=d.max_passos,
                         nativo=self.nativo, roteador=True,
                         max_ferramentas=14, timeout_s=self.timeout_s,
                         raciocinio={"planejar": False, "verificar": True,
                                     "aprovar_plano": "nunca"})

    def _rodar(self, d: Definicao, tarefa: str, contexto: str = "",
               should_stop=None) -> dict:
        nomes = self.ferramentas_de(d)
        if d.ferramentas and not nomes:
            return {"agente": d.nome, "ok": False,
                    "erro": f"nenhuma das ferramentas {d.ferramentas} existe"}
        inicio = time.time()
        passos: list[str] = []

        def evento(tipo, dado):
            if tipo == "ferramenta" and isinstance(dado, dict) and len(passos) < 40:
                passos.append(str(dado.get("nome"))[:60])

        sistema = (d.prompt + "\n\n## COMO TRABALHAR\n- Você é um subagente: o usuário "
                   "não fala com você. Não faça perguntas; decida e execute.\n"
                   "- Só afirme o que uma ferramenta confirmou.\n"
                   "- Termine com o resultado final, curto e completo.")
        pedido = tarefa if not contexto else f"{tarefa}\n\n## CONTEXTO\n{contexto[:6000]}"
        try:
            resposta = self._criar_loop(self._registro_restrito(nomes), d).run(
                sistema, [{"role": "user", "content": pedido}], on_event=evento,
                should_stop=should_stop, forcar_provider=_MODELOS.get(d.modelo))
        except Exception as exc:
            _log.warning("subagente %s falhou: %s", d.nome, exc, exc_info=True)
            return {"agente": d.nome, "ok": False, "erro": f"{type(exc).__name__}: {exc}"}
        return {"agente": d.nome, "ok": True, "resposta": str(resposta or "").strip()[:12000],
                "ferramentas_usadas": passos, "segundos": round(time.time() - inicio, 1)}

    def delegar(self, agente: str = "geral", tarefa: str = "", contexto: str = "",
                tarefas=None) -> dict:
        if isinstance(tarefas, str) and tarefas.strip():
            try:
                tarefas = json.loads(tarefas)
            except ValueError:
                return {"ok": False, "error": "tarefas deve ser uma lista JSON "
                        '[{"agente":"…","tarefa":"…"}]'}
        lote = [t for t in (tarefas or []) if isinstance(t, dict) and t.get("tarefa")] \
            or ([{"agente": agente, "tarefa": tarefa, "contexto": contexto}]
                if (tarefa or "").strip() else [])
        if not lote:
            return {"ok": False, "error": "informe 'tarefa' (ou 'tarefas')"}
        lote = lote[:MAX_PARALELO]
        trabalhos = []
        for t in lote:
            d = self._resolver(str(t.get("agente") or agente or "geral"))
            if d is None:
                return {"ok": False, "error": f"agente {t.get('agente')!r} não existe",
                        "disponiveis": sorted(self.definicoes())}
            trabalhos.append((d, str(t["tarefa"]), str(t.get("contexto") or contexto or "")))
        if len(trabalhos) == 1:
            r = self._rodar(*trabalhos[0])
            return {"ok": r["ok"], **r}
        # O popup de confirmação é por thread: sem repassá-lo, toda ação
        # protegida de um subagente em paralelo era negada (falha segura, mas
        # o subagente não conseguia rodar shell nem gravar arquivo).
        from yvakor.tools.guard import (
            _thread_confirmer, clear_thread_confirmer, set_thread_confirmer)
        confirmador = _thread_confirmer()

        def em_thread(w):
            if confirmador is not None:
                set_thread_confirmer(confirmador)
            try:
                return self._rodar(*w)
            finally:
                clear_thread_confirmer()
        with ThreadPoolExecutor(max_workers=len(trabalhos)) as ex:
            resultados = list(ex.map(em_thread, trabalhos))
        return {"ok": any(r["ok"] for r in resultados), "resultados": resultados}


def register_agentes_tools(registry, agentes: Agentes) -> list[str]:
    registry.register(
        "agentes_listar", agentes.listar,
        "Lista os SUBAGENTES especialistas para quem você pode delegar tarefas "
        "(nome, para que servem, ferramentas). Não confunda com skills.", {})
    registry.register(
        "agente_delegar", agentes.delegar,
        "Delega uma parte independente da tarefa a um subagente que EXECUTA "
        "ferramentas num contexto isolado e devolve só o resultado. agente "
        "(padrão 'geral'), tarefa (pedido completo e autossuficiente), contexto "
        "opcional; ou tarefas=[{agente,tarefa}] (até 4 em paralelo).",
        {"agente": "str?", "tarefa": "str?", "contexto": "str?", "tarefas": "list?"})
    return ["agentes_listar", "agente_delegar"]
