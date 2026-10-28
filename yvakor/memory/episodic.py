"""
YVAKOR — Memória episódica (o que aconteceu)

SQLite otimizado para crescer com o aprendizado:

  • índices por (sessão, tipo, id) — histórico e listagem em O(log n)
  • contadores denormalizados na tabela de sessões (sem subquery por sessão)
  • FTS5 para busca no conteúdo das conversas (bm25 + trecho destacado)
  • poda de logs operacionais antigos + VACUUM incremental
  • backup consistente via API do SQLite

Mantém a mesma API pública da v0.2 (nada quebra em quem já usa).
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from yvakor.memory.db import (
    conectar, criar_fts, colunas, fts_query, hash_texto, meta_get, meta_set,
    otimizar_fts, tabela_existe, tem_fts5,
)

SCHEMA_VERSAO = 2
KINDS_OPERACIONAIS = ("ferramenta", "manutencao", "bootstrap", "skill_bootstrap")


def _agora(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now().strftime(fmt)


class EpisodicMemory:
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        self.db_path = db_path
        self.conn = conectar(db_path)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._fts = tem_fts5(self.conn)
        self._migrate()
        self._ensure_active_session()

    def modo_privado(self, ativo: bool) -> None:
        """Enquanto ativo, nada é gravado no histórico (conversa privada)."""
        self._local.privado = bool(ativo)

    # ------------------------------------------------------------------ #
    # Schema / migração
    # ------------------------------------------------------------------ #
    def _migrate(self) -> None:
        with self._lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    input TEXT,
                    output TEXT,
                    success INTEGER DEFAULT 1,
                    session_id TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    active INTEGER DEFAULT 0,
                    kind TEXT DEFAULT 'chat',
                    last_at TEXT,
                    last_preview TEXT DEFAULT '',
                    msg_count INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS skill_usage (
                    skill TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    success INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS meta (
                    chave TEXT PRIMARY KEY,
                    valor TEXT
                );
            """)

            # --- migração da v1 (sem contadores) ---
            sess_cols = colunas(self.conn, "sessions")
            for coluna, tipo in (("last_at", "TEXT"),
                                 ("last_preview", "TEXT DEFAULT ''"),
                                 ("msg_count", "INTEGER DEFAULT 0")):
                if coluna not in sess_cols:
                    self.conn.execute(f"ALTER TABLE sessions ADD COLUMN {coluna} {tipo}")

            if "session_id" not in colunas(self.conn, "episodes"):
                self.conn.execute("ALTER TABLE episodes ADD COLUMN session_id TEXT")

            # --- índices que sustentam as consultas quentes ---
            self.conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_ep_session_kind
                    ON episodes(session_id, kind, id DESC);
                CREATE INDEX IF NOT EXISTS idx_ep_kind_id
                    ON episodes(kind, id DESC);
                CREATE INDEX IF NOT EXISTS idx_ep_ts ON episodes(ts);
                CREATE INDEX IF NOT EXISTS idx_usage_skill
                    ON skill_usage(skill, success);
                CREATE INDEX IF NOT EXISTS idx_sessions_kind
                    ON sessions(COALESCE(kind,'chat'), active);
            """)

            if meta_get(self.conn, "schema_versao") != str(SCHEMA_VERSAO):
                self._backfill_sessoes()
                meta_set(self.conn, "schema_versao", SCHEMA_VERSAO)

            self._fts = criar_fts(self.conn, "episodes_fts", "episodes",
                                  ["input", "output"])
            self.conn.commit()

    def _backfill_sessoes(self) -> None:
        """Uma vez só: preenche last_at/preview/msg_count das sessões antigas."""
        self.conn.execute("""
            UPDATE sessions SET
              last_at = COALESCE(last_at,
                  (SELECT MAX(e.ts) FROM episodes e WHERE e.session_id=sessions.id),
                  created_at),
              msg_count = CASE WHEN COALESCE(msg_count,0)=0 THEN
                  (SELECT COUNT(*) FROM episodes e WHERE e.session_id=sessions.id)
                  ELSE msg_count END,
              last_preview = COALESCE(NULLIF(last_preview,''),
                  (SELECT COALESCE(NULLIF(e.output,''), e.input) FROM episodes e
                    WHERE e.session_id=sessions.id AND e.kind='conversa'
                    ORDER BY e.id DESC LIMIT 1), '')
        """)
        # limpa previews gigantes
        self.conn.execute("UPDATE sessions SET last_preview=substr(last_preview,1,180) "
                          "WHERE length(last_preview)>180")

    # ------------------------------------------------------------------ #
    # Sessões
    # ------------------------------------------------------------------ #
    def _ensure_active_session(self) -> None:
        ativa = self.conn.execute(
            "SELECT id FROM sessions WHERE active=1 LIMIT 1").fetchone()
        if ativa:
            return
        ultima = self.conn.execute(
            "SELECT id FROM sessions WHERE COALESCE(kind,'chat')='chat' "
            "ORDER BY COALESCE(last_at, created_at) DESC LIMIT 1").fetchone()
        if ultima:
            self.conn.execute("UPDATE sessions SET active=1 WHERE id=?", (ultima[0],))
        else:
            self._create_session("Conversa 1")
        self.conn.commit()

    def _create_session(self, title: str = "", activate: bool = True,
                        kind: str = "chat") -> str:
        sid = uuid.uuid4().hex[:8]
        if activate:
            self.conn.execute("UPDATE sessions SET active=0")
        if not title:
            total = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            title = f"Conversa {total + 1}"
        ts = _agora()
        self.conn.execute(
            "INSERT INTO sessions (id, title, created_at, active, kind, last_at, "
            "last_preview, msg_count) VALUES (?,?,?,?,?,?,'',0)",
            (sid, title, ts, 1 if activate else 0, kind, ts))
        self.conn.commit()
        return sid

    def create_session(self, title: str = "", activate: bool = False,
                       kind: str = "task") -> str:
        with self._lock:
            return self._create_session(title, activate=activate, kind=kind)

    @property
    def active_id(self) -> str | None:
        row = self.conn.execute(
            "SELECT id FROM sessions WHERE active=1 LIMIT 1").fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ #
    # Escrita
    # ------------------------------------------------------------------ #
    def log(self, kind: str, inp: str, out: str, success: bool = True,
            session_id: str | None = None) -> int:
        if getattr(self._local, "privado", False):
            return 0
        sid = session_id or self.active_id
        entrada = (inp or "")[:4000]
        saida = (out or "")[:4000]
        ts = datetime.now().isoformat(timespec="seconds")
        with self._lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO episodes (ts, kind, input, output, success, session_id) "
                "VALUES (?,?,?,?,?,?)", (ts, kind, entrada, saida, int(success), sid))
            if sid and kind == "conversa":
                preview = entrada if not saida else saida
                self.conn.execute(
                    "UPDATE sessions SET msg_count=COALESCE(msg_count,0)+1, "
                    "last_at=?, last_preview=? WHERE id=?",
                    (ts, preview[:180], sid))
                preview = entrada if (kind != "conversa" or not saida) else saida
        return int(cur.lastrowid)

    def log_many(self, registros: list[tuple]) -> int:
        """Inserção em lote (kind, input, output, [success], [session_id])."""
        if getattr(self._local, "privado", False):
            return 0
        total = 0
        with self._lock, self.conn:
            for r in registros:
                kind, inp, out = r[0], r[1], r[2]
                ok = r[3] if len(r) > 3 else True
                sid = r[4] if len(r) > 4 else self.active_id
                self.conn.execute(
                    "INSERT INTO episodes (ts, kind, input, output, success, "
                    "session_id) VALUES (?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), kind,
                     (inp or "")[:4000], (out or "")[:4000], int(ok), sid))
                total += 1
        return total

    def register_skill_use(self, skill: str, success: bool = True):
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO skill_usage (skill, ts, success) VALUES (?,?,?)",
                (skill, datetime.now().isoformat(timespec="seconds"), int(success)))

    # ------------------------------------------------------------------ #
    # Leitura
    # ------------------------------------------------------------------ #
    def last_interactions(self, n: int, session_id: str | None = None) -> list[str]:
        rows = self.conn.execute(
            "SELECT ts, input, output FROM episodes "
            "WHERE kind='conversa' AND session_id=? ORDER BY id DESC LIMIT ?",
            (session_id or self.active_id, n)).fetchall()
        out = []
        for ts, inp, outp in reversed(rows):
            out.append(f"[{ts}] usuário: {(inp or '')[:200]}")
            out.append(f"[{ts}] yvakor: {(outp or '')[:200]}")
        return out

    def history_messages(self, n: int, session_id: str | None = None) -> list[dict]:
        n = max(1, min(int(n), 12))   # até 6 pares: continuidade sem exagero
        rows = self.conn.execute(
            "SELECT input, output FROM episodes "
            "WHERE kind='conversa' AND session_id=? ORDER BY id DESC LIMIT ?",
            (session_id or self.active_id, n)).fetchall()
        msgs: list[dict] = []
        for inp, outp in reversed(rows):
            if inp:
                msgs.append({"role": "user", "content": inp[:1200]})
            if outp:
                msgs.append({"role": "assistant", "content": outp[:1200]})
        return msgs

    def mensagens_da_conversa(self, sid: str | None = None) -> list[dict]:
        sid = sid or self.active_id
        rows = self.conn.execute(
            "SELECT input, output FROM episodes "
            "WHERE kind='conversa' AND session_id=? ORDER BY id", (sid,)).fetchall()
        msgs = []
        for inp, outp in rows:
            msgs.append({"role": "user", "content": inp or ""})
            msgs.append({"role": "yvakor", "content": outp or ""})
        return msgs

    def buscar(self, termo: str, limite: int = 20,
               session_id: str | None = None, kind: str | None = None) -> list[dict]:
        """Busca no conteúdo das conversas (FTS5, com fallback LIKE)."""
        limite = max(1, min(int(limite), 200))
        q = fts_query(termo)
        if q and self._fts:
            sql = ("SELECT e.id, e.ts, e.kind, e.session_id, s.title, "
                   "snippet(episodes_fts, 0, '[', ']', '…', 14) AS trecho_in, "
                   "snippet(episodes_fts, 1, '[', ']', '…', 14) AS trecho_out, "
                   "bm25(episodes_fts) AS score "
                   "FROM episodes_fts JOIN episodes e ON e.id = episodes_fts.rowid "
                   "LEFT JOIN sessions s ON s.id = e.session_id "
                   "WHERE episodes_fts MATCH ?")
            params: list = [q]
            if session_id:
                sql += " AND e.session_id = ?"
                params.append(session_id)
            if kind:
                sql += " AND e.kind = ?"
                params.append(kind)
            sql += " ORDER BY score LIMIT ?"
            params.append(limite)
            try:
                rows = self.conn.execute(sql, params).fetchall()
                return [self._busca_dict(r) for r in rows]
            except sqlite3.DatabaseError:
                pass
        # fallback simples
        padrao = f"%{termo}%"
        rows = self.conn.execute(
            "SELECT e.id, e.ts, e.kind, e.session_id, s.title, e.input, e.output, 0 "
            "FROM episodes e LEFT JOIN sessions s ON s.id=e.session_id "
            "WHERE (e.input LIKE ? OR e.output LIKE ?) "
            "ORDER BY e.id DESC LIMIT ?", (padrao, padrao, limite)).fetchall()
        return [self._busca_dict(r) for r in rows]

    @staticmethod
    def _busca_dict(r) -> dict:
        texto = (r[5] or "") + " … " + (r[6] or "")
        return {"id": r[0], "ts": r[1], "kind": r[2], "session_id": r[3],
                "titulo": r[4] or "", "trecho": texto.strip()[:400],
                "score": r[7] if len(r) > 7 else 0}

    def listar_conversas(self, kind: str | None = "chat") -> list[dict]:
        sql = ("SELECT id, title, created_at, active, COALESCE(kind,'chat'), "
               "COALESCE(msg_count,0), last_at, COALESCE(last_preview,'') "
               "FROM sessions")
        params: tuple = ()
        if kind is not None:
            sql += " WHERE COALESCE(kind,'chat')=?"
            params = (kind,)
        sql += " ORDER BY COALESCE(last_at, created_at) DESC"
        rows = self.conn.execute(sql, params).fetchall()
        return [{
            "id": r[0], "title": r[1] or "", "created_at": r[2],
            "active": bool(r[3]), "kind": r[4], "episodes": r[5],
            "last_at": r[6] or r[2], "preview": (r[7] or "").strip()[:160],
        } for r in rows]

    def episodes_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    def skill_success_count(self, skill: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM skill_usage WHERE skill=? AND success=1",
            (skill,)).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------ #
    # Gestão de conversas
    # ------------------------------------------------------------------ #
    def nova_conversa(self, titulo: str = "") -> str:
        with self._lock:
            sid = self._create_session(titulo)
        row = self.conn.execute("SELECT title FROM sessions WHERE id=?",
                                (sid,)).fetchone()
        return f"{sid} ({row[0] if row else ''})"

    def conversa_nova_ao_abrir(self) -> str:
        """App/extensão abriram: começa numa conversa nova. Se a ativa ainda está
        vazia (ninguém escreveu nela), reaproveita — sem acumular "Conversa N"
        vazias a cada abertura. As anteriores ficam no histórico."""
        with self._lock:
            row = self.conn.execute(
                "SELECT id, COALESCE(msg_count,0) FROM sessions WHERE active=1 "
                "AND COALESCE(kind,'chat')='chat' LIMIT 1").fetchone()
            if row:
                tem = self.conn.execute(
                    "SELECT 1 FROM episodes WHERE session_id=? AND kind='conversa' "
                    "LIMIT 1", (row[0],)).fetchone()
                if not row[1] and not tem:
                    return row[0]
            return self._create_session("")

    def buscar_conversas(self, termo: str, limite: int = 40) -> list[dict]:
        """Conversas cujo título OU conteúdo (perguntas e respostas) contém o
        termo — para retomar uma conversa antiga pelo que se falou nela."""
        termo = (termo or "").strip()
        if not termo:
            return self.listar_conversas()
        like = f"%{termo.lower()}%"
        achados = self.conn.execute(
            "SELECT session_id, MAX(id), "
            "MAX(CASE WHEN lower(input) LIKE ? THEN input ELSE output END) "
            "FROM episodes WHERE kind='conversa' AND session_id IS NOT NULL AND "
            "(lower(input) LIKE ? OR lower(output) LIKE ?) "
            "GROUP BY session_id", (like, like, like)).fetchall()
        trechos = {sid: (txt or "") for sid, _, txt in achados}
        saida = []
        for s in self.listar_conversas():
            if s["id"] in trechos or termo.lower() in (s["title"] or "").lower():
                t = trechos.get(s["id"], "")
                i = t.lower().find(termo.lower())
                if i >= 0:
                    ini = max(0, i - 50)
                    s = {**s, "trecho": ("…" if ini else "")
                         + " ".join(t[ini:i + len(termo) + 90].split())}
                saida.append(s)
            if len(saida) >= limite:
                break
        return saida

    def retomar_conversa(self, sid: str) -> bool:
        with self._lock:
            existe = self.conn.execute("SELECT 1 FROM sessions WHERE id=?",
                                       (sid,)).fetchone()
            if not existe:
                return False
            self.conn.execute("UPDATE sessions SET active=0")
            self.conn.execute("UPDATE sessions SET active=1 WHERE id=?", (sid,))
            self.conn.commit()
        return True

    def apagar_conversa(self, sid: str) -> tuple[bool, str]:
        with self._lock, self.conn:
            total = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            if total <= 1:
                return False, "Não é possível apagar a única conversa."
            linha = self.conn.execute(
                "SELECT active FROM sessions WHERE id=?", (sid,)).fetchone()
            if not linha:
                return False, "Conversa não encontrada."
            self.conn.execute("DELETE FROM episodes WHERE session_id=?", (sid,))
            self.conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
            if linha[0]:
                ultima = self.conn.execute(
                    "SELECT id FROM sessions WHERE COALESCE(kind,'chat')='chat' "
                    "ORDER BY COALESCE(last_at, created_at) DESC LIMIT 1").fetchone()
                if ultima:
                    self.conn.execute("UPDATE sessions SET active=1 WHERE id=?",
                                      (ultima[0],))
        return True, "Conversa apagada."

    def renomear_conversa(self, sid: str, titulo: str) -> bool:
        with self._lock, self.conn:
            cur = self.conn.execute("UPDATE sessions SET title=? WHERE id=?",
                                    (titulo, sid))
        return cur.rowcount > 0

    def maybe_autotitle(self, texto: str, session_id: str | None = None) -> None:
        import re as _re
        sid = session_id or self.active_id
        if not sid:
            return
        row = self.conn.execute("SELECT title FROM sessions WHERE id=?",
                                (sid,)).fetchone()
        titulo = (row[0] if row else "") or ""
        n = self.conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE kind='conversa' AND session_id=?",
            (sid,)).fetchone()[0]
        if n <= 1 and (not titulo.strip() or _re.match(r"^Conversa \d+$", titulo)):
            novo = " ".join(texto.strip().split())[:48]
            if novo:
                self.renomear_conversa(sid, novo)

    # ------------------------------------------------------------------ #
    # Manutenção / performance
    # ------------------------------------------------------------------ #
    def podar(self, dias: int = 30, max_operacionais: int = 20000) -> dict:
        """Remove logs operacionais antigos, preservando conversas e erros."""
        limite = (datetime.now() - timedelta(days=max(1, int(dias)))).isoformat()
        removidos = 0
        with self._lock, self.conn:
            cur = self.conn.execute(
                "DELETE FROM episodes WHERE kind IN (?,?,?,?) AND ts < ?",
                (*KINDS_OPERACIONAIS, limite))
            removidos += cur.rowcount
            total = self.conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE kind IN (?,?,?,?)",
                KINDS_OPERACIONAIS).fetchone()[0]
            if total > max_operacionais:
                # id do registro mais antigo que deve ser PRESERVADO
                corte = self.conn.execute(
                    "SELECT id FROM episodes WHERE kind IN (?,?,?,?) "
                    "ORDER BY id DESC LIMIT 1 OFFSET ?",
                    (*KINDS_OPERACIONAIS, max(1, max_operacionais) - 1)).fetchone()
                if corte:
                    cur = self.conn.execute(
                        "DELETE FROM episodes WHERE kind IN (?,?,?,?) AND id < ?",
                        (*KINDS_OPERACIONAIS, corte[0]))
                    removidos += cur.rowcount
            if removidos:
                self._recalcular_contadores()
        return {"removidos": removidos, "dias": dias}

    def _recalcular_contadores(self) -> None:
        self.conn.execute("""
            UPDATE sessions SET
              msg_count = (SELECT COUNT(*) FROM episodes e WHERE e.session_id=sessions.id),
              last_at = COALESCE((SELECT MAX(e.ts) FROM episodes e
                                  WHERE e.session_id=sessions.id), last_at)
        """)

    def otimizar(self, forcar_analyze: bool = False) -> dict:
        """Mantém o banco rápido: FTS optimize, ANALYZE e vacuum incremental."""
        resultado = {"fts": False, "analyze": False, "vacuum": False}
        with self._lock:
            try:
                self.conn.execute("PRAGMA optimize")
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.DatabaseError:
                pass
            if self._fts:
                otimizar_fts(self.conn, "episodes_fts")
                resultado["fts"] = True
            ultimo = meta_get(self.conn, "ultimo_analyze")
            precisa = forcar_analyze
            if not precisa and ultimo:
                try:
                    precisa = (datetime.now()
                               - datetime.fromisoformat(ultimo)).days >= 7
                except ValueError:
                    precisa = True
            if precisa or not ultimo:
                try:
                    self.conn.execute("ANALYZE")
                    meta_set(self.conn, "ultimo_analyze", _agora())
                    resultado["analyze"] = True
                except sqlite3.DatabaseError:
                    pass
            try:
                self.conn.execute("PRAGMA incremental_vacuum(500)")
                resultado["vacuum"] = True
            except sqlite3.DatabaseError:
                pass
            self.conn.commit()
        resultado["mb"] = round(self.db_path.stat().st_size / 1048576, 2) \
            if self.db_path.exists() else 0
        return resultado

    def estatisticas(self) -> dict:
        def um(sql, params=()):
            try:
                return self.conn.execute(sql, params).fetchone()[0]
            except sqlite3.DatabaseError:
                return 0
        por_tipo = {r[0]: r[1] for r in self.conn.execute(
            "SELECT kind, COUNT(*) FROM episodes GROUP BY kind ORDER BY 2 DESC")}
        return {
            "episodios": um("SELECT COUNT(*) FROM episodes"),
            "sessoes": um("SELECT COUNT(*) FROM sessions"),
            "conversas": um("SELECT COUNT(*) FROM episodes WHERE kind='conversa'"),
            "por_tipo": por_tipo,
            "fts": self._fts,
            "mb": round(self.db_path.stat().st_size / 1048576, 2)
            if self.db_path.exists() else 0,
            "schema": meta_get(self.conn, "schema_versao", "?"),
        }

    def backup(self, destino: Path | str) -> str:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        alvo = sqlite3.connect(str(destino))
        try:
            with alvo:
                self.conn.backup(alvo)
        finally:
            alvo.close()
        return str(destino)

    def fechar(self) -> None:
        try:
            self.otimizar()
            self.conn.close()
        except Exception:
            pass
