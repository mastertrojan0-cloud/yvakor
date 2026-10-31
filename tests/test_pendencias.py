"""Pendências resolvidas: compactação (conversa e passos do agente), MCP pelo
transporte SSE antigo, login OAuth do MCP (descoberta, registro, PKCE,
renovação) e o cofre de tokens (DPAPI)."""
import base64
import hashlib
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from yvakor import cofre, mcp_oauth
from yvakor.agent import AgentLoop
from yvakor.compactacao import CompactadorConversa
from yvakor.mcp import MCPClienteHTTP, MCPClienteSSE, MCPManager
from yvakor.memory.episodic import EpisodicMemory
from yvakor.tools.registry import ToolRegistry


def _subir(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _json(h, status, dados, extra=None):
    corpo = json.dumps(dados).encode()
    h.send_response(status)
    h.send_header("Content-Type", "application/json")
    for k, v in (extra or {}).items():
        h.send_header(k, v)
    h.send_header("Content-Length", str(len(corpo)))
    h.end_headers()
    h.wfile.write(corpo)


def _resposta_mcp(corpo):
    m = corpo.get("method")
    if m == "initialize":
        return {"protocolVersion": "2025-03-26", "capabilities": {}}
    if m == "tools/list":
        return {"tools": [{"name": "eco", "inputSchema": {"properties": {"t": {}}}}]}
    return {"content": [{"type": "text", "text": "eco: " + corpo["params"]["arguments"]["t"]}]}


# --------------------------------------------------------------------- #
# Compactação
# --------------------------------------------------------------------- #
class RouterFalso:
    def __init__(self):
        self.pedidos = []

    def complete_messages(self, tarefa, msgs, timeout=None, forcar=None):
        self.pedidos.append(msgs[1]["content"])
        return "- usuário quer orçamento da clínica Sorriso: R$ 4.800"


def test_conversa_compacta_so_o_que_saiu_da_janela(tmp_path):
    ep = EpisodicMemory(tmp_path / "ep.db")
    sid = ep.nova_conversa("teste").split(" ")[0]     # devolve "id (título)"
    router = RouterFalso()
    c = CompactadorConversa(ep, router, janela=4, lote=3)
    for i in range(6):
        ep.log("conversa", f"pergunta {i}", f"resposta {i}", session_id=sid)
    assert c.atualizar(sid)["compactou"] == 0         # 2 fora da janela < lote 3
    ep.log("conversa", "pergunta 6", "resposta 6", session_id=sid)
    r = c.atualizar(sid)
    assert r["compactou"] == 3 and "pergunta 0" in router.pedidos[0] \
        and "pergunta 3" not in router.pedidos[0]
    assert "clínica Sorriso" in c.bloco_prompt(sid)
    assert c.atualizar(sid, forcar=True)["compactou"] == 0   # nada novo
    ep.log("conversa", "pergunta 7", "resposta 7", session_id=sid)
    assert c.atualizar(sid, forcar=True)["compactou"] == 1   # /compactar força
    assert "RESUMO ATUAL" in router.pedidos[-1] and "R$ 4.800" in router.pedidos[-1]
    ep.nova_conversa("outra")
    assert ep.apagar_conversa(sid)[0]
    assert c.resumo(sid) == ""                        # apagar conversa apaga o resumo


def test_janela_do_agente_resume_passos_em_vez_de_esquecer():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "pedido"}]
    for i in range(20):
        msgs.append({"role": "assistant", "content": f'{{"acao": {i}}}'})
        ok = "true" if i % 2 else "false"
        msgs.append({"role": "user", "content":
                     f'OBSERVAÇÃO (ferramenta_{i}): {{"ok": {ok}, "result": "dado {i}"}}'})
    janela = AgentLoop._janela(msgs, base=2, manter=6)
    assert len(janela) == 2 + 1 + 6
    nota = janela[2]["content"]
    assert "PASSOS JÁ FEITOS" in nota and "ferramenta_0 ✗" in nota and "ferramenta_1 ✓" in nota
    assert "dado 3" in nota and "ferramenta_19" not in nota      # o fim fica inteiro


