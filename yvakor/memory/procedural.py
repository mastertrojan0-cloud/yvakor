"""
YVAKOR — Memória procedural (skills em markdown)

Os arquivos continuam sendo a fonte da verdade (editáveis à mão, versionáveis).
O que mudou: um índice SQLite + FTS5 evita reler todos os arquivos a cada
mensagem e faz o ranking por relevância em milissegundos.

  data/skills.db  → tabela `skills` + `skills_fts`
  reindexação     → incremental por mtime/hash (só o que mudou)

Dois formatos convivem na mesma pasta:
  skills_library/nome.md          → formato antigo (cabeçalho <!-- skill: -->)
  skills_library/nome/SKILL.md    → padrão aberto Agent Skills (o mesmo do
      Claude e do Hermes Agent): front-matter YAML (name, description, tags,
      platforms) + corpo, e arquivos de apoio em references/, templates/,
      scripts/, examples/ e assets/, lidos só quando o procedimento pedir.

Divulgação progressiva (register_skills_tools):
  nível 0  skills_listar          → nome + descrição de cada skill
  nível 1  skill_ver(nome)        → o SKILL.md inteiro
  nível 2  skill_ver(nome, arq)   → um arquivo de apoio
  skill_gerenciar                 → criar, editar, apagar, gravar/remover arquivo
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import threading
import time
import unicodedata
from pathlib import Path

import yaml

from yvakor.memory.db import (
    colunas, conectar, criar_fts, fts_query, hash_texto, otimizar_fts, tem_fts5,
)
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
INTERVALO_SYNC = 5.0     # segundos entre verificações de mtime
ARQ_SKILL = "SKILL.md"
PASTAS_APOIO = ("references", "templates", "scripts", "examples", "assets")
NOME_VALIDO = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")   # spec Agent Skills
MAX_NOME, MAX_DESCRICAO = 64, 1024
_PLATAFORMA = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def front_matter(texto: str) -> tuple[dict, str]:
    """Separa o front-matter YAML (--- ... ---) do corpo."""
    m = re.match(r"^\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)",
                 texto or "", re.S)
    if not m:
        return {}, texto or ""
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), texto[m.end():]


def _lista(valor) -> list[str]:
    if isinstance(valor, str):
        return [v.strip() for v in valor.strip("[]").split(",") if v.strip()]
    if isinstance(valor, (list, tuple)):
        return [str(v).strip() for v in valor if str(v).strip()]
    return []


def nome_skill(texto: str) -> str:
    """'Gerar Relatório PDF' → 'gerar-relatorio-pdf' (kebab-case da spec)."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:MAX_NOME].strip("-")


