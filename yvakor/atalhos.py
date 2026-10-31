"""Atalhos "/comando" (como os workflows do Claude) para o app nativo.

Espelho de chrome-extension/atalhos.js — os mesmos atalhos padrão e as mesmas
regras. tests/test_extensao_estilo_claude.py confere que os dois não divergem.
O prompt aceita {args}, {selecao}, {url} e {titulo}.

Comandos do NÚCLEO (GET /api/comandos: /skills, /plugins, /<skill>, comandos
de plugin) entram com "servidor": True e seguem intactos para o servidor.
"""
from __future__ import annotations

import re

PADRAO = [
    {"comando": "resumir", "nome": "Resumir a página",
     "prompt": "Resuma esta página em até 6 tópicos curtos e destaque o ponto principal."},
    {"comando": "explicar", "nome": "Explicar a seleção", "exige": "selecao",
     "prompt": "Explique de forma simples o trecho que selecionei na página:\n\n{selecao}"},
    {"comando": "pesquisar", "nome": "Pesquisar na web", "exige": "args",
     "prompt": "Pesquise na web sobre: {args}. Traga as 3 melhores fontes, "
               "com um resumo de cada e o link."},
    {"comando": "extrair", "nome": "Extrair dados em tabela",
     "prompt": "Extraia os dados principais desta página e apresente em uma tabela."},
    {"comando": "formulario", "nome": "Preencher formulário", "exige": "args",
     "prompt": "Veja os campos do formulário desta página e preencha o que for óbvio "
               "com estes dados: {args}. Antes de enviar, me mostre o que preencheu "
               "e pergunte o que faltar."},
    {"comando": "traduzir", "nome": "Traduzir a página",
     "prompt": "Traduza o conteúdo principal desta página para o português do Brasil."},
]


def _norm(c) -> str:
    return re.sub(r"[^a-z0-9_:-]", "", str(c or "").lower().lstrip("/"))


def juntar(usuario=None, servidor=None) -> list[dict]:
    mapa = {a["comando"]: dict(a) for a in PADRAO}
    for a in usuario or []:
        c = _norm((a or {}).get("comando"))
        if c and str(a.get("prompt") or "").strip():
            mapa[c] = {"comando": c, "nome": str(a.get("nome") or c)[:60],
                       "prompt": str(a["prompt"]), "exige": a.get("exige") or None}
    for s in servidor or []:
        c = _norm((s or {}).get("comando"))
        if c and c not in mapa:
            mapa[c] = {"comando": c, "nome": str(s.get("nome") or c)[:60], "servidor": True}
    return list(mapa.values())


def expandir(texto: str, lista: list[dict] | None = None, ctx: dict | None = None) -> dict:
    """{'ok':True,'prompt':...} | {'nao_atalho':True} | {'erro':...}"""
    lista = lista if lista is not None else juntar()
    ctx = ctx or {}
    t = str(texto or "").strip()
    if not t.startswith("/"):
        return {"nao_atalho": True}
    m = re.match(r"^/(\S+)\s*([\s\S]*)$", t)
    if not m:
        return {"nao_atalho": True}
    cmd, args = _norm(m.group(1)), (m.group(2) or "").strip()
    atalho = next((a for a in lista if a["comando"] == cmd), None)
    if atalho is None:
        if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{1,19}", m.group(1)):
            return {"erro": f"O atalho /{cmd} não existe. Digite / para ver os disponíveis."}
        return {"nao_atalho": True}
    if atalho.get("servidor"):
        return {"ok": True, "prompt": t}
    if atalho.get("exige") == "selecao" and not str(ctx.get("selecao") or "").strip():
        return {"erro": f"Selecione um texto na página antes de usar /{cmd}."}
    if atalho.get("exige") == "args" and not args:
        return {"erro": f"Use: /{cmd} <o que você quer>"}
    vals = {"args": args, "selecao": str(ctx.get("selecao") or "")[:4000],
            "url": ctx.get("url") or "", "titulo": ctx.get("titulo") or ""}
    prompt = re.sub(r"\{(args|selecao|url|titulo)\}", lambda k: vals[k.group(1)],
                    atalho["prompt"])
    if args and "{args}" not in atalho["prompt"]:
        prompt += "\n\nInformação adicional: " + args
    return {"ok": True, "prompt": prompt}
