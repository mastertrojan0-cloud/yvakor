"""
YVAKOR — Telemetria (custo, latência e origem de cada resposta)

Registra uma linha por resposta em data/telemetria.db:
quem respondeu (cérebro/receita/local/api), provedor, duração, ferramentas e
sucesso. É a base do painel de economia de IA.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from yvakor.memory.db import conectar
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


class Telemetria:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else (ROOT / "data" / "telemetria.db")
        self.conn = conectar(self.db_path)
        self._lock = threading.Lock()
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                origem TEXT NOT NULL,
                provedor TEXT DEFAULT '',
                ms REAL DEFAULT 0,
                ferramentas INTEGER DEFAULT 0,
                ok INTEGER DEFAULT 1,
                detalhe TEXT DEFAULT ''
            )""")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos(ts)")
        self.conn.execute(
            "DELETE FROM eventos WHERE ts < datetime('now','-90 day')")
        self.conn.commit()

    def registrar(self, origem: str, ms: float, ok: bool = True,
                  provedor: str = "", ferramentas: int = 0,
                  detalhe: str = "") -> None:
        try:
            with self._lock, self.conn:
                self.conn.execute(
                    "INSERT INTO eventos (ts, origem, provedor, ms, ferramentas, "
                    "ok, detalhe) VALUES (?,?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), origem[:30],
                     provedor[:30], round(float(ms), 1), int(ferramentas),
                     1 if ok else 0, detalhe[:200]))
        except sqlite3.DatabaseError:
            pass

    def resumo(self, dias: int = 7) -> dict:
        desde = (datetime.now() - timedelta(days=max(1, int(dias)))).isoformat()
        rows = self.conn.execute(
            "SELECT origem, COUNT(*), AVG(ms), SUM(ferramentas), "
            "SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) "
            "FROM eventos WHERE ts >= ? GROUP BY origem ORDER BY 2 DESC",
            (desde,)).fetchall()
        por_origem = {r[0]: {"chamadas": r[1], "ms_medio": round(r[2] or 0, 1),
                             "ferramentas": r[3] or 0, "falhas": r[4] or 0}
                      for r in rows}
        total = sum(v["chamadas"] for v in por_origem.values())
        sem_ia = sum(v["chamadas"] for k, v in por_origem.items()
                     if k in ("cerebro", "receita"))
        return {"dias": dias, "total": total, "por_origem": por_origem,
                "sem_ia": sem_ia,
                "economia_pct": round(sem_ia / total * 100, 1) if total else 0}

    def recentes(self, limite: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ts, origem, provedor, ms, ferramentas, ok, detalhe "
            "FROM eventos ORDER BY id DESC LIMIT ?",
            (max(1, int(limite)),)).fetchall()
        return [dict(r) for r in rows]

    def fechar(self) -> None:
        try:
            self.conn.execute("PRAGMA optimize")
            self.conn.close()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
