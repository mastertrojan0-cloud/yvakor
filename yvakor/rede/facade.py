"""
YVAKOR — Fachada de rede

Um único objeto que o orquestrador cria e as ferramentas usam: escopo,
registro de dispositivos, câmeras, Chromecast, TVs, celulares e IoT.
"""
from __future__ import annotations

from yvakor.rede.camera import Cameras
from yvakor.rede.cast import Chromecasts
from yvakor.rede.descoberta import Descobridor, ROTULOS
from yvakor.rede.escopo import EscopoRede
from yvakor.rede.iot import MQTT, HTTPDispositivo
from yvakor.rede.registro import RegistroRede
from yvakor.rede.telefone import Telefones
from yvakor.rede.tv import Televisores


class Rede:
    def __init__(self, settings: dict):
        self.settings = settings
        self.escopo = EscopoRede(settings)
        self.registro = RegistroRede()
        self.descobridor = Descobridor(settings, self.escopo, self.registro)
        self.cameras = Cameras(settings, self.escopo, self.registro)
        self.casts = Chromecasts(self.escopo)
        self.tvs = Televisores(self.registro, self.escopo)
        self.telefones = Telefones(settings, self.escopo)
        self.http = HTTPDispositivo(self.escopo)
        self.mqtt = MQTT(((settings or {}).get("rede") or {}).get("mqtt"))

    # ------------------------------------------------------------------ #
    def resumo(self) -> str:
        devs = self.registro.listar()
        if not devs:
            return ("Nenhum dispositivo conhecido. Use rede_escanear para "
                    "descobrir o que está na rede.")
        por_tipo: dict[str, int] = {}
        for d in devs:
            por_tipo[d["tipo"]] = por_tipo.get(d["tipo"], 0) + 1
        partes = [f"{ROTULOS.get(t, t)}: {n}" for t, n in
                  sorted(por_tipo.items(), key=lambda x: -x[1])]
        return (f"{len(devs)} dispositivo(s) conhecido(s) — " + " · ".join(partes)
                + "\n" + self.escopo.descrever())

    def shutdown(self) -> None:
        try:
            self.casts.shutdown()
        except Exception:
            pass
