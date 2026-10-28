"""
YVAKOR — Ferramentas no estilo das do Claude

  pensar             → espaço para raciocinar no meio da tarefa (o "think tool"
                       da Anthropic): sem efeito colateral, só organiza a ideia
                       antes de decidir o próximo passo.
  tarefas_checklist  → lista de tarefas com estado (como o TodoWrite do Claude
                       Code): o agente mantém o progresso visível no painel.
  arquivos_grep      → busca por CONTEÚDO (regex) dentro de arquivos, com número
                       de linha — o Grep do Claude Code (arquivos_buscar só
                       procura por nome).
  web_ler            → lê uma URL e devolve o texto limpo em markdown (título,
                       cabeçalhos, parágrafos, listas, links) — o WebFetch do
                       Claude. O http_get devolvia HTML cru.
"""
from __future__ import annotations

import ast
import json
import os
import re
import threading
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

_tl = threading.local()


# ----------------------------------------------------------------- pensar
def pensar(pensamento: str = "") -> dict:
    """Registra um raciocínio. Não age em nada."""
    texto = str(pensamento or "").strip()
    if not texto:
        return {"ok": False, "error": "faltou o argumento obrigatório pensamento"}
    return {"ok": True, "registrado": True,
            "dica": "Pensamento anotado. Agora execute o próximo passo decidido."}


# ------------------------------------------------------- tarefas_checklist
ESTADOS = {"pendente": "⬜", "fazendo": "🔄", "feito": "✅", "bloqueado": "⛔"}
_SINONIMOS = {"pending": "pendente", "todo": "pendente", "a fazer": "pendente",
              "in_progress": "fazendo", "em andamento": "fazendo",
              "andamento": "fazendo", "doing": "fazendo",
              "completed": "feito", "done": "feito", "concluido": "feito",
              "concluído": "feito", "ok": "feito",
              "blocked": "bloqueado", "falhou": "bloqueado", "erro": "bloqueado"}


def _ler_itens(itens) -> list[dict]:
    if isinstance(itens, str):
        bruto = itens.strip()
        dado = None
        for leitor in (json.loads, ast.literal_eval):
            try:
                dado = leitor(bruto)
                break
            except Exception:
                continue
        if dado is None:      # uma tarefa por linha: "[x] texto" / "- texto"
            dado = []
            for linha in bruto.splitlines():
                linha = linha.strip(" -•\t")
                if not linha:
                    continue
                feito = linha.lower().startswith(("[x]", "✅"))
                linha = re.sub(r"^(\[[ x]\]|✅|⬜)\s*", "", linha, flags=re.I)
                dado.append({"texto": linha, "estado": "feito" if feito else "pendente"})
        itens = dado
    if isinstance(itens, dict):
        itens = [itens]
    saida = []
    for item in itens or []:
        if isinstance(item, str):
            item = {"texto": item}
        if not isinstance(item, dict):
            continue
        texto = str(item.get("texto") or item.get("content") or
                    item.get("tarefa") or "").strip()
        if not texto:
            continue
        estado = str(item.get("estado") or item.get("status") or "pendente").lower()
        estado = _SINONIMOS.get(estado, estado)
        if estado not in ESTADOS:
            estado = "pendente"
        saida.append({"texto": texto[:200], "estado": estado})
    return saida[:20]


def tarefas_checklist(itens="") -> dict:
    """Substitui a lista inteira de tarefas da execução atual."""
    lista = _ler_itens(itens)
    if not lista:
        return {"ok": False, "error": "faltou o argumento obrigatório itens "
                "(lista de {texto, estado})"}
    _tl.checklist = lista
    feitos = sum(1 for i in lista if i["estado"] == "feito")
    return {"ok": True, "progresso": f"{feitos}/{len(lista)}",
            "lista": "\n".join(f"{ESTADOS[i['estado']]} {i['texto']}" for i in lista)}


def checklist_atual() -> list[dict]:
    return list(getattr(_tl, "checklist", None) or [])


def limpar_checklist() -> None:
    _tl.checklist = []


def resumo_checklist(itens) -> str:
    lista = _ler_itens(itens)
    if not lista:
        return "☑ checklist"
    feitos = sum(1 for i in lista if i["estado"] == "feito")
    atual = next((i["texto"] for i in lista if i["estado"] == "fazendo"), "")
    return f"☑ Checklist {feitos}/{len(lista)}" + (f": {atual[:70]}" if atual else "")


# ------------------------------------------------------------ arquivos_grep
_PULAR_PASTAS = {".git", "node_modules", "venv", ".venv", "__pycache__",
                 ".mypy_cache", ".pytest_cache", "dist", "build", ".idea"}
_MAX_BYTES = 2_000_000


