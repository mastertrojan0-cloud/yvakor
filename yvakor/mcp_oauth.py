"""
YVAKOR — Login OAuth para servidores MCP remotos (spec de autorização do MCP)

É o "Conectar" dos conectores do Claude: em vez de colar um token, você entra
pelo navegador e autoriza o YVAKOR.

  1. descoberta: WWW-Authenticate (resource_metadata) → /.well-known/
     oauth-protected-resource → servidor de autorização →
     /.well-known/oauth-authorization-server (ou openid-configuration);
     sem nada disso, os caminhos padrão /authorize, /token e /register;
  2. registro dinâmico do YVAKOR como cliente público (RFC 7591), a não ser
     que o config traga "oauth": {"client_id": …};
  3. PKCE S256 + state, navegador aberto no login, retorno numa porta local
     (http://127.0.0.1:<porta>/callback) que só vive durante o login;
  4. tokens guardados em data/mcp_oauth.json CIFRADOS com a DPAPI do Windows
     (yvakor/cofre.py); o access_token é renovado sozinho pelo refresh_token.

Quem abre o login é a ferramenta mcp_entrar (yvakor/mcp.py). O YVAKOR nunca
vê sua senha: ela é digitada só no site do serviço.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from yvakor import cofre, seguro
from yvakor.config import ROOT

_log = logging.getLogger(__name__)

ARQ = ROOT / "data" / "mcp_oauth.json"
TIMEOUT_LOGIN = 300
_lock = threading.Lock()


class ErroOAuth(RuntimeError):
    pass


def _origem(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _get_json(url: str) -> dict | None:
    import requests
    try:
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=15)
        if r.status_code == 200:
            dados = r.json()
            return dados if isinstance(dados, dict) else None
    except Exception:
        _log.debug("descoberta OAuth falhou em %s", url, exc_info=True)
    return None


def descobrir(url_mcp: str, www_authenticate: str = "") -> dict:
    """Endpoints de autorização do servidor MCP."""
    origem = _origem(url_mcp)
    caminho = urllib.parse.urlsplit(url_mcp).path.rstrip("/")
    candidatos = []
    m = re.search(r'resource_metadata="([^"]+)"', www_authenticate or "")
    if m:
        candidatos.append(m.group(1))
    candidatos += [f"{origem}/.well-known/oauth-protected-resource{caminho}",
                   f"{origem}/.well-known/oauth-protected-resource"]
    recurso = next((d for d in map(_get_json, dict.fromkeys(candidatos)) if d), {}) or {}
    emissor = ((recurso.get("authorization_servers") or [origem])[0]).rstrip("/")
    em_origem, em_caminho = _origem(emissor), urllib.parse.urlsplit(emissor).path.rstrip("/")
    meta = None
    for url in dict.fromkeys([
            f"{em_origem}/.well-known/oauth-authorization-server{em_caminho}",
            f"{em_origem}/.well-known/openid-configuration{em_caminho}",
            f"{emissor}/.well-known/openid-configuration",
            f"{em_origem}/.well-known/oauth-authorization-server"]):
        meta = _get_json(url)
        if meta and meta.get("token_endpoint"):
            break
    meta = meta or {}
    return {
        "authorization_endpoint": meta.get("authorization_endpoint") or f"{em_origem}/authorize",
        "token_endpoint": meta.get("token_endpoint") or f"{em_origem}/token",
        "registration_endpoint": meta.get("registration_endpoint")
                                 or (None if meta else f"{em_origem}/register"),
        "scopes": recurso.get("scopes_supported") or [],
    }


def _pkce() -> tuple[str, str]:
    verificador = secrets.token_urlsafe(48)
    desafio = base64.urlsafe_b64encode(
        hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    return verificador, desafio


class _Retorno(BaseHTTPRequestHandler):
    recebido: dict = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        qs = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        if not ({"code", "error"} & set(qs)):
            self.send_response(404)
            self.end_headers()
            return
        self.server.recebido = qs                   # type: ignore[attr-defined]
        ok = "code" in qs
        corpo = ("<html><meta charset='utf-8'><body style='font-family:sans-serif'>"
                 f"<h2>{'✅ YVAKOR conectado' if ok else '❌ Login não concluído'}</h2>"
                 "<p>Pode fechar esta aba e voltar ao YVAKOR.</p></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


class LoginOAuth:
    def __init__(self, nome: str, url_mcp: str, cfg: dict | None = None,
                 arq: Path | None = None, abrir=None,
                 timeout: float = TIMEOUT_LOGIN):
        self.nome = nome
        self.url = url_mcp
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self.arq = Path(arq or ARQ)
        self.abrir = abrir or (lambda url: webbrowser.open(url))
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    def _todos(self) -> dict:
        return seguro.ler_json(self.arq, {}) or {}

    def _meu(self) -> dict:
        return self._todos().get(self.nome) or {}

    def _guardar(self, dados: dict) -> None:
        with _lock:
            todos = self._todos()
            todos[self.nome] = dados
            seguro.gravar_json(self.arq, todos)

    def conectado(self) -> bool:
        return bool(self._meu().get("access"))

    def sair(self) -> None:
        with _lock:
            todos = self._todos()
            todos.pop(self.nome, None)
            seguro.gravar_json(self.arq, todos)

    # ------------------------------------------------------------------ #
    def token(self) -> str | None:
        meu = self._meu()
        if not meu.get("access"):
            return None
        if meu.get("expira") and time.time() > float(meu["expira"]) - 60:
            return self.renovar()
        return cofre.revelar(meu["access"]) or None

    def _trocar(self, endpoint: str, form: dict, meu: dict) -> str:
        import requests
        if meu.get("client_secret"):
            form["client_secret"] = cofre.revelar(meu["client_secret"])
        try:
            r = requests.post(endpoint, data=form, timeout=30,
                              headers={"Accept": "application/json"})
            dados = r.json()
        except Exception as exc:
            raise ErroOAuth(f"troca de token falhou: {exc}") from exc
        if r.status_code >= 400 or not dados.get("access_token"):
            raise ErroOAuth(f"servidor recusou o token: {dados.get('error_description') or dados.get('error') or r.status_code}")
        novo = {**meu, "access": cofre.proteger(dados["access_token"]),
                "expira": (time.time() + float(dados["expires_in"]))
                if dados.get("expires_in") else None,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        if dados.get("refresh_token"):
            novo["refresh"] = cofre.proteger(dados["refresh_token"])
        self._guardar(novo)
        return dados["access_token"]

    def renovar(self) -> str | None:
        meu = self._meu()
        refresh = cofre.revelar(meu.get("refresh") or "")
        if not refresh or not meu.get("token_endpoint"):
            return None
        try:
            return self._trocar(meu["token_endpoint"], {
                "grant_type": "refresh_token", "refresh_token": refresh,
                "client_id": meu.get("client_id", ""), "resource": self.url}, meu)
        except ErroOAuth as exc:
            _log.warning("MCP %s: não renovou o token (%s)", self.nome, exc)
            return None

    # ------------------------------------------------------------------ #
    def _registrar(self, endpoint: str | None, redirect: str) -> tuple[str, str]:
        if self.cfg.get("client_id"):
            return str(self.cfg["client_id"]), str(self.cfg.get("client_secret") or "")
        if not endpoint:
            raise ErroOAuth("o servidor não aceita registro automático; informe "
                            '"oauth": {"client_id": "..."} no config/mcp.json')
        import requests
        try:
            r = requests.post(endpoint, timeout=30, json={
                "client_name": "YVAKOR", "redirect_uris": [redirect],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"], "token_endpoint_auth_method": "none"})
            dados = r.json()
        except Exception as exc:
            raise ErroOAuth(f"registro do cliente falhou: {exc}") from exc
        if r.status_code >= 400 or not dados.get("client_id"):
            raise ErroOAuth(f"registro do cliente recusado: {dados.get('error') or r.status_code}")
        return dados["client_id"], dados.get("client_secret") or ""

    def entrar(self, www_authenticate: str = "") -> dict:
        """Fluxo completo (bloqueia até o login terminar ou dar timeout)."""
        meta = descobrir(self.url, www_authenticate)
        srv = HTTPServer(("127.0.0.1", 0), _Retorno)
        srv.recebido = {}                          # type: ignore[attr-defined]
        redirect = f"http://127.0.0.1:{srv.server_address[1]}/callback"
        try:
            client_id, client_secret = self._registrar(meta["registration_endpoint"], redirect)
            verificador, desafio = _pkce()
            estado = secrets.token_urlsafe(24)
            escopo = self.cfg.get("scope") or " ".join(meta["scopes"])
            params = {"response_type": "code", "client_id": client_id,
                      "redirect_uri": redirect, "state": estado,
                      "code_challenge": desafio, "code_challenge_method": "S256",
                      "resource": self.url}
            if escopo:
                params["scope"] = escopo
            sep = "&" if "?" in meta["authorization_endpoint"] else "?"
            self.abrir(meta["authorization_endpoint"] + sep + urllib.parse.urlencode(params))
            srv.timeout = 1
            limite = time.time() + self.timeout
            while not srv.recebido and time.time() < limite:   # type: ignore[attr-defined]
                srv.handle_request()
            recebido = srv.recebido                            # type: ignore[attr-defined]
        finally:
            srv.server_close()
        if not recebido:
            raise ErroOAuth("o login não foi concluído a tempo (5 min)")
        if recebido.get("error"):
            raise ErroOAuth(f"login recusado: {recebido.get('error_description') or recebido['error']}")
        if recebido.get("state") != estado:
            raise ErroOAuth("resposta de login inválida (state não confere)")
        meu = {"client_id": client_id, "token_endpoint": meta["token_endpoint"],
               "client_secret": cofre.proteger(client_secret) if client_secret else ""}
        self._trocar(meta["token_endpoint"], {
            "grant_type": "authorization_code", "code": recebido["code"],
            "redirect_uri": redirect, "client_id": client_id,
            "code_verifier": verificador, "resource": self.url}, meu)
        return {"ok": True, "result": f"conectado a {self.nome}"}
