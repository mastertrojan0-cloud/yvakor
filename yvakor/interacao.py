"""YVAKOR — canal agente → usuário durante uma execução (pergunta e plano).

Mesmo padrão do confirmador do Guard (tools/guard.py): o orquestrador injeta,
por thread, uma função que faz o handshake com a interface que está olhando
aquela conversa (app, web ou extensão) via ConfirmationBroker. Sem função
injetada (CLI, testes, chamada direta) o agente segue sem perguntar.

    fn(tipo, titulo, detalhe, opcoes) -> {"allow": bool, "resposta": str|None} | None
"""
from __future__ import annotations

import threading

_local = threading.local()


def definir(fn) -> None:
    _local.perguntar = fn


def limpar() -> None:
    _local.perguntar = None


def disponivel() -> bool:
    return getattr(_local, "perguntar", None) is not None


def perguntar(tipo: str, titulo: str, detalhe: str = "",
              opcoes: list[str] | None = None) -> dict | None:
    """None = não há interface ou o usuário não respondeu a tempo."""
    fn = getattr(_local, "perguntar", None)
    if fn is None:
        return None
    try:
        return fn(tipo, titulo, detalhe, list(opcoes or []))
    except Exception:
        return None