def arquivos_grep(padrao: str = "", raiz: str = "", arquivos: str = "",
                  ignorar_maiusculas: bool = False, contexto: int = 0,
                  limite: int = 100, caminho: str = "") -> dict:
    """Procura `padrao` (regex) no conteúdo dos arquivos sob `raiz`
    (`caminho` é aceito como sinônimo: o modelo escreve assim com frequência)."""
    raiz = raiz or caminho or "."
    if not padrao:
        return {"ok": False, "error": "faltou o argumento obrigatório padrao"}
    try:
        rx = re.compile(padrao, re.I if ignorar_maiusculas else 0)
    except re.error as exc:
        return {"ok": False, "error": f"regex inválida: {exc}"}
    base = Path(os.path.expanduser(raiz or ".")).resolve()
    if not base.exists():
        return {"ok": False, "error": f"caminho não existe: {base}"}
    filtro = [f.strip() for f in str(arquivos or "").split(",") if f.strip()]
    limite = max(1, min(int(limite or 100), 500))
    contexto = max(0, min(int(contexto or 0), 5))
    achados, arquivos_com, vistos = [], set(), 0

    def candidatos():
        if base.is_file():
            yield base
            return
        for pasta, subpastas, nomes in os.walk(base):
            subpastas[:] = [s for s in subpastas if s not in _PULAR_PASTAS]
            for nome in nomes:
                p = Path(pasta) / nome
                if filtro and not any(p.match(f) for f in filtro):
                    continue
                yield p

    for p in candidatos():
        if len(achados) >= limite:
            break
        try:
            if p.stat().st_size > _MAX_BYTES:
                continue
            dados = p.read_bytes()
        except OSError:
            continue
        if b"\0" in dados[:4096]:              # binário
            continue
        vistos += 1
        linhas = dados.decode("utf-8", errors="replace").splitlines()
        for n, linha in enumerate(linhas, 1):
            if rx.search(linha):
                item = {"arquivo": str(p), "linha": n, "texto": linha.strip()[:300]}
                if contexto:
                    ini, fim = max(0, n - 1 - contexto), min(len(linhas), n + contexto)
                    item["contexto"] = "\n".join(linhas[ini:fim])[:1200]
                achados.append(item)
                arquivos_com.add(str(p))
                if len(achados) >= limite:
                    break
    return {"ok": True, "padrao": padrao, "raiz": str(base),
            "arquivos_lidos": vistos, "arquivos_com_ocorrencia": len(arquivos_com),
            "ocorrencias": achados, "truncado": len(achados) >= limite}


