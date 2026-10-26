"""Teste Edge + Chrome: motores independentes e aba isolada por tarefa.

Offline (páginas file://), headless.

    python tests/test_navegadores.py
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


def _pagina(caminho: Path, titulo: str) -> str:
    caminho.write_text(
        f"<!doctype html><meta charset=utf-8><title>{titulo}</title>"
        f"<h1>{titulo}</h1><p>corpo de {titulo}</p>", encoding="utf-8")
    return caminho.as_uri()


def test_motores_e_abas():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("  [skip] Playwright não instalado")
        return

    from yvakor.browser import Navegadores

    tmp = Path(tempfile.mkdtemp(prefix="yvk-navegadores-"))
    a = _pagina(tmp / "a.html", "Edge Principal")
    b = _pagina(tmp / "b.html", "Edge Tarefa")
    c = _pagina(tmp / "c.html", "Chrome Principal")

    settings = {"browser": {
        "headless": True, "motor_padrao": "edge",
        "engines": {
            "edge": {"channel": "msedge", "mode": "launch",
                     "profile_dir": str(tmp / "perfil-edge")},
            "chrome": {"channel": "chrome", "mode": "launch",
                       "profile_dir": str(tmp / "perfil-chrome")},
        }}}
    nav = Navegadores(settings)
    try:
        _corpo_teste(nav, tmp, a, b, c)
    finally:
        try:
            nav.fechar()
            nav.shutdown()
        except Exception:
            pass
    print("  ✅ navegadores — Edge e Chrome independentes, aba por tarefa, CDP com erro claro")


def _corpo_teste(nav, tmp, a, b, c):
    assert nav.nomes() == ["edge", "chrome"]
    assert nav.padrao == "edge"

    edge = nav.sessao("edge")
    chrome = nav.sessao("chrome")
    assert edge is not chrome

    with edge.trilho:
        edge.selecionar_aba("principal")
        r = edge.open(a)
        assert r["ok"] and "Edge Principal" in r["titulo"], r
    with chrome.trilho:
        chrome.selecionar_aba("principal")
        r = chrome.open(c)
        assert r["ok"] and "Chrome Principal" in r["titulo"], r

    # aba isolada por tarefa no MESMO motor
    with edge.trilho:
        edge.selecionar_aba("tarefa-1")
        r = edge.open(b)
        assert "Edge Tarefa" in r["titulo"], r
    with edge.trilho:
        edge.selecionar_aba("principal")
        atual = edge.snapshot()
        assert "Edge Principal" in atual["titulo"], atual
    with edge.trilho:
        edge.selecionar_aba("tarefa-1")
        assert "Edge Tarefa" in edge.snapshot()["titulo"]
    assert set(edge.abas_internas()["abertas"]) >= {"principal", "tarefa-1"}

    st = nav.status()
    assert st["motores"]["edge"]["aberto"] is True
    assert st["motores"]["chrome"]["aberto"] is True
    assert "b.html" in st["motores"]["edge"]["url"]      # última aba usada
    assert "c.html" in st["motores"]["chrome"]["url"]

    # CDP para um endereço inexistente: erro claro, sem travar
    # Isola o Chrome real: sem este patch, conectar_cdp() -> garantir_para_url()
    # ABRIA um Chrome visível na porta 9931 e o deixava vivo a cada execução
    # (o teste então falhava porque o CDP conectava com sucesso).
    from unittest import mock
    from yvakor.browser.session import BrowserSession
    cdp = BrowserSession({"browser": {"headless": True}}, engine="chrome",
                         mode="cdp", cdp_url="http://127.0.0.1:9931",
                         profile_dir=str(tmp / "cdp"))
    falha = {"ok": False, "erro": "connection refused (porta 9931 sem navegador)"}
    try:
        with mock.patch("yvakor.browser.chrome_cdp.garantir_para_url",
                        return_value=falha):
            try:
                cdp.conectar_cdp()
                raise AssertionError("CDP deveria falhar sem navegador na porta")
            except AssertionError:
                raise
            except Exception as exc:
                assert "connect" in str(exc).lower() or "refused" in str(exc).lower(), exc
    finally:
        cdp.shutdown()


if __name__ == "__main__":
    test_motores_e_abas()
