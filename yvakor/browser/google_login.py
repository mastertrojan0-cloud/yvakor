"""Abre o login do Google no navegador do YVAKOR (rota de sessão)."""
from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from yvakor.config import load_settings  # noqa: E402
from yvakor.browser.session import BrowserSession  # noqa: E402


def main() -> int:
    s = BrowserSession(load_settings())
    print("Abrindo o Google — conclua o login na janela do navegador...")
    r = s.login_google(timeout_s=300)
    print(r)
    s.shutdown()
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
