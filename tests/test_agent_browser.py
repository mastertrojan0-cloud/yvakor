"""Teste de integração: loop do agente dirigindo o navegador de verdade.

Usa um "LLM falso" que devolve as mesmas ações JSON que o modelo real devolve,
mas executa as ferramentas de verdade no Playwright. Assim validamos o ciclo
completo (protocolo → registry → navegador → observação → resposta) sem gastar
API e sem depender de rede.

    python tests/test_agent_browser.py
"""
from __future__ import annotations

import json
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
<title>Perfil YVAKOR</title>
<h1>Cadastro</h1>
<input id="nome" placeholder="Digite seu nome">
<button id="ok" onclick="document.getElementById('saida').textContent =
 'Olá, ' + document.getElementById('nome').value">Saudar</button>
<p id="saida">—</p>
"""


class FakeRouter:
    """Devolve respostas roteirizadas (como o modelo faria)."""

    def __init__(self, roteiro: list[str]):
        self.roteiro = list(roteiro)
        self.chamadas = 0
        self.ultimas_mensagens: list[dict] = []

    def complete_messages(self, task_type: str, messages: list[dict],
                          forcar=None) -> str:
        self.chamadas += 1
        self.ultimas_mensagens = messages
        idx = min(self.chamadas - 1, len(self.roteiro) - 1)
        return self.roteiro[idx]


def _registro_com_navegador():
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    from yvakor.browser.session import BrowserSession
    from yvakor.browser.tools import register_browser_tools

    settings = load_settings()
    tmp = Path(tempfile.mkdtemp(prefix="yvk-agent-"))
    settings["browser"] = dict(settings.get("browser") or {})
    settings["browser"].update({"headless": True, "channel": "msedge",
                                "profile_dir": str(tmp / "perfil")})
    registry = ToolRegistry(settings)
    session = BrowserSession(settings)
    register_browser_tools(registry, session)
    return registry, session


def test_agent_dirige_navegador() -> None:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("  [skip] Playwright não instalado")
        return

    from yvakor.agent import AgentLoop

    tmp = Path(tempfile.mkdtemp(prefix="yvk-agent-page-"))
    pagina = tmp / "perfil.html"
    pagina.write_text(HTML, encoding="utf-8")

    registry, session = _registro_com_navegador()
    roteiro = [
        json.dumps({"acao": "usar_ferramenta", "ferramenta": "navegador_abrir",
                    "args": {"url": pagina.as_uri()}, "motivo": "abrir"}),
        json.dumps({"acao": "usar_ferramenta", "ferramenta": "navegador_ver",
                    "args": {}, "motivo": "ver"}),
        json.dumps({"acao": "usar_ferramenta", "ferramenta": "navegador_preencher",
                    "args": {"alvo": "Digite seu nome", "valor": "Antonio"},
                    "motivo": "preencher"}),
        json.dumps({"acao": "usar_ferramenta", "ferramenta": "navegador_clicar",
                    "args": {"alvo": "Saudar"}, "motivo": "clicar"}),
        "Pronto: abri a página, preenchi o nome e cliquei em Saudar.",
    ]
    router = FakeRouter(roteiro)
    loop = AgentLoop(router, registry, max_iterations=10)

    eventos: list[tuple] = []
    resposta = loop.run("Você é um agente de teste.",
                        history=[{"role": "user",
                                  "content": "Preencha o nome Antonio e clique"}],
                        on_event=lambda t, d: eventos.append((t, d)))

    nomes = [d.get("nome") for t, d in eventos if t == "ferramenta"]
    assert nomes == ["navegador_abrir", "navegador_ver",
                     "navegador_preencher", "navegador_clicar"], nomes
    assert "Pronto" in resposta, resposta

    # A observação do clique tem que conter o efeito real no DOM
    observacoes = [d["resultado"] for t, d in eventos if t == "observacao"]
    click = observacoes[-1]
    assert click.get("ok"), click
    assert "Olá, Antonio" in click.get("resumo", ""), click["resumo"][:600]

    # O system prompt enviado ao modelo tem o manifesto com as ferramentas
    system = router.ultimas_mensagens[0]["content"]
    assert "navegador_ver" in system and "CONTROLE DO NAVEGADOR" in system

    session.shutdown()
    print("  ✅ agente ok — abriu, viu, preencheu e clicou de verdade")


def test_cancelamento_entre_passos() -> None:
    from yvakor.agent import AgentLoop
    registry, session = _registro_com_navegador()
    acao = json.dumps({"acao": "usar_ferramenta",
                       "ferramenta": "navegador_ver", "args": {}})
    router = FakeRouter([acao])          # sempre pede ferramenta: loop infinito
    loop = AgentLoop(router, registry, max_iterations=20)
    passos = {"n": 0}

    def deve_parar():
        passos["n"] += 1
        return passos["n"] > 2

    resposta = loop.run("teste", history=[{"role": "user", "content": "x"}],
                        should_stop=deve_parar)
    assert "interrompida" in resposta.lower(), resposta
    assert router.chamadas <= 3, router.chamadas
    session.shutdown()
    print("  ✅ cancelamento ok — o loop para entre um passo e outro")


if __name__ == "__main__":
    test_agent_dirige_navegador()
    test_cancelamento_entre_passos()
