"""Utilitários de texto sem dependências pesadas (usados pelo agente e pela GUI)."""
from __future__ import annotations

import json
import re


def sem_json_de_ferramenta(texto: str) -> str:
    """Tira do texto final os blocos JSON de chamada de ferramenta que o modelo
    deixou escapar no meio da prosa ({"acao":"usar_ferramenta",...}): são
    protocolo interno, não resposta. Se só sobrar isso, devolve o original."""
    dec = json.JSONDecoder()
    saida, i = [], 0
    while True:
        j = texto.find("{", i)
        if j < 0:
            saida.append(texto[i:])
            break
        try:
            obj, fim = dec.raw_decode(texto[j:])
        except Exception:
            saida.append(texto[i:j + 1])
            i = j + 1
            continue
        if isinstance(obj, dict) and (
                "acao" in obj or ("ferramenta" in obj and "args" in obj)):
            saida.append(texto[i:j])
        else:
            saida.append(texto[i:j + fim])
        i = j + fim
    limpo = re.sub(r"\n{3,}", "\n\n", "".join(saida)).strip()
    return limpo or texto