# --------------------------------------------------------------------- #
# MCP pelo transporte SSE antigo
# --------------------------------------------------------------------- #
class _SSE(BaseHTTPRequestHandler):
    fila: list = []
    evento = threading.Event()

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b"event: endpoint\ndata: /mensagens?s=1\n\n")
        self.wfile.flush()
        fim = time.time() + 15
        while time.time() < fim:
            if _SSE.evento.wait(0.1):
                _SSE.evento.clear()
                while _SSE.fila:
                    msg = _SSE.fila.pop(0)
                    self.wfile.write(f"event: message\ndata: {json.dumps(msg)}\n\n".encode())
                    self.wfile.flush()

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/mensagens?s=1"
        self.send_response(202)
        self.end_headers()
        if "id" in corpo:
            _SSE.fila.append({"jsonrpc": "2.0", "id": corpo["id"],
                              "result": _resposta_mcp(corpo)})
            _SSE.evento.set()


def test_mcp_sse_antigo():
    srv, base = _subir(_SSE)
    try:
        cli = MCPClienteSSE("velho", {"type": "sse", "url": base + "/sse",
                                      "headers": {"Authorization": "Bearer x"}})
        assert cli.iniciar(), cli.erro
        assert cli.endpoint == base + "/mensagens?s=1"
        assert [t["name"] for t in cli.tools] == ["eco"]
        assert cli.chamar("eco", {"t": "oi"})["resultado"] == "eco: oi"
        cli.parar()
    finally:
        srv.shutdown()


