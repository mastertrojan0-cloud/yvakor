"""YVAKOR — gerente autônomo de dispositivos (o agente no comando).

A cada ciclo: agrupa por tipo, testa capacidades e mantém a ficha atualizada.
Campos com `manual=1` foram definidos pelo usuário e NÃO são sobrescritos.
"""
from __future__ import annotations
import logging

_log = logging.getLogger(__name__)

GRUPOS = {"camera": "câmeras", "tv": "TVs", "telefone": "telefones",
          "roteador": "infra", "iot": "IoT", "impressora": "impressoras",
          "computador": "computadores"}


def organizar(rede) -> dict:
    from yvakor.ambiente import _probe
    acoes = []
    for dev in rede.registro.listar():
        if dev.get("manual"):
            acoes.append({"ip": dev.get("ip"), "acao": "preservado (manual)"})
            continue
        campos = {}
        grupo = GRUPOS.get((dev.get("tipo") or "").lower(), "")
        if grupo and dev.get("grupo") != grupo:
            campos["grupo"] = grupo
        try:
            testes = _probe(rede, dev)
            if testes:
                campos["ultimo_teste"] = " | ".join(testes)[:300]
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        if campos:
            rede.registro.atualizar(dev.get("ip"), **campos)
            acoes.append({"ip": dev.get("ip"), "acao": "atualizado",
                          "campos": sorted(campos)})
    return {"ok": True, "dispositivos": len(acoes), "acoes": acoes}
