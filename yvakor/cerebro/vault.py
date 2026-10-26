"""
YVAKOR — Cérebro em markdown (estilo Obsidian)

O banco é rápido; o conhecimento, legível e portável. Esta camada mantém um
vault markdown que você abre no Obsidian:

    data/vault/
      Home.md                  → mapa de conteúdo (hub de links)
      Identidade.md            → quem o agente é
      Memoria/<hash>.md        → um fato por nota (Zettelkasten)
      Skills/<nome>.md         → procedimentos aprendidos
      Conversas/<data>-<id>.md → resumo + últimas mensagens

Tudo usa wikilinks `[[Nota]]` e front-matter com tags. O vault é a fonte
legível; `data/cerebro.db` (SQLite + FTS5) é o índice que o agente consulta
em milissegundos — o mesmo truque que o Obsidian usa por baixo.

Sincronização é incremental: só reescreve nota cujo conteúdo mudou e só
reindexa arquivo cujo hash/mtime mudou.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from yvakor.memory.db import (
    conectar, criar_fts, fts_query, hash_texto, meta_get, meta_set,
    normalizar, otimizar_fts, tabela_existe, tem_fts5,
)
from yvakor.cerebro.resolvedor import Resolvedor
from yvakor.cerebro.receitas import (
    ExecutorReceitas, Receita, carregar_todas,
)

ROOT = Path(__file__).resolve().parent.parent.parent
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def _slug(texto: str, limite: int = 60) -> str:
    t = re.sub(r"[^\w\s-]", "", str(texto), flags=re.UNICODE).strip()
    t = re.sub(r"[\s_]+", "-", t).strip("-")
    return (t[:limite] or "nota").lower()


def _frontmatter(titulo: str, tipo: str, tags: list[str], id_: str = "") -> str:
    linhas = ["---", f"titulo: \"{titulo.replace(chr(34), chr(39))}\"",
              f"tipo: {tipo}", f"tags: [{', '.join(t for t in tags if t)}]",
              f"atualizado: {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    if id_:
        linhas.append(f"id: {id_}")
    linhas.append("---\n")
    return "\n".join(linhas)


class Cerebro:
    def __init__(self, settings: dict, episodic, semantic, skills,
                 vault_dir: Path | None = None, db_path: Path | None = None):
        cfg = (settings or {}).get("cerebro", {}) or {}
        self.cfg = cfg
        self.episodic = episodic
        self.semantic = semantic
        self.skills = skills
        self.dir = Path(vault_dir or cfg.get("vault_dir") or (ROOT / "data" / "vault"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else (ROOT / "data" / "cerebro.db")
        self.conn = conectar(self.db_path)
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._fts = tem_fts5(self.conn)
        self._migrar()
        self.resolvedor = Resolvedor(self, self.cfg)
        self.receitas: list[Receita] = []
        self.executor = None
        try:
            self.receitas = carregar_todas(self.skills.path)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #
    def _migrar(self) -> None:
        with self._lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    caminho TEXT UNIQUE NOT NULL,
                    titulo TEXT DEFAULT '',
                    tipo TEXT DEFAULT 'nota',
                    tags TEXT DEFAULT '',
                    conteudo TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    atualizado TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS links (
                    origem TEXT NOT NULL,
                    destino TEXT NOT NULL,
                    UNIQUE(origem, destino)
                );
                CREATE INDEX IF NOT EXISTS idx_links_destino ON links(destino);
                CREATE INDEX IF NOT EXISTS idx_notes_tipo ON notes(tipo);
                CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
            """)
            self._fts = criar_fts(self.conn, "notes_fts", "notes",
                                  ["titulo", "tags", "conteudo"])
            self.conn.commit()

    # ------------------------------------------------------------------ #
    # Exportação (banco → markdown)
    # ------------------------------------------------------------------ #
    def _escrever(self, caminho: Path, conteudo: str) -> bool:
        """Só escreve se mudou (evita I/O e ruído de mtime no Obsidian)."""
        try:
            if caminho.exists() and caminho.read_text(encoding="utf-8") == conteudo:
                return False
        except OSError:
            pass
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo, encoding="utf-8")
        return True

    def _exportar(self) -> dict:
        escritos = {"memorias": 0, "skills": 0, "conversas": 0, "identidade": 0}
        # --- identidade ---
        partes = []
        for nome, arq in (("core_identity", ROOT / "identity" / "core_identity.md"),
                          ("principles", ROOT / "identity" / "principles.md")):
            if arq.exists():
                partes.append(arq.read_text(encoding="utf-8"))
        if partes:
            corpo = (_frontmatter("Identidade", "identidade", ["identidade", "agente"])
                     + "# Identidade do YVAKOR\n\n"
                     + "\n\n---\n\n".join(partes)
                     + "\n\n## Ligações\n- [[Home]]\n")
            if self._escrever(self.dir / "Identidade.md", corpo):
                escritos["identidade"] += 1

        # --- memórias (um fato por nota) ---
        max_memorias = int(self.cfg.get("max_memorias", 300))
        fatos = self.semantic.recentes(max_memorias) if self.semantic else []
        for fato in fatos:
            h = hash_texto(fato)[:12]
            titulo = " ".join(fato.split())[:70]
            corpo = (_frontmatter(titulo, "memoria", ["memoria", "fato"], h)
                     + f"# {titulo}\n\n{fato}\n\n## Ligações\n- [[Home]]\n")
            if self._escrever(self.dir / "Memoria" / f"{h}.md", corpo):
                escritos["memorias"] += 1

        # --- skills ---
        if self.skills:
            try:
                arquivos = self.skills.all_skills()
            except Exception:
                arquivos = []
            for arq in arquivos[:200]:
                try:
                    texto = arq.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                titulo = arq.stem
                for linha in texto.splitlines():
                    if linha.startswith("# "):
                        titulo = linha[2:].strip()
                        break
                corpo = (_frontmatter(titulo, "skill", ["skill", arq.stem])
                         + f"# {titulo}\n\n{texto}\n\n## Ligações\n- [[Home]]\n")
                if self._escrever(self.dir / "Skills" / f"{arq.stem}.md", corpo):
                    escritos["skills"] += 1

        # --- conversas (resumo + últimas mensagens) ---
        if self.cfg.get("exportar_conversas", True) and self.episodic:
            limite = int(self.cfg.get("max_conversas", 50))
            esperados = set()
            for s in self.episodic.listar_conversas(kind=None)[:limite]:
                if not (s.get("episodes") or 0):
                    continue
                try:
                    msgs = self.episodic.mensagens_da_conversa(s["id"])[-20:]
                except Exception:
                    msgs = []
                corpo_txt = "\n\n".join(
                    f"**{'Você' if m['role'] == 'user' else 'YVAKOR'}:** "
                    f"{(m['content'] or '')[:1200]}" for m in msgs if m.get("content"))
                slug = _slug(s.get("title") or s["id"], 40)
                titulo = s.get("title") or s["id"]
                nome = f"{s['id']}-{slug}.md"
                esperados.add(nome)
                corpo = (_frontmatter(titulo, "conversa", ["conversa"],
                                      s["id"])
                         + f"# {titulo}\n\n"
                         f"- **Sessão:** `{s['id']}`\n"
                         f"- **Criada:** {s.get('created_at')}\n"
                         f"- **Última atividade:** {s.get('last_at')}\n"
                         f"- **Mensagens:** {s.get('episodes')}\n\n"
                         f"## Últimas mensagens\n\n{corpo_txt}\n\n"
                         "## Ligações\n- [[Home]]\n")
                if self._escrever(self.dir / "Conversas" / nome, corpo):
                    escritos["conversas"] += 1
            # remove notas antigas de conversa (nomes por data) que sobraram
            pasta = self.dir / "Conversas"
            if pasta.is_dir():
                for arq in pasta.glob("*.md"):
                    if arq.name not in esperados and re.match(r"^\d{4}-\d{2}-\d{2}-",
                                                             arq.name):
                        try:
                            arq.unlink()
                        except OSError:
                            pass

        # --- Home (mapa de conteúdo) ---
        self._escrever(self.dir / "Home.md", self._home())
        return escritos

    def _home(self) -> str:
        def notas(pasta: str, limite: int = 40) -> list[Path]:
            base = self.dir / pasta
            if not base.is_dir():
                return []
            return sorted(base.glob("*.md"), key=lambda p: p.stat().st_mtime,
                          reverse=True)[:limite]

        linhas = [_frontmatter("Home", "mapa", ["moc", "home"]),
                  "# YVAKOR — Cérebro\n",
                  "Mapa de conteúdo do agente. Abra esta pasta no Obsidian "
                  "para navegar pelos links.\n",
                  "## Núcleo\n- [[Identidade]]\n"]
        for pasta, rotulo in (("Skills", "Skills (procedimentos)"),
                              ("Memoria", "Memórias"), ("Conversas", "Conversas")):
            itens = notas(pasta)
            if not itens:
                continue
            linhas.append(f"\n## {rotulo}\n")
            for p in itens:
                linhas.append(f"- [[{p.stem}]]")
        return "\n".join(linhas) + "\n"

    # ------------------------------------------------------------------ #
    # Indexação (markdown → SQLite)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse(texto: str, caminho_rel: str) -> dict:
        titulo, tipo, tags, id_ = "", "nota", [], ""
        corpo = texto
        if texto.startswith("---"):
            partes = texto.split("---", 2)
            if len(partes) >= 3:
                cabeca, corpo = partes[1], partes[2]
                for linha in cabeca.splitlines():
                    if ":" not in linha:
                        continue
                    chave, valor = linha.split(":", 1)
                    chave, valor = chave.strip().lower(), valor.strip()
                    if chave == "titulo":
                        titulo = valor.strip('"\'')
                    elif chave == "tipo":
                        tipo = valor or "nota"
                    elif chave == "tags":
                        tags = [t.strip() for t in re.split(r"[,\[\]]", valor)
                                if t.strip()]
                    elif chave == "id":
                        id_ = valor
        if not titulo:
            for linha in corpo.splitlines():
                if linha.startswith("# "):
                    titulo = linha[2:].strip()
                    break
        if not titulo:
            titulo = Path(caminho_rel).stem
        return {"titulo": titulo[:200], "tipo": tipo, "tags": tags,
                "id": id_, "corpo": texto}

    def _indexar(self) -> dict:
        vistos, novos, atualizados = set(), 0, 0
        with self._lock:
            for arquivo in self.dir.rglob("*.md"):
                rel = arquivo.relative_to(self.dir).as_posix()
                vistos.add(rel)
                try:
                    mtime = arquivo.stat().st_mtime
                    texto = arquivo.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                h = hash_texto(texto)
                atual = self.conn.execute(
                    "SELECT id, hash FROM notes WHERE caminho=?", (rel,)).fetchone()
                if atual and atual["hash"] == h:
                    continue
                meta = self._parse(texto, rel)
                self.conn.execute("""
                    INSERT INTO notes (caminho, titulo, tipo, tags, conteudo,
                                       hash, mtime, atualizado)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(caminho) DO UPDATE SET
                      titulo=excluded.titulo, tipo=excluded.tipo,
                      tags=excluded.tags, conteudo=excluded.conteudo,
                      hash=excluded.hash, mtime=excluded.mtime,
                      atualizado=excluded.atualizado
                """, (rel, meta["titulo"], meta["tipo"], ",".join(meta["tags"]),
                      meta["corpo"][:60000], h, mtime,
                      datetime.now().strftime("%Y-%m-%d %H:%M")))
                # links (wikilinks) — refeitos a cada mudança da nota.
                # Remove blocos de código antes: `[[` de Python não é link.
                self.conn.execute("DELETE FROM links WHERE origem=?", (rel,))
                sem_codigo = re.sub(r"```.*?```", " ", meta["corpo"], flags=re.DOTALL)
                destinos = {d.strip() for d in WIKILINK.findall(sem_codigo)}
                for destino in destinos:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO links (origem, destino) VALUES (?,?)",
                        (rel, destino))
                if atual:
                    atualizados += 1
                else:
                    novos += 1

            removidos = 0
            for (rel,) in self.conn.execute("SELECT caminho FROM notes").fetchall():
                if rel not in vistos:
                    self.conn.execute("DELETE FROM notes WHERE caminho=?", (rel,))
                    self.conn.execute("DELETE FROM links WHERE origem=?", (rel,))
                    removidos += 1
            if self._fts and (novos or atualizados or removidos):
                otimizar_fts(self.conn, "notes_fts")
            self.conn.commit()
        return {"novos": novos, "atualizados": atualizados,
                "removidos": removidos, "notas": len(vistos)}

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    def sincronizar(self, exportar: bool = True) -> dict:
        with self._sync_lock:
            exportados = self._exportar() if exportar else {}
            indexados = self._indexar()
            try:
                self.receitas = carregar_todas(self.skills.path)
            except Exception:
                self.receitas = self.receitas or []
        try:
            st = self.status()
        except Exception:
            st = {}
        return {"ok": True, "exportados": exportados, "indexados": indexados,
                "receitas": len(self.receitas), "status": st}

    # ------------------------------------------------------------------ #
    # Receitas executáveis
    # ------------------------------------------------------------------ #
    def definir_executor(self, registry) -> None:
        self.executor = registry

    def casar_receita(self, mensagem: str) -> Receita | None:
        if not self.cfg.get("receitas", True):
            return None
        alvo = normalizar(mensagem or "")
        melhor = None
        for receita in self.receitas:
            if not receita.aprovada:
                continue
            for gatilho in receita.gatilhos:
                g = normalizar(gatilho)
                if g and g in alvo:
                    if melhor is None or len(g) > melhor[0]:
                        melhor = (len(g), receita)
        return melhor[1] if melhor else None

    def executar_receita(self, receita: Receita, texto: str = "",
                         simular: bool = False) -> dict:
        if self.executor is None:
            return {"ok": False, "erro": "executor de ferramentas indisponível"}
        return ExecutorReceitas(self.executor).executar(receita, texto, simular)

    def buscar(self, termo: str, limite: int = 10) -> list[dict]:
        q = fts_query(termo)
        if q and self._fts:
            try:
                rows = self.conn.execute(
                    "SELECT n.caminho, n.titulo, n.tipo, n.tags, "
                    "snippet(notes_fts, 2, '[', ']', '…', 16) AS trecho, "
                    "bm25(notes_fts) AS score "
                    "FROM notes_fts JOIN notes n ON n.id = notes_fts.rowid "
                    "WHERE notes_fts MATCH ? ORDER BY score LIMIT ?",
                    (q, max(1, min(int(limite), 100)))).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.DatabaseError:
                pass
        padrao = f"%{termo}%"
        rows = self.conn.execute(
            "SELECT caminho, titulo, tipo, tags, substr(conteudo,1,300) AS trecho, 0 "
            "FROM notes WHERE titulo LIKE ? OR conteudo LIKE ? LIMIT ?",
            (padrao, padrao, limite)).fetchall()
        return [dict(r) for r in rows]

    def nota(self, nome: str) -> dict | None:
        alvo = str(nome).strip()
        row = self.conn.execute(
            "SELECT caminho, titulo, tipo, tags, conteudo, atualizado FROM notes "
            "WHERE caminho=? OR titulo=? OR caminho LIKE ? ORDER BY "
            "CASE WHEN caminho=? THEN 0 ELSE 1 END LIMIT 1",
            (alvo, alvo, f"%/{alvo}.md", alvo)).fetchone()
        if not row:
            return None
        return {"caminho": row["caminho"], "titulo": row["titulo"],
                "tipo": row["tipo"], "tags": row["tags"].split(",") if row["tags"] else [],
                "conteudo": row["conteudo"], "atualizado": row["atualizado"],
                "backlinks": self.backlinks(row["caminho"])}

    def backlinks(self, nome: str) -> list[dict]:
        stem = Path(str(nome)).stem
        rows = self.conn.execute(
            "SELECT DISTINCT n.caminho, n.titulo FROM links l "
            "JOIN notes n ON n.caminho = l.origem "
            "WHERE l.destino=? OR l.destino LIKE ?",
            (stem, f"%/{stem}%")).fetchall()
        return [dict(r) for r in rows]

    def grafo(self, nome: str = "", profundidade: int = 1) -> dict:
        nos: dict[str, dict] = {}
        arestas: set[tuple[str, str]] = set()

        def visitar(chave: str, nivel: int):
            row = self.conn.execute(
                "SELECT caminho, titulo, tipo FROM notes "
                "WHERE caminho=? OR titulo=? LIMIT 1", (chave, chave)).fetchone()
            if row:
                atual = row["caminho"]
            else:
                atual = chave
            if atual in nos:
                return
            nos[atual] = {"id": atual, "titulo": (row["titulo"] if row else chave),
                          "tipo": (row["tipo"] if row else "externo")}
            if nivel <= 0:
                return
            ligados = self.conn.execute(
                "SELECT destino FROM links WHERE origem=? OR origem LIKE ? "
                "UNION SELECT origem FROM links WHERE destino=? OR destino LIKE ?",
                (atual, f"%{Path(atual).stem}.md", Path(atual).stem,
                 f"%{Path(atual).stem}%")).fetchall()
            for (destino,) in ligados:
                nos.setdefault(destino, {"id": destino, "titulo": Path(destino).stem,
                                         "tipo": "nota"})
                arestas.add(tuple(sorted((atual, destino))))
                # só expande um nível além do nó pedido
                if nivel > 1:
                    visitar(destino, nivel - 1)

        if nome:
            visitar(nome, max(1, min(int(profundidade), 3)))
        else:
            for row in self.conn.execute(
                    "SELECT caminho, titulo, tipo FROM notes LIMIT 400"):
                nos[row["caminho"]] = {"id": row["caminho"], "titulo": row["titulo"],
                                       "tipo": row["tipo"]}
            for origem, destino in self.conn.execute(
                    "SELECT origem, destino FROM links LIMIT 2000"):
                arestas.add(tuple(sorted((origem, destino))))
        return {"nos": list(nos.values()),
                "arestas": [{"de": a, "para": b} for a, b in sorted(arestas)]}

    def escrever(self, titulo: str, corpo: str, tags: str = "",
                 tipo: str = "nota") -> dict:
        if not (titulo or "").strip() or not (corpo or "").strip():
            raise ValueError("título e corpo são obrigatórios")
        lista_tags = [t.strip() for t in re.split(r"[,\[\]]", tags or "") if t.strip()]
        slug = _slug(titulo)
        pasta = {"skill": "Skills", "memoria": "Memoria",
                 "conversa": "Conversas"}.get(tipo, "")
        caminho = self.dir / pasta / f"{slug}.md" if pasta else self.dir / f"{slug}.md"
        if not caminho.exists():
            conteudo = (_frontmatter(titulo, tipo, lista_tags or [tipo])
                        + f"# {titulo}\n\n{corpo.strip()}\n\n## Ligações\n- [[Home]]\n")
            self._escrever(caminho, conteudo)
        else:  # já existe: anexa em vez de sobrescrever
            atual = caminho.read_text(encoding="utf-8")
            caminho.write_text(atual.rstrip() + "\n\n" + corpo.strip() + "\n",
                               encoding="utf-8")
        self._indexar()
        return {"ok": True, "arquivo": str(caminho.resolve()),
                "caminho": caminho.relative_to(self.dir).as_posix()}

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Resolução: conhecimento antes da IA
    # ------------------------------------------------------------------ #
    def decidir(self, mensagem: str) -> dict | None:
        return self.resolvedor.decidir(mensagem)

    def registrar_origem(self, origem: str) -> None:
        chave = f"economia_{origem}"
        atual = int(meta_get(self.conn, chave, "0") or 0)
        with self._lock:
            meta_set(self.conn, chave, atual + 1)
            self.conn.commit()

    def economia(self) -> dict:
        return {o: int(meta_get(self.conn, f"economia_{o}", "0") or 0)
                for o in ("cerebro", "receita", "local", "api")}

    def status(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        links = self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        por_tipo = {r[0]: r[1] for r in self.conn.execute(
            "SELECT tipo, COUNT(*) FROM notes GROUP BY tipo ORDER BY 2 DESC")}
        return {"vault": str(self.dir.resolve()), "notas": total,
                "links": links, "por_tipo": por_tipo, "fts": self._fts,
                "receitas": len(self.receitas),
                "economia": self.economia(),
                "mb": round(self.db_path.stat().st_size / 1048576, 2)
                if self.db_path.exists() else 0}

    def otimizar(self) -> dict:
        with self._lock:
            try:
                self.conn.execute("PRAGMA optimize")
            except sqlite3.DatabaseError:
                pass
            if self._fts:
                otimizar_fts(self.conn, "notes_fts")
            self.conn.commit()
        return self.status()

    def fechar(self) -> None:
        try:
            self.otimizar()
            self.conn.close()
        except Exception:
            pass
