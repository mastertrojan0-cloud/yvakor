"""
YVAKOR — Memória curada (MEMORY.md + USER.md), no modelo do Hermes Agent

Dois arquivos pequenos, escritos pelo próprio agente, que entram INTEIROS no
system prompt de toda conversa:

  data/memories/MEMORY.md → anotações do agente: fatos do ambiente,
                            convenções, o que funcionou (limite ~2200 chars)
  data/memories/USER.md   → perfil do usuário: preferências, jeito de
                            trabalhar, correções que ele fez (limite ~1375)

Entradas separadas por "§". O limite é fixo de propósito: a memória não
cresce sem controle — quando enche, o agente precisa resumir/remover algo
para caber o novo (a ferramenta devolve as entradas atuais para isso).

Diferente das outras memórias do YVAKOR:
  - licoes.py        → regras curtas escolhidas por relevância à mensagem;
  - memory/semantic  → fatos buscados por similaridade;
  - memória curada   → o pouco que vale estar SEMPRE presente.

Ações (ferramenta memoria_editar): adicionar, editar (troca um trecho único),
remover (por trecho único) e lote (várias de uma vez, atômico). Não há
"ler": o conteúdo já está no prompt. Entradas passam pelo detector de
prompt-injection e duplicatas exatas são recusadas.
"""
from __future__ import annotations

import json
import threading
import unicodedata
from pathlib import Path

from yvakor import injecao, seguro
from yvakor.config import ROOT
import logging

_log = logging.getLogger(__name__)

PASTA = ROOT / "data" / "memories"
SEP = "\n§\n"
ALVOS = {
    "memoria": ("MEMORY.md", 2200, "MEMÓRIA DO AGENTE (suas anotações)"),
    "usuario": ("USER.md", 1375, "PERFIL DO USUÁRIO (o que você sabe sobre ele)"),
}
_SINONIMOS = {"memory": "memoria", "memória": "memoria", "agente": "memoria",
              "user": "usuario", "usuário": "usuario", "perfil": "usuario"}
_ACOES = {"add": "adicionar", "patch": "editar", "remove": "remover",
          "batch": "lote", "substituir": "editar", "apagar": "remover"}


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


