"""
YVAKOR — Ferramentas de voz para o agente

O agente pode falar (TTS) e transcrever áudios (STT). Ouvir pelo microfone
também é possível, mas depende de hardware e de alguém falando na hora — em
tarefa de segundo plano isso não faz sentido, então o texto vem de arquivo.
"""
from __future__ import annotations

from yvakor.voz.assistente import AssistenteVoz, contem_ativacao, limpar_para_fala


def _safe(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def register_voz_tools(registry, voz: AssistenteVoz) -> list[str]:
    reg = registry.register

    def falar(texto: str, motor: str = "", idioma: str = "") -> dict:
        r = voz.tts.falar(limpar_para_fala(texto), motor=motor or None,
                          idioma=idioma or None)
        if r.get("ok"):
            r["texto_falado"] = limpar_para_fala(texto)[:300]
        return r

    def ouvir(segundos: float = 6, idioma: str = "") -> dict:
        return _safe(voz.ouvir, float(segundos))

    def transcrever(arquivo: str, idioma: str = "") -> dict:
        return voz.stt.transcrever_arquivo(arquivo, idioma=idioma or None)

    def status() -> dict:
        return {"ok": True, "stt": voz.stt.status(), "tts": voz.tts.vozes(),
                "palavra_ativacao": voz.palavra}

    reg("voz_falar", falar,
        "Fala um texto em voz alta (pt-BR) no alto-falante desta máquina. "
        "Use para avisos e para responder quando o usuário pedir por voz.",
        {"texto": "str", "motor": "str?", "idioma": "str?"})
    reg("voz_ouvir", ouvir,
        "Escuta o microfone até o silêncio e devolve o texto transcrito.",
        {"segundos": "float?", "idioma": "str?"})
    reg("voz_transcrever", transcrever,
        "Transcreve um arquivo de áudio (wav/mp3/ogg) para texto.",
        {"arquivo": "str", "idioma": "str?"})
    reg("voz_status", status,
        "Mostra o estado da voz: modelo STT, microfone e vozes TTS.", {})

    return [n for n in registry.tools if n.startswith("voz_")]


__all__ = ["register_voz_tools", "AssistenteVoz", "contem_ativacao",
           "limpar_para_fala"]
