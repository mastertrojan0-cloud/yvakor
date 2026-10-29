"""YVAKOR — memória estatística do entorno (data/entorno.db).

Aprende de forma incremental, sem guardar o dado bruto:
  métricas → média e variância móveis por hora da semana (168 faixas),
             por hora do dia (24) e geral; a janela é limitada, então o
             perfil se adapta quando a rotina muda;
  itens    → apps, processos, dispositivos e ferramentas já vistos, com
             contagem e horário habitual (novidade = item nunca visto);
  eventos  → anomalias e novidades, com teto de linhas.

Tudo fica em memória e vai ao disco em lote (flush), para o custo por
observação ser só aritmética.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

JANELA = 60          # observações efetivas por faixa (adaptação à mudança)
MIN_SEMANA = 6       # observações mínimas para confiar na faixa semanal
MIN_HORA = 8
MIN_GERAL = 20
MAX_EVENTOS = 3000

GERAL = 999


def faixas(ts: float | None = None) -> tuple[int, int]:
    d = datetime.fromtimestamp(ts or time.time())
    return d.weekday() * 24 + d.hour, 200 + d.hour


class Perfil:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        for p in ("journal_mode=WAL", "synchronous=NORMAL", "busy_timeout=5000"):
            try:
                self.conn.execute(f"PRAGMA {p}")
            except sqlite3.Error:
                pass
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS metricas (
                chave TEXT, faixa INTEGER, n INTEGER, media REAL, var REAL,
                PRIMARY KEY (chave, faixa));
            CREATE TABLE IF NOT EXISTS itens (
                tipo TEXT, nome TEXT, primeiro REAL, ultimo REAL,
                contagem REAL, horas TEXT, rotulo TEXT DEFAULT '',
                PRIMARY KEY (tipo, nome));
            CREATE TABLE IF NOT EXISTS eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, tipo TEXT,
                chave TEXT, valor REAL, esperado REAL, detalhe TEXT);
            CREATE INDEX IF NOT EXISTS ix_eventos_ts ON eventos(ts);
            CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
        """)
        self.conn.commit()
        self._m: dict[tuple[str, int], list] = {}
        self._i: dict[tuple[str, str], dict] = {}
        self._sujo_m: set = set()
        self._sujo_i: set = set()
        self._carregar()

    def _carregar(self) -> None:
        for chave, faixa, n, media, var in self.conn.execute(
                "SELECT chave, faixa, n, media, var FROM metricas"):
            self._m[(chave, faixa)] = [n, media, var]
        for tipo, nome, pri, ult, cont, horas, rot in self.conn.execute(
                "SELECT tipo, nome, primeiro, ultimo, contagem, horas, rotulo FROM itens"):
            try:
                h = json.loads(horas or "[]")
            except ValueError:
                h = []
            self._i[(tipo, nome)] = {"primeiro": pri, "ultimo": ult,
                                     "contagem": cont, "rotulo": rot or "",
                                     "horas": (h + [0] * 24)[:24]}

    # ------------------------------------------------------------------ #
    # Métricas
    # ------------------------------------------------------------------ #
    def esperado(self, chave: str, ts: float | None = None) -> tuple[float, float, int] | None:
        """(média, desvio, n) da faixa mais específica que já é confiável."""
        semana, hora = faixas(ts)
        with self._lock:
            for faixa, minimo in ((semana, MIN_SEMANA), (hora, MIN_HORA),
                                  (GERAL, MIN_GERAL)):
                s = self._m.get((chave, faixa))
                if s and s[0] >= minimo:
                    return s[1], math.sqrt(max(s[2], 0.0)), s[0]
        return None

    def observar(self, chave: str, valor: float, ts: float | None = None) -> float | None:
        """Atualiza o perfil e devolve o z-score em relação ao esperado ANTES."""
        exp = self.esperado(chave, ts)
        z = None
        if exp is not None:
            media, desvio, _ = exp
            # piso no desvio: série quase constante não vira alarme por ruído
            piso = max(abs(media) * 0.05, 0.5)
            z = (valor - media) / max(desvio, piso)
        with self._lock:
            for faixa in (*faixas(ts), GERAL):
                s = self._m.setdefault((chave, faixa), [0, valor, 0.0])
                n = s[0]
                a = 1.0 / min(n + 1, JANELA)
                delta = valor - s[1]
                s[1] += a * delta
                s[2] = (1 - a) * (s[2] + a * delta * delta)
                s[0] = n + 1
                self._sujo_m.add((chave, faixa))
        return z

    def curva(self, chave: str) -> list[dict]:
        """Valor esperado em cada hora do dia (faixa horária)."""
        with self._lock:
            out = []
            for h in range(24):
                s = self._m.get((chave, 200 + h))
                if s:
                    out.append({"hora": h, "media": round(s[1], 2),
                                "desvio": round(math.sqrt(max(s[2], 0)), 2),
                                "n": s[0]})
            return out

    def chaves(self) -> list[str]:
        with self._lock:
            return sorted({c for c, f in self._m if f == GERAL})

    # ------------------------------------------------------------------ #
    # Itens (novidade e hábito)
    # ------------------------------------------------------------------ #
    def item(self, tipo: str, nome: str, peso: float = 1.0,
             ts: float | None = None, rotulo: str = "") -> bool:
        """Registra o item; devolve True se nunca tinha sido visto."""
        ts = ts or time.time()
        hora = datetime.fromtimestamp(ts).hour
        with self._lock:
            it = self._i.get((tipo, nome))
            novo = it is None
            if novo:
                it = {"primeiro": ts, "ultimo": ts, "contagem": 0.0,
                      "rotulo": rotulo, "horas": [0] * 24}
                self._i[(tipo, nome)] = it
            it["ultimo"] = max(it["ultimo"], ts)
            it["contagem"] += peso
            it["horas"][hora] += 1
            if rotulo:
                it["rotulo"] = rotulo
            self._sujo_i.add((tipo, nome))
        return novo

    def itens(self, tipo: str, limite: int = 10) -> list[dict]:
        with self._lock:
            lista = [{"nome": n, **v} for (t, n), v in self._i.items() if t == tipo]
        lista.sort(key=lambda x: -x["contagem"])
        return lista[:limite]

    def tem_itens(self, tipo: str) -> bool:
        with self._lock:
            return any(t == tipo for t, _ in self._i)

    def esquecer(self, tipo: str, nome: str = "") -> int:
        with self._lock:
            alvo = [k for k in self._i if k[0] == tipo and (not nome or k[1] == nome)]
            for k in alvo:
                self._i.pop(k, None)
                self._sujo_i.discard(k)
            with self.conn:
                if nome:
                    self.conn.execute("DELETE FROM itens WHERE tipo=? AND nome=?",
                                      (tipo, nome))
                else:
                    self.conn.execute("DELETE FROM itens WHERE tipo=?", (tipo,))
        return len(alvo)

    # ------------------------------------------------------------------ #
    # Eventos e meta
    # ------------------------------------------------------------------ #
    def evento(self, tipo: str, chave: str, valor: float = 0.0,
               esperado: float = 0.0, detalhe: str = "") -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO eventos (ts, tipo, chave, valor, esperado, detalhe) "
                "VALUES (?,?,?,?,?,?)",
                (time.time(), tipo, chave, valor, esperado, detalhe[:300]))

    def eventos(self, horas: float = 24, tipo: str = "", limite: int = 30) -> list[dict]:
        desde = time.time() - horas * 3600
        sql = "SELECT ts, tipo, chave, valor, esperado, detalhe FROM eventos WHERE ts>=?"
        params: list = [desde]
        if tipo:
            sql += " AND tipo=?"
            params.append(tipo)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(int(limite))
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [{"em": datetime.fromtimestamp(r[0]).strftime("%d/%m %H:%M"),
                 "tipo": r[1], "chave": r[2], "valor": round(r[3], 2),
                 "esperado": round(r[4], 2), "detalhe": r[5]} for r in rows]

    def meta(self, chave: str, valor: str | None = None) -> str | None:
        with self._lock:
            if valor is None:
                r = self.conn.execute("SELECT valor FROM meta WHERE chave=?",
                                      (chave,)).fetchone()
                return r[0] if r else None
            with self.conn:
                self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                                  (chave, valor))
            return valor

    # ------------------------------------------------------------------ #
    def flush(self) -> int:
        with self._lock:
            m = [(c, f, *self._m[(c, f)]) for c, f in self._sujo_m if (c, f) in self._m]
            i = [(t, n, v["primeiro"], v["ultimo"], v["contagem"],
                  json.dumps(v["horas"]), v["rotulo"])
                 for (t, n) in self._sujo_i if (v := self._i.get((t, n)))]
            self._sujo_m.clear()
            self._sujo_i.clear()
            with self.conn:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO metricas VALUES (?,?,?,?,?)", m)
                self.conn.executemany(
                    "INSERT OR REPLACE INTO itens VALUES (?,?,?,?,?,?,?)", i)
                self.conn.execute(
                    "DELETE FROM eventos WHERE id <= (SELECT MAX(id) FROM eventos) - ?",
                    (MAX_EVENTOS,))
        return len(m) + len(i)

    def fechar(self) -> None:
        try:
            self.flush()
            self.conn.close()
        except sqlite3.Error:
            pass