class SkillLibrary:
    def __init__(self, path: Path, db_path: Path | None = None,
                 estado_path: Path | None = None, extras=None):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else (ROOT / "data" / "skills.db")
        self.lixeira = ROOT / "data" / "lixeira" / "skills"
        # skills desligadas (ficam no disco, mas fora do prompt e da lista)
        self.estado_path = Path(estado_path) if estado_path else \
            self.db_path.with_name("skills_estado.json")
        # skills de plugins ativos: callable → {"plugin:skill": Path}
        self.extras = extras
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
            if "descricao" not in colunas(self.conn, "skills"):
                self.conn.execute(
                    "ALTER TABLE skills ADD COLUMN descricao TEXT DEFAULT ''")
            # Esquema 2 (descrição + SKILL.md): índice antigo é refeito uma vez.
            # Sem isto as skills que não mudaram no disco nunca ganhavam
            # descrição (o sync pula por mtime/hash).
            versao = self.conn.execute(
                "SELECT valor FROM meta WHERE chave='esquema'").fetchone()
            if not versao or str(versao[0]) < "2":
                self.conn.execute("UPDATE skills SET mtime=0, hash=''")
                self.conn.execute("INSERT OR REPLACE INTO meta (chave, valor) "
                                  "VALUES ('esquema', '2')")
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
        meta, _ = front_matter(texto)
        if meta:
            extra = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
            extra = extra.get("yvakor") if isinstance(extra.get("yvakor"), dict) else extra
            titulo = str(meta.get("name") or "").strip()
            tags = ", ".join(_lista(meta.get("tags") or extra.get("tags")))
        m = None if titulo else re.search(
            r"<!--\s*skill:\s*([^|>]+)(?:\|\s*tags:\s*([^>]+))?-->", texto, re.I)
        if m:
            titulo = (m.group(1) or "").strip()
            tags = tags or (m.group(2) or "").strip()
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

    @staticmethod
    def _descricao(texto: str) -> str:
        """A frase que decide quando usar a skill (nível 0 da divulgação)."""
        meta, corpo = front_matter(texto)
        if meta.get("description"):
            return " ".join(str(meta["description"]).split())[:MAX_DESCRICAO]
        m = re.search(r"^##\s*Quando usar\s*\n+(.+?)(?:\n\s*\n|\n#)", corpo, re.S | re.M)
        if m:
            return " ".join(m.group(1).split())[:300]
        for linha in corpo.splitlines():
            linha = linha.strip()
            if linha and not linha.startswith(("#", "<!--", "---")):
                return linha[:300]
        return ""

    @staticmethod
    def _plataforma_ok(texto: str) -> bool:
        plataformas = [p.lower() for p in _lista(front_matter(texto)[0].get("platforms"))]
        return not plataformas or _PLATAFORMA in plataformas

    # ------------------------------------------------------------------ #
    @staticmethod
    def nome_de(arquivo: Path) -> str:
        """Nome da skill: a pasta (nome/SKILL.md) ou o arquivo (nome.md)."""
        arquivo = Path(arquivo)
        return arquivo.parent.name if arquivo.name == ARQ_SKILL else arquivo.stem

    def _arquivos(self) -> dict[str, Path]:
        achados = {f.stem: f for f in self.path.glob("*.md")}
        # pasta com SKILL.md vence o .md solto de mesmo nome
        achados.update({f.parent.name: f for f in self.path.glob(f"*/{ARQ_SKILL}")})
        if self.extras is not None:
            try:
                achados.update(self.extras())
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        return achados

    # ------------------------------------------------------------------ #
    # Ligar/desligar
    # ------------------------------------------------------------------ #
    def desligadas(self) -> set[str]:
        from yvakor import seguro
        return set((seguro.ler_json(self.estado_path, {}) or {}).get("desligadas") or [])

    def ligada(self, nome: str) -> bool:
        return nome not in self.desligadas()

    def definir(self, nome: str, ligada: bool) -> dict:
        from yvakor import seguro
        if nome not in self._arquivos():
            return {"ok": False, "error": f"skill {nome!r} não existe; veja skills_listar"}
        with self._lock:
            desligadas = self.desligadas()
            (desligadas.discard if ligada else desligadas.add)(nome)
            seguro.gravar_json(self.estado_path, {"desligadas": sorted(desligadas)})
        return {"ok": True, "result": f"skill {nome} {'ligada' if ligada else 'desligada'}"}

    def resolver(self, nome: str) -> str | None:
        """Nome exato, kebab-case ou, para skill de plugin, só a parte depois do ':'."""
        arquivos = self._arquivos()
        for candidato in (nome, nome_skill(nome)):
            if candidato in arquivos:
                return candidato
        de_plugin = [n for n in arquivos if ":" in n and n.split(":", 1)[1] == nome]
        return de_plugin[0] if len(de_plugin) == 1 else None

    def sincronizar(self, forcar: bool = False) -> dict:
        agora = time.time()
        if not forcar and (agora - self._ultimo_sync) < INTERVALO_SYNC:
            return {"ok": True, "pulado": True}
        self._ultimo_sync = agora
        vistos, novos, atualizados = set(), 0, 0
        with self._lock:
            for nome, arquivo in self._arquivos().items():
                try:
                    mtime = arquivo.stat().st_mtime
                except OSError:
                    continue
                atual = self.conn.execute(
                    "SELECT hash, mtime FROM skills WHERE nome=?", (nome,)).fetchone()
                if atual and abs(float(atual["mtime"]) - mtime) < 0.001:
                    vistos.add(nome)
                    continue
                try:
                    texto = arquivo.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                if not self._plataforma_ok(texto):
                    continue        # skill de outro sistema: fora do índice
                vistos.add(nome)
                h = hash_texto(texto)
                if atual and atual["hash"] == h:
                    self.conn.execute("UPDATE skills SET mtime=? WHERE nome=?",
                                      (mtime, nome))
                    continue
                titulo, tags = self._ler_meta(texto)
                self.conn.execute("""
                    INSERT INTO skills (nome, titulo, tags, descricao, conteudo,
                                        hash, mtime, ts)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(nome) DO UPDATE SET
                      titulo=excluded.titulo, tags=excluded.tags,
                      descricao=excluded.descricao,
                      conteudo=excluded.conteudo, hash=excluded.hash,
                      mtime=excluded.mtime, ts=excluded.ts
                """, (nome, titulo, tags, self._descricao(texto), texto[:20000],
                      h, mtime, time.strftime("%Y-%m-%d %H:%M:%S")))
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
        return sorted(self._arquivos().values(), key=self.nome_de)

    def find_relevant(self, query: str, top_k: int = 2) -> list[str]:
        self.sincronizar()
        top_k = max(1, min(int(top_k), 10))
        desligadas = self.desligadas()
        q = fts_query(query)
        if q and self._fts:
            try:
                rows = self.conn.execute(
                    "SELECT s.conteudo, s.nome FROM skills_fts JOIN skills s "
                    "ON s.id = skills_fts.rowid WHERE skills_fts MATCH ? "
                    "ORDER BY bm25(skills_fts) LIMIT ?",
                    (q, top_k + len(desligadas))).fetchall()
                rows = [r for r in rows if r[1] not in desligadas][:top_k]
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
                "SELECT conteudo, titulo, nome FROM skills"):
            if row["nome"] in desligadas:
                continue
            texto = row["conteudo"].lower()
            score = sum(2 for w in palavras if w in row["titulo"].lower())
            score += sum(1 for w in palavras if w in texto)
            if score >= 2:
                candidatos.append((score, row["conteudo"]))
        candidatos.sort(key=lambda x: -x[0])
        return [t for _, t in candidatos[:top_k]]

    # ------------------------------------------------------------------ #
    # Divulgação progressiva
    # ------------------------------------------------------------------ #
    def listar(self, filtro: str = "", incluir_desligadas: bool = False) -> dict:
        """Nível 0: nome + descrição (o que decide se a skill serve)."""
        self.sincronizar()
        desligadas = self.desligadas()
        rows = self.conn.execute(
            "SELECT nome, tags, descricao FROM skills ORDER BY nome").fetchall()
        f = (filtro or "").lower().strip()
        itens = [{"nome": r["nome"], "descricao": r["descricao"] or "",
                  "tags": r["tags"] or "", "ligada": r["nome"] not in desligadas}
                 for r in rows
                 if (incluir_desligadas or r["nome"] not in desligadas)
                 and (not f or f in (r["nome"] + " " + (r["tags"] or "") + " "
                                     + (r["descricao"] or "")).lower())]
        return {"ok": True, "total": len(itens), "skills": itens,
                "dica": "use skill_ver(nome) para ler o procedimento completo"}

    def _apoio(self, pasta: Path) -> list[str]:
        return sorted(str(f.relative_to(pasta)).replace("\\", "/")
                      for f in pasta.rglob("*")
                      if f.is_file() and f.name != ARQ_SKILL)

    def _dentro(self, pasta: Path, relativo: str) -> Path | None:
        """Caminho de apoio dentro da pasta da skill (bloqueia ../ e absolutos)."""
        rel = Path(str(relativo or "").replace("\\", "/"))
        if rel.is_absolute() or not rel.parts or rel.parts[0] not in PASTAS_APOIO:
            return None
        alvo = (pasta / rel).resolve()
        try:
            alvo.relative_to(pasta.resolve())
        except ValueError:
            return None
        return alvo

    def ver(self, nome: str, arquivo: str = "") -> dict:
        """Nível 1 (SKILL.md) ou nível 2 (um arquivo de apoio)."""
        resolvido = self.resolver(nome)
        if not resolvido:
            return {"ok": False, "error": f"skill {nome!r} não existe; veja skills_listar"}
        if resolvido in self.desligadas():
            return {"ok": False, "error": f"skill {resolvido!r} está desligada pelo usuário"}
        achado = self._arquivos()[resolvido]
        if not arquivo:
            res = {"ok": True, "nome": self.nome_de(achado),
                   "conteudo": achado.read_text(encoding="utf-8", errors="replace")}
            if achado.name == ARQ_SKILL:
                res["arquivos_de_apoio"] = self._apoio(achado.parent)
            return res
        if achado.name != ARQ_SKILL:
            return {"ok": False, "error": "esta skill não tem arquivos de apoio"}
        alvo = self._dentro(achado.parent, arquivo)
        if not alvo or not alvo.is_file():
            return {"ok": False, "error": f"arquivo {arquivo!r} não existe",
                    "arquivos_de_apoio": self._apoio(achado.parent)}
        return {"ok": True, "arquivo": arquivo,
                "conteudo": alvo.read_text(encoding="utf-8", errors="replace")[:60000]}

    # ------------------------------------------------------------------ #
    def _para_lixeira(self, origem: Path, nome: str) -> Path:
        self.lixeira.mkdir(parents=True, exist_ok=True)
        destino = self.lixeira / f"{time.strftime('%Y%m%d-%H%M%S')}-{nome}"
        shutil.move(str(origem), str(destino))
        return destino

    def _para_pasta(self, nome: str) -> Path:
        """Converte nome.md (formato antigo) em nome/SKILL.md."""
        achado = self._arquivos()[nome]
        if achado.name == ARQ_SKILL:
            return achado
        pasta = self.path / nome
        pasta.mkdir(exist_ok=True)
        novo = pasta / ARQ_SKILL
        shutil.move(str(achado), str(novo))
        return novo

    def gerenciar(self, acao: str, nome: str, conteudo: str = "",
                  descricao: str = "", antigo: str = "", novo: str = "",
                  arquivo: str = "", conteudo_arquivo: str = "") -> dict:
        from yvakor import injecao
        acao = (acao or "").strip().lower()
        acao = {"create": "criar", "patch": "editar", "edit": "editar",
                "delete": "apagar", "write_file": "gravar_arquivo",
                "remove_file": "remover_arquivo", "enable": "ligar",
                "disable": "desligar"}.get(acao, acao)
        if acao in ("ligar", "desligar"):
            resolvido = self.resolver(nome)
            if not resolvido:
                return {"ok": False, "error": f"skill {nome!r} não existe; veja skills_listar"}
            return self.definir(resolvido, acao == "ligar")
        if ":" in (nome or ""):
            return {"ok": False, "error": "skill de plugin é só leitura; edite o plugin "
                    "ou crie uma skill sua com outro nome"}
        # skills antigas podem ter "_" no nome (save()); valem como estão
        slug = nome if acao != "criar" and nome in self._arquivos() else nome_skill(nome)
        if not slug or len(slug) > MAX_NOME or not (
                NOME_VALIDO.match(slug) or slug in self._arquivos()):
            return {"ok": False, "error": "nome inválido (minúsculas, números e hífens)"}
        for texto in (conteudo, novo, conteudo_arquivo):
            motivos = injecao.varrer(texto)
            if motivos:
                return {"ok": False, "error": "conteúdo recusado (suspeita de "
                        f"prompt-injection: {', '.join(motivos)})"}
        with self._lock:
            existentes = self._arquivos()
            if acao == "criar":
                if slug in existentes:
                    return {"ok": False, "error": f"skill {slug!r} já existe; use acao=editar"}
                if not (conteudo or "").strip():
                    return {"ok": False, "error": "informe 'conteudo' (o procedimento)"}
                meta, corpo = front_matter(conteudo)
                desc = " ".join(str(meta.get("description") or descricao or "").split())
                if not desc:
                    return {"ok": False, "error": "informe 'descricao': quando usar a skill"}
                if len(desc) > MAX_DESCRICAO:
                    return {"ok": False, "error": f"descrição passa de {MAX_DESCRICAO} caracteres"}
                meta = {**meta, "name": slug, "description": desc}
                texto = ("---\n" + yaml.safe_dump(meta, allow_unicode=True,
                                                  sort_keys=False).strip()
                         + "\n---\n\n" + corpo.lstrip())
                pasta = self.path / slug
                pasta.mkdir(parents=True, exist_ok=True)
                (pasta / ARQ_SKILL).write_text(texto, encoding="utf-8")
                self.sincronizar(forcar=True)
                return {"ok": True, "result": f"skill criada: skills_library/{slug}/{ARQ_SKILL}"}
            if slug not in existentes:
                return {"ok": False, "error": f"skill {slug!r} não existe; veja skills_listar"}
            arq = existentes[slug]
            if acao == "editar":
                if conteudo.strip():
                    arq.write_text(conteudo, encoding="utf-8")
                else:
                    atual = arq.read_text(encoding="utf-8", errors="replace")
                    vezes = atual.count(antigo) if antigo else 0
                    if vezes != 1:
                        return {"ok": False, "error": (
                            "'antigo' precisa aparecer exatamente 1 vez no SKILL.md "
                            f"(apareceu {vezes}); ou mande 'conteudo' para reescrever")}
                    arq.write_text(atual.replace(antigo, novo, 1), encoding="utf-8")
                self.sincronizar(forcar=True)
                return {"ok": True, "result": f"skill {slug!r} atualizada"}
            if acao == "apagar":
                origem = arq.parent if arq.name == ARQ_SKILL else arq
                destino = self._para_lixeira(origem, slug)
                self.sincronizar(forcar=True)
                return {"ok": True, "result": f"skill movida para a lixeira: {destino}"}
            if acao in ("gravar_arquivo", "remover_arquivo"):
                arq = self._para_pasta(slug)
                alvo = self._dentro(arq.parent, arquivo)
                if not alvo:
                    return {"ok": False, "error": "arquivo deve ficar em "
                            + ", ".join(f"{p}/" for p in PASTAS_APOIO)}
                if acao == "gravar_arquivo":
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    alvo.write_text(conteudo_arquivo or "", encoding="utf-8")
                    self.sincronizar(forcar=True)
                    return {"ok": True, "result": f"{slug}/{arquivo} gravado"}
                if not alvo.is_file():
                    return {"ok": False, "error": f"{arquivo!r} não existe"}
                self._para_lixeira(alvo, f"{slug}-{alvo.name}")
                return {"ok": True, "result": f"{slug}/{arquivo} movido para a lixeira"}
        return {"ok": False, "error": "acao deve ser criar, editar, apagar, "
                "gravar_arquivo ou remover_arquivo"}

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
            _log.debug("exceção ignorada", exc_info=True)


