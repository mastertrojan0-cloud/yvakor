"""YVAKOR — Ferramentas Google (Calendar, Drive, Gmail).

A mecânica de OAuth (login, troca de code, renovação de token) é genérica e
vive em yvakor.connectors.oauth. Aqui ficam só as ferramentas, que pegam um
access_token válido via oauth.get_access_token / oauth.api.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error

import yvakor.connectors.oauth as oauth

SCOPES = {
    "google_calendar": "https://www.googleapis.com/auth/calendar",
    "google_drive": "https://www.googleapis.com/auth/drive",
    "google_gmail": ("https://www.googleapis.com/auth/gmail.send "
                     "https://www.googleapis.com/auth/gmail.readonly"),
}


# --------------------------------------------------------------------------- #
# Google Calendar
# --------------------------------------------------------------------------- #
def calendar_register(reg, reg_guarded, creds):
    base = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

    def listar(limite: int = 10) -> dict:
        from datetime import datetime, timezone
        import urllib.parse
        agora = datetime.now(timezone.utc).isoformat()
        url = (f"{base}?maxResults={int(limite)}&orderBy=startTime"
               f"&singleEvents=true&timeMin={urllib.parse.quote(agora)}")
        r = oauth.api(creds, url)
        if r["ok"]:
            itens = [{"titulo": e.get("summary"),
                      "inicio": e.get("start", {}).get("dateTime")
                      or e.get("start", {}).get("date"),
                      "id": e.get("id")} for e in r["data"].get("items", [])]
            return {"ok": True, "eventos": itens}
        return r
    reg("calendar_listar_eventos", listar,
        "Lista os próximos eventos da agenda do Google.", {"limite": "int?"})

    def criar(titulo: str, inicio: str, fim: str, descricao: str = "") -> dict:
        """inicio/fim em ISO 8601, ex.: 2026-06-20T14:00:00-04:00"""
        body = {"summary": titulo, "description": descricao,
                "start": {"dateTime": inicio}, "end": {"dateTime": fim}}
        r = oauth.api(creds, base, "POST", body)
        if r["ok"]:
            return {"ok": True, "id": r["data"].get("id"),
                    "link": r["data"].get("htmlLink")}
        return r
    reg_guarded("calendar_criar_evento", criar,
                "Cria um evento na agenda (datas em ISO 8601).",
                {"titulo": "str", "inicio": "str", "fim": "str", "descricao": "str?"})


# --------------------------------------------------------------------------- #
# Google Drive
# --------------------------------------------------------------------------- #
def drive_register(reg, reg_guarded, creds):
    def listar(limite: int = 20) -> dict:
        url = ("https://www.googleapis.com/drive/v3/files?"
               f"pageSize={int(limite)}&orderBy=modifiedTime%20desc"
               "&fields=files(id,name,mimeType,modifiedTime)")
        r = oauth.api(creds, url)
        if r["ok"]:
            return {"ok": True, "arquivos": r["data"].get("files", [])}
        return r
    reg("drive_listar_arquivos", listar,
        "Lista arquivos recentes do Google Drive.", {"limite": "int?"})

    def enviar(caminho: str, nome: str = "") -> dict:
        """Faz upload de um arquivo local para o Drive (upload multipart)."""
        from pathlib import Path
        import mimetypes
        p = Path(caminho).expanduser()
        if not p.exists() or not p.is_file():
            return {"ok": False, "erro": "arquivo local não encontrado"}
        token = oauth.get_access_token(creds)
        if not token:
            return {"ok": False, "erro": "falha ao obter token Google (reautorize)"}
        meta = {"name": nome or p.name}
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        boundary = "yvakorBoundary7777"
        corpo = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: {ctype}\r\n\r\n"
        ).encode() + p.read_bytes() + f"\r\n--{boundary}--".encode()
        req = urllib.request.Request(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            data=corpo, method="POST", headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                d = json.loads(resp.read().decode())
                return {"ok": True, "id": d.get("id"), "nome": d.get("name")}
        except urllib.error.HTTPError as e:
            return {"ok": False, "erro": e.read().decode("utf-8", "replace")[:800]}
        except Exception as e:
            return {"ok": False, "erro": str(e)}
    reg_guarded("drive_enviar_arquivo", enviar,
                "Envia um arquivo local para o Google Drive.",
                {"caminho": "str", "nome": "str?"})


# --------------------------------------------------------------------------- #
# Gmail (via API — sem senha de app)
# --------------------------------------------------------------------------- #
def gmail_register(reg, reg_guarded, creds):
    BASE = "https://gmail.googleapis.com/gmail/v1/users/me/messages"

    def enviar(para: str, assunto: str, corpo: str) -> dict:
        import base64
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["To"] = para
        msg["Subject"] = assunto
        msg.set_content(corpo)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        r = oauth.api(creds, BASE + "/send", "POST", {"raw": raw})
        if r["ok"]:
            return {"ok": True, "para": para, "assunto": assunto,
                    "id": r["data"].get("id")}
        return r
    reg_guarded("gmail_enviar", enviar,
                "Envia um e-mail pelo Gmail (via API, sem senha de app).",
                {"para": "str", "assunto": "str", "corpo": "str"})

    def ler(limite: int = 5) -> dict:
        lst = oauth.api(creds, BASE + f"?maxResults={int(limite)}")
        if not lst["ok"]:
            return lst
        emails = []
        for m in lst["data"].get("messages", []):
            det = oauth.api(creds, BASE + f"/{m['id']}?format=metadata"
                            "&metadataHeaders=From&metadataHeaders=Subject"
                            "&metadataHeaders=Date")
            if not det["ok"]:
                continue
            hs = {h["name"]: h["value"]
                  for h in det["data"].get("payload", {}).get("headers", [])}
            emails.append({"de": hs.get("From"), "assunto": hs.get("Subject"),
                           "data": hs.get("Date"),
                           "trecho": det["data"].get("snippet", "")[:300]})
        return {"ok": True, "emails": emails}
    reg("gmail_ler", ler, "Lê os últimos e-mails do Gmail.", {"limite": "int?"})
