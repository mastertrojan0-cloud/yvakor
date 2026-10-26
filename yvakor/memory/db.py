"""
YVAKOR — utilitários de SQLite para a memória

Centraliza o que faz diferença de performance em todos os bancos do agente:

  • PRAGMAs de produção (WAL, synchronous=NORMAL, cache, mmap, busy_timeout)
  • criação idempotente de índices FTS5 com triggers de sincronização
  • versão de schema em tabela `meta`
  • hash normalizado para deduplicação de fatos
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
import unicodedata
from pathlib import Path

PRAGMAS = (
    "journal_mode=WAL",
    "synchronous=NORMAL",
    "busy_timeout=5000",
    "cache_size=-16000",        # 16 MB de cache de páginas
    "temp_store=MEMORY",
    "mmap_size=67108864",       # 64 MB mapeados
    "wal_autocheckpoint=400",
)


def _abrir_conn(caminho: str) -> sqlite3.Connection:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    for p in PRAGMAS:
        try:
            conn.execute(f"PRAGMA {p}")
        except sqlite3.DatabaseError:
            pass
    return conn


class ConexaoThreadLocal:
    """Uma conexão SQLite por thread (WAL permite leituras concorrentes).

    Antes um único `sqlite3.Connection` era compartilhado entre a thread da
    conversa e as threads daemon (absorção, avaliação, sync do vault,
    manutenção). Como uma conexão tem UMA transação, uma leitura numa thread
    entrava na transação de escrita de outra — causando rollback cruzado e
    erros intermitentes ("database is locked", "Recursive use of cursors").

    Esta classe entrega a cada thread a sua própria conexão, de forma
    transparente: o código segue usando `self.conn.execute(...)` e
    `with self.conn:` como antes. Expõe só o que a memória usa.
    """

    def __init__(self, caminho: Path | str):
        self._caminho = str(caminho)
        self._local = threading.local()
        self._todas: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self.row_factory = sqlite3.Row
        self._obter()  # cria a conexão da thread atual (schema/migração no init)

    def _obter(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = _abrir_conn(self._caminho)
            conn.row_factory = self.row_factory
            self._local.conn = conn
            with self._lock:
                self._todas.append(conn)
        return conn

    # --- proxy dos métodos usados pela memória --- #
    def execute(self, *a, **k):
        return self._obter().execute(*a, **k)

    def executemany(self, *a, **k):
        return self._obter().executemany(*a, **k)

    def executescript(self, *a, **k):
        return self._obter().executescript(*a, **k)

    def cursor(self, *a, **k):
        return self._obter().cursor(*a, **k)

    def commit(self):
        return self._obter().commit()

    def rollback(self):
        return self._obter().rollback()

    def backup(self, *a, **k):
        return self._obter().backup(*a, **k)

    def create_function(self, *a, **k):
        return self._obter().create_function(*a, **k)

    def __enter__(self):
        return self._obter().__enter__()

    def __exit__(self, *a):
        return self._obter().__exit__(*a)

    def close(self):
        with self._lock:
            for conn in self._todas:
                try:
                    conn.close()
                except Exception:
                    pass
            self._todas.clear()
        try:
            self._local.conn = None
        except Exception:
            pass


def conectar(caminho: Path | str) -> ConexaoThreadLocal:
    return ConexaoThreadLocal(caminho)


def tem_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts_probe")
        return True
    except sqlite3.DatabaseError:
        return False


def tabela_existe(conn: sqlite3.Connection, nome: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (nome,)).fetchone()
    return row is not None


def colunas(conn: sqlite3.Connection, tabela: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
    except sqlite3.DatabaseError:
        return set()


def meta_get(conn: sqlite3.Connection, chave: str, padrao: str = "") -> str:
    try:
        row = conn.execute("SELECT valor FROM meta WHERE chave=?",
                           (chave,)).fetchone()
        return row[0] if row else padrao
    except sqlite3.DatabaseError:
        return padrao


def meta_set(conn: sqlite3.Connection, chave: str, valor) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, "
                 "valor TEXT)")
    conn.execute("INSERT INTO meta (chave, valor) VALUES (?,?) "
                 "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                 (chave, str(valor)))


def normalizar(texto: str) -> str:
    """minúsculas, sem acento, espaços colapsados — base para dedup e busca."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


def hash_texto(texto: str) -> str:
    return hashlib.sha1(normalizar(texto).encode("utf-8")).hexdigest()[:20]


def fts_query(termo: str, minimo: int = 3) -> str:
    """Converte texto livre em consulta FTS5 segura (termos com OR).

    Palavras longas viram prefixo ("relatorio"*) para casar plural/variações,
    que é o erro mais comum em português ("relatórios" × "relatorio").
    """
    palavras = [p for p in re.findall(r"\w+", normalizar(termo))
                if len(p) >= minimo]
    if not palavras:
        return ""
    vistos: list[str] = []
    for p in palavras:
        if p not in vistos:
            vistos.append(p)
    termos = [f'"{p}"*' if len(p) >= 5 else f'"{p}"' for p in vistos[:12]]
    return " OR ".join(termos)


def criar_fts(conn: sqlite3.Connection, nome: str, tabela: str,
              campos: list[str], id_col: str = "id") -> bool:
    """Cria tabela FTS5 (external content) + triggers de sincronização.

    Idempotente: se já existe, não recria nem reindexa.
    """
    if not tem_fts5(conn):
        return False
    if tabela_existe(conn, nome):
        return True
    cols = ", ".join(campos)
    conn.execute(
        f"CREATE VIRTUAL TABLE {nome} USING fts5({cols}, content='{tabela}', "
        f"content_rowid='{id_col}', tokenize='unicode61 remove_diacritics 2')")
    novos = ", ".join(f"new.{c}" for c in campos)
    velhos = ", ".join(f"old.{c}" for c in campos)
    for gatilho, corpo in (
        (f"{nome}_ai", f"INSERT INTO {nome}(rowid, {cols}) "
                       f"VALUES (new.{id_col}, {novos})"),
        (f"{nome}_ad", f"INSERT INTO {nome}({nome}, rowid, {cols}) "
                       f"VALUES('delete', old.{id_col}, {velhos})"),
        (f"{nome}_au", f"INSERT INTO {nome}({nome}, rowid, {cols}) "
                       f"VALUES('delete', old.{id_col}, {velhos}); "
                       f"INSERT INTO {nome}(rowid, {cols}) "
                       f"VALUES (new.{id_col}, {novos})"),
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {gatilho}")
        evento = {"ai": "INSERT", "ad": "DELETE", "au": "UPDATE"}[gatilho[-2:]]
        conn.execute(f"CREATE TRIGGER {gatilho} AFTER {evento} ON {tabela} "
                     f"BEGIN {corpo}; END")
    conn.execute(f"INSERT INTO {nome}({nome}) VALUES('rebuild')")
    return True


def otimizar_fts(conn: sqlite3.Connection, nome: str) -> None:
    if tabela_existe(conn, nome):
        try:
            conn.execute(f"INSERT INTO {nome}({nome}) VALUES('optimize')")
        except sqlite3.DatabaseError:
            pass
