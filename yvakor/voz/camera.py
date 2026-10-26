"""YVAKOR — comandos de voz diretos para a câmera (sem passar pela IA).

Frases como "mostre a câmera", "tire uma foto", "grave dez segundos",
"mova para a esquerda" ou "feche a câmera" são reconhecidas e executam a
ferramenta certa na hora, com resposta falada curta.
"""
from __future__ import annotations

import re

from yvakor.memory.db import normalizar

PALAVRAS_CAMERA = ("camara", "camaras", "camera", "câmera", "cameras",
                   "câmeras", "vigia", "monitor", "entrada", "garagem",
                   "quintal", "portao", "portão")


def detectar(texto: str) -> dict | None:
    low = normalizar(texto or "")
    tem_camera = any(p in low for p in PALAVRAS_CAMERA) or "camera" in low
    if tem_camera and any(w in low for w in ("abra", "abrir", "mostre",
                                             "mostrar", "ver", "ao vivo",
                                             "live", "janela", "monitorar",
                                             "muestra", "muestrame", "abre",
                                             "ensename", "en vivo")):
        return {"acao": "abrir"}
    if any(w in low for w in ("foto", "fotografia", "snapshot", "captura",
                              "imagem", "quadro", "imagen")):
        return {"acao": "foto"}
    if any(w in low for w in ("grave", "gravar", "gravacao", "gravação",
                              "clipe", "filme", "graba", "grabar",
                              "grabacion")):
        segundos = re.search(r"(\d+)\s*(segundo|s\b)", low)
        return {"acao": "gravar", "segundos": int(segundos.group(1)) if segundos else 10}
    direcao = ""
    for nome in ("esquerda", "direita", "cima", "baixo",
                 "izquierda", "derecha", "arriba", "abajo"):
        if nome in low:
            direcao = {"izquierda": "esquerda", "derecha": "direita",
                       "arriba": "cima", "abajo": "baixo"}.get(nome, nome)
    if "zoom" in low or direcao or "acerca" in low or "aleja" in low:
        if ("zoom out" in low or "afast" in low or "menos zoom" in low
                or "aleja" in low):
            zoom = "menos"
        elif ("zoom" in low or "aproxim" in low or "acerca" in low):
            zoom = "mais"
        else:
            zoom = ""
        return {"acao": "ptz", "direcao": direcao, "zoom": zoom}
    if tem_camera and any(w in low for w in ("feche", "fechar", "pare",
                                             "parar", "desligue", "cierra",
                                             "cerrar", "deten", "apaga")):
        return {"acao": "fechar"}
    if tem_camera and any(w in low for w in ("lista", "listar", "quais",
                                             "dispositivos", "quantas",
                                             "cuales", "cuantas")):
        return {"acao": "listar"}
    if tem_camera and any(w in low for w in ("status", "estado",
                                             "funcionando", "online",
                                             "en linea")):
        return {"acao": "status"}
    return None


def _alvo(orchestrator, texto: str) -> str:
    ip = re.search(r"\d{1,3}(?:\.\d{1,3}){3}", texto or "")
    if ip:
        return ip.group(0)
    try:
        cams = [d for d in orchestrator.rede.cameras.registro.dispositivos()
                if d.get("tipo") == "camera" or 554 in (d.get("portas") or [])]
        if cams:
            return cams[0]["ip"]
    except Exception:
        pass
    return "192.168.15.7"


def executar(orchestrator, texto: str) -> dict:
    intent = detectar(texto)
    if not intent:
        return {"ok": False, "fala": ""}
    acao = intent["acao"]
    alvo = _alvo(orchestrator, texto)
    tools = orchestrator.tools
    try:
        if acao == "abrir":
            r = tools.run("rede_camera_janela", alvo=alvo)
            fala = "Abrindo a câmera ao vivo no monitor do YVAKOR."
        elif acao == "foto":
            r = tools.run("rede_camera_snapshot", alvo=alvo)
            fala = ("Foto da câmera salva." if r.get("ok")
                    else f"Não consegui a foto: {r.get('erro', 'sem imagem')}")
        elif acao == "gravar":
            r = tools.run("rede_camera_gravar", alvo=alvo,
                          segundos=intent.get("segundos", 10))
            fala = ("Gravação concluída." if r.get("ok")
                    else f"Não consegui gravar: {r.get('erro', 'sem sinal')}")
        elif acao == "ptz":
            x = -1.0 if intent.get("direcao") == "esquerda" else (
                1.0 if intent.get("direcao") == "direita" else 0.0)
            y = 1.0 if intent.get("direcao") == "cima" else (
                -1.0 if intent.get("direcao") == "baixo" else 0.0)
            zoom = 0.4 if intent.get("zoom") == "mais" else (
                -0.4 if intent.get("zoom") == "menos" else 0.0)
            r = tools.run("rede_camera_ptz", alvo=alvo, x=x, y=y, zoom=zoom)
            fala = ("Movimento enviado." if r.get("ok")
                    else f"Não consegui mover: {r.get('erro', 'câmera sem PTZ')}")
        elif acao == "listar":
            r = tools.run("rede_camera_listar")
            total = r.get("total", len(r.get("cameras") or []))
            fala = f"Encontrei {total} câmera(s)."
        elif acao == "status":
            r = tools.run("rede_camera_info", alvo=alvo)
            fala = ("Câmera online." if r.get("ok")
                    else "Câmera sem resposta agora.")
        else:  # fechar
            r = {"ok": True}
            fala = "Feche a aba do monitor para encerrar a visualização."
        return {"ok": True, "acao": acao, "fala": fala,
                "resultado": r}
    except Exception as exc:
        return {"ok": False, "acao": acao,
                "fala": f"Falha no comando de câmera: {exc}"}