# --------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------- #
class _OAuth(BaseHTTPRequestHandler):
    """Servidor MCP + servidor de autorização no mesmo host (como muitos SaaS)."""
    base = ""
    codigos: dict = {}
    tokens: set = set()
    renovacoes = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = urllib.parse.urlsplit(self.path)
        if p.path == "/.well-known/oauth-protected-resource/mcp":
            return _json(self, 200, {"resource": self.base + "/mcp",
                                     "authorization_servers": [self.base],
                                     "scopes_supported": ["ler"]})
        if p.path == "/.well-known/oauth-authorization-server":
            return _json(self, 200, {"issuer": self.base,
                                     "authorization_endpoint": self.base + "/auth",
                                     "token_endpoint": self.base + "/token",
                                     "registration_endpoint": self.base + "/register"})
        if p.path == "/auth":                    # "usuário aprovou": redireciona com code
            q = dict(urllib.parse.parse_qsl(p.query))
            assert q["code_challenge_method"] == "S256" and q["scope"] == "ler"
            assert q["resource"] == self.base + "/mcp" and q["client_id"] == "cli-1"
            _OAuth.codigos["c0de"] = q["code_challenge"]
            self.send_response(302)
            self.send_header("Location", q["redirect_uri"] + "?" + urllib.parse.urlencode(
                {"code": "c0de", "state": q["state"]}))
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        dados = self.rfile.read(int(self.headers["Content-Length"])).decode()
        p = urllib.parse.urlsplit(self.path).path
        if p == "/register":
            reg = json.loads(dados)
            assert reg["token_endpoint_auth_method"] == "none"
            assert reg["redirect_uris"][0].startswith("http://127.0.0.1:")
            return _json(self, 201, {"client_id": "cli-1"})
        if p == "/token":
            f = dict(urllib.parse.parse_qsl(dados))
            if f["grant_type"] == "authorization_code":
                desafio = base64.urlsafe_b64encode(hashlib.sha256(
                    f["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                assert _OAuth.codigos.pop(f["code"]) == desafio        # PKCE confere
                _OAuth.tokens.add("tok-1")
                return _json(self, 200, {"access_token": "tok-1", "refresh_token": "ref-1",
                                         "expires_in": 3600})
            assert f["grant_type"] == "refresh_token" and f["refresh_token"] == "ref-1"
            _OAuth.renovacoes += 1
            _OAuth.tokens = {"tok-2"}
            return _json(self, 200, {"access_token": "tok-2", "expires_in": 3600})
        if p == "/mcp":
            auth = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            if auth not in _OAuth.tokens:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Bearer resource_metadata="'
                                 + self.base + '/.well-known/oauth-protected-resource/mcp"')
                self.end_headers()
                return
            corpo = json.loads(dados)
            if "id" not in corpo:
                self.send_response(202)
                self.end_headers()
                return
            return _json(self, 200, {"jsonrpc": "2.0", "id": corpo["id"],
                                     "result": _resposta_mcp(corpo)})
        self.send_response(404)
        self.end_headers()


def _navegador(url):
    """Faz o papel do navegador: segue o /auth até o retorno local."""
    threading.Thread(target=lambda: requests.get(url, timeout=10), daemon=True).start()


def test_mcp_oauth_login_completo_e_renovacao(tmp_path, monkeypatch):
    srv, base = _subir(_OAuth)
    _OAuth.base, _OAuth.tokens, _OAuth.renovacoes = base, set(), 0
    try:
        cfg = {"enabled": True, "type": "http", "url": base + "/mcp"}
        cli = MCPClienteHTTP("saas", cfg)
        assert not cli.iniciar() and "mcp_entrar" in cli.erro    # sem login ainda

        login = mcp_oauth.LoginOAuth("saas", base + "/mcp", abrir=_navegador, timeout=20)
        assert login.entrar(cli.www_authenticate)["ok"]
        guardado = json.loads(mcp_oauth.ARQ.read_text("utf-8"))["saas"]
        assert "tok-1" not in json.dumps(guardado)              # cifrado no disco
        assert login.token() == "tok-1"

        cli = MCPClienteHTTP("saas", cfg)
        assert cli.iniciar(), cli.erro
        _OAuth.tokens = set()                                   # token revogado/expirado
        assert cli.chamar("eco", {"t": "x"})["resultado"] == "eco: x"   # renovou sozinho
        assert _OAuth.renovacoes == 1 and login.token() == "tok-2"
    finally:
        srv.shutdown()


def test_mcp_manager_entrar_sobe_o_servidor(tmp_path, monkeypatch):
    srv, base = _subir(_OAuth)
    _OAuth.base, _OAuth.tokens = base, set()
    monkeypatch.setattr(mcp_oauth.webbrowser, "open", _navegador)
    try:
        cfg_path = tmp_path / "mcp.json"
        cfg_path.write_text(json.dumps({"servers": {"saas": {
            "enabled": True, "type": "http", "url": base + "/mcp"}}}), "utf-8")
        reg = ToolRegistry({"tools": {"guarded_actions": []}})
        m = MCPManager(reg, cfg_path)
        assert m.iniciar()["servidores"] == 0
        st = reg.run("mcp_status")["servidores"]["saas"]
        assert st["vivo"] is False and "mcp_entrar" in st["erro"]
        r = m.entrar("saas", esperar=True)
        assert r["ok"], r
        assert "mcp_saas_eco" in reg.tools and reg.run("mcp_saas_eco", t="y")["resultado"] == "eco: y"
        assert m.sair("saas")["ok"] and "mcp_saas_eco" not in reg.tools
        assert not m.entrar("inexistente")["ok"]
    finally:
        srv.shutdown()


# --------------------------------------------------------------------- #
@pytest.mark.skipif(os.name != "nt", reason="DPAPI é do Windows")
def test_cofre_dpapi():
    s = cofre.proteger("segredo-çã")
    assert s.startswith("dpapi:") and "segredo" not in s
    assert cofre.revelar(s) == "segredo-çã"
    assert cofre.revelar("dpapi:AAAA") == "" and cofre.revelar("plano:x") == "x"
    assert cofre.proteger("") == ""


# --------------------------------------------------------------------- #
# Achados da revisão de engenharia
# --------------------------------------------------------------------- #
def test_ferramenta_mcp_que_escreve_pede_confirmacao():
    p = MCPManager._precisa_confirmar
    assert p({}, "create_issue", {}) and p({}, "sendMessage", {}) and p({}, "delete-file", {})
    assert not p({}, "get_dataset", {}) and not p({}, "list_issues", {})
    assert not p({}, "update_x", {"annotations": {"readOnlyHint": True}})
    assert p({}, "consultar", {"annotations": {"destructiveHint": True}})
    assert p({"confirmar": "todas"}, "list_issues", {})
    assert not p({"confirmar": "nenhuma"}, "create_issue", {})
    assert p({"confirmar": ["buscar"]}, "buscar", {}) and not p({"confirmar": ["x"]}, "buscar", {})


def test_subagentes_em_paralelo_recebem_o_popup_de_confirmacao(tmp_path):
    from yvakor.agentes import Agentes
    from yvakor.tools import guard
    vistos = []

    class Loop:
        def __init__(self, registro, d):
            pass

        def run(self, *a, **k):
            vistos.append(guard._thread_confirmer())
            return "ok"

    reg = ToolRegistry({"tools": {"guarded_actions": []}})
    ag = Agentes(None, reg, tmp_path / "agents", criar_loop=Loop)
    confirmador = lambda acao, detalhe: True                     # noqa: E731
    guard.set_thread_confirmer(confirmador)
    try:
        ag.delegar(tarefas=[{"tarefa": "a"}, {"tarefa": "b"}])
    finally:
        guard.clear_thread_confirmer()
    assert vistos == [confirmador, confirmador]
