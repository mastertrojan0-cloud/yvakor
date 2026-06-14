"""YVAKOR — OAuth 2.0 genérico (Authorization Code com redirect loopback).

Suporta múltiplos provedores (Google, GitHub, …) com o mesmo fluxo:
  clicar "Entrar com X" → consentimento no site do provedor → redireciona para
  REDIRECT_URI com um code → trocamos por token → conector fica ativo.

Cada provedor define endpoints, de onde vêm as credenciais do app (.env) e o
tipo de token que guardamos:
  - "refresh": guardamos refresh_token e renovamos o access_token a cada uso
               (Google).
  - "access":  guardamos o access_token direto (GitHub OAuth App).

Tudo em stdlib (urllib).
"""
from __future__ import annotations
import os
import json
import urllib.parse
import urllib.request
import urllib.error

# Deve bater EXATAMENTE com a URI registrada no app do provedor e com a porta
# do servidor (yvakor.server.PORT = 7777).
REDIRECT_URI = "http://localhost:7777/api/oauth/callback"

PROVIDERS = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "client_env": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
        "extra_auth": {"access_type": "offline", "prompt": "consent"},
        "token_kind": "refresh",
        "label": "Google",
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "client_env": ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"),
        "extra_auth": {},
        "token_kind": "access",
        "label": "GitHub",
    },
    "slack": {
        "auth_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "client_env": ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"),
        "extra_auth": {},
        "token_kind": "access",   # guarda o bot token (access_token de topo)
        "label": "Slack",
    },
}


def app_credentials(provider: str) -> tuple[str | None, str | None]:
    """Credenciais de app compartilhadas (via .env). Se definidas, o usuário
    entra em um clique, sem colar Client ID/Secret."""
    p = PROVIDERS.get(provider)
    if not p:
        return (None, None)
    cid_env, sec_env = p["client_env"]
    return (os.environ.get(cid_env), os.environ.get(sec_env))


def _post_form(url: str, form: dict) -> dict:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            try:
                return {"ok": True, "data": json.loads(raw)}
            except json.JSONDecodeError:
                # alguns endpoints (GitHub legado) devolvem urlencoded
                return {"ok": True, "data": dict(urllib.parse.parse_qsl(raw))}
    except urllib.error.HTTPError as e:
        return {"ok": False, "erro": e.read().decode("utf-8", "replace")[:800]}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def build_auth_url(provider: str, client_id: str, scope: str, state: str) -> str:
    p = PROVIDERS[provider]
    params = {"client_id": client_id, "redirect_uri": REDIRECT_URI,
              "response_type": "code", "scope": scope, "state": state}
    params.update(p.get("extra_auth", {}))
    return p["auth_url"] + "?" + urllib.parse.urlencode(params)


def exchange_code(provider: str, client_id: str, client_secret: str,
                  code: str) -> dict:
    """Troca o code por token. Devolve {ok, token, erro?} onde token é o
    refresh_token (Google) ou o access_token (GitHub)."""
    p = PROVIDERS[provider]
    r = _post_form(p["token_url"], {
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"})
    if not r["ok"]:
        return r
    tok = r["data"]
    if p["token_kind"] == "refresh":
        if "refresh_token" not in tok:
            return {"ok": False, "erro": "provedor não devolveu refresh_token "
                    "(revogue o acesso e tente de novo)."}
        return {"ok": True, "token": tok["refresh_token"]}
    # access: GitHub/Slack devolvem access_token (no Slack é o bot token)
    if not tok.get("access_token"):
        return {"ok": False, "erro": tok.get("error_description")
                or tok.get("error") or "provedor não devolveu access_token"}
    return {"ok": True, "token": tok["access_token"]}


def get_access_token(creds: dict) -> str | None:
    """Token de acesso válido a partir das credenciais do conector.
    creds deve conter _provider, client_id, client_secret e oauth_token."""
    provider = creds.get("_provider")
    p = PROVIDERS.get(provider or "")
    if not p:
        return None
    if p["token_kind"] == "access":
        return creds.get("oauth_token")
    # refresh: renova o access_token
    r = _post_form(p["token_url"], {
        "client_id": creds.get("client_id"),
        "client_secret": creds.get("client_secret"),
        "refresh_token": creds.get("oauth_token"),
        "grant_type": "refresh_token"})
    return r["data"].get("access_token") if r.get("ok") else None


def api(creds: dict, url: str, method: str = "GET", body: dict | None = None,
        extra_headers: dict | None = None) -> dict:
    """Chamada JSON autenticada (Bearer) a uma API do provedor."""
    token = get_access_token(creds)
    if not token:
        return {"ok": False, "erro": "falha ao obter token (reautorize o conector)"}
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json", "User-Agent": "YVAKOR/1.0"}
    headers.update(extra_headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return {"ok": True, "data": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code,
                "erro": e.read().decode("utf-8", "replace")[:800]}
    except Exception as e:
        return {"ok": False, "erro": str(e)}