def register_skills_tools(registry, skills: SkillLibrary) -> list[str]:
    registry.register(
        "skills_listar", skills.listar,
        "Lista suas skills (procedimentos salvos que VOCÊ segue): nome e quando "
        "usar. filtro opcional. Não são subagentes — esses são agentes_listar.",
        {"filtro": "str?"})
    registry.register(
        "skill_ver", skills.ver,
        "Lê o procedimento completo de uma skill (SKILL.md). Com 'arquivo' "
        "(ex.: references/api.md, scripts/rodar.py) lê um arquivo de apoio.",
        {"nome": "str", "arquivo": "str?"})
    registry.register(
        "skill_gerenciar", skills.gerenciar,
        "Cria ou melhora skills. Salve uma skill depois de resolver um fluxo de "
        "vários passos, contornar um erro ou ser corrigido pelo usuário. "
        "acao: criar (nome, descricao, conteudo), editar (antigo→novo, ou "
        "conteudo p/ reescrever), apagar, gravar_arquivo/remover_arquivo "
        "(arquivo em references/|templates/|scripts/|examples/|assets/, "
        "conteudo_arquivo), ligar/desligar (só quando o usuário pedir). "
        "Registre lições gerais, não logs nem datas.",
        {"acao": "str", "nome": "str", "descricao": "str?", "conteudo": "str?",
         "antigo": "str?", "novo": "str?", "arquivo": "str?",
         "conteudo_arquivo": "str?"})
    return ["skills_listar", "skill_ver", "skill_gerenciar"]
