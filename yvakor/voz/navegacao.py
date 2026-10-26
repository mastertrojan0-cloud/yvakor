"""YVAKOR — abrir sites e diagnosticar navegador por texto/voz (sem IA)."""
from __future__ import annotations

import re

from yvakor.memory.db import normalizar

SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "whatsapp": "https://web.whatsapp.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://www.netflix.com",
    "mercado livre": "https://www.mercadolivre.com.br",
    "correios": "https://www.correios.com.br",
}


def detectar(texto: str) -> dict | None:
    low = normalizar(texto or "")
    if any(p in low for p in ("nao esta abrindo", "não está abrindo",
                              "nao abre nada", "não abre nada",
                              "nada abre", "nao abriu")):
        return {"acao": "diagnostico"}
    if not re.search(r"\b(abre|abra|abrir|abram)\b", low):
        return None
    url = re.search(r"https?://\S+", texto or "")
    if url:
        alvo = url.group(0).rstrip(".,;)")
    else:
        alvo = ""
        for chave, link in SITES.items():
            if re.search(rf"\b{re.escape(chave)}\b", low):
                alvo = link
                break
        if not alvo:
            dominio = re.search(
                r"\b((?:www\.)?[a-z0-9-]+\.(?:com|com\.br|net|org|io|dev|gov|edu)(?:\.br)?)\b",
                low)
            if dominio:
                alvo = "https://" + dominio.group(1)
    if not alvo:
        return None
    # Pedido composto ("abre o YouTube e pesquise X") precisa do agente,
    # não apenas do atalho de abertura.
    if re.search(r"\b(e|depois|em seguida|entao|então)\b", low) and re.search(
            r"\b(pesquise|pesquisa|busque|busca|procure|procura|clique|clica|"
            r"digite|digita|preencha|preenche|assista|assiste|toque|toca|"
            r"tocar|coloca|coloque|colocar|reproduza|reproduz|baixe|compre|"
            r"envie|leia|resuma|analise|verifique|escolha|escolhe|diga|dizer|"
            r"fale|mostre|mostrar)\b", low):
        return None
    motor = "chrome" if "chrome" in low else ("edge" if "edge" in low else "")
    return {"acao": "abrir", "url": alvo, "motor": motor}


def executar(orchestrator, intent: dict) -> str:
    if intent.get("acao") == "diagnostico":
        try:
            st = orchestrator.navegadores.status()
            return ("O navegador controlado está "
                    + ("aberto" if st.get("aberto") else "fechado")
                    + ". Diga o site que devo abrir, por exemplo: "
                    "“abre o YouTube no Chrome”.")
        except Exception:
            return ("O navegador não está aberto. Diga o site: "
                    "“abre o YouTube no Chrome”.")
    url = intent.get("url") or ""
    motor = intent.get("motor") or ""
    try:
        r = orchestrator.tools.run("navegador_abrir", url=url,
                                   navegador=motor)
    except Exception as exc:
        return f"Não consegui abrir {url}: {exc}"
    if not r.get("ok"):
        return f"Não consegui abrir {url}: {r.get('erro') or r.get('error')}"
    nome = "Chrome" if motor == "chrome" else (
        "Edge" if motor == "edge" else r.get("engine", "navegador"))
    return f"Abri {r.get('titulo') or url} no {nome}."
