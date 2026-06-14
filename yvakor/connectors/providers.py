"""YVAKOR — Catálogo de conectores + implementações (apenas stdlib).

Cada conector declara:
  - metadados (nome, ícone, descrição)
  - campos de login/cadastro (o que o usuário preenche no painel)
  - quais são obrigatórios para considerar o conector "conectado"
  - uma função register(reg, reg_guarded, creds) que registra as ferramentas
    daquele conector no agente, capturando as credenciais.

reg / reg_guarded recebem (nome, função, descrição, args):
  - reg          → ferramenta de leitura (sem confirmação)
  - reg_guarded  → ação externa/sensível (passa pelo popup de confirmação)
"""
from __future__ import annotations
import json
import smtplib
import imaplib
import email
import urllib.request
import urllib.error

import yvakor.connectors.google as _google
import yvakor.connectors.oauth as _oauth


# --------------------------------------------------------------------------- #
# Helpers HTTP (JSON) — usados por WhatsApp, Telegram, GitHub
# --------------------------------------------------------------------------- #
def _http_json(url: str, method: str = "GET", body: dict | None = None,
               headers: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", "User-Agent": "YVAKOR/1.0"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw[:2000]}
            return {"ok": True, "status": resp.status, "data": payload}
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", errors="replace")[:1000]
        return {"ok": False, "status": e.code, "erro": detalhe}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


# --------------------------------------------------------------------------- #
# E-mail (SMTP envio / IMAP leitura) — compartilhado por "email" e "outlook"
# --------------------------------------------------------------------------- #
def _email_enviar(creds: dict, para: str, assunto: str, corpo: str) -> dict:
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = creds["usuario"]
    msg["To"] = para
    msg["Subject"] = assunto
    msg.set_content(corpo)
    host = creds["smtp_host"]
    port = int(creds.get("smtp_port") or 587)
    try:
        if port == 465:
            srv = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            srv = smtplib.SMTP(host, port, timeout=30)
            srv.starttls()
        srv.login(creds["usuario"], creds["senha"])
        srv.send_message(msg)
        srv.quit()
        return {"ok": True, "para": para, "assunto": assunto}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def _email_ler(creds: dict, limite: int = 5, pasta: str = "INBOX") -> dict:
    host = creds.get("imap_host")
    if not host:
        return {"ok": False, "erro": "IMAP não configurado para esta conta"}
    try:
        m = imaplib.IMAP4_SSL(host)
        m.login(creds["usuario"], creds["senha"])
        m.select(pasta)
        _typ, data = m.search(None, "ALL")
        ids = data[0].split()[-int(limite):]
        out = []
        for i in reversed(ids):
            _typ, msgdata = m.fetch(i, "(RFC822)")
            msg = email.message_from_bytes(msgdata[0][1])
            snippet = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        snippet = part.get_payload(decode=True).decode(
                            "utf-8", "replace")[:300]
                        break
            else:
                snippet = (msg.get_payload(decode=True) or b"").decode(
                    "utf-8", "replace")[:300]
            out.append({"de": msg.get("From"), "assunto": msg.get("Subject"),
                        "data": msg.get("Date"), "trecho": snippet})
        m.logout()
        return {"ok": True, "emails": out}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def _make_email_register(sufixo: str, rotulo: str):
    """Cria a função register de um conector de e-mail (genérico ou outlook).
    sufixo evita colisão de nomes quando há mais de uma conta de e-mail."""
    nome_env = f"enviar_email{sufixo}"
    nome_ler = f"ler_emails{sufixo}"

    def register(reg, reg_guarded, creds):
        reg_guarded(nome_env, lambda para, assunto, corpo: _email_enviar(
            creds, para, assunto, corpo),
            f"Envia um e-mail pela conta {rotulo}.",
            {"para": "str", "assunto": "str", "corpo": "str"})
        reg(nome_ler, lambda limite=5, pasta="INBOX": _email_ler(
            creds, limite, pasta),
            f"Lê os últimos e-mails da conta {rotulo}.",
            {"limite": "int?", "pasta": "str?"})
    return register


# --------------------------------------------------------------------------- #
# WhatsApp Cloud API
# --------------------------------------------------------------------------- #
def _whatsapp_register(reg, reg_guarded, creds):
    def enviar(para: str, mensagem: str) -> dict:
        url = (f"https://graph.facebook.com/v20.0/"
               f"{creds['phone_number_id']}/messages")
        body = {"messaging_product": "whatsapp", "to": para,
                "type": "text", "text": {"body": mensagem}}
        return _http_json(url, "POST", body,
                          {"Authorization": f"Bearer {creds['token']}"})
    reg_guarded("enviar_whatsapp", enviar,
                "Envia mensagem de WhatsApp (Cloud API).",
                {"para": "str (com DDI, ex 5592...)", "mensagem": "str"})


# --------------------------------------------------------------------------- #
# Telegram Bot
# --------------------------------------------------------------------------- #
def _telegram_register(reg, reg_guarded, creds):
    def enviar(mensagem: str, chat_id: str = "") -> dict:
        chat = chat_id or creds.get("chat_id")
        if not chat:
            return {"ok": False, "erro": "informe chat_id (ou salve um padrão)"}
        url = f"https://api.telegram.org/bot{creds['token']}/sendMessage"
        return _http_json(url, "POST", {"chat_id": chat, "text": mensagem})
    reg_guarded("enviar_telegram", enviar,
                "Envia mensagem via bot do Telegram.",
                {"mensagem": "str", "chat_id": "str?"})

    def updates(limite: int = 10) -> dict:
        url = f"https://api.telegram.org/bot{creds['token']}/getUpdates"
        return _http_json(url + f"?limit={int(limite)}")
    reg("telegram_mensagens", updates,
        "Lê as últimas mensagens recebidas pelo bot do Telegram.",
        {"limite": "int?"})


# --------------------------------------------------------------------------- #
# Slack
# --------------------------------------------------------------------------- #
def _slack_register(reg, reg_guarded, creds):
    def enviar(mensagem: str, canal: str) -> dict:
        if not canal:
            return {"ok": False, "erro": "informe o canal (ex.: #geral)"}
        r = _oauth.api(creds, "https://slack.com/api/chat.postMessage", "POST",
                       {"channel": canal, "text": mensagem})
        # Slack devolve 200 com ok=false em caso de erro lógico
        if r.get("ok") and isinstance(r.get("data"), dict) and not r["data"].get("ok"):
            return {"ok": False, "erro": r["data"].get("error", "falha no Slack")}
        return r
    reg_guarded("enviar_slack", enviar,
                "Envia mensagem em um canal do Slack.",
                {"mensagem": "str", "canal": "str (ex.: #geral)"})

    def canais(limite: int = 100) -> dict:
        return _oauth.api(
            creds, "https://slack.com/api/conversations.list?limit="
            f"{int(limite)}&types=public_channel,private_channel")
    reg("slack_canais", canais, "Lista os canais do Slack.", {"limite": "int?"})


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
def _github_register(reg, reg_guarded, creds):
    GH = {"Accept": "application/vnd.github+json"}

    def listar_repos(limite: int = 30) -> dict:
        return _oauth.api(
            creds, f"https://api.github.com/user/repos?per_page={int(limite)}"
            "&sort=updated", "GET", None, GH)
    reg("github_listar_repos", listar_repos,
        "Lista seus repositórios no GitHub.", {"limite": "int?"})

    def ler_arquivo(repo: str, caminho: str, ref: str = "") -> dict:
        url = f"https://api.github.com/repos/{repo}/contents/{caminho}"
        if ref:
            url += f"?ref={ref}"
        return _oauth.api(creds, url, "GET", None, GH)
    reg("github_ler_arquivo", ler_arquivo,
        "Lê um arquivo de um repositório (repo='dono/nome').",
        {"repo": "str", "caminho": "str", "ref": "str?"})

    def criar_issue(repo: str, titulo: str, corpo: str = "") -> dict:
        return _oauth.api(creds, f"https://api.github.com/repos/{repo}/issues",
                          "POST", {"title": titulo, "body": corpo}, GH)
    reg_guarded("github_criar_issue", criar_issue,
                "Abre uma issue num repositório (repo='dono/nome').",
                {"repo": "str", "titulo": "str", "corpo": "str?"})

    def criar_repo(nome: str, privado: bool = True, descricao: str = "") -> dict:
        return _oauth.api(creds, "https://api.github.com/user/repos", "POST",
                          {"name": nome, "private": bool(privado),
                           "description": descricao}, GH)
    reg_guarded("github_criar_repo", criar_repo,
                "Cria um novo repositório na sua conta.",
                {"nome": "str", "privado": "bool?", "descricao": "str?"})


# --------------------------------------------------------------------------- #
# CATÁLOGO
# --------------------------------------------------------------------------- #
CATALOGO: dict[str, dict] = {
    "email": {
        "name": "E-mail (SMTP/IMAP)",
        "icon": "✉️",
        "desc": "Enviar e ler e-mails por qualquer provedor (Gmail, etc.).",
        "fields": [
            {"key": "usuario", "label": "E-mail", "placeholder": "voce@gmail.com"},
            {"key": "senha", "label": "Senha de app", "type": "password"},
            {"key": "smtp_host", "label": "Servidor SMTP", "placeholder": "smtp.gmail.com"},
            {"key": "smtp_port", "label": "Porta SMTP", "placeholder": "587"},
            {"key": "imap_host", "label": "Servidor IMAP (opcional)",
             "placeholder": "imap.gmail.com"},
        ],
        "required": ["usuario", "senha", "smtp_host", "smtp_port"],
        "register": _make_email_register("", "principal"),
    },
    "outlook": {
        "name": "Outlook / Microsoft 365",
        "icon": "📧",
        "desc": "Enviar e ler e-mails da sua conta Outlook/Hotmail.",
        "fields": [
            {"key": "usuario", "label": "E-mail Outlook",
             "placeholder": "voce@outlook.com"},
            {"key": "senha", "label": "Senha de app", "type": "password"},
            {"key": "smtp_host", "label": "Servidor SMTP",
             "placeholder": "smtp-mail.outlook.com", "default": "smtp-mail.outlook.com"},
            {"key": "smtp_port", "label": "Porta SMTP",
             "placeholder": "587", "default": "587"},
            {"key": "imap_host", "label": "Servidor IMAP",
             "placeholder": "outlook.office365.com", "default": "outlook.office365.com"},
        ],
        "required": ["usuario", "senha", "smtp_host", "smtp_port"],
        "register": _make_email_register("_outlook", "Outlook"),
    },
    "whatsapp": {
        "name": "WhatsApp (Cloud API)",
        "icon": "💬",
        "desc": "Enviar mensagens de WhatsApp via API oficial da Meta.",
        "fields": [
            {"key": "token", "label": "Token de acesso", "type": "password"},
            {"key": "phone_number_id", "label": "Phone Number ID",
             "placeholder": "ex.: 1029384756"},
        ],
        "required": ["token", "phone_number_id"],
        "register": _whatsapp_register,
    },
    "telegram": {
        "name": "Telegram Bot",
        "icon": "✈️",
        "desc": "Enviar/receber mensagens por um bot do Telegram.",
        "fields": [
            {"key": "token", "label": "Token do bot (BotFather)", "type": "password"},
            {"key": "chat_id", "label": "Chat ID padrão (opcional)",
             "placeholder": "ex.: 123456789"},
        ],
        "required": ["token"],
        "register": _telegram_register,
    },
    "github": {
        "name": "GitHub",
        "icon": "🐙",
        "desc": "Criar repos/issues e ler código dos seus repositórios.",
        "fields": [
            {"key": "client_id", "label": "Client ID (OAuth App)"},
            {"key": "client_secret", "label": "Client Secret", "type": "password"},
        ],
        "required": ["client_id", "client_secret"],
        "oauth": {"provider": "github", "scope": "repo read:user"},
        "register": _github_register,
    },
    "slack": {
        "name": "Slack",
        "icon": "💼",
        "desc": "Enviar mensagens e listar canais do Slack.",
        "fields": [
            {"key": "client_id", "label": "Client ID (Slack App)"},
            {"key": "client_secret", "label": "Client Secret", "type": "password"},
        ],
        "required": ["client_id", "client_secret"],
        "oauth": {"provider": "slack", "scope": "chat:write,channels:read,groups:read"},
        "register": _slack_register,
    },
    "google_calendar": {
        "name": "Google Calendar",
        "icon": "📅",
        "desc": "Listar e criar eventos na sua agenda do Google.",
        "fields": [
            {"key": "client_id", "label": "Client ID (Google Cloud)"},
            {"key": "client_secret", "label": "Client Secret", "type": "password"},
        ],
        "required": ["client_id", "client_secret"],
        "oauth": {"provider": "google", "scope": _google.SCOPES["google_calendar"]},
        "register": _google.calendar_register,
    },
    "google_drive": {
        "name": "Google Drive",
        "icon": "📂",
        "desc": "Listar arquivos e enviar arquivos para o Drive.",
        "fields": [
            {"key": "client_id", "label": "Client ID (Google Cloud)"},
            {"key": "client_secret", "label": "Client Secret", "type": "password"},
        ],
        "required": ["client_id", "client_secret"],
        "oauth": {"provider": "google", "scope": _google.SCOPES["google_drive"]},
        "register": _google.drive_register,
    },
    "google_gmail": {
        "name": "Gmail",
        "icon": "📨",
        "desc": "Enviar e ler e-mails pelo Gmail via API (sem senha de app).",
        "fields": [
            {"key": "client_id", "label": "Client ID (Google Cloud)"},
            {"key": "client_secret", "label": "Client Secret", "type": "password"},
        ],
        "required": ["client_id", "client_secret"],
        "oauth": {"provider": "google", "scope": _google.SCOPES["google_gmail"]},
        "register": _google.gmail_register,
    },
}
