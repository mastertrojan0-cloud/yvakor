"""
YVAKOR — Preparação do navegador (CLI).

Uso:
  python -m yvakor.browser.setup          # verifica e, se preciso, instala
  python -m yvakor.browser.setup --check  # só verifica (não baixa nada)

O caminho preferido usa o Edge/Chrome já instalado no Windows (zero download).
Se nenhum existir, baixa o Chromium do Playwright (~130 MB, uma vez só).
"""
from __future__ import annotations

import sys
import subprocess
from yvakor import proc as _ywproc


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    only_check = "--check" in argv

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [navegador] Playwright ausente. Rode: pip install playwright")
        return 1

    for channel in ("msedge", "chrome"):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel=channel, headless=True)
                versao = browser.version
                browser.close()
            print(f"  [navegador] OK - {channel} {versao} (navegador do sistema)")
            return 0
        except Exception:
            continue

    # Nenhum navegador do sistema: Chromium embutido já baixado?
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        print("  [navegador] OK - Chromium do Playwright")
        return 0
    except Exception:
        pass

    if only_check:
        print("  [navegador] nenhum navegador disponível "
              "(instale o Chrome/Edge ou rode sem --check)")
        return 1

    print("  [navegador] baixando Chromium do Playwright (~130 MB, uma vez)…")
    try:
        _ywproc.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=True)
    except Exception as exc:
        print(f"  [navegador] falhou: {exc}")
        return 1
    print("  [navegador] Chromium instalado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
