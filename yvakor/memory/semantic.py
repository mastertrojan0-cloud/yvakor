"""
YVAKOR — Memória semântica (fatos sobre o usuário, clientes, projetos)

Agora em SQLite + FTS5 (data/semantic/facts.db), em vez de varrer JSONL:

  • deduplicação por hash normalizado (não cresce com repetição)
  • busca full-text com ranking bm25 (milissegundos, mesmo com milhares)
  • importa o facts.jsonl antigo uma única vez
  • exporta JSONL sob demanda (portabilidade / fine-tuning)

API pública igual à v0.2: store / search / maybe_store.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from yvakor.memory.db import (
    conectar, criar_fts, fts_query, hash_texto, meta_get, meta_set,
    normalizar, otimizar_fts, tem_fts5,
)
import logging

_log = logging.getLogger(__name__)

try:  # opcional, continua suportado se instalado
    import chromadb  # noqa: F401  (só testa se está instalado)
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False


class SemanticMemory:
    def __init__(self, index_dir: Path):
        self.dir = Path(index_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.dir / "facts.jsonl"      # legado / exportação
        self.db_path = self.dir / "facts.db"
        self.conn = conectar(self.db_path)
        self._lock = threading.RLock()
        self._fts = tem_fts5(self.conn)
        self._migrar()
        self._importar_jsonl()

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #
    def _migrar(self) -> None:
        with self._lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash TEXT UNIQUE NOT NULL,
                    fato TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    fonte TEXT DEFAULT '',
                    tags TEXT DEFAULT '',
                    confianca REAL DEFAULT 0.8,
                    revisar INTEGER DEFAULT 0,
                    obsoleto INTEGER DEFAULT 0,
                    validade TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS meta (
                    chave TEXT PRIMARY KEY, valor TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(id DESC);
            """)
            # migração v2 (qualidade): colunas novas em bancos antigos
            existentes = {r[1] for r in self.conn.execute(
                "PRAGMA table_info(facts)").fetchall()}
            for coluna, tipo in (("confianca", "REAL DEFAULT 0.8"),
                                 ("revisar", "INTEGER DEFAULT 0"),
                                 ("obsoleto", "INTEGER DEFAULT 0"),
                                 ("validade", "TEXT DEFAULT ''")):
                if coluna not in existentes:
                    self.conn.execute(f"ALTER TABLE facts ADD COLUMN {coluna} {tipo}")
            self._fts = criar_fts(self.conn, "facts_fts", "facts", ["fato"])
            self.conn.commit()

    def _importar_jsonl(self) -> None:
        if meta_get(self.conn, "jsonl_importado") == "1":
            return
        importados = 0
        if self.jsonl.exists():
            for linha in self.jsonl.read_text(encoding="utf-8").splitlines():
                try:
                    fato = json.loads(linha).get("fact", "").strip()
                except Exception:
                    continue
                if fato and self.store(fato, fonte="jsonl"):
                    importados += 1
        meta_set(self.conn, "jsonl_importado", "1")
        self.conn.commit()
        if importados:
            print(f"  [memória] {importados} fato(s) importado(s) do facts.jsonl")

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Portão de qualidade
    # ------------------------------------------------------------------ #
    _COMANDOS = ("diga ", "responda ", "liste ", "abra ", "crie ", "apague ",
                 "edite ", "execute ", "rode ", "faça ", "faca ", "gere ",
                 "instale ", "baixe ", "mova ", "copie ", "salve ", "envie ",
                 "pesquise ", "navegue ", "clique ", "preencha ", "teste ")

    @classmethod
    def _ruido(cls, fato: str) -> str:
        t = (fato or "").strip()
        low = normalizar(t)
        if len(t) < 8:
            return "curto"
        if t.endswith("?"):
            return "pergunta"
        if low.startswith(cls._COMANDOS):
            return "comando"
        if low in {"ok", "ola", "bom dia", "boa tarde", "boa noite", "obrigado"}:
            return "saudacao"
        if len(re.findall(r"\w+", low)) < 3:
            return "sem contexto"
        return ""

    def _contraditorio(self, fato: str) -> int | None:
        """Fato com quase as mesmas palavras mas número diferente → obsoleto.

        Antes varria a tabela INTEIRA a cada gravação (O(N) dentro do lock de
        escrita) — gravar não escalava. Agora pré-filtra por FTS5: só os fatos
        que compartilham termos entram no Jaccard; sem FTS, cai para uma
        varredura limitada aos mais recentes.
        """
        novo = set(normalizar(fato).split())
        numeros_novos = set(re.findall(r"\d+", fato))
        if not numeros_novos or len(novo) < 3:
            return None
        novo_palavras = {t for t in novo if not any(c.isdigit() for c in t)}
        if not novo_palavras:
            return None

        candidatos = []
        q = fts_query(" ".join(novo_palavras))
        if q and self._fts:
            try:
                candidatos = self.conn.execute(
                    "SELECT f.id, f.fato FROM facts_fts JOIN facts f "
                    "ON f.id = facts_fts.rowid WHERE facts_fts MATCH ? "
                    "AND f.obsoleto=0 ORDER BY bm25(facts_fts) LIMIT 50",
                    (q,)).fetchall()
            except sqlite3.DatabaseError:
                candidatos = []
        if not candidatos:
            candidatos = self.conn.execute(
                "SELECT id, fato FROM facts WHERE obsoleto=0 "
                "ORDER BY id DESC LIMIT 200").fetchall()

        for row in candidatos:
            velho = set(normalizar(row["fato"]).split())
            if not velho:
                continue
            # compara sem os tokens numéricos (IP, valor, data mudam)
            velho_palavras = {t for t in velho if not any(c.isdigit() for c in t)}
            if not velho_palavras:
                continue
            jaccard = (len(novo_palavras & velho_palavras)
                       / len(novo_palavras | velho_palavras))
            if jaccard >= 0.8:
                numeros_velhos = set(re.findall(r"\d+", row["fato"]))
                if numeros_velhos and numeros_velhos != numeros_novos:
                    return int(row["id"])
        return None

    def store(self, fact: str, fonte: str = "", tags: str = "",
              confianca: float = 0.8, validade: str = "") -> bool:
        fact = (fact or "").strip()
        if self._ruido(fact):
            return False
        confianca = max(0.0, min(1.0, float(confianca)))
        h = hash_texto(fact)
        try:
            with self._lock, self.conn:
                antigo = self.conn.execute(
                    "SELECT id FROM facts WHERE hash=? AND obsoleto=0",
                    (h,)).fetchone()
                if antigo:
                    self.conn.execute(
                        "UPDATE facts SET ts=?, confianca=MAX(confianca,?) WHERE id=?",
                        (datetime.now().isoformat(timespec="seconds"),
                         confianca, antigo["id"]))
                    return False
                conflito = self._contraditorio(fact)
                if conflito:
                    self.conn.execute(
                        "UPDATE facts SET obsoleto=1 WHERE id=?", (conflito,))
                cur = self.conn.execute(
                    "INSERT INTO facts (hash, fato, ts, fonte, tags, confianca, "
                    "revisar, validade) VALUES (?,?,?,?,?,?,?,?)",
                    (h, fact[:2000],
                     datetime.now().isoformat(timespec="seconds"),
                     fonte[:60], tags[:200], confianca,
                     1 if confianca < 0.6 else 0, validade or ""))
            return cur.rowcount > 0
        except sqlite3.DatabaseError:
            return False

    def store_many(self, fatos: list[str], fonte: str = "",
                   tags: str = "") -> int:
        total = 0
        for f in fatos:
            if self.store(f, fonte=fonte, tags=tags):
                total += 1
        return total

    def maybe_store(self, user_msg: str, answer: str):
        triggers = ("meu ", "minha ", "eu sou", "eu uso", "prefiro", "trabalho",
                    "cliente", "sempre", "nunca")
        low = (user_msg or "").lower()
        if any(t in low for t in triggers) and len(user_msg) < 400:
            self.store(f"Usuário: {user_msg.strip()}", fonte="conversa")

    # ------------------------------------------------------------------ #
    # Leitura
    # ------------------------------------------------------------------ #
    def search(self, query: str, top_k: int = 5) -> list[str]:
        top_k = max(1, min(int(top_k), 500))
        q = fts_query(query)
        filtro = ("f.obsoleto=0 AND f.revisar=0 AND "
                  "(f.validade IS NULL OR f.validade='' OR f.validade >= date('now'))")
        if q and self._fts:
            try:
                rows = self.conn.execute(
                    "SELECT f.fato FROM facts_fts JOIN facts f "
                    "ON f.id = facts_fts.rowid WHERE facts_fts MATCH ? "
                    f"AND {filtro} ORDER BY bm25(facts_fts) LIMIT ?",
                    (q, top_k)).fetchall()
                if rows:
                    return [r[0] for r in rows]
            except sqlite3.DatabaseError:
                pass
        if not q:
            return self.recentes(top_k)
        padrao = f"%{normalizar(query)}%"
        rows = self.conn.execute(
            "SELECT fato FROM facts WHERE lower(fato) LIKE ? "
            "AND obsoleto=0 AND revisar=0 ORDER BY id DESC LIMIT ?",
            (padrao, top_k)).fetchall()
        return [r[0] for r in rows]

    def recentes(self, limite: int = 5) -> list[str]:
        try:
            rows = self.conn.execute(
                "SELECT fato FROM facts WHERE obsoleto=0 AND revisar=0 "
                "ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limite), 500)),)).fetchall()
            return [r[0] for r in rows]
        except sqlite3.ProgrammingError:
            return []

    def todos(self, limite: int = 500) -> list[str]:
        return self.recentes(limite)

    def substituir(self, fatos: list[str], fonte: str = "consolidacao") -> int:
        """Troca o conjunto de fatos (usado pela consolidação periódica)."""
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM facts")
            otimizar_fts(self.conn, "facts_fts")
        total = self.store_many(fatos, fonte=fonte)
        self.exportar_jsonl()
        return total

    # ------------------------------------------------------------------ #
    # Manutenção
    # ------------------------------------------------------------------ #
    def consolidar(self, min_chars: int = 12) -> dict:
        """Limpeza: ruído óbvio, duplicatas e fatos vencidos/obsoletos antigos."""
        removidos = 0
        with self._lock, self.conn:
            cur = self.conn.execute(
                "DELETE FROM facts WHERE length(trim(fato)) < ?", (min_chars,))
            removidos += cur.rowcount
            cur = self.conn.execute(
                "DELETE FROM facts WHERE validade != '' AND validade < date('now')")
            removidos += cur.rowcount
            cur = self.conn.execute(
                "DELETE FROM facts WHERE obsoleto=1 AND ts < datetime('now','-30 day')")
            removidos += cur.rowcount
            repetidos = self.conn.execute("""
                SELECT id FROM facts WHERE id NOT IN (
                    SELECT MIN(id) FROM facts GROUP BY hash)
            """).fetchall()
            for (fid,) in repetidos:
                self.conn.execute("DELETE FROM facts WHERE id=?", (fid,))
                removidos += 1
            if removidos:
                otimizar_fts(self.conn, "facts_fts")
        return {"removidos": removidos, "restantes": self.contar()}

    def exportar_jsonl(self, destino: Path | str | None = None) -> str:
        alvo = Path(destino) if destino else self.jsonl
        alvo.parent.mkdir(parents=True, exist_ok=True)
        linhas = []
        for row in self.conn.execute(
                "SELECT ts, fato, fonte FROM facts ORDER BY id"):
            linhas.append(json.dumps(
                {"ts": row["ts"], "fact": row["fato"], "fonte": row["fonte"]},
                ensure_ascii=False))
        alvo.write_text("\n".join(linhas) + ("\n" if linhas else ""),
                        encoding="utf-8")
        return str(alvo)

    def contar(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    def estatisticas(self) -> dict:
        def um(sql):
            try:
                return self.conn.execute(sql).fetchone()[0]
            except sqlite3.DatabaseError:
                return 0
        return {
            "fatos": self.contar(),
            "revisar": um("SELECT COUNT(*) FROM facts WHERE revisar=1 AND obsoleto=0"),
            "obsoletos": um("SELECT COUNT(*) FROM facts WHERE obsoleto=1"),
            "fts": self._fts,
            "mb": round(self.db_path.stat().st_size / 1048576, 2)
            if self.db_path.exists() else 0,
            "jsonl": str(self.jsonl) if self.jsonl.exists() else "",
        }

    def otimizar(self) -> dict:
        with self._lock:
            try:
                self.conn.execute("PRAGMA optimize")
            except sqlite3.DatabaseError:
                pass
            if self._fts:
                otimizar_fts(self.conn, "facts_fts")
            self.conn.commit()
        return self.estatisticas()

    def fechar(self) -> None:
        try:
            self.otimizar()
            self.conn.close()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
