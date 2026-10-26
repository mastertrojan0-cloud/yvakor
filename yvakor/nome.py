"""YVAKOR — reconhecer quando o agente é chamado pelo nome."""
from __future__ import annotations

import re

VARIANTES = ("yvakor", "yvacor", "ivacor", "evacor", "eva cor", "iva cor",
             "yva kor", "yvakour", "i vakor", "yva cor", "eva coruja",
             "iva coruja")
_PADRAO = re.compile(
    r"^(?:(?:oi|olá|ola|ei|hey|fala)\s*[,.!]?\s*)?("
    + "|".join(re.escape(v) for v in sorted(VARIANTES, key=len, reverse=True))
    + r")(?:\s*[,.!?;:\-–—]\s*|\s+|$)(.*)$",
    re.IGNORECASE | re.DOTALL)


def separar(texto: str) -> tuple[bool, str]:
    """Retorna (foi_chamado_pelo_nome, resto_do_pedido)."""
    t = (texto or "").strip()
    m = _PADRAO.match(t)
    if not m:
        return False, t
    return True, (m.group(2) or "").strip()


def apenas_nome(texto: str) -> bool:
    chamou, resto = separar(texto)
    return chamou and not resto
