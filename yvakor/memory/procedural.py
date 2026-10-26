"""
YVAKOR — Memória procedural (skills em markdown)

Os arquivos continuam sendo a fonte da verdade (editáveis à mão, versionáveis).
O que mudou: um índice SQLite + FTS5 evita reler todos os arquivos a cada
mensagem e faz o ranking por relevância em milissegundos.

  data/skills.db  → tabela `skills` + `skills_fts`
  reindexação     → incremental por mtime/hash (só o que mudou)
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path

from yvakor.memory.db import (
    conectar, criar_fts, fts_query, hash_texto, otimizar_fts, tem_fts5,
)

ROOT = Path(__file__).resolve().parent.parent.parent
INTERVALO_SYNC = 5.0     # segundos entre verificações de mtime


class SkillLibrary:
    def __init__(self, path: Path, db_path: Path | None = None):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else (ROOT / "data" / "skills.db")
        self.conn = conectar(self.db_path)
        self._lock = threading.RLock()
        self._fts = tem_fts5(self.conn)
        self._ultimo_sync = 0.0
        self._migrar()
        self.sincronizar(forcar=True)

    # ------------------------------------------------------------------ #
    def _migrar(self) -> None:
        with self._lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT UNIQUE NOT NULL,
                    titulo TEXT DEFAULT '',
                    tags TEXT DEFAULT '',
                    conteudo TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    ts TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
                CREATE INDEX IF NOT EXISTS idx_skills_nome ON skills(nome);
            """)
            self._fts = criar_fts(self.conn, "skills_fts", "skills",
                                  ["titulo", "tags", "conteudo"], id_col="id")
            if not self._fts:
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_skills_titulo ON skills(titulo)")
            self.conn.commit()

    @staticmethod
    def _ler_meta(texto: str) -> tuple[str, str]:
        """Extrai (titulo, tags) do cabeçalho markdown/front-matter."""
        titulo, tags = "", ""
        m = re.search(r"<!--\s*skill:\s*([^|>]+)(?:\|\s*tags:\s*([^>]+))?-->",
                      texto, re.I)
        if m:
            titulo = (m.group(1) or "").strip()
            tags = (m.group(2) or "").strip()
        if not titulo:
            for linha in texto.splitlines():
                if linha.startswith("# "):
                    titulo = linha[2:].strip()
                    break
        if not tags:
            m2 = re.search(r"^tags:\s*\[?([^\]\n]+)", texto, re.M | re.I)
            if m2:
                tags = m2.group(1).strip()
        return titulo[:160], tags[:200]

    # ------------------------------------------------------------------ #
    def sincronizar(self, forcar: bool = False) -> dict:
        agora = time.time()
        if not forcar and (agora - self._ultimo_sync) < INTERVALO_SYNC:
            return {"ok": True, "pulado": True}
        self._ultimo_sync = agora
        vistos, novos, atualizados = set(), 0, 0
        with self._lock:
            for arquivo in self.path.glob("*.md"):
                nome = arquivo.stem
                vistos.add(nome)
                try:
                    mtime = arquivo.stat().st_mtime
                except OSError:
                    continue
                atual = self.conn.execute(
                    "SELECT hash, mtime FROM skills WHERE nome=?", (nome,)).fetchone()
                if atual and abs(float(atual["mtime"]) - mtime) < 0.001:
                    continue
                try:
                    texto = arquivo.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                h = hash_texto(texto)
                if atual and atual["hash"] == h:
                    self.conn.execute("UPDATE skills SET mtime=? WHERE nome=?",
                                      (mtime, nome))
                    continue
                titulo, tags = self._ler_meta(texto)
                self.conn.execute("""
                    INSERT INTO skills (nome, titulo, tags, conteudo, hash, mtime, ts)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(nome) DO UPDATE SET
                      titulo=excluded.titulo, tags=excluded.tags,
                      conteudo=excluded.conteudo, hash=excluded.hash,
                      mtime=excluded.mtime, ts=excluded.ts
                """, (nome, titulo, tags, texto[:20000], h, mtime,
                      time.strftime("%Y-%m-%d %H:%M:%S")))
                if atual:
                    atualizados += 1
                else:
                    novos += 1
            # remove skills apagadas do disco
            nomes_db = {r[0] for r in self.conn.execute("SELECT nome FROM skills")}
            apagados = 0
            for nome in nomes_db - vistos:
                self.conn.execute("DELETE FROM skills WHERE nome=?", (nome,))
                apagados += 1
            if self._fts and (novos or atualizados or apagados):
                otimizar_fts(self.conn, "skills_fts")
            self.conn.commit()
        return {"ok": True, "novos": novos, "atualizados": atualizados,
                "apagados": apagados, "total": len(vistos)}

    # ------------------------------------------------------------------ #
    def all_skills(self) -> list[Path]:
        self.sincronizar()
        return sorted(self.path.glob("*.md"))

    def find_relevant(self, query: str, top_k: int = 2) -> list[str]:
        self.sincronizar()
        top_k = max(1, min(int(top_k), 10))
        q = fts_query(query)
        if q and self._fts:
            try:
                rows = self.conn.execute(
                    "SELECT conteudo FROM skills_fts JOIN skills s "
                    "ON s.id = skills_fts.rowid WHERE skills_fts MATCH ? "
                    "ORDER BY bm25(skills_fts) LIMIT ?", (q, top_k)).fetchall()
                if rows:
                    return [r[0] for r in rows]
            except sqlite3.DatabaseError:
                pass
        # fallback: palavras no título/conteúdo (bem mais raro agora)
        palavras = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 3}
        if not palavras:
            return []
        candidatos = []
        for row in self.conn.execute(
                "SELECT conteudo, titulo FROM skills"):
            texto = row["conteudo"].lower()
            score = sum(2 for w in palavras if w in row["titulo"].lower())
            score += sum(1 for w in palavras if w in texto)
            if score >= 2:
                candidatos.append((score, row["conteudo"]))
        candidatos.sort(key=lambda x: -x[0])
        return [t for _, t in candidatos[:top_k]]

    # ------------------------------------------------------------------ #
    def save(self, name: str, content: str) -> str:
        seguro = re.sub(r"[^\w\-]+", "_", name.lower()).strip("_")[:60] or "skill"
        arquivo = self.path / f"{seguro}.md"
        arquivo.write_text(content, encoding="utf-8")
        self.sincronizar(forcar=True)
        return seguro

    def estatisticas(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        return {"skills": total, "fts": self._fts,
                "db": str(self.db_path) if self.db_path.exists() else ""}

    def otimizar(self) -> dict:
        self.sincronizar(forcar=True)
        if self._fts:
            otimizar_fts(self.conn, "skills_fts")
        try:
            self.conn.execute("PRAGMA optimize")
            self.conn.commit()
        except sqlite3.DatabaseError:
            pass
        return self.estatisticas()

    def fechar(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
