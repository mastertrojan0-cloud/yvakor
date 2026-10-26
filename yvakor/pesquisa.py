"""YVAKOR — pesquisa profunda na web com fontes citadas."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from yvakor.config import ROOT

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
        pass
    return href


def buscar(pergunta: str, limite: int = 8) -> list[dict]:
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
        pass
    return itens


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
        pass
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
            return {"ok": True, "resultados": buscar(pergunta, limite)}
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}

    tools.register("pesquisa_web", web,
                   "Busca na web (DuckDuckGo) e devolve títulos/links.",
                   {"pergunta": "str", "limite": "int?"})
    tools.register("pesquisa_profunda", profunda,
                   "Pesquisa várias fontes, sintetiza com citações [n] e salva um relatório.",
                   {"pergunta": "str", "max_fontes": "int?"})
