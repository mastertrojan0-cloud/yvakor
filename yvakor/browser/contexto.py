"""
YVAKOR — Contexto de navegação por tarefa

Cada thread (chat, tarefa cowork, requisição da interface) pode ter sua própria
aba/motor. É o que impede duas tarefas de segundo plano de dirigirem a mesma
página ao mesmo tempo.
"""
from __future__ import annotations

import threading

_local = threading.local()


def definir(aba: str | None = None, motor: str | None = None) -> None:
    _local.aba = aba
    _local.motor = motor


def limpar() -> None:
    _local.aba = None
    _local.motor = None


def aba_atual() -> str:
    return getattr(_local, "aba", None) or "principal"


def motor_atual() -> str | None:
    return getattr(_local, "motor", None)
