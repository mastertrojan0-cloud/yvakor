"""YVAKOR — pesquisa profunda na web com fontes citadas."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime

from yvakor.config import ROOT
import logging

_log = logging.getLogger(__name__)

PASTA = ROOT / "data" / "pesquisas"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YVAKOR/1.0"


def _limpar_html(bruto: str) -> str:
    bruto = re.sub(r"(?is)<(script|style|noscript|svg).*?>.*?</\1>", " ", bruto)
    bruto = re.sub(r"(?s)<[^>]+>", " ", bruto)
    return html.unescape(re.sub(r"\s+", " ", bruto)).strip()


def _titulo(bruto: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", bruto)
    return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()[:140] if m else ""


def _decodificar_bing(href: str) -> str:
    if "bing.com/ck/a" not in href:
        return href
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        u = (q.get("u") or [""])[0]
        if u.startswith("a1"):
            import base64
            bruto = u[2:]
            bruto += "=" * (-len(bruto) % 4)
            return base64.urlsafe_b64decode(bruto).decode("utf-8", "replace")
    except Exception:
        _log.debug("exceção ignorada", exc_info=True)
    return href


def buscar(pergunta: str, limite: int = 8) -> list[dict]:
    """Busca na web. Limpa o pedido ("pesquise sobre…"), junta notícias recentes quando o assunto
    é de agora e devolve os resultados mais relevantes primeiro."""
    original = pergunta
    pergunta = limpar_consulta(pergunta)
    extras: list[dict] = []

    def tentar(fn, *a):
        try:
            extras.extend(fn(*a))
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)                       # cada fonte é opcional: a que falhar não derruba a busca
    if _PEDIDO_NOTICIA.search(original):
        tentar(buscar_noticias, pergunta, 5)
    if _PEDIDO_DEFINICAO.search(original):
        tentar(buscar_wikipedia, pergunta, 4)
    if _PEDIDO_TECNICO.search(original):
        tentar(buscar_stackoverflow, pergunta, 4)
    tentar(buscar_brave, pergunta, max(limite, 8))
    web = _buscar_motores(pergunta, max(limite, 8)) if len(extras) < limite else []
    q = set(_tokens(pergunta))
    achados = extras + [i for i in web if _relevante(i, q)]
    vistos, unicos = set(), []
    for i in reordenar(achados, pergunta):
        if i["url"] not in vistos:
            vistos.add(i["url"])
            unicos.append(i)
    return unicos[:limite]


def _buscar_motores(pergunta: str, limite: int = 8) -> list[dict]:
    q = urllib.parse.quote_plus(pergunta)
    itens: list[dict] = []
    # DuckDuckGo HTML (primário)
    try:
        req = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?q={q}&kl=br-pt",
            headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        with urllib.request.urlopen(req, timeout=25) as r:
            bruto = r.read(2_500_000).decode("utf-8", errors="replace")
        for m in re.finditer(
                r'(?is)<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                bruto):
            href = html.unescape(m.group(1))
            titulo = _limpar_html(m.group(2))
            if href.startswith("//"):
                href = "https:" + href
            if "uddg=" in href:
                try:
                    href = urllib.parse.unquote(urllib.parse.parse_qs(
                        urllib.parse.urlparse(href).query)["uddg"][0])
                except Exception:
                    continue
            if not href.startswith("http") or "duckduckgo.com" in href:
                continue
            if any(i["url"] == href for i in itens):
                continue
            itens.append({"titulo": titulo or href, "url": href})
            if len(itens) >= limite:
                return itens
    except Exception:
        itens = []
    if itens:
        return itens
    # fallback Bing
    try:
        req = urllib.request.Request(
            f"https://www.bing.com/search?q={q}&setlang=pt-BR",
            headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
        with urllib.request.urlopen(req, timeout=25) as r:
            bruto = r.read(2_500_000).decode("utf-8", errors="replace")
        for m in re.finditer(
                r'(?is)<li[^>]+class="[^"]*b_algo[^"]*"[^>]*>.*?'
                r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', bruto):
            href = _decodificar_bing(html.unescape(m.group(1)))
            titulo = _limpar_html(m.group(2))
            if not href.startswith("http") or "bing.com" in href:
                continue
            if any(i["url"] == href for i in itens):
                continue
            itens.append({"titulo": titulo or href, "url": href})
            if len(itens) >= limite:
                break
    except Exception:
        _log.debug("exceção ignorada", exc_info=True)
    return itens


# --------------------------------------------------------------------------- #
# Qualidade da busca: limpar o pedido, notícias recentes e reordenar por relevância
# --------------------------------------------------------------------------- #
_IMPERATIVOS = re.compile(
    r"^\s*(?:por favor\s*,?\s*)?(?:pesquis\w+|busqu\w+|procur\w+|encontr\w+|me\s+(?:diga|fale|mostre|traga)|"
    r"fa[cç]a\s+uma\s+pesquisa\s+(?:sobre|de)|quero\s+saber|preciso\s+saber)\s+(?:(?:sobre|a\s+respeito\s+de|por)\s+)?",
    re.I)
_PEDIDO_NOTICIA = re.compile(
    r"\b(not[ií]cias?|hoje|agora|[uú]ltimas?|recente|esta semana|ontem|cota[cç][aã]o|"
    r"o que (?:est[aá] )?acontec\w+|aconteceu)\b", re.I)
_SITES_DICIONARIO = re.compile(
    r"(dicio\.com\.br|significados\.com\.br|priberam|wiktionary|infopedia|michaelis|aulete)", re.I)
_PEDIDO_DEFINICAO = re.compile(r"\b(significado|o que (?:é|significa)|defini[cç][aã]o|sin[oô]nimo)\b", re.I)
_STOP = {"de", "do", "da", "dos", "das", "o", "a", "os", "as", "e", "em", "no", "na", "um", "uma", "para",
         "com", "por", "que", "sobre", "como", "me", "meu", "minha", "sua", "seu", "hoje", "agora"}


def _tokens(texto: str) -> list[str]:
    import unicodedata
    t = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return [w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2 and w not in _STOP]


def limpar_consulta(pergunta: str) -> str:
    q = _IMPERATIVOS.sub("", pergunta or "").strip()
    return re.sub(r"\s+", " ", q) or (pergunta or "").strip()


def reordenar(itens: list[dict], pergunta: str) -> list[dict]:
    """Mais relevantes primeiro (palavras da pergunta no título/URL); dicionários só se for definição."""
    q = set(_tokens(pergunta))
    quer_definicao = bool(_PEDIDO_DEFINICAO.search(pergunta))

    def nota(i: dict) -> float:
        alvo = set(_tokens(i.get("titulo", "") + " " + i.get("url", "")))
        pts = len(q & alvo) / max(1, len(q))
        if _SITES_DICIONARIO.search(i.get("url", "")) and not quer_definicao:
            pts -= 1.0
        if i.get("fonte") == "noticias":
            pts += 0.15
        return pts
    return sorted(itens, key=nota, reverse=True)


def buscar_noticias(pergunta: str, limite: int = 8) -> list[dict]:
    """Notícias recentes (Google News RSS, sem chave). Parse por regex: sem XML não confiável."""
    q = urllib.parse.quote_plus(limpar_consulta(pergunta))
    req = urllib.request.Request(
        f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        bruto = r.read(1_500_000).decode("utf-8", errors="replace")
    saida = []
    for m in re.finditer(r"(?is)<item>(.*?)</item>", bruto):
        bloco = m.group(1)
        t = re.search(r"(?is)<title>(.*?)</title>", bloco)
        l = re.search(r"(?is)<link>(.*?)</link>", bloco)
        d = re.search(r"(?is)<pubDate>(.*?)</pubDate>", bloco)
        f = re.search(r"(?is)<source[^>]*>(.*?)</source>", bloco)
        if not (t and l):
            continue
        titulo = _limpar_html(re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1)))
        saida.append({"titulo": titulo, "url": html.unescape(l.group(1)).strip(), "fonte": "noticias",
                      "data": (d.group(1).strip() if d else ""), "veiculo": (_limpar_html(f.group(1)) if f else "")})
        if len(saida) >= limite:
            break
    return saida


# --------------------------------------------------------------------------- #
# Fontes com API própria (sem chave): Wikipédia, Stack Overflow; e Brave Search com chave opcional
# --------------------------------------------------------------------------- #
_PEDIDO_TECNICO = re.compile(
    r"\b(python|javascript|typescript|java|c\+\+|sql|docker|linux|windows|git|npm|pip|erro|exception|"
    r"c[oó]digo|instalar|configurar|api|bug|compilar|servidor|banco de dados|react|node|html|css|regex|"
    r"powershell|bash|kubernetes|como (?:fazer|usar|resolver))\b", re.I)


def _get_json(url: str, cabecalhos: dict | None = None, timeout: int = 20):
    import gzip
    req = urllib.request.Request(url, headers={"User-Agent": "YVAKOR/1.0 (agente local; pesquisa)",
                                               "Accept": "application/json", **(cabecalhos or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        bruto = r.read(1_500_000)
        if r.headers.get("Content-Encoding") == "gzip":
            bruto = gzip.decompress(bruto)
    return json.loads(bruto.decode("utf-8", errors="replace"))


def buscar_wikipedia(pergunta: str, limite: int = 4) -> list[dict]:
    q = re.sub(r"(?i)\b(o que (?:é|significa)|defini[cç][aã]o de|significado de|quem (?:é|foi))\b", " ", pergunta)
    q = re.sub(r"\s+", " ", q).strip() or pergunta
    d = _get_json("https://pt.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit="
                  f"{limite}&srsearch={urllib.parse.quote_plus(q)}")
    saida = []
    for it in (d.get("query") or {}).get("search", []):
        titulo = it.get("title", "")
        saida.append({"titulo": f"{titulo} — Wikipédia", "url": "https://pt.wikipedia.org/wiki/"
                      + urllib.parse.quote(titulo.replace(" ", "_")), "fonte": "wikipedia",
                      "trecho": _limpar_html(it.get("snippet", ""))})
    return saida


def buscar_stackoverflow(pergunta: str, limite: int = 4) -> list[dict]:
    q = urllib.parse.quote_plus(limpar_consulta(pergunta))
    saida: list[dict] = []
    for site in ("pt.stackoverflow", "stackoverflow"):
        try:
            d = _get_json("https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance"
                          f"&q={q}&site={site}&pagesize={limite}&filter=default")
        except Exception:
            continue
        for it in d.get("items", []):
            if it.get("is_answered") or it.get("answer_count"):
                saida.append({"titulo": html.unescape(it.get("title", "")), "url": it.get("link", ""),
                              "fonte": "stackoverflow",
                              "trecho": f"{it.get('answer_count', 0)} respostas · {it.get('score', 0)} votos"})
        if len(saida) >= limite:
            break
    return saida[:limite]


def buscar_brave(pergunta: str, limite: int = 8) -> list[dict]:
    """Busca oficial por API (chave BRAVE_API_KEY no .env). Sem a chave, não é usada."""
    import os
    chave = os.environ.get("BRAVE_API_KEY", "").strip()
    if not chave:
        return []
    d = _get_json("https://api.search.brave.com/res/v1/web/search?count="
                  f"{limite}&country=BR&search_lang=pt&q={urllib.parse.quote_plus(pergunta)}",
                  {"X-Subscription-Token": chave})
    return [{"titulo": r.get("title", ""), "url": r.get("url", ""), "fonte": "brave",
             "trecho": _limpar_html(r.get("description", ""))}
            for r in (d.get("web") or {}).get("results", [])]


def _relevante(item: dict, q: set[str]) -> bool:
    """Descarta resultado sem NENHUMA palavra da pergunta (ex.: 'baixar Chrome' para 'instalar docker')."""
    if item.get("fonte") in ("noticias", "wikipedia", "stackoverflow", "brave") or len(q) < 2:
        return True
    comum = q & set(_tokens(item.get("titulo", "") + " " + item.get("url", "") + " " + item.get("trecho", "")))
    return len(comum) >= max(1, (len(q) + 1) // 2)        # pelo menos metade dos termos da pergunta


def _pagina(url: str, limite: int = 2800, timeout: int = 12) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            bruto = r.read(1_200_000).decode("utf-8", errors="replace")
        return {"ok": True, "url": url, "titulo": _titulo(bruto),
                "texto": _limpar_html(bruto)[:limite]}
    except Exception as exc:
        return {"ok": False, "url": url, "erro": f"{type(exc).__name__}: {exc}"}


def _consulta_busca(pergunta: str) -> str:
    """Reordena para o buscador não interpretar 'funções' como matemática."""
    baixo = pergunta.lower()
    if "agente" in baixo and re.search(r"\bia\b", baixo):
        resto = re.sub(r"\b(melhores?|principais?|top|de|do|da|em|sobre|"
                       r"as|os|o|a|e)\b", " ", baixo)
        resto = re.sub(r"\bagentes?\b|\bia\b", " ", resto)
        tokens = []
        for t in re.split(r"\s+", resto):
            if len(t) > 2 and t not in tokens:
                tokens.append(t)
        return "agentes de IA " + " ".join(tokens[:6])
    return pergunta


def pesquisa_profunda(pergunta: str, router, max_fontes: int = 4) -> dict:
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return {"ok": False, "erro": "pergunta vazia"}
    try:
        consulta = _consulta_busca(pergunta)
        achados = buscar(consulta, limite=max(3, max_fontes + 2))
        if "agente" in consulta.lower():
            relevantes = [a for a in achados
                          if "agente" in (a["titulo"] + a["url"]).lower()]
            if len(relevantes) >= 2:
                achados = relevantes
    except Exception as exc:
        return {"ok": False, "erro": f"busca: {exc}"}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    fontes: list[dict] = []
    candidatos = achados[:max_fontes + 2]
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(candidatos)))) as ex:
        futuros = {ex.submit(_pagina, item["url"]): item for item in candidatos}
        for fut in as_completed(futuros):
            if len(fontes) >= max_fontes:
                break
            item = futuros[fut]
            try:
                p = fut.result()
            except Exception:
                continue
            if not p.get("ok") or len(p.get("texto") or "") < 200:
                continue
            fontes.append({"titulo": p.get("titulo") or item["titulo"],
                           "url": item["url"], "texto": p["texto"][:2600]})
    # preserva a ordem dos resultados da busca
    ordem = {i["url"]: n for n, i in enumerate(candidatos)}
    fontes.sort(key=lambda f: ordem.get(f["url"], 99))
    if not fontes:
        return {"ok": False, "erro": "nenhuma fonte legível encontrada",
                "resultados": achados[:5]}
    trecho = "\n\n".join(
        f"[{i+1}] {f['titulo']}\nURL: {f['url']}\n{f['texto'][:2200]}"
        for i, f in enumerate(fontes))
    prompt = (
        f"PERGUNTA: {pergunta}\n\nFONTES:\n{trecho}\n\n"
        "Produza uma síntese em português, objetiva e útil. Use citações "
        "numéricas [1], [2]... junto às afirmações. No final, liste as fontes "
        "com título e URL. Se as fontes discordarem, diga isso. Não invente "
        "fatos que não estejam nas fontes.")
    try:
        resposta = router.complete_messages(
            "pesquisa_sintese",
            [{"role": "system", "content":
              "Você é um pesquisador rigoroso. Responda apenas com base nas "
              "fontes fornecidas; cite [n] e liste URLs."},
             {"role": "user", "content": prompt}]) or ""
    except Exception as exc:
        resposta = f"Resumo das fontes (síntese indisponível: {exc}):\n\n" + \
                   "\n".join(f"[{i+1}] {f['titulo']} — {f['url']}" for i, f in enumerate(fontes))
    PASTA.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", pergunta.lower())[:50].strip("-") or "pesquisa"
    arq = PASTA / f"{slug}_{int(time.time())}.md"
    corpo = (f"# Pesquisa: {pergunta}\n\n**Data:** {datetime.now():%Y-%m-%d %H:%M}\n\n"
             f"{resposta}\n\n## Fontes\n" +
             "\n".join(f"{i+1}. [{f['titulo']}]({f['url']})" for i, f in enumerate(fontes)))
    try:
        arq.write_text(corpo, encoding="utf-8")
    except Exception:
        _log.debug("exceção ignorada", exc_info=True)
    return {"ok": True, "resposta": resposta, "fontes": fontes,
            "arquivo": str(arq), "pergunta": pergunta}


def registrar_ferramentas(tools, router):
    def profunda(pergunta: str, max_fontes: int = 4) -> dict:
        r = pesquisa_profunda(pergunta, router, max_fontes)
        if r.get("ok"):
            r["resultado"] = r.pop("resposta")
        return r

    def web(pergunta: str, limite: int = 8) -> dict:
        try:
            achados = buscar(pergunta, limite)
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}
        if not achados:
            return {"ok": True, "resultados": [],
                    "aviso": "Nenhum resultado relevante (os buscadores gratuitos bloqueiam robôs). Tente "
                             "navegador_pesquisar (usa o seu Chrome), reformule com termos mais específicos "
                             "ou configure BRAVE_API_KEY no .env (busca oficial por API)."}
        return {"ok": True, "resultados": achados}

    tools.register("pesquisa_web", web,
                   "Busca na web e devolve títulos/links, com notícias recentes (hoje/agora), Wikipédia (definições) "
                   "e Stack Overflow (programação). Para análise de preço/cripto/ações use mercado_analisar.",
                   {"pergunta": "str", "limite": "int?"})
    tools.register("pesquisa_profunda", profunda,
                   "Pesquisa várias fontes, sintetiza com citações [n] e salva um relatório.",
                   {"pergunta": "str", "max_fontes": "int?"})
