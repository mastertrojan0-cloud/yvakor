"""YVAKOR — apagar todo o histórico de conversas SEM apagar o aprendizado.

Apaga (histórico):
  - conversas (sessões de chat) e suas mensagens/passos de ferramenta;
  - notas de conversa exportadas no cérebro (vault/Conversas);
  - rastros de tarefas (data/rastros.jsonl: pedido + resposta);
  - anexos enviados nas conversas (data/uploads);
  - o TEXTO das avaliações (pergunta/resposta) — as notas ficam.

Mantém (aprendizado): lições, skills, fatos da memória semântica, demais notas
do cérebro, perfil/preferências, entorno, guardião, workspaces, tarefas do
Cowork e os registros de aprendizado (skill_destilada, erro, manutencao).

Antes de apagar, faz um backup em data/backups/historico_<data>.zip.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from yvakor.config import ROOT

_log = logging.getLogger(__name__)

CONFIRMACAO = "APAGAR"
# registros de aprendizado: ficam (sem o vínculo com a conversa apagada)
KINDS_APRENDIZADO = ("skill_destilada", "erro", "manutencao")


def resumo(episodic, raiz: Path | None = None) -> dict:
    """O que seria apagado — para a tela de confirmação."""
    raiz = Path(raiz or ROOT)
    conn = episodic.conn
    conversas = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE COALESCE(kind,'chat')='chat'").fetchone()[0]
    mensagens = conn.execute(
        "SELECT COUNT(*) FROM episodes WHERE kind IN ('conversa','ferramenta','voz') AND "
        "(session_id IS NULL OR session_id IN (SELECT id FROM sessions "
        "WHERE COALESCE(kind,'chat')='chat'))").fetchone()[0]
    notas = len(list((raiz / "data" / "vault" / "Conversas").glob("*.md")))
    return {"conversas": conversas, "mensagens": mensagens, "notas_conversa": notas}


def _backup(episodic, raiz: Path) -> Path:
    pasta = raiz / "data" / "backups"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"historico_{datetime.now():%Y%m%d_%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "yvakor_memory.db"
        episodic.backup(db)
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db, "yvakor_memory.db")
            for rel in ("data/rastros.jsonl", "data/avaliacoes.jsonl"):
                arq = raiz / rel
                if arq.is_file():
                    z.write(arq, rel)
            for pasta_rel in ("data/vault/Conversas", "data/uploads"):
                for arq in (raiz / pasta_rel).rglob("*"):
                    if arq.is_file():
                        z.write(arq, arq.relative_to(raiz).as_posix())
    return destino


def _limpar_avaliacoes(arq: Path) -> int:
    """Tira pergunta/resposta das avaliações; nota e métricas ficam."""
    if not arq.is_file():
        return 0
    linhas, n = [], 0
    for linha in arq.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(linha)
        except ValueError:
            continue
        for campo in ("pergunta", "resposta", "problemas", "melhoria"):
            if campo in r:
                r.pop(campo)
                n += 1
        linhas.append(json.dumps(r, ensure_ascii=False))
    arq.write_text("\n".join(linhas) + ("\n" if linhas else ""), encoding="utf-8")
    return n


def apagar_historico(episodic, cerebro=None, raiz: Path | None = None,
                     confirmar: str = "") -> dict:
    if (confirmar or "").strip().upper() != CONFIRMACAO:
        return {"ok": False, "erro": f'confirme digitando "{CONFIRMACAO}"'}
    raiz = Path(raiz or ROOT)
    antes = resumo(episodic, raiz)
    backup = _backup(episodic, raiz)
    conn = episodic.conn
    with episodic._lock:
        chats = "SELECT id FROM sessions WHERE COALESCE(kind,'chat')='chat'"
        conn.execute(f"UPDATE episodes SET session_id=NULL WHERE kind IN "
                     f"({','.join('?' * len(KINDS_APRENDIZADO))}) AND session_id IN ({chats})",
                     KINDS_APRENDIZADO)
        apagados = conn.execute(
            f"DELETE FROM episodes WHERE kind IN ('conversa','ferramenta','voz') AND "
            f"(session_id IS NULL OR session_id IN ({chats}))").rowcount
        try:                                  # resumos compactados (yvakor/compactacao.py)
            conn.execute(f"DELETE FROM conversa_resumos WHERE session_id IN ({chats})")
        except sqlite3.OperationalError:
            pass                              # tabela ainda não criada
        conn.execute("DELETE FROM sessions WHERE COALESCE(kind,'chat')='chat'")
        conn.commit()
        try:                                  # índice de busca + espaço em disco
            conn.execute("INSERT INTO episodes_fts(episodes_fts) VALUES('rebuild')")
            conn.commit()
            conn.execute("VACUUM")
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
    notas = 0
    for arq in (raiz / "data" / "vault" / "Conversas").glob("*.md"):
        try:
            arq.unlink()
            notas += 1
        except OSError:
            _log.debug("exceção ignorada", exc_info=True)
    for rel in ("data/rastros.jsonl",):
        try:
            (raiz / rel).unlink(missing_ok=True)
        except OSError:
            _log.debug("exceção ignorada", exc_info=True)
    shutil.rmtree(raiz / "data" / "uploads", ignore_errors=True)
    campos = _limpar_avaliacoes(raiz / "data" / "avaliacoes.jsonl")
    if cerebro is not None:
        try:
            cerebro.sincronizar()             # tira do índice as notas apagadas
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
    nova = episodic.nova_conversa()           # o app sempre tem uma conversa aberta
    return {"ok": True, "conversas_apagadas": antes["conversas"],
            "mensagens_apagadas": apagados, "notas_apagadas": notas,
            "avaliacoes_sem_texto": campos, "backup": str(backup),
            "nova_conversa": nova.split(" ", 1)[0],
            "mantido": "lições, skills, memória de fatos, notas do cérebro, perfil, "
                       "entorno, guardião, workspaces e tarefas"}


def buscar_sessoes(episodic, termo: str, limite: int = 8) -> dict:
    """Busca nas conversas passadas (FTS5), agrupando os trechos por conversa.

    É a memória "sob demanda" (como o session_search do Hermes): o que não
    está na memória curada, mas foi dito em alguma conversa, se acha aqui."""
    if not (termo or "").strip():
        return {"ok": False, "error": "informe 'termo'"}
    limite = max(1, min(int(limite or 8), 20))
    achados = episodic.buscar(termo, limite=limite * 3, kind="conversa")
    conversas: dict[str, dict] = {}
    for a in achados:
        c = conversas.setdefault(a["session_id"] or "?", {
            "conversa": a["session_id"], "titulo": a["titulo"], "data": a["ts"],
            "trechos": []})
        if len(c["trechos"]) < 3:
            c["trechos"].append(a["trecho"])
    itens = list(conversas.values())[:limite]
    return {"ok": True, "total": len(itens), "conversas": itens,
            "dica": "sessao_ler(conversa) mostra a conversa inteira"}


def ler_sessao(episodic, conversa: str, ultimas: int = 20) -> dict:
    msgs = episodic.mensagens_da_conversa(conversa) if conversa else []
    if not msgs:
        return {"ok": False, "error": f"conversa {conversa!r} não encontrada"}
    ultimas = max(2, min(int(ultimas or 20), 60))
    return {"ok": True, "conversa": conversa, "total_mensagens": len(msgs),
            "mensagens": [{"role": m["role"], "content": m["content"][:1500]}
                          for m in msgs[-ultimas:]]}


def register_historico_tools(registry, episodic, cerebro=None) -> list[str]:
    registry.register(
        "sessao_buscar",
        lambda termo="", limite=8: buscar_sessoes(episodic, termo, limite),
        "Procura em conversas passadas o que já foi dito/decidido (busca por "
        "palavras). Use quando o usuário citar algo de outra conversa "
        "(\"como falamos\", \"aquele projeto\", \"o que eu te disse sobre…\").",
        {"termo": "str", "limite": "int?"})
    registry.register(
        "sessao_ler",
        lambda conversa="", ultimas=20: ler_sessao(episodic, conversa, ultimas),
        "Lê as últimas mensagens de uma conversa passada (id vindo de sessao_buscar).",
        {"conversa": "str", "ultimas": "int?"})
    registry.register(
        "historico_apagar_tudo",
        lambda confirmar="": apagar_historico(episodic, cerebro, confirmar=confirmar),
        "Apaga TODO o histórico de conversas (mantém o aprendizado: lições, skills, "
        f'fatos). Faz backup antes. Só use se o usuário pedir; confirmar="{CONFIRMACAO}".',
        {"confirmar": "str"})
    return ["sessao_buscar", "sessao_ler", "historico_apagar_tudo"]
