"""YVAKOR — comandos de voz para a rede (direto, sem IA)."""
from __future__ import annotations


from yvakor.memory.db import normalizar

PALAVRAS = ("rede", "redes", "red", "dispositivos", "dispositivo",
            "aparelhos", "aparatos", "wifi", "roteador", "smart tv",
            "chromecast", "celular", "telefone", "impressora", "iot", "lan")


def detectar(texto: str) -> dict | None:
    low = normalizar(texto or "")
    tem = any(p in low for p in PALAVRAS)
    if not tem:
        return None
    # perguntas conceituais não são comandos de rede
    if any(w in low for w in ("explique", "explica", "como funciona",
                              "por que", "porque", "o que é", "o que e",
                              "significa", "diferença", "diferenca")):
        return None
    if "monitor" in low:
        if any(w in low for w in ("pare", "parar", "desligue", "stop",
                                  "deten", "desativa")):
            return {"acao": "monitor_parar"}
        if any(w in low for w in ("inicie", "ligue", "ative", "volte",
                                  "start", "encender")):
            return {"acao": "monitor_iniciar"}
        return {"acao": "monitor_status"}
    if any(w in low for w in ("escaneie", "escanear", "escaneia", "varra",
                              "varredura", "descubra", "descobrir", "busque",
                              "procure", "scan", "escanea", "busca")):
        return {"acao": "escanear"}
    if any(w in low for w in ("camera", "câmera", "cameras", "cámaras",
                              "camaras")) and any(
            w in low for w in ("liste", "listar", "quais", "mostre",
                               "quantas", "cuantos", "cuales")):
        return {"acao": "cameras"}
    if any(w in low for w in ("quais", "liste", "listar", "mostre", "quantos",
                              "quem", "aparelhos", "dispositivos", "cuantos",
                              "cuales", "aparatos")):
        return {"acao": "listar"}
    return None


def _resumo(devs: list[dict]) -> str:
    tipos = {}
    for d in devs:
        tipos[d.get("tipo") or "desconhecido"] = tipos.get(
            d.get("tipo") or "desconhecido", 0) + 1
    partes = [f"{q} {t}" for t, q in tipos.items()]
    total = len(devs)
    nomes = [d.get("nome") for d in devs
             if d.get("tipo") in ("camera", "roteador", "tv")][:3]
    extra = f" Principais: {', '.join(nomes)}." if nomes else ""
    return f"Encontrei {total} dispositivo(s): {', '.join(partes)}.{extra}"


def executar(orchestrator, texto: str) -> dict:
    intent = detectar(texto)
    if not intent:
        return {"ok": False, "fala": ""}
    tools = orchestrator.tools
    r: dict = {}
    try:
        if intent["acao"] == "monitor_iniciar":
            m = getattr(orchestrator, "monitor_rede", None)
            r = m.iniciar() if m else {}
            fala = ("Monitoramento da rede ativado."
                    if r.get("ativo") else "Monitor de rede indisponível.")
        elif intent["acao"] == "monitor_parar":
            m = getattr(orchestrator, "monitor_rede", None)
            if m:
                m.parar()
            fala = "Monitoramento da rede parado."
        elif intent["acao"] == "monitor_status":
            m = getattr(orchestrator, "monitor_rede", None)
            st = m.status() if m else {"ativo": False}
            total = (st.get("ultima") or {}).get("total", 0)
            fala = (f"Monitoramento {'ativo' if st.get('ativo') else 'parado'}; "
                    f"{total} dispositivo(s) na última varredura.")
            r = st
        elif intent["acao"] == "escanear":
            r = tools.run("rede_escanear")
            devs = r.get("dispositivos") or []
            fala = _resumo(devs) if r.get("ok") else f"Falha na varredura: {r.get('erro')}"
        elif intent["acao"] == "cameras":
            r = tools.run("rede_camera_listar")
            cams = r.get("cameras") or []
            fala = f"Encontrei {len(cams)} câmera(s)."
        else:
            r = tools.run("rede_dispositivos")
            devs = r.get("dispositivos") or []
            fala = _resumo(devs) if devs else "Nenhum dispositivo conhecido; posso escanear a rede."
        return {"ok": True, "acao": intent["acao"], "fala": fala,
                "resultado": r}
    except Exception as exc:
        return {"ok": False, "acao": intent["acao"],
                "fala": f"Falha no comando de rede: {exc}"}
