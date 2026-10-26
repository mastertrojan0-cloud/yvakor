"""YVAKOR — detectar continuações de conversa (para não responder no vácuo)."""
from __future__ import annotations

import re

from yvakor.memory.db import normalizar

_INICIO = ("e ", "entao ", "então ", "sim", "nao", "não", "isso", "disso",
           "ai ", "aí ", "certo", "ok", "pode ", "faca ", "faça ", "continua",
           "continue", "prossiga")
_PRONOMES = ("isso", "disso", "desse", "dessa", "dele", "dela", "ele", "ela",
             "anterior", "acima", "mesmo", "mesma")
_REFERENCIA = ("estou", "estava", "falei", "pedi", "disse", "mencionei",
               "queria", "pedido", "pergunta")


def eh_continuacao(texto: str) -> bool:
    """True quando a fala depende do turno anterior para fazer sentido."""
    low = normalizar(texto or "").strip()
    if not low:
        return True
    palavras = low.split()
    if len(palavras) <= 2 and palavras[0] in ("sim", "nao", "não", "ok",
                                              "certo", "isso", "continue"):
        return True
    if low.startswith(_INICIO):
        return True
    if any(p in palavras for p in _PRONOMES):
        return True
    if re.search(r"\b(estou|estava|falei|pedi|disse|mencionei|queria)\b", low):
        return True
    if re.search(r"\b(meu|minha|comigo|eu)\b.{0,40}"
                 r"\b(nome|projeto|pedido|pergunta|tarefa|conversa|falei|"
                 r"disse|estou|estava)\b", low):
        return True
    return False
