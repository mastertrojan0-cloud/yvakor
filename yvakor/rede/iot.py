"""
YVAKOR — IoT: Wake-on-LAN, MQTT e HTTP de dispositivos

  • WoL          — liga PC/TV pela rede (magic packet)
  • MQTT         — publica/lê tópicos (Tasmota, ESPHome, Shelly, Zigbee2MQTT)
  • HTTP device  — Tasmota (`/cm?cmnd=`), Shelly (`/rpc/`) e qualquer API HTTP
                   simples de aparelho dentro do escopo autorizado
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


# ----------------------------------------------------------------------- #
# Wake-on-LAN
# ----------------------------------------------------------------------- #
def wol(mac: str, broadcast: str = "255.255.255.255", porta: int = 9) -> dict:
    limpo = mac.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(limpo) != 12 or any(c not in "0123456789abcdefABCDEF" for c in limpo):
        raise ValueError(f"MAC inválido: {mac}")
    pacote = b"\xff" * 6 + bytes.fromhex(limpo) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        enviados = 0
        for destino in (broadcast, "255.255.255.255"):
            try:
                s.sendto(pacote, (destino, porta))
                enviados += 1
            except OSError:
                continue
    finally:
        s.close()
    if not enviados:
        return {"ok": False, "erro": "não consegui enviar o magic packet"}
    return {"ok": True, "mac": mac, "broadcast": broadcast,
            "obs": "o aparelho precisa ter WoL ligado na BIOS/rede"}


# ----------------------------------------------------------------------- #
# MQTT
# ----------------------------------------------------------------------- #
class MQTT:
    def __init__(self, cfg: dict | None = None):
        self.cfg = (cfg or {})
        self.host = str(self.cfg.get("host") or "").strip()
        self.porta = int(self.cfg.get("port") or 1883)
        self.user = str(self.cfg.get("user") or "")
        self.senha = str(self.cfg.get("password") or "")
        self.tls = bool(self.cfg.get("tls"))
        self.ultimo_erro = ""

    def configurado(self) -> bool:
        return bool(self.host)

    def _cliente(self, client_id: str = "yvakor"):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("instale paho-mqtt") from exc
        c = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        if self.user:
            c.username_pw_set(self.user, self.senha or None)
        if self.tls:
            c.tls_set()
        return c

    def publicar(self, topico: str, payload, retain: bool = False,
                 timeout: float = 8.0) -> dict:
        if not self.configurado():
            raise RuntimeError("MQTT não configurado (rede.mqtt.host no settings.yaml)")
        c = self._cliente()
        c.connect(self.host, self.porta, keepalive=20)
        c.loop_start()
        try:
            if not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False)
            info = c.publish(topico, payload, qos=0, retain=bool(retain))
            info.wait_for_publish(timeout=timeout)
            return {"ok": info.is_published(), "topico": topico,
                    "payload": payload[:200], "retain": bool(retain)}
        finally:
            c.loop_stop()
            try:
                c.disconnect()
            except Exception:
                pass

    def ler(self, topico: str, segundos: float = 3.0,
            max_msgs: int = 30) -> dict:
        if not self.configurado():
            raise RuntimeError("MQTT não configurado (rede.mqtt.host no settings.yaml)")
        mensagens: list[dict] = []

        def ao_receber(cliente, userdata, msg):
            try:
                texto = msg.payload.decode("utf-8", "replace")
            except Exception:
                texto = repr(msg.payload[:100])
            mensagens.append({"topico": msg.topic, "payload": texto[:500],
                              "retain": bool(msg.retain)})

        c = self._cliente()
        c.on_message = ao_receber
        c.connect(self.host, self.porta, keepalive=20)
        c.loop_start()
        try:
            c.subscribe(topico, qos=0)
            fim = time.time() + max(0.5, min(float(segundos), 20))
            while time.time() < fim and len(mensagens) < max_msgs:
                time.sleep(0.1)
            return {"ok": True, "topico": topico, "mensagens": mensagens[:max_msgs]}
        finally:
            c.loop_stop()
            try:
                c.disconnect()
            except Exception:
                pass


# ----------------------------------------------------------------------- #
# HTTP de dispositivos
# ----------------------------------------------------------------------- #
class HTTPDispositivo:
    def __init__(self, escopo=None, timeout: float = 6.0):
        self.escopo = escopo
        self.timeout = timeout

    def requisicao(self, alvo: str, caminho: str = "/", metodo: str = "GET",
                   dados: dict | str | None = None) -> dict:
        alvo = str(alvo).strip()
        porta = 80
        if alvo.count(":") == 1:
            host, possivel_porta = alvo.split(":")
            if possivel_porta.isdigit():
                alvo, porta = host, int(possivel_porta)
        ip = self.escopo.exigir(alvo) if self.escopo else alvo
        if not caminho.startswith("/"):
            caminho = "/" + caminho
        base = f"http://{ip}" + ("" if porta == 80 else f":{porta}")
        url = base + caminho
        corpo = None
        headers = {"User-Agent": "YVAKOR/2.0"}
        if dados is not None:
            if isinstance(dados, dict):
                corpo = urllib.parse.urlencode(dados).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                corpo = str(dados).encode()
        req = urllib.request.Request(url, data=corpo, headers=headers,
                                     method=metodo.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                texto = r.read(200_000).decode("utf-8", "replace")
                return {"ok": True, "url": url, "status": r.status,
                        "corpo": texto[:8000],
                        "content_type": r.headers.get("Content-Type", "")}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "url": url, "status": exc.code,
                    "erro": exc.read(2000).decode("utf-8", "replace")[:500]}
        except Exception as exc:
            return {"ok": False, "url": url, "erro": str(exc)[:300]}

    def tasmota(self, alvo: str, comando: str) -> dict:
        cmd = urllib.parse.quote(str(comando))
        r = self.requisicao(alvo, f"/cm?cmnd={cmd}")
        if r.get("ok"):
            try:
                r["json"] = json.loads(r.get("corpo") or "{}")
            except Exception:
                pass
        return r

    def shelly(self, alvo: str, metodo: str = "Shelly.GetStatus",
               params: dict | None = None) -> dict:
        consulta = ""
        if params:
            consulta = "?" + urllib.parse.urlencode(params)
        r = self.requisicao(alvo, f"/rpc/{metodo}{consulta}")
        if r.get("ok"):
            try:
                r["json"] = json.loads(r.get("corpo") or "{}")
            except Exception:
                pass
        return r

    def esphome(self, alvo: str, entidade: str = "sensor") -> dict:
        return self.requisicao(alvo, f"/{entidade}")