class MemoriaCurada:
    def __init__(self, pasta: Path | None = None, limites: dict | None = None):
        self.pasta = Path(pasta or PASTA)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.limites = {a: int((limites or {}).get(a) or lim)
                        for a, (_, lim, _) in ALVOS.items()}
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, list[str]]] = {}

    # ------------------------------------------------------------------ #
    def _arquivo(self, alvo: str) -> Path:
        return self.pasta / ALVOS[alvo][0]

    @staticmethod
    def _alvo(alvo: str) -> str | None:
        a = (alvo or "").strip().lower()
        a = _SINONIMOS.get(a, a)
        return a if a in ALVOS else None

    def entradas(self, alvo: str) -> list[str]:
        alvo = self._alvo(alvo) or alvo
        arq = self._arquivo(alvo)
        try:
            mtime = arq.stat().st_mtime
        except OSError:
            return []
        em_cache = self._cache.get(alvo)
        if em_cache and em_cache[0] == mtime:
            return list(em_cache[1])
        texto = arq.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        itens = [e.strip() for e in texto.split("§") if e.strip()]
        self._cache[alvo] = (mtime, itens)
        return list(itens)

    def uso(self, alvo: str, itens: list[str] | None = None) -> tuple[int, int]:
        itens = self.entradas(alvo) if itens is None else itens
        return len(SEP.join(itens)), self.limites[alvo]

    def _gravar(self, alvo: str, itens: list[str]) -> None:
        seguro.gravar_texto(self._arquivo(alvo),
                            (SEP.join(itens) + "\n") if itens else "")
        self._cache.pop(alvo, None)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _achar(itens: list[str], trecho: str) -> tuple[int | None, str]:
        """Índice da ÚNICA entrada que contém o trecho (ou erro)."""
        if not (trecho or "").strip():
            return None, "informe 'antigo': um trecho da entrada a alterar"
        achados = [i for i, e in enumerate(itens) if trecho in e]
        if not achados:
            achados = [i for i, e in enumerate(itens) if _norm(trecho) in _norm(e)]
        if not achados:
            return None, f"nenhuma entrada contém {trecho[:60]!r}"
        if len(achados) > 1:
            return None, (f"{len(achados)} entradas contêm {trecho[:60]!r}; "
                          "use um trecho mais específico")
        return achados[0], ""

    def _aplicar(self, itens: list[str], op: dict) -> str:
        """Aplica uma operação em `itens` (in-place). Devolve erro ou ''."""
        acao = str(op.get("acao") or "").strip().lower()
        acao = _ACOES.get(acao, acao)
        texto = str(op.get("texto") or "").strip()
        antigo = str(op.get("antigo") or "")
        if acao in ("adicionar", "editar") and texto:
            motivos = injecao.varrer(texto)
            if motivos:
                return f"entrada recusada (suspeita de prompt-injection: {', '.join(motivos)})"
            if "§" in texto:
                return "o texto não pode conter '§' (é o separador de entradas)"
        if acao == "adicionar":
            if not texto:
                return "informe 'texto' com a entrada nova"
            if any(_norm(texto) == _norm(e) for e in itens):
                return "essa entrada já existe"
            itens.append(texto)
            return ""
        if acao in ("editar", "remover"):
            i, erro = self._achar(itens, antigo)
            if erro:
                return erro
            if acao == "remover":
                itens.pop(i)
                return ""
            if not texto:
                return "informe 'texto' (o novo trecho); para apagar use acao=remover"
            atual = itens[i]
            itens[i] = (atual.replace(antigo, texto, 1) if antigo in atual
                        else texto)
            return ""
        return f"ação desconhecida: {acao!r} (use adicionar, editar, remover ou lote)"

    def editar(self, acao: str = "", alvo: str = "memoria", texto: str = "",
               antigo: str = "", operacoes=None) -> dict:
        destino = self._alvo(alvo)
        if not destino:
            return {"ok": False, "error": "alvo deve ser 'memoria' ou 'usuario'"}
        acao_n = _ACOES.get((acao or "").strip().lower(), (acao or "").strip().lower())
        if acao_n == "lote" or (operacoes and not acao_n):
            if isinstance(operacoes, str):
                try:
                    operacoes = json.loads(operacoes)
                except ValueError:
                    return {"ok": False, "error": "operacoes deve ser uma lista JSON"}
            if not isinstance(operacoes, list) or not operacoes:
                return {"ok": False, "error": "lote precisa de 'operacoes': "
                        '[{"acao":"remover","antigo":"..."}, ...]'}
            ops = [o for o in operacoes if isinstance(o, dict)]
        else:
            ops = [{"acao": acao_n, "texto": texto, "antigo": antigo}]
        with self._lock:
            itens = self.entradas(destino)
            for n, op in enumerate(ops, 1):
                erro = self._aplicar(itens, op)
                if erro:
                    prefixo = f"operação {n}: " if len(ops) > 1 else ""
                    return {"ok": False, "error": prefixo + erro + " — nada foi gravado"}
            usado, limite = self.uso(destino, itens)
            if usado > limite:
                atuais = self.entradas(destino)
                return {"ok": False, "error": (
                    f"não cabe: ficaria com {usado}/{limite} caracteres. Nada foi "
                    "gravado. Use acao=lote para remover/encurtar entradas e "
                    "incluir a nova numa só chamada."),
                    "entradas_atuais": atuais,
                    "uso": f"{self.uso(destino, atuais)[0]}/{limite}"}
            self._gravar(destino, itens)
        return {"ok": True, "result": f"{ALVOS[destino][0]} atualizado "
                f"({usado}/{limite} caracteres, {len(itens)} entradas)"}

    # ------------------------------------------------------------------ #
    def bloco_prompt(self) -> str:
        partes = []
        for alvo, (_, _, titulo) in ALVOS.items():
            itens = self.entradas(alvo)
            usado, limite = self.uso(alvo, itens)
            corpo = SEP.join(itens) if itens else "(vazio)"
            partes.append(f"## {titulo} · {usado}/{limite} caracteres\n{corpo}")
        partes.append(
            "Mantenha essa memória com memoria_editar: guarde preferências, "
            "correções do usuário, fatos do ambiente e convenções que valem "
            "para conversas futuras. Não guarde o trivial, o que se acha "
            "fácil de novo, dados brutos nem coisas passageiras.")
        return "\n\n".join(partes)

    def bloco_compacto(self, limite: int = 600) -> str:
        """Só o perfil do usuário, para o prompt enxuto do modelo local."""
        itens = self.entradas("usuario")
        return ("Sobre o usuário:\n" + "\n".join(f"- {e}" for e in itens))[:limite] \
            if itens else ""


_PADRAO: MemoriaCurada | None = None
_PADRAO_LOCK = threading.Lock()


def padrao() -> MemoriaCurada:
    global _PADRAO
    with _PADRAO_LOCK:
        if _PADRAO is None:
            _PADRAO = MemoriaCurada()
        return _PADRAO


def register_memoria_tools(registry, memoria: MemoriaCurada) -> list[str]:
    registry.register(
        "memoria_editar", memoria.editar,
        "Edita sua memória permanente (sempre presente no prompt). "
        "alvo='memoria' (suas anotações) ou 'usuario' (perfil/preferências). "
        "acao: adicionar (texto), editar (antigo=trecho único, texto=novo), "
        "remover (antigo=trecho único) ou lote (operacoes=[{acao,texto,antigo}]). "
        "Tem limite de caracteres: se encher, remova/resuma entradas no mesmo lote.",
        {"acao": "str", "alvo": "str", "texto": "str?", "antigo": "str?",
         "operacoes": "list?"})
    return ["memoria_editar"]
