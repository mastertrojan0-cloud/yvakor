"""
YVAKOR — Câmeras (foto, vídeo, PTZ)

Duas rotas, na ordem:
  1. ONVIF  — snapshot oficial da câmera (JPEG), metadados e PTZ.
  2. RTSP   — se o ONVIF não responder/autenticar, tenta os caminhos RTSP
              mais comuns (Hikvision/Intelbras, Dahua, genérico) com ffmpeg.

Credenciais vêm do registro (data/rede.json) — o agente nunca tenta adivinhar
senha. Sem credencial, tenta apenas o que a câmera permitir anonimamente e
devolve um erro claro pedindo usuário/senha ao dono.
"""
from __future__ import annotations

import shutil
import subprocess
from yvakor import proc as _ywproc
import threading
import time
from pathlib import Path

from yvakor.rede import onvif
from yvakor.rede.rtsp import CameraRTSP
from yvakor.rede.escopo import EscopoRede
from yvakor.rede.registro import RegistroRede
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent


class Cameras:
    def __init__(self, settings: dict, escopo: EscopoRede,
                 registro: RegistroRede):
        cfg = (settings or {}).get("rede", {}) or {}
        self.cfg = cfg
        self.escopo = escopo
        self.registro = registro
        self.dir = ROOT / "data" / "rede_shots"
        self.ffmpeg = cfg.get("ffmpeg") or "ffmpeg"
        self.rtsp_transport = cfg.get("rtsp_transport") or "udp"
        self._vivos: dict[str, CameraRTSP] = {}

    # ------------------------------------------------------------------ #
    # Resolução do alvo
    # ------------------------------------------------------------------ #
    def _dev(self, alvo: str) -> dict:
        dev = self.registro.obter(alvo)
        if dev:
            return dev
        ip = self.escopo.exigir(alvo)
        return {"ip": ip, "mac": "", "nome": ip, "tipo": "camera",
                "chave": ip, "servicos": [], "portas": []}

    def _creds(self, dev: dict) -> tuple[str, str]:
        c = self.registro.credenciais(dev.get("ip") or dev.get("chave", ""))
        return str(c.get("user") or c.get("usuario") or ""), str(
            c.get("password") or c.get("senha") or "")

    def _camera(self, dev: dict) -> onvif.OnvifCamera:
        usuario, senha = self._creds(dev)
        creds = self.registro.credenciais(dev.get("ip") or dev.get("chave", ""))
        porta = int(creds.get("onvif_port") or 80)
        return onvif.OnvifCamera(dev["ip"], usuario, senha, porta=porta)

    @staticmethod
    def _ffmpeg_ok(caminho: str) -> bool:
        return bool(shutil.which(caminho) or Path(caminho).exists())

    def _urls_rtsp(self, dev: dict) -> list[str]:
        ip = dev["ip"]
        usuario, senha = self._creds(dev)
        from urllib.parse import quote
        auth = f"{quote(usuario, safe='')}:{quote(senha, safe='')}@" if usuario else ""
        base = f"rtsp://{auth}{ip}:554"
        portas = set(dev.get("portas") or [])
        sufixos = ["/onvif1", "/onvif2",                  # Yoosee/GWell
                   "/Streaming/Channels/101",             # Hikvision/Intelbras
                   "/cam/realmonitor?channel=1&subtype=0",  # Dahua
                   "/stream1"]
        if 8554 in portas:
            sufixos.insert(0, "/")
        return [base + s for s in sufixos]

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #
    def listar(self) -> list[dict]:
        devs = [d for d in self.registro.listar() if d.get("tipo") == "camera"]
        for d in devs:
            d["credenciais"] = bool(self._creds(d)[0])
        return devs

    def descobrir(self, segundos: float = 3.0) -> list[dict]:
        """Câmeras ONVIF que respondem WS-Discovery + registro."""
        achadas = []
        for item in onvif.descobrir(segundos):
            ip = item["ip"]
            if not self.escopo.permitido(ip):
                continue
            dev = self.registro.upsert({
                "ip": ip, "tipo": "camera",
                "servicos": ["onvif"] + item.get("tipos", []),
                "portas": [80],
            })
            dev["xaddr"] = item.get("xaddr")
            achadas.append(dev)
        return achadas

    def info(self, alvo: str) -> dict:
        dev = self._dev(alvo)
        cam = self._camera(dev)
        dados = cam.info()
        dados["perfis"] = cam.perfis()
        try:
            dados["snapshot_url"] = cam.snapshot_url()
        except onvif.OnvifErro:
            dados["snapshot_url"] = ""
        dados["ip"] = dev["ip"]
        dados["credenciais"] = bool(self._creds(dev)[0])
        # Guarda fabricante/modelo no registro para nomear o aparelho
        if dados.get("fabricante") or dados.get("modelo"):
            self.registro.upsert({
                "ip": dev["ip"], "tipo": "camera",
                "fabricante": dados.get("fabricante", ""),
                "modelo": dados.get("modelo", ""),
            })
        return dados

    # ------------------------------------------------------------------ #
    # Janela ao vivo (ffplay)
    # ------------------------------------------------------------------ #
    def _vivo(self, dev: dict) -> CameraRTSP:
        ip = dev["ip"]
        atual = self._vivos.get(ip)
        if atual is not None:
            if atual.status().get("ativo") and atual.quadro():
                return atual
            atual.parar()
            self._vivos.pop(ip, None)
        usuario, senha = self._creds(dev)
        erros = []
        for caminho in ("/onvif1", "/onvif2",
                        "/Streaming/Channels/101",
                        "/cam/realmonitor?channel=1&subtype=0", "/stream1"):
            c = CameraRTSP(ip, caminho, usuario, senha, 554)
            try:
                c.iniciar()
                limite = time.time() + 7
                while time.time() < limite and c.quadro() is None:
                    if not c.status().get("ativo"):
                        break
                    time.sleep(0.2)
                if c.quadro():
                    self._vivos[ip] = c
                    return c
                erros.append(f"{caminho}: sem imagem {c.status()}")
                c.parar()
            except Exception as exc:
                erros.append(f"{caminho}: {exc}")
                try:
                    c.parar()
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
        raise RuntimeError(" | ".join(erros)[:500])

    def quadro(self, ip: str) -> bytes | None:
        c = self._vivos.get(ip)
        return c.quadro() if c else None

    def vivo_ativo(self, ip: str) -> bool:
        c = self._vivos.get(ip)
        return bool(c and c.status().get("ativo"))

    def parar_vivo(self, ip: str) -> dict:
        c = self._vivos.pop(ip, None)
        if c:
            c.parar()
        return {"ok": True, "parado": ip}

    def ao_vivo(self, alvo: str, segundos: int = 0) -> dict:
        dev = self._dev(alvo)
        try:
            c = self._vivo(dev)
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}
        if int(segundos) > 0:
            threading.Timer(int(segundos),
                            lambda: self.parar_vivo(dev["ip"])).start()
        return {"ok": True, "ip": dev["ip"],
                "url": f"http://127.0.0.1:7777/camera/{dev['ip']}",
                "quadros": c.quadros,
                "diagnostico": c.status().get("diagnostico", [])}

    def _ao_vivo_antigo(self, alvo: str, segundos: int = 0) -> dict:
        dev = self._dev(alvo)
        url = ""
        try:
            url = self._camera(dev).stream_url()
        except Exception:
            urls = self._urls_rtsp(dev)
            url = urls[0] if urls else ""
        if not url:
            return {"ok": False, "erro": "câmera sem URL RTSP"}
        ffplay = shutil.which("ffplay")
        if not ffplay:
            tentativa = Path(self.ffmpeg).with_name("ffplay.exe")
            ffplay = str(tentativa) if tentativa.exists() else ""
        if not ffplay:
            from yvakor.midia import encontrar_vlc
            vlc = encontrar_vlc()
            if vlc:
                import re as _re
                titulo = f"YVAKOR · {dev.get('nome') or dev['ip']}"
                cmd = [vlc, "--no-one-instance", "--no-video-title-show",
                       "--rtsp-tcp", "--network-caching=300", url]
                try:
                    proc = _ywproc.popen(cmd, close_fds=True)
                except Exception as exc:
                    return {"ok": False, "erro": str(exc)}
                if int(segundos) > 0:
                    threading.Timer(int(segundos),
                                    lambda: proc.terminate()).start()
                return {"ok": True, "pid": proc.pid, "janela": True,
                        "player": "vlc",
                        "url_mascarada": _re.sub(r"//[^@/]+@", "//***@", url),
                        "obs": "feche a janela do VLC ou peça para fechar"}
            return {"ok": False, "erro": "ffplay/VLC não encontrado"}
        import re as _re
        titulo = f"YVAKOR · {dev.get('nome') or dev['ip']}"
        cmd = [ffplay, "-rtsp_transport", self.rtsp_transport, "-fflags", "nobuffer",
               "-flags", "low_delay", "-window_title", titulo,
               "-loglevel", "warning", "-i", url]
        try:
            proc = _ywproc.popen(cmd, close_fds=True)
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}
        if int(segundos) > 0:
            threading.Timer(int(segundos), lambda: proc.terminate()).start()
        seguro = _re.sub(r"//[^@/]+@", "//***@", url)
        return {"ok": True, "pid": proc.pid, "janela": True,
                "url_mascarada": seguro,
                "obs": "feche a janela do player ou peça para fechar"}

    # ------------------------------------------------------------------ #
    # Foto
    # ------------------------------------------------------------------ #
    def url_ao_vivo(self, alvo: str) -> dict:
        """URL RTSP real (com credenciais) para player embutido."""
        try:
            dev = self._dev(alvo)
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}
        url = ""
        transporte = self.rtsp_transport
        try:
            creds = self.registro.credenciais(dev.get("ip") or dev.get("chave", ""))
            url = str(creds.get("rtsp_url") or "")
            transporte = str(creds.get("rtsp_transport") or transporte)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        if not url:
            try:
                url = self._camera(dev).stream_url()
            except Exception:
                urls = self._urls_rtsp(dev)
                url = urls[0] if urls else ""
        if not url:
            return {"ok": False, "erro": "câmera sem URL RTSP"}
        import re as _re
        return {"ok": True, "url": url, "ip": dev.get("ip"),
                "nome": dev.get("nome") or dev.get("ip"),
                "transporte": transporte,
                "mascarada": _re.sub(r"//[^@/]+@", "//***@", url)}

    def snapshot(self, alvo: str, perfil: str | None = None) -> dict:
        dev = self._dev(alvo)
        self.dir.mkdir(parents=True, exist_ok=True)
        nome = f"camera_{dev['ip'].replace('.', '-')}_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
        destino = self.dir / nome
        tentativas: list[str] = []

        # 1) ONVIF
        try:
            cam = self._camera(dev)
            url = cam.snapshot_url(perfil)
            usuario, senha = self._creds(dev)
            dados = onvif.baixar_snapshot(url, usuario, senha)
            destino.write_bytes(dados)
            return {"ok": True, "via": "onvif", "arquivo": str(destino.resolve()),
                    "bytes": destino.stat().st_size, "ip": dev["ip"],
                    "url_snapshot": url}
        except Exception as exc:
            tentativas.append(f"onvif: {str(exc)[:160]}")

        # 2) RTSP via ffmpeg
        if self._ffmpeg_ok(self.ffmpeg):
            for url in self._urls_rtsp(dev):
                try:
                    cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error",
                           "-rtsp_transport", self.rtsp_transport,
                           "-i", url, "-frames:v", "1", "-q:v", "2",
                           "-y", str(destino)]
                    p = _ywproc.run(cmd, capture_output=True, text=True,
                                       timeout=25, encoding="utf-8",
                                       errors="replace")
                    if destino.exists() and destino.stat().st_size > 1000:
                        return {"ok": True, "via": "rtsp",
                                "arquivo": str(destino.resolve()),
                                "bytes": destino.stat().st_size, "ip": dev["ip"]}
                    tentativas.append(f"rtsp {url.split('@')[-1]}: "
                                      f"{(p.stderr or '').strip()[:120]}")
                except subprocess.TimeoutExpired:
                    tentativas.append(f"rtsp {url.split('@')[-1]}: timeout")
                except Exception as exc:
                    tentativas.append(f"rtsp: {str(exc)[:100]}")
        else:
            tentativas.append("ffmpeg não encontrado no PATH")

        dica = ("salve usuário/senha da câmera com rede_camera_credenciais"
                if not self._creds(dev)[0] else
                "confira usuário/senha e o perfil de vídeo")
        return {"ok": False, "ip": dev["ip"], "erro": "não consegui obter imagem",
                "tentativas": tentativas, "dica": dica}

    # ------------------------------------------------------------------ #
    # Vídeo
    # ------------------------------------------------------------------ #
    def gravar(self, alvo: str, segundos: int = 10,
               perfil: str | None = None) -> dict:
        dev = self._dev(alvo)
        if not self._ffmpeg_ok(self.ffmpeg):
            return {"ok": False, "erro": "ffmpeg não encontrado no PATH"}
        self.dir.mkdir(parents=True, exist_ok=True)
        destino = (self.dir /
                   f"camera_{dev['ip'].replace('.', '-')}_"
                   f"{time.strftime('%Y%m%d_%H%M%S')}.mp4")

        url = ""
        try:
            url = self._camera(dev).stream_url(perfil)
        except Exception:
            urls = self._urls_rtsp(dev)
            url = urls[0] if urls else ""
        if not url:
            return {"ok": False, "erro": "câmera sem URL RTSP"}

        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error",
               "-rtsp_transport", self.rtsp_transport,
               "-i", url, "-t", str(max(1, min(int(segundos), 300))),
               "-c", "copy", "-y", str(destino)]
        try:
            p = _ywproc.run(cmd, capture_output=True, text=True, timeout=segundos + 30,
                               encoding="utf-8", errors="replace")
            ok = destino.exists() and destino.stat().st_size > 1000
            if not ok:
                return {"ok": False, "erro": (p.stderr or "falha ao gravar")[:300]}
            return {"ok": True, "arquivo": str(destino.resolve()),
                    "bytes": destino.stat().st_size, "segundos": segundos}
        except subprocess.TimeoutExpired:
            return {"ok": False, "erro": f"timeout ao gravar {segundos}s"}

    # ------------------------------------------------------------------ #
    # PTZ
    # ------------------------------------------------------------------ #
    def ptz(self, alvo: str, x: float = 0.0, y: float = 0.0,
            zoom: float = 0.0, segundos: float = 0.4) -> dict:
        dev = self._dev(alvo)
        cam = self._camera(dev)
        r = cam.ptz(x, y, zoom, segundos)
        r["ip"] = dev["ip"]
        return r

    def parar(self, alvo: str) -> dict:
        dev = self._dev(alvo)
        return self._camera(dev).parar()

    def url_stream(self, alvo: str, perfil: str | None = None) -> dict:
        dev = self._dev(alvo)
        url = self._camera(dev).stream_url(perfil)
        # Não devolve senha para o modelo/LLM
        seguro = url
        if "@" in url:
            seguro = url.split("://")[0] + "://***@" + url.split("@", 1)[1]
        return {"ok": True, "ip": dev["ip"], "url_mascarada": seguro}
