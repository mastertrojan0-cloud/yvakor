"""
YVAKOR — wrappers de subprocess que não piscam janela de console no Windows.

No Windows, chamar um programa de console (nbtstat, arp, ffmpeg, powershell,
adb…) com subprocess abre uma janela de console preta por um instante, mesmo
com stdout/stderr redirecionados. Como o YVAKOR roda varreduras de rede, OCR,
TTS e snapshots em segundo plano (inclusive periodicamente), isso fazia janelas
"piscarem na tela a cada momento".

Estas funções injetam CREATE_NO_WINDOW (e um STARTUPINFO com janela oculta) por
padrão. Em outros SOs são equivalentes a subprocess.run/Popen.
"""
from __future__ import annotations

import os
import subprocess

_NT = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if _NT else 0


def _preparar(kwargs: dict) -> dict:
    # Só CREATE_NO_WINDOW: suprime a janela de console de programas de console
    # e é inofensivo para apps GUI. NÃO usamos STARTUPINFO/SW_HIDE, que poderia
    # esconder a janela de um app GUI legítimo (o Chrome controlado, o Yoosee).
    if _NT:
        kwargs.setdefault("creationflags", NO_WINDOW)
    return kwargs


def run(*args, **kwargs):
    return subprocess.run(*args, **_preparar(kwargs))


def popen(*args, **kwargs):
    return subprocess.Popen(*args, **_preparar(kwargs))
