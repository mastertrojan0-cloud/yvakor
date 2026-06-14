"""Memória episódica — o que aconteceu (SQLite, stdlib pura).
Suporte a múltiplas conversas: cada sessão agrupa episódios.
"""
from __future__ import annotations
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime


class EpisodicMemory:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self._ensure_active_session()

    # ------------------------------------------------------------------ #
    # Schema / Migração
    # ------------------------------------------------------------------ #
    def _migrate(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                input TEXT,
                output TEXT,
                success INTEGER DEFAULT 1,
                session_id TEXT
            )""")
        # Coluna session_id (v0.2): adiciona se não existir
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(episodes)").fetchall()}
        if "session_id" not in cols:
            self.conn.execute("ALTER TABLE episodes ADD COLUMN session_id TEXT")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                active INTEGER DEFAULT 0
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_usage (
                skill TEXT NOT NULL,
                ts TEXT NOT NULL,
                success INTEGER DEFAULT 1
            )""")
        self.conn.commit()

    # ------------------------------------------------------------------ #
    # Sessões
    # ------------------------------------------------------------------ #
    def _ensure_active_session(self):
        """Garante que existe pelo menos uma sessão ativa."""
        active = self.conn.execute(
            "SELECT id FROM sessions WHERE active=1 LIMIT 1").fetchone()
        if not active:
            # Reativa a última sessão, ou cria uma nova
            last = self.conn.execute(
                "SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1").fetchone()
            if last:
                self.conn.execute("UPDATE sessions SET active=1 WHERE id=?", (last[0],))
            else:
                self._create_session("Conversa 1")
            self.conn.commit()

    def _create_session(self, title: str = "") -> str:
        sid = str(uuid.uuid4())[:8]
        # Desativa todas as outras
        self.conn.execute("UPDATE sessions SET active=0")
        if not title:
            total = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            title = f"Conversa {total + 1}"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO sessions (id, title, created_at, active) VALUES (?,?,?,1)",
            (sid, title, ts))
        self.conn.commit()
        return sid

    @property
    def active_id(self) -> str | None:
        row = self.conn.execute(
            "SELECT id FROM sessions WHERE active=1 LIMIT 1").fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ #
    # Log
    # ------------------------------------------------------------------ #
    def log(self, kind: str, inp: str, out: str, success: bool = True):
        self.conn.execute(
            "INSERT INTO episodes (ts, kind, input, output, success, session_id) "
            "VALUES (?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), kind,
             inp[:4000], out[:4000], int(success), self.active_id))
        self.conn.commit()

    def last_interactions(self, n: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT ts, kind, input, output FROM episodes "
            "WHERE kind='conversa' AND session_id=? "
            "ORDER BY id DESC LIMIT ?", (self.active_id, n)).fetchall()
        out = []
        for ts, kind, inp, outp in reversed(rows):
            out.append(f"[{ts}] usuário: {inp[:200]}")
            out.append(f"[{ts}] yvakor: {(outp or '')[:200]}")
        return out

    def history_messages(self, n: int) -> list[dict]:
        """Últimos n turnos da conversa ativa como mensagens reais
        [{"role":"user"|"assistant","content":...}] para enviar ao modelo.
        Diferente de last_interactions (texto truncado p/ system prompt),
        aqui devolvemos o conteúdo completo como diálogo multi-turno."""
        rows = self.conn.execute(
            "SELECT input, output FROM episodes "
            "WHERE kind='conversa' AND session_id=? "
            "ORDER BY id DESC LIMIT ?", (self.active_id, n)).fetchall()
        msgs: list[dict] = []
        for inp, outp in reversed(rows):
            if inp:
                msgs.append({"role": "user", "content": inp})
            if outp:
                msgs.append({"role": "assistant", "content": outp})
        return msgs

    def maybe_autotitle(self, texto: str) -> None:
        """Estilo Claude: dá título à conversa a partir da 1ª mensagem do
        usuário, se ela ainda estiver com o nome automático ('Conversa N')."""
        import re
        sid = self.active_id
        if not sid:
            return
        row = self.conn.execute(
            "SELECT title FROM sessions WHERE id=?", (sid,)).fetchone()
        titulo = (row[0] if row else "") or ""
        n = self.conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE kind='conversa' AND session_id=?",
            (sid,)).fetchone()[0]
        if n <= 1 and (not titulo.strip() or re.match(r"^Conversa \d+$", titulo)):
            novo = " ".join(texto.strip().split())[:48]
            if novo:
                self.renomear_conversa(sid, novo)

    def register_skill_use(self, skill: str, success: bool = True):
        self.conn.execute(
            "INSERT INTO skill_usage (skill, ts, success) VALUES (?,?,?)",
            (skill, datetime.now().isoformat(timespec="seconds"), int(success)))
        self.conn.commit()

    def skill_success_count(self, skill: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM skill_usage WHERE skill=? AND success=1",
            (skill,)).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------ #
    # Gestão de conversas
    # ------------------------------------------------------------------ #
    def nova_conversa(self, titulo: str = "") -> str:
        """Cria uma nova sessão e torna-a ativa. Retorna o id."""
        sid = self._create_session(titulo)
        active = self.conn.execute(
            "SELECT title FROM sessions WHERE id=?", (sid,)).fetchone()
        return f"{sid} ({active[0]})"

    def listar_conversas(self) -> list[dict]:
        """Lista todas as sessões com estatísticas."""
        rows = self.conn.execute(
            "SELECT s.id, s.title, s.created_at, s.active, "
            "(SELECT COUNT(*) FROM episodes e WHERE e.session_id=s.id) AS total "
            "FROM sessions s ORDER BY s.created_at DESC").fetchall()
        return [
            {"id": r[0], "title": r[1], "created_at": r[2],
             "active": bool(r[3]), "episodes": r[4]}
            for r in rows
        ]

    def retomar_conversa(self, sid: str) -> bool:
        """Ativa uma sessão existente. Retorna False se não encontrada."""
        exists = self.conn.execute(
            "SELECT id FROM sessions WHERE id=?", (sid,)).fetchone()
        if not exists:
            return False
        self.conn.execute("UPDATE sessions SET active=0")
        self.conn.execute("UPDATE sessions SET active=1 WHERE id=?", (sid,))
        self.conn.commit()
        return True

    def apagar_conversa(self, sid: str) -> tuple[bool, str]:
        """Remove uma sessão e seus episódios. Não apaga se for a única."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM sessions").fetchone()[0]
        if total <= 1:
            return False, "Não é possível apagar a única conversa."
        active = self.conn.execute(
            "SELECT active FROM sessions WHERE id=?", (sid,)).fetchone()
        if not active:
            return False, "Conversa não encontrada."

        self.conn.execute("DELETE FROM episodes WHERE session_id=?", (sid,))
        self.conn.execute("DELETE FROM sessions WHERE id=?", (sid,))

        # Se apagou a ativa, ativa a mais recente
        if active[0]:
            last = self.conn.execute(
                "SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1").fetchone()
            if last:
                self.conn.execute(
                    "UPDATE sessions SET active=1 WHERE id=?", (last[0],))
        self.conn.commit()
        return True, "Conversa apagada."

    def renomear_conversa(self, sid: str, titulo: str) -> bool:
        exists = self.conn.execute(
            "SELECT id FROM sessions WHERE id=?", (sid,)).fetchone()
        if not exists:
            return False
        self.conn.execute(
            "UPDATE sessions SET title=? WHERE id=?", (titulo, sid))
        self.conn.commit()
        return True

    def episodes_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM episodes").fetchone()
        return row[0] if row else 0

    def mensagens_da_conversa(self, sid: str | None = None) -> list[dict]:
        """Histórico de uma conversa como pares {role, content} (para a UI)."""
        sid = sid or self.active_id
        rows = self.conn.execute(
            "SELECT input, output FROM episodes "
            "WHERE kind='conversa' AND session_id=? ORDER BY id", (sid,)).fetchall()
        msgs = []
        for inp, outp in rows:
            msgs.append({"role": "user", "content": inp or ""})
            msgs.append({"role": "yvakor", "content": outp or ""})
        return msgs
