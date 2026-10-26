"""YVAKOR — Chrome real via CDP, sem flags de automação.

Estratégia: abrir o Google Chrome instalado com um perfil dedicado e
`--remote-debugging-port`, e anexar o Playwright via CDP. O Chrome é o
navegador real (não o Chromium de automação), o que reduz bloqueios de login
e mantém cookies/sessões entre execuções.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from yvakor.config import ROOT

PERFIL_PADRAO = ROOT / "data" / "browser_profiles" / "chrome-cdp"


def _candidatos() -> list[Path]:
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        Path(os.environ.get("YVAKOR_CHROME", "")) if os.environ.get("YVAKOR_CHROME") else Path(),
        Path(pf) / "Google/Chrome/Application/chrome.exe",
        Path(pf86) / "Google/Chrome/Application/chrome.exe",
        Path(local) / "Google/Chrome/Application/chrome.exe",
    ]


def achar_chrome() -> str:
    for p in _candidatos():
        try:
            if p and p.is_file():
                return str(p)
        except OSError:
            pass
    return ""


def info_cdp(url: str = "http://127.0.0.1:9222", timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version",
                                    timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def garantir(url: str = "http://127.0.0.1:9222",
             perfil: str | Path | None = None,
             espera_s: float = 25) -> dict:
    """Garante um Chrome real com CDP na porta indicada; abre se preciso."""
    atual = info_cdp(url)
    if atual:
        return {"ok": True, "ja_aberto": True, "url": url,
                "browser": atual.get("Browser"), "perfil": str(perfil or "")}
    chrome = achar_chrome()
    if not chrome:
        return {"ok": False, "erro": "Google Chrome não encontrado"}
    try:
        porta = url.rsplit(":", 1)[-1].split("/")[0]
    except Exception:
        return {"ok": False, "erro": f"URL CDP inválida: {url}"}
    pasta = Path(perfil or PERFIL_PADRAO).resolve()
    pasta.mkdir(parents=True, exist_ok=True)
    cmd = [
        chrome,
        f"--remote-debugging-port={porta}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={pasta}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
        "--start-maximized",
        "about:blank",
    ]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except Exception as exc:
        return {"ok": False, "erro": f"não consegui abrir o Chrome: {exc}"}
    fim = time.time() + espera_s
    while time.time() < fim:
        info = info_cdp(url, timeout=1.0)
        if info:
            return {"ok": True, "ja_aberto": False, "url": url,
                    "browser": info.get("Browser"), "perfil": str(pasta)}
        time.sleep(0.5)
    return {"ok": False, "erro": "o Chrome abriu, mas o CDP não respondeu",
            "perfil": str(pasta), "porta": porta}


def garantir_para_url(url: str, perfil: str | Path | None = None) -> dict:
    if not url:
        return {"ok": False, "erro": "cdp_url vazio"}
    return garantir(url, perfil=perfil)
