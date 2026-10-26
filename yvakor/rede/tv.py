"""
YVAKOR — TVs (Samsung Tizen e LG webOS)

Samsung: canal remoto em `ws://<ip>:8001/api/v2/channels/samsung.remote.control`.
  No primeiro uso a TV mostra "Permitir?" — o token fica salvo em data/rede.json
  e as próximas conexões são silenciosas.

LG webOS: `ws://<ip>:3000` (ou wss 3001). O primeiro pareamento também pede
  confirmação na TV e devolve um client-key que salvamos.

Ligar TV desligada só é possível por Wake-on-LAN (MAC do registro).
"""
from __future__ import annotations

import base64
import json
import ssl
import time

TECLAS_SAMSUNG = {
    "power": "KEY_POWER", "volume+": "KEY_VOLUP", "volume-": "KEY_VOLDOWN",
    "mudo": "KEY_MUTE", "cima": "KEY_UP", "baixo": "KEY_DOWN",
    "esquerda": "KEY_LEFT", "direita": "KEY_RIGHT", "ok": "KEY_ENTER",
    "voltar": "KEY_RETURN", "menu": "KEY_MENU", "home": "KEY_HOME",
    "play": "KEY_PLAY", "pause": "KEY_PAUSE", "canal+": "KEY_CHUP",
    "canal-": "KEY_CHDOWN", "netflix": "KEY_NETFLIX",
}

APPS_LG = {"netflix": "netflix", "youtube": "youtube.leanback.v4",
           "prime": "amazon", "globoplay": "globoplay", "spotify": "spotify-bee"}


