"""Utilitários de texto sem dependências pesadas (usados pelo agente e pela GUI)."""
from __future__ import annotations

import json
import re
import logging

_log = logging.getLogger(__name__)


_OBS = re.compile(r"OBSERVA[ÇC][ÃA]O\s*\([^)\n]{0,60}\)\s*:\s*", re.I)


def sem_json_de_ferramenta(texto: str) -> str:
    """Tira do texto final os blocos JSON de chamada de ferramenta que o modelo
    deixou escapar no meio da prosa ({"acao":"usar_ferramenta",...}): são
    protocolo interno, não resposta. Se só sobrar isso, devolve o original.
    A marcação DSML do DeepSeek (<｜｜DSML｜｜ invoke …>) sai sempre, mesmo que
    não sobre nada: nunca é texto para o usuário."""
    if "DSML" in texto:
        texto = re.sub(r"<[^>\n]*DSML.*DSML[^>\n]*>", "", texto, flags=re.S)
        texto = re.sub(r"</?[^>\n]*DSML[^>\n]*>", "", texto).strip()
        if not texto:
            return ""
    if "<tool_" in texto:                 # <tool_browser_navigate>…</tool_…>
        sem = re.sub(r"<tool_(\w+)>.*?</tool_\1>", "", texto, flags=re.S).strip()
        if sem != texto.strip():
            if not sem:
                return ""
            texto = sem
    dec = json.JSONDecoder()
    if _OBS.search(texto):
        # o modelo pequeno ecoava "OBSERVAÇÃO (navegador_ver): {json cru}"
        partes, i = [], 0
        for m in _OBS.finditer(texto):
            if m.start() < i:
                continue
            partes.append(texto[i:m.start()])
            i = m.end()
            resto = texto[i:].lstrip()
            if resto.startswith("{"):
                try:
                    _, fim = dec.raw_decode(resto)
                    i += (len(texto[i:]) - len(resto)) + fim
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
        partes.append(texto[i:])
        sem_obs = "".join(partes).strip()
        if sem_obs:
            texto = sem_obs
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
                "acao" in obj or (("ferramenta" in obj or "tool" in obj)
                                  and ("args" in obj or "arguments" in obj))):
            saida.append(texto[i:j])
        else:
            saida.append(texto[i:j + fim])
        i = j + fim
    limpo = re.sub(r"\n{3,}", "\n\n", "".join(saida)).strip()
    return limpo or texto
