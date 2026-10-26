"""YVAKOR Doctor — diagnóstico de instalação e prontidão."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _pkg(nome: str) -> bool:
    return importlib.util.find_spec(nome) is not None


def _ping() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:7777/api/ping",
                                    timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def coletar() -> list[dict]:
    versao = {}
    try:
        versao = json.loads((ROOT / "config" / "version.json").read_text(
            encoding="utf-8"))
    except Exception:
        pass
    chrome = ""
    for p in (Path(os.environ.get("ProgramFiles", "C:/Program Files"))
              / "Google/Chrome/Application/chrome.exe",
              Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
              / "Google/Chrome/Application/chrome.exe"):
        if p.is_file():
            chrome = str(p)
            break
    checks = [
        ("python", sys.version.split()[0], sys.version_info >= (3, 10), ""),
        ("versao", versao.get("version", "?"), bool(versao), str(versao)),
        ("yaml", "pyyaml", _pkg("yaml"), "pip install pyyaml"),
        ("playwright", "playwright", _pkg("playwright"),
         "pip install playwright"),
        ("pdf", "pymupdf", _pkg("pymupdf"), "pip install pymupdf"),
        ("pypdf", "pypdf", _pkg("pypdf"), "pip install pypdf"),
        ("xlsx", "openpyxl", _pkg("openpyxl"), "pip install openpyxl"),
        ("docx", "python-docx", _pkg("docx"), "pip install python-docx"),
        ("vlc", "python-vlc", _pkg("vlc"), "pip install python-vlc"),
        ("ffmpeg", shutil.which("ffmpeg") or "", bool(shutil.which("ffmpeg")),
         "instale ffmpeg e coloque no PATH"),
        ("chrome", chrome, bool(chrome), "instale o Google Chrome"),
        ("extensao", "chrome-extension",
         (ROOT / "chrome-extension" / "manifest.json").is_file(), ""),
        ("build_ext", "build.json",
         (ROOT / "chrome-extension" / "build.json").is_file(), ""),
        ("vault", "data/vault", (ROOT / "data" / "vault").is_dir(), ""),
        ("banco", "data/yvakor_memory.db",
         (ROOT / "data" / "yvakor_memory.db").is_file(), ""),
        ("nucleo", "127.0.0.1:7777", _ping(), "inicie o YVAKOR"),
    ]
    return [{"nome": n, "detalhe": d, "ok": bool(ok), "ajuda": a}
            for n, d, ok, a in checks]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    checks = coletar()
    falhas = [c for c in checks if not c["ok"]]
    if args.json:
        print(json.dumps({"checks": checks, "falhas": len(falhas)},
                         ensure_ascii=False, indent=2))
    else:
        print("\n  YVAKOR · diagnóstico\n  " + "=" * 40)
        for c in checks:
            marca = "OK " if c["ok"] else "!! "
            print(f"  [{marca}] {c['nome']:<12} {c['detalhe']}")
            if not c["ok"] and c["ajuda"]:
                print(f"          → {c['ajuda']}")
        print("  " + "=" * 40)
        print(f"  {len(checks) - len(falhas)}/{len(checks)} verificações OK")
    return 0 if not any(not c["ok"] for c in checks
                        if c["nome"] in ("python", "yaml", "versao")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
