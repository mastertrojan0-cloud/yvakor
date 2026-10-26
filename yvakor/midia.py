"""YVAKOR — reprodução de mídia com VLC (local, URL, RTSP)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

VLC_CAMINHOS = (
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
)


def encontrar_vlc() -> str:
    for p in VLC_CAMINHOS:
        if Path(p).is_file():
            return p
    for nome in ("vlc.exe", "vlc"):
        from shutil import which
        achado = which(nome)
        if achado:
            return achado
    return ""


class Player:
    def __init__(self):
        self.vlc = encontrar_vlc()
        self.proc: subprocess.Popen | None = None
        self.alvo = ""

    def status(self) -> dict:
        vivo = bool(self.proc and self.proc.poll() is None)
        return {"ok": True, "vlc": self.vlc, "tocando": vivo,
                "alvo": self.alvo if vivo else ""}

    def tocar(self, alvo: str, titulo: str = "") -> dict:
        if not self.vlc:
            return {"ok": False, "erro": "VLC não encontrado"}
        alvo = (alvo or "").strip().strip('"')
        if not alvo:
            return {"ok": False, "erro": "nenhum arquivo/URL informado"}
        e_url = alvo.lower().startswith(("http://", "https://", "rtsp://",
                                         "rtmp://", "mms://"))
        if not e_url and not Path(alvo).expanduser().is_file():
            return {"ok": False, "erro": f"arquivo não encontrado: {alvo}"}
        if not e_url:
            alvo = str(Path(alvo).expanduser().resolve())
        self.parar()
        cmd = [self.vlc, "--no-one-instance", "--no-video-title-show",
               "--play-and-exit"]
        if alvo.lower().startswith("rtsp://"):
            cmd.append("--rtsp-tcp")
        cmd.append(alvo)
        try:
            self.proc = subprocess.Popen(cmd, close_fds=True)
            self.alvo = alvo
            return {"ok": True, "alvo": alvo, "titulo": titulo or Path(alvo).name,
                    "vlc": self.vlc}
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}

    def parar(self) -> dict:
        if self.proc and self.proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T",
                                "/F"], capture_output=True, timeout=10)
            except Exception:
                try:
                    self.proc.terminate()
                except Exception:
                    pass
        self.proc = None
        self.alvo = ""
        return {"ok": True, "parado": True}


def registrar_ferramentas(tools, player: Player):
    def tocar(alvo: str, titulo: str = "") -> dict:
        return player.tocar(alvo, titulo)

    def parar() -> dict:
        return player.parar()

    def status() -> dict:
        return player.status()

    tools.register("midia_tocar", tocar,
                   "Toca um arquivo, URL ou stream RTSP no VLC.",
                   {"alvo": {"type": "string"},
                    "titulo": {"type": "string"}})
    tools.register("midia_parar", parar, "Para o VLC.", {})
    tools.register("midia_status", status, "Estado do player VLC.", {})
