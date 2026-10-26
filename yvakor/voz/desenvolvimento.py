"""YVAKOR — desenvolvimento completo por texto/voz (gera, salva, mostra)."""
from __future__ import annotations

from yvakor.memory.db import normalizar

VERBOS = ("crie", "criar", "desenvolva", "desenvolver", "faça", "faca",
          "construa", "monte", "gere", "gerar")
ALVOS = ("calculadora", "site", "aplicativo", "app", "jogo", "painel",
         "dashboard", "interface", "frontend", "formulario", "formulário",
         "pagina", "página", "landing", "sistema web")


def detectar(texto: str) -> dict | None:
    low = normalizar(texto or "")
    if any(v in low for v in VERBOS) and any(a in low for a in ALVOS):
        return {"acao": "desenvolver"}
    return None


def executar(orchestrator, texto: str) -> dict:
    if not detectar(texto):
        return {"ok": False, "fala": ""}
    try:
        r = orchestrator.tools.run("cap_desenvolver", descricao=texto,
                                   tipo="html", abrir=True)
        if not r.get("ok"):
            return {"ok": False, "fala": f"Não consegui gerar: {r.get('erro')}"}
        fala = ("Projeto criado e aberto no navegador. "
                f"Arquivo: {r.get('arquivo')}")
        return {"ok": True, "acao": "desenvolver", "fala": fala,
                "url": r.get("url"), "arquivo": r.get("arquivo"),
                "resultado": r}
    except Exception as exc:
        return {"ok": False, "fala": f"Falha ao desenvolver: {exc}"}
