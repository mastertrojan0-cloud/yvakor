"""Teste do controle de navegador (offline, headless, página local).

Roda sem internet: cria um HTML temporário, abre no navegador controlado pelo
Playwright e verifica snapshot, refs, preenchimento, clique, abas e captura.

    python tests/test_browser.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HTML = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Teste YVAKOR</title>
<h1>Formulário de teste</h1>
<label for="nome">Seu nome</label>
<input id="nome" placeholder="Digite seu nome">
<button id="acao" onclick="document.getElementById('saida').textContent =
  'Olá, ' + document.getElementById('nome').value">Saudar</button>
<button id="segundo" onclick="this.textContent='clicado'">Outro botão</button>
<a href="#secao">Ir para a seção</a>
<p id="saida">—</p>
<ul><li>Item um</li><li>Item dois</li></ul>
"""


def test_browser() -> None:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("  [skip] Playwright não instalado")
        return

    from yvakor.browser.session import BrowserSession

    tmp = Path(tempfile.mkdtemp(prefix="yvk-browser-"))
    pagina = tmp / "teste.html"
    pagina.write_text(HTML, encoding="utf-8")

    session = BrowserSession({
        "browser": {
            "headless": True,
            "channel": "msedge",
            "viewport": {"width": 1100, "height": 720},
            "timeout_ms": 8000,
            "profile_dir": str(tmp / "perfil"),
        }
    })
    try:
        r = session.open(pagina.as_uri())
        assert r["ok"], r
        assert "Teste YVAKOR" in r["titulo"], r["titulo"]
        resumo = r["resumo"]
        assert "Formulário de teste" in resumo, resumo
        assert "[e1]" in resumo, "snapshot não gerou refs:\n" + resumo

        # Preenche pelo placeholder e confere no snapshot seguinte
        r = session.fill("Digite seu nome", "Antonio")
        assert r["ok"], r
        assert 'valor="Antonio"' in r["resumo"], r["resumo"]

        # Clica pelo texto do botão e valida o efeito no DOM
        r = session.click("Saudar")
        assert r["ok"], r
        assert "Olá, Antonio" in r["resumo"], r["resumo"]

        # Clicar por ref (extraída do snapshot atual)
        import re
        refs = re.findall(r"\[(e\d+)\] button", r["resumo"])
        if refs:
            r = session.click(refs[0])
            assert r["ok"], r

        # Ref inválida deve falhar com erro claro (as ferramentas do agente
        # convertem isso em {"ok": False, "erro": ...} via _safe).
        try:
            session.click("e9999")
            raise AssertionError("ref inválida deveria falhar")
        except ValueError as exc:
            assert "ref" in str(exc).lower(), exc

        # Extração de texto e screenshot
        r = session.extract("ul")
        assert r["ok"] and "Item dois" in r["texto"], r

        r = session.screenshot()
        assert r["ok"] and Path(r["arquivo"]).stat().st_size > 1000, r

        # Abas
        r = session.tabs()
        assert r["ok"] and len(r["abas"]) >= 1, r
        r = session.new_tab("about:blank")
        assert r["ok"], r
        r = session.close_tab(-1)
        assert r["ok"], r

        # Frame ao vivo (JPEG) usado pelo painel da interface
        frame = session.live_frame()
        assert frame[:2] == b"\xff\xd8", "frame não é JPEG"

        print("  ✅ navegador ok — snapshot, refs, fill, click, abas, captura")
    finally:
        try:
            session.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    test_browser()
