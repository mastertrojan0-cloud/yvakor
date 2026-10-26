"""YVAKOR — Detecção simples de idioma (português × espanhol)."""
from __future__ import annotations

import re

from yvakor.memory.db import normalizar

_MARCAS_ES = {"el", "la", "los", "las", "muy", "gracias", "quiero", "puedes",
              "hola", "buenos", "buenas", "cómo", "como", "estás", "esta",
              "abre", "busca", "necesito", "tengo", "hace", "favor", "dónde",
              "donde", "qué", "que", "porque", "también", "tambien", "ahora",
              "cámara", "camara", "puerta", "luz", "archivo", "carpeta"}
_MARCAS_PT = {"muito", "obrigado", "obrigada", "você", "voce", "pode",
              "olá", "ola", "bom", "boa", "tudo", "estou", "quero", "preciso",
              "tenho", "faz", "favor", "onde", "porque", "também", "tambem",
              "agora", "câmera", "camera", "porta", "luz", "arquivo", "pasta",
              "abra", "busque", "por favor"}


def detectar(texto: str, padrao: str = "pt-BR") -> str:
    """Heurística leve (sem modelo): devolve 'pt-BR' ou 'es-ES'."""
    t = " " + normalizar(texto) + " "
    if not t.strip():
        return padrao
    pontos_es = sum(1 for p in _MARCAS_ES if re.search(rf"\b{p}\b", t))
    pontos_pt = sum(1 for p in _MARCAS_PT if re.search(rf"\b{p}\b", t))
    # "¿" e "ñ" são fortes indícios de espanhol
    if "¿" in texto or "ñ" in texto.lower():
        pontos_es += 2
    if "ã" in texto.lower() or "õ" in texto.lower() or "ç" in texto.lower():
        pontos_pt += 2
    if pontos_es > pontos_pt:
        return "es-ES"
    if pontos_pt > pontos_es:
        return "pt-BR"
    return padrao


def normalizar_idioma(idioma: str | None, padrao: str = "pt-BR") -> str:
    if not idioma or idioma.lower() in ("auto", ""):
        return padrao
    baixo = idioma.lower()
    if baixo.startswith("es"):
        return "es-ES"
    if baixo.startswith("pt"):
        return "pt-BR"
    return padrao