# ------------------------------------------------------------------ web_ler
class _Leitor(HTMLParser):
    _IGNORAR = {"script", "style", "noscript", "svg", "head", "template",
                "iframe", "nav", "footer", "aside", "button"}
    _BLOCOS = {"p", "div", "section", "article", "main", "br", "tr", "table",
               "ul", "ol", "header", "blockquote", "pre", "figure", "dd", "dt"}

    def __init__(self, url: str):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.partes: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.titulo = ""
        self._pular = 0
        self._pre = 0
        self._no_titulo = False
        self._href = None
        self._texto_link: list[str] = []
        # Conteúdo principal (<main>, <article>, role=main, #mw-content-text…):
        # em sites como a Wikipédia, menus e a lista de idiomas vêm antes do
        # artigo e não estão em <nav>. Se houver região principal, ela vence.
        # Regiões candidatas podem se aninhar (na Wikipédia o <main> também
        # contém o menu de idiomas; o artigo está em #mw-content-text): cada
        # região tem prioridade e no fim vence a mais específica com texto.
        self.regioes: list[dict] = []     # {prio, tag, nivel, partes}

    _IDS_PRINCIPAIS = {"mw-content-text": 4, "bodycontent": 3,
                       "article": 3, "artigo": 3, "post": 3,
                       "main-content": 2, "maincontent": 2, "conteudo": 2,
                       "conteudo-principal": 2, "content": 1, "main": 1}

    def _add(self, texto: str) -> None:
        self.partes.append(texto)
        for r in self.regioes:
            if r["nivel"]:
                r["partes"].append(texto)

    def _prioridade(self, tag, attrs) -> int:
        a = dict(attrs)
        prio = self._IDS_PRINCIPAIS.get((a.get("id") or "").lower(), 0)
        if tag == "article":
            prio = max(prio, 3)
        elif tag == "main" or (a.get("role") or "") == "main":
            prio = max(prio, 1)
        return prio

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._no_titulo = True
        if tag in self._IGNORAR:
            self._pular += 1
            return
        if self._pular:
            return
        for r in self.regioes:
            if r["nivel"] and tag == r["tag"]:
                r["nivel"] += 1
        prio = self._prioridade(tag, attrs)
        if prio and len(self.regioes) < 12:
            self.regioes.append({"prio": prio, "tag": tag, "nivel": 1, "partes": []})
        if tag == "pre":
            self._pre += 1
        if tag in ("h1", "h2", "h3", "h4"):
            self._add("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self._add("\n- ")
        elif tag in ("td", "th"):
            self._add(" | ")
        elif tag in self._BLOCOS:
            self._add("\n")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                self._href = urljoin(self.url, href)
                self._texto_link = []
        elif tag == "img":
            alt = (dict(attrs).get("alt") or "").strip()
            if alt:
                self._add(f"[imagem: {alt}]")

    def handle_endtag(self, tag):
        if tag == "title":
            self._no_titulo = False
        if tag in self._IGNORAR:
            self._pular = max(0, self._pular - 1)
            return
        if self._pular:
            return
        if tag == "pre":
            self._pre = max(0, self._pre - 1)
        if tag == "a" and self._href:
            texto = " ".join("".join(self._texto_link).split())
            if texto and len(self.links) < 60:
                self.links.append((texto[:80], self._href))
            self._href = None
        elif tag in ("h1", "h2", "h3", "h4", "p") or tag in self._BLOCOS:
            self._add("\n")
        for r in self.regioes:
            if r["nivel"] and tag == r["tag"]:
                r["nivel"] -= 1

    def handle_data(self, data):
        if self._no_titulo:
            self.titulo += data
        if self._pular:
            return
        if not self._pre:          # quebra de linha do HTML não é parágrafo
            data = re.sub(r"\s+", " ", data)
        self._add(data)
        if self._href is not None:
            self._texto_link.append(data)

    def markdown(self) -> str:
        texto = "".join(self.partes)
        for r in sorted(self.regioes, key=lambda r: -r["prio"]):
            candidato = "".join(r["partes"])
            if len(candidato.strip()) >= 300:
                texto = candidato
                break
        texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
        texto = re.sub(r" *\n *", "\n", texto)
        texto = re.sub(r"\n(- |\| )?\n", "\n\n", texto)
        texto = re.sub(r"\n{3,}", "\n\n", texto)
        linhas = [l for l in texto.split("\n") if l.strip() not in ("-", "|", "#")]
        return "\n".join(linhas).strip()


def web_ler(url: str = "", inicio: int = 0, max_chars: int = 12000,
            links: bool = True) -> dict:
    """Baixa a página e devolve o texto legível em markdown, paginável."""
    if not str(url).lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "url deve começar com http(s)://"}
    req = urllib.request.Request(url, headers={
        "User-Agent": "YVAKOR/1.0", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tipo = resp.headers.get("Content-Type", "")
            bruto = resp.read(4_000_000)
            final = resp.geturl()
            charset = resp.headers.get_content_charset() or "utf-8"
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                "dica": "se a página exige JavaScript ou login, use navegador_ir + "
                        "navegador_extrair"}
    html = bruto.decode(charset, errors="replace")
    if "html" not in tipo.lower() and not re.search(r"<html|<body", html[:2000], re.I):
        texto, titulo, lista = html, "", []
    else:
        leitor = _Leitor(final)
        try:
            leitor.feed(html)
        except Exception:
            pass
        texto, titulo, lista = leitor.markdown(), leitor.titulo.strip(), leitor.links
    inicio = max(0, int(inicio or 0))
    max_chars = max(500, min(int(max_chars or 12000), 40000))
    trecho = texto[inicio:inicio + max_chars]
    saida = {"ok": True, "url": final, "titulo": titulo[:200],
             "texto": trecho, "total_chars": len(texto),
             "inicio": inicio}
    if inicio + max_chars < len(texto):
        saida["continua"] = f"há mais texto: chame web_ler com inicio={inicio + max_chars}"
    if links and lista:
        saida["links"] = [f"{t} → {h}" for t, h in lista[:40]]
    if len(texto) < 200:
        saida["dica"] = ("pouco texto: a página provavelmente monta o conteúdo com "
                         "JavaScript — use navegador_ir + navegador_extrair")
    return saida


# ---------------------------------------------------------------- registro
def register_ferramentas_claude(registry) -> list[str]:
    reg = registry.register
    reg("pensar", pensar,
        "Espaço para pensar no meio da tarefa, sem agir: use antes de uma "
        "decisão difícil, depois de uma observação confusa ou de um erro, para "
        "conferir regras/pedido e decidir o próximo passo.",
        {"pensamento": "str"})
    reg("tarefas_checklist", tarefas_checklist,
        "Mantém a lista de tarefas desta execução visível ao usuário (substitui "
        "a lista inteira). Use em tarefas com 3+ passos: crie no início, marque "
        "'fazendo' ao começar um item e 'feito' ao concluir. itens = JSON "
        '[{"texto":"...","estado":"pendente|fazendo|feito|bloqueado"}].',
        {"itens": "str"})
    reg("arquivos_grep", arquivos_grep,
        "Procura TEXTO/regex dentro dos arquivos de uma pasta (com número da "
        "linha). arquivos='*.py,*.md' filtra; contexto=N mostra linhas em volta.",
        {"padrao": "str", "raiz": "str?", "arquivos": "str?",
         "ignorar_maiusculas": "bool?", "contexto": "int?", "limite": "int?",
         "caminho": "str?"})
    reg("web_ler", web_ler,
        "Lê uma página web e devolve o texto limpo em markdown (título, "
        "cabeçalhos, listas, links). Use para ler artigos/documentação; "
        "inicio=N continua páginas longas. Para página com login ou JavaScript "
        "use o navegador.",
        {"url": "str", "inicio": "int?", "max_chars": "int?", "links": "bool?"})
    return ["pensar", "tarefas_checklist", "arquivos_grep", "web_ler"]