class Televisores:
    def __init__(self, registro, escopo=None):
        self.registro = registro
        self.escopo = escopo

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    def _ip(self, alvo: str) -> str:
        dev = self.registro.obter(alvo)
        if dev and dev.get("ip"):
            ip = dev["ip"]
        else:
            ip = alvo
        if self.escopo:
            return self.escopo.exigir(ip)
        return ip

    def _mac(self, alvo: str) -> str:
        dev = self.registro.obter(alvo) or {}
        return dev.get("mac") or ""

    def _creds(self, ip: str) -> dict:
        return self.registro.credenciais(ip)

    # ------------------------------------------------------------------ #
    # Samsung
    # ------------------------------------------------------------------ #
    def _samsung_ws(self, ip: str):
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("instale websocket-client para controlar TVs") from exc
        token = self._creds(ip).get("samsung_token", "")
        nome = base64.b64encode(b"YVAKOR").decode()
        url = (f"ws://{ip}:8001/api/v2/channels/samsung.remote.control"
               f"?name={nome}" + (f"&token={token}" if token else ""))
        ws = websocket.create_connection(url, timeout=8)
        bruto = ws.recv()
        try:
            dados = json.loads(bruto)
        except Exception:
            dados = {}
        if dados.get("event") == "ms.channel.unauthorized":
            ws.close()
            raise RuntimeError(
                "a TV pediu autorização: aceite o popup na tela e tente de novo")
        novo = ((dados.get("data") or {}).get("token")
                if isinstance(dados.get("data"), dict) else None)
        if novo and novo != token:
            self.registro.salvar_credenciais(ip, samsung_token=novo)
        return ws

    def _samsung_chave(self, ip: str, tecla: str) -> dict:
        codigo = TECLAS_SAMSUNG.get(tecla.lower(), tecla if tecla.startswith("KEY_") else None)
        if not codigo:
            raise ValueError(f"tecla desconhecida: {tecla}")
        ws = self._samsung_ws(ip)
        try:
            ws.send(json.dumps({
                "method": "ms.remote.control",
                "params": {"Cmd": "Click", "DataOfCmd": codigo,
                           "Option": "false", "TypeOfRemote": "SendRemoteKey"},
            }))
            time.sleep(0.15)
        finally:
            ws.close()
        return {"ok": True, "tecla": codigo}

    # ------------------------------------------------------------------ #
    # LG webOS
    # ------------------------------------------------------------------ #
    def _lg_ws(self, ip: str):
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("instale websocket-client para controlar TVs") from exc
        token = self._creds(ip).get("lg_client_key", "")
        tentativas = [
            (f"ws://{ip}:3000", None),
            (f"wss://{ip}:3001", {"cert_reqs": ssl.CERT_NONE,
                                  "check_hostname": False}),
        ]
        ultimo = None
        for url, sslopt in tentativas:
            try:
                ws = websocket.create_connection(url, timeout=8, sslopt=sslopt)
            except Exception as exc:
                ultimo = exc
                continue
            ws.send(json.dumps({
                "id": "reg0", "type": "register",
                "payload": {"forcePairing": False, "pairingType": "PROMPT",
                            "client-key": token,
                            "manifest": {"appVersion": "1.0", "manifestVersion": 1,
                                         "permissions": ["CONTROL_POWER", "CONTROL_AUDIO",
                                                         "CONTROL_INPUT_MEDIA_PLAYBACK",
                                                         "READ_INSTALLED_APPS",
                                                         "CONTROL_INPUT_TV"]}},
            }))
            resposta = {}
            fim = time.time() + 6
            while time.time() < fim:
                try:
                    bruto = ws.recv()
                except Exception:
                    break
                try:
                    resposta = json.loads(bruto)
                except Exception:
                    continue
                if resposta.get("type") in ("registered", "error"):
                    break
            if resposta.get("type") == "registered":
                chave = (resposta.get("payload") or {}).get("client-key")
                if chave and chave != token:
                    self.registro.salvar_credenciais(ip, lg_client_key=chave)
                return ws
            ws.close()
            ultimo = RuntimeError(
                f"LG recusou o pareamento ({resposta.get('type')}) — "
                "aceite o aviso na TV e tente de novo")
        raise ultimo or RuntimeError("não consegui falar com a TV LG")

    def _lg_pedido(self, ip: str, uri: str, payload: dict | None = None) -> dict:
        ws = self._lg_ws(ip)
        try:
            corpo = {"id": "cmd0", "type": "request", "uri": uri}
            if payload is not None:
                corpo["payload"] = payload
            ws.send(json.dumps(corpo))
            bruto = ws.recv()
            try:
                return json.loads(bruto)
            except Exception:
                return {"bruto": bruto[:200]}
        finally:
            ws.close()

    # ------------------------------------------------------------------ #
    # API única
    # ------------------------------------------------------------------ #
    def ligar(self, alvo: str) -> dict:
        mac = self._mac(alvo)
        if not mac:
            raise RuntimeError(
                "não tenho o MAC desta TV; rode rede_escanear para registrar")
        from yvakor.rede.iot import wol
        r = wol(mac)
        r["mac"] = mac
        r["obs"] = "TV liga em ~10s (requer WoL habilitada na TV)"
        return r

    def desligar(self, alvo: str) -> dict:
        ip = self._ip(alvo)
        dev = self.registro.obter(alvo) or {}
        servicos = " ".join(dev.get("servicos") or []).lower()
        try:
            return self._samsung_chave(ip, "power")
        except Exception as exc_s:
            try:
                self._lg_pedido(ip, "ssap://system/turnOff")
                return {"ok": True, "acao": "desligar (LG)"}
            except Exception as exc_l:
                raise RuntimeError(
                    f"não consegui desligar. Samsung: {str(exc_s)[:90]} | "
                    f"LG: {str(exc_l)[:90]}")

    def tecla(self, alvo: str, tecla: str) -> dict:
        ip = self._ip(alvo)
        try:
            return self._samsung_chave(ip, tecla)
        except Exception as exc_s:
            mapa = {"volume+": "ssap://audio/volumeUp",
                    "volume-": "ssap://audio/volumeDown",
                    "mudo": "ssap://audio/setMute",
                    "ok": "ssap://com.webos.service.networkinput/getPointerInputSocket"}
            uri = mapa.get(tecla.lower())
            if not uri:
                raise RuntimeError(
                    f"tecla '{tecla}' não suportada nesta TV. Samsung: {str(exc_s)[:80]}")
            self._lg_pedido(ip, uri)
            return {"ok": True, "tecla": tecla, "via": "lg"}

    def volume(self, alvo: str, nivel: int | None = None) -> dict:
        ip = self._ip(alvo)
        try:
            if nivel is None:
                return {"ok": True, **self._lg_pedido(ip, "ssap://audio/getVolume")}
            atual = self._lg_pedido(ip, "ssap://audio/getVolume")
            valor = int(((atual.get("payload") or {}).get("volumeStatus") or {})
                        .get("volume", 0))
            alvo_n = max(0, min(100, int(nivel)))
            passo = "volumeUp" if alvo_n > valor else "volumeDown"
            for _ in range(abs(alvo_n - valor)):
                self._lg_pedido(ip, f"ssap://audio/{passo}")
            return {"ok": True, "volume": alvo_n}
        except Exception:
            tecla = "volume+" if (nivel or 0) >= 50 else "volume-"
            return self._samsung_chave(ip, tecla)

    def app(self, alvo: str, nome_app: str) -> dict:
        ip = self._ip(alvo)
        app_id = APPS_LG.get(nome_app.lower(), nome_app)
        try:
            self._lg_pedido(ip, "ssap://system.launcher/launch", {"id": app_id})
            return {"ok": True, "app": app_id, "via": "lg"}
        except Exception as exc:
            raise RuntimeError(f"não consegui abrir '{nome_app}': {str(exc)[:120]}")

    def status(self, alvo: str) -> dict:
        ip = self._ip(alvo)
        info = {"ip": ip, "mac": self._mac(alvo)}
        try:
            ws = self._samsung_ws(ip)
            ws.close()
            info.update({"ok": True, "marca": "samsung"})
            return info
        except Exception as exc_s:
            info["samsung"] = str(exc_s)[:90]
        try:
            r = self._lg_pedido(ip, "ssap://audio/getVolume")
            info.update({"ok": True, "marca": "lg", "volume": r})
            return info
        except Exception as exc_l:
            info["lg"] = str(exc_l)[:90]
        info["ok"] = False
        return info
