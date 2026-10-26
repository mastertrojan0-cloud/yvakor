"""YVAKOR — comandos de voz/texto para o aprendiz de entorno."""
from __future__ import annotations

from yvakor.memory.db import normalizar


def detectar(texto: str) -> dict | None:
    low = normalizar(texto or "")
    if any(w in low for w in ("mapeie", "mapear", "mapeamento", "inventario",
                              "inventário", "aprenda o ambiente",
                              "aprender o ambiente", "atualize o ambiente")):
        return {"acao": "mapear"}
    if any(w in low for w in ("aprenda sobre", "aprender sobre",
                              "ficha de", "ficha do", "aprenda o",
                              "aprender o")):
        alvo = low
        for prefixo in ("aprenda sobre ", "aprender sobre ", "ficha de ",
                        "ficha do ", "aprenda o ", "aprender o "):
            if prefixo in alvo:
                alvo = alvo.split(prefixo, 1)[1].strip()
                break
        return {"acao": "ficha", "alvo": alvo}
    return None


def executar(orchestrator, texto: str) -> dict:
    intent = detectar(texto)
    if not intent:
        return {"ok": False, "fala": ""}
    try:
        if intent["acao"] == "mapear":
            r = orchestrator.tools.run("ambiente_mapear")
            fala = (f"Ambiente mapeado: {r.get('equipamentos', 0)} "
                    f"equipamento(s) com ficha no vault.")
        else:
            r = orchestrator.tools.run("ambiente_equipamento",
                                       alvo=intent.get("alvo") or "")
            fala = (f"Ficha de {r.get('ip')} atualizada." if r.get("ok")
                    else f"Não encontrei: {r.get('erro')}")
        return {"ok": bool(r.get("ok")), "acao": intent["acao"],
                "fala": fala, "resultado": r}
    except Exception as exc:
        return {"ok": False, "acao": intent["acao"],
                "fala": f"Falha no aprendiz de ambiente: {exc}"}
