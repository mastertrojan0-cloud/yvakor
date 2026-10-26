"""
YVAKOR — Celulares Android via ADB

O que dá para fazer com o aparelho autorizado:
  • listar dispositivos (USB ou Wi-Fi via `adb connect`)
  • print da tela, toque, deslize, digitar texto, teclas
  • abrir app, instalar APK, shell (com confirmação)

Pré-requisitos do lado do dono: Depuração USB ligada (ou "Depuração sem fio"
no Android 11+) e o popup "Permitir depuração" aceito. O YVAKOR não contorna
isso — faz parte do contrato de segurança do Android.

Se o `adb` não estiver instalado, `preparar()` baixa o platform-tools oficial
do Google para data/platform-tools.
"""
from __future__ import annotations

import shutil
import subprocess
from yvakor import proc as _ywproc
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
URL_PLATFORM_TOOLS = ("https://dl.google.com/android/repository/"
                      "platform-tools-latest-windows.zip")


class Telefones:
    def __init__(self, settings: dict, escopo=None):
        cfg = (settings or {}).get("rede", {}) or {}
        self.cfg = cfg
        self.escopo = escopo
        self.dir = ROOT / "data" / "platform-tools"
        self._adb_cfg = cfg.get("adb") or "adb"

    # ------------------------------------------------------------------ #
    # ADB: localizar/preparar
    # ------------------------------------------------------------------ #
    def adb(self) -> str | None:
        caminho = shutil.which(self._adb_cfg)
        if caminho:
            return caminho
        local = self.dir / "platform-tools" / "adb.exe"
        if local.exists():
            return str(local)
        return None

    def preparar(self) -> dict:
        """Baixa o platform-tools do Google se o adb não existir."""
        atual = self.adb()
        if atual:
            return {"ok": True, "adb": atual, "ja_instalado": True}
        self.dir.mkdir(parents=True, exist_ok=True)
        zip_path = self.dir / "platform-tools.zip"
        try:
            req = urllib.request.Request(URL_PLATFORM_TOOLS,
                                         headers={"User-Agent": "YVAKOR/2.0"})
            with urllib.request.urlopen(req, timeout=180) as r, \
                    zip_path.open("wb") as f:
                shutil.copyfileobj(r, f)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(self.dir)
            zip_path.unlink(missing_ok=True)
            exe = self.dir / "platform-tools" / "adb.exe"
            if not exe.exists():
                return {"ok": False, "erro": "zip baixado sem adb.exe"}
            return {"ok": True, "adb": str(exe), "ja_instalado": False}
        except Exception as exc:
            return {"ok": False, "erro": f"falha ao baixar platform-tools: {exc}"}

    # ------------------------------------------------------------------ #
    # Execução
    # ------------------------------------------------------------------ #
    def _run(self, args: list[str], timeout: int = 25,
             binario: bool = False) -> dict:
        adb = self.adb()
        if not adb:
            return {"ok": False, "erro": "adb não encontrado — rode "
                                         "rede_telefone_preparar primeiro"}
        comando = [adb] + args
        try:
            p = _ywproc.run(
                comando, capture_output=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            saida = p.stdout if binario else p.stdout.decode("utf-8", "replace")
            erro = p.stderr.decode("utf-8", "replace")
            return {"ok": p.returncode == 0, "stdout": saida,
                    "stderr": erro[:600], "returncode": p.returncode}
        except subprocess.TimeoutExpired:
            return {"ok": False, "erro": f"adb timeout após {timeout}s"}
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}

    # ------------------------------------------------------------------ #
    # Dispositivos
    # ------------------------------------------------------------------ #
    def dispositivos(self) -> list[dict]:
        r = self._run(["devices", "-l"], timeout=15)
        if not r.get("ok"):
            return []
        saida = []
        for linha in (r.get("stdout") or "").splitlines()[1:]:
            if not linha.strip() or "\t" not in linha:
                continue
            serial, resto = linha.split("\t", 1)
            if "unauthorized" in resto:
                estado = "não autorizado (aceite o popup no celular)"
            elif "offline" in resto:
                estado = "offline"
            else:
                estado = "pronto"
            modelo = ""
            for parte in resto.split():
                if parte.startswith("model:"):
                    modelo = parte.split(":", 1)[1]
            saida.append({"serial": serial.strip(), "estado": estado,
                          "modelo": modelo.replace("_", " ")})
        return saida

    def conectar(self, ip: str, porta: int = 5555) -> dict:
        alvo = ip if self.escopo is None else self.escopo.exigir(ip)
        r = self._run(["connect", f"{alvo}:{porta}"], timeout=20)
        return {"ok": bool(r.get("ok")) and "connected" in (r.get("stdout") or ""),
                "saida": (r.get("stdout") or r.get("erro") or "").strip()[:200],
                "alvo": f"{alvo}:{porta}"}

    def _serial(self, serial: str = "") -> str:
        devs = [d["serial"] for d in self.dispositivos() if d["estado"] == "pronto"]
        if not devs:
            raise RuntimeError("nenhum celular pronto via ADB (autorize no aparelho)")
        if serial and serial in devs:
            return serial
        return devs[0]

    # ------------------------------------------------------------------ #
    # Controle
    # ------------------------------------------------------------------ #
    def tela(self, serial: str = "") -> dict:
        s = self._serial(serial)
        r = self._run(["-s", s, "exec-out", "screencap", "-p"], timeout=20,
                      binario=True)
        dados = r.get("stdout") or b""
        if not isinstance(dados, bytes) or not dados.startswith(b"\x89PNG"):
            return {"ok": False, "erro": "não recebi PNG do celular"}
        destino = (ROOT / "data" / "rede_shots" /
                   f"celular_{s.replace(':', '-')}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
        return {"ok": True, "arquivo": str(destino.resolve()),
                "bytes": len(dados), "serial": s}

    def tocar(self, x: int, y: int, serial: str = "") -> dict:
        s = self._serial(serial)
        return self._run(["-s", s, "shell", "input", "tap", str(int(x)),
                          str(int(y))], timeout=15)

    def deslizar(self, x1: int, y1: int, x2: int, y2: int,
                 ms: int = 300, serial: str = "") -> dict:
        s = self._serial(serial)
        return self._run(["-s", s, "shell", "input", "swipe", str(int(x1)),
                          str(int(y1)), str(int(x2)), str(int(y2)),
                          str(int(ms))], timeout=15)

    def texto(self, txt: str, serial: str = "") -> dict:
        s = self._serial(serial)
        seguro = str(txt).replace(" ", "%s")
        return self._run(["-s", s, "shell", "input", "text", seguro], timeout=15)

    def tecla(self, codigo: str = "KEYCODE_ENTER", serial: str = "") -> dict:
        s = self._serial(serial)
        return self._run(["-s", s, "shell", "input", "keyevent", codigo],
                         timeout=15)

    def abrir_app(self, pacote: str, serial: str = "") -> dict:
        s = self._serial(serial)
        return self._run(["-s", s, "shell", "monkey", "-p", pacote,
                          "-c", "android.intent.category.LAUNCHER", "1"],
                         timeout=25)

    def instalar(self, apk: str, serial: str = "") -> dict:
        s = self._serial(serial)
        caminho = Path(apk).expanduser()
        if not caminho.is_file():
            return {"ok": False, "erro": f"APK não encontrado: {apk}"}
        return self._run(["-s", s, "install", "-r", str(caminho)], timeout=180)

    def shell(self, comando: str, serial: str = "") -> dict:
        s = self._serial(serial)
        return self._run(["-s", s, "shell", comando], timeout=30)
