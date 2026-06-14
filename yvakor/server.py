"""
YVAKOR — Servidor da interface 3D
Stdlib pura (http.server): roda em qualquer computador, sem dependências web.

Uso:  python -m yvakor.server   →  http://localhost:7777

Endpoints:
  GET    /                          → interface 3D (interface/index.html)
  GET    /api/status                → estado do agente
  POST   /api/chat                  → {"message","session?"} → {"answer","session"}
  POST   /api/confirm               → {"session","allow"} responde a ação protegida
  GET    /api/sessions              → lista conversas + ativa
  POST   /api/sessions              → cria conversa {"title?"}
  GET    /api/sessions/<id>/messages→ histórico da conversa
  POST   /api/sessions/<id>/activate→ retoma conversa
  POST   /api/sessions/<id>/rename  → renomeia {"title"}
  DELETE /api/sessions/<id>         → apaga conversa
  GET    /api/cowork[/<id>]         → tarefas em segundo plano
  GET    /api/connectors            → lista de conectores + status
  POST   /api/connectors/<id>/connect    → {"fields": {...}} salva login
  POST   /api/connectors/<id>/disconnect → remove credenciais
  POST   /api/connectors/<id>/authorize  → inicia OAuth (devolve auth_url)
  GET    /api/oauth/callback             → redirect do Google (troca o code)
"""
from __future__ import annotations
import sys
import json
import threading

# Console Windows usa cp1252 por padrão e quebra com emojis/acentos.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from yvakor.orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parent.parent
INTERFACE = ROOT / "interface"
PORT = 7777

BUILD = "v0.3 · agente+ferramentas+auto"   # selo p/ confirmar build no ar

_agent: Orchestrator | None = None
_lock = threading.Lock()


def get_agent() -> Orchestrator:
    global _agent
    with _lock:
        if _agent is None:
            _agent = Orchestrator()
        return _agent


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    # ------------------------------ GET ------------------------------ #
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (INTERFACE / "index.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")

        if self.path == "/api/status":
            agent = get_agent()
            skills = [f.stem for f in agent.skills.all_skills()]
            episodes = agent.episodic.conn.execute(
                "SELECT COUNT(*) FROM episodes").fetchone()[0]
            return self._json(200, {
                "agent": "YVAKOR",
                "build": BUILD,
                "provider": agent.settings["llm"]["default_provider"],
                "model": agent.settings["llm"]["providers"][
                    agent.settings["llm"]["default_provider"]]["model"],
                "skills": skills,
                "episodes": episodes,
                "cowork_pending": agent.cowork.pending_count(),
            })

        # Conversas
        if self.path == "/api/sessions":
            ag = get_agent()
            return self._json(200, {"sessions": ag.episodic.listar_conversas(),
                                    "active": ag.episodic.active_id})

        if self.path.startswith("/api/sessions/") and self.path.endswith("/messages"):
            sid = self.path[len("/api/sessions/"):-len("/messages")]
            return self._json(200,
                              {"messages": get_agent().episodic.mensagens_da_conversa(sid)})

        # Conectores (lista + status; sem expor segredos)
        if self.path == "/api/connectors":
            return self._json(200, {"connectors": get_agent().connectors.catalog()})

        # Callback do OAuth (Google redireciona o navegador para cá)
        if self.path.startswith("/api/oauth/callback"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            code = (q.get("code", [None])[0])
            state = (q.get("state", [None])[0])
            erro = (q.get("error", [None])[0])
            if erro or not code or not state:
                msg = f"Autorização cancelada ou inválida ({erro or 'sem code'})."
                ok = False
            else:
                r = get_agent().connectors.oauth_callback(state, code)
                ok = r.get("ok")
                msg = ("Conectado com sucesso! Pode fechar esta aba e voltar ao YVAKOR."
                       if ok else f"Falha: {r.get('erro', 'erro desconhecido')}")
            cor = "#3FBFAE" if ok else "#ff8b86"
            page = (f"<!doctype html><meta charset=utf-8><title>YVAKOR</title>"
                    f"<body style='background:#060D12;color:#EAE4D3;font-family:sans-serif;"
                    f"display:flex;align-items:center;justify-content:center;height:100vh'>"
                    f"<div style='text-align:center'><h2 style='color:{cor}'>"
                    f"{'✓' if ok else '✕'} YVAKOR</h2><p>{msg}</p></div>")
            return self._send(200, page.encode(), "text/html; charset=utf-8")

        # Progresso ao vivo da tarefa em andamento
        if self.path.startswith("/api/progress"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ag = get_agent()
            sid = (q.get("session", [None])[0]) or ag.episodic.active_id
            return self._json(200, ag.get_progress(sid))

        if self.path == "/api/maintenance":
            return self._json(200, get_agent().maintenance.last)

        # Cowork endpoints
        if self.path == "/api/cowork":
            return self._json(200, {"tasks": get_agent().cowork.status()})

        if self.path.startswith("/api/cowork/"):
            tid = self.path[len("/api/cowork/"):]
            result = get_agent().cowork.status(tid)
            if result is None:
                return self._json(404, {"error": "tarefa não encontrada"})
            return self._json(200, result)
        return self._json(404, {"error": "não encontrado"})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode())

    # ------------------------------ POST ----------------------------- #
    def do_POST(self):
        ag = get_agent()
        try:
            data = self._body()

            if self.path == "/api/chat":
                message = (data.get("message") or "").strip()
                if not message:
                    return self._json(400, {"error": "mensagem vazia"})
                # ativa a conversa indicada antes de responder (continuidade)
                if data.get("session"):
                    ag.episodic.retomar_conversa(data["session"])
                return self._json(200, {"answer": ag.process(message),
                                        "session": ag.episodic.active_id})

            # conectar / desconectar um conector
            if self.path.startswith("/api/connectors/") and self.path.endswith("/connect"):
                cid = self.path[len("/api/connectors/"):-len("/connect")]
                r = ag.connectors.connect(cid, data.get("fields", {}))
                return self._json(200 if r.get("ok") else 400, r)

            if self.path.startswith("/api/connectors/") and self.path.endswith("/disconnect"):
                cid = self.path[len("/api/connectors/"):-len("/disconnect")]
                return self._json(200, ag.connectors.disconnect(cid))

            # iniciar autorização OAuth (devolve a URL de consentimento)
            if self.path.startswith("/api/connectors/") and self.path.endswith("/authorize"):
                cid = self.path[len("/api/connectors/"):-len("/authorize")]
                r = ag.connectors.authorize_url(cid)
                return self._json(200 if r.get("ok") else 400, r)

            # resposta do usuário a uma ação protegida (popup da interface)
            if self.path == "/api/confirm":
                sid = data.get("session") or ag.episodic.active_id
                ok = ag.confirm_broker.resolve(sid, bool(data.get("allow")))
                return self._json(200, {"ok": ok})

            # criar conversa
            if self.path == "/api/sessions":
                ag.episodic.nova_conversa(data.get("title", ""))
                return self._json(200, {"active": ag.episodic.active_id,
                                        "sessions": ag.episodic.listar_conversas()})

            # ativar conversa
            if self.path.startswith("/api/sessions/") and self.path.endswith("/activate"):
                sid = self.path[len("/api/sessions/"):-len("/activate")]
                ok = ag.episodic.retomar_conversa(sid)
                return self._json(200 if ok else 404, {"active": ag.episodic.active_id})

            # renomear conversa
            if self.path.startswith("/api/sessions/") and self.path.endswith("/rename"):
                sid = self.path[len("/api/sessions/"):-len("/rename")]
                ok = ag.episodic.renomear_conversa(sid, data.get("title", ""))
                return self._json(200 if ok else 404, {"ok": ok})

            return self._json(404, {"error": "não encontrado"})
        except Exception as e:
            return self._json(500, {"error": str(e)})

    # ----------------------------- DELETE ---------------------------- #
    def do_DELETE(self):
        if self.path.startswith("/api/sessions/"):
            sid = self.path[len("/api/sessions/"):]
            ok, motivo = get_agent().episodic.apagar_conversa(sid)
            return self._json(200 if ok else 400,
                              {"ok": ok, "motivo": motivo,
                               "active": get_agent().episodic.active_id})
        return self._json(404, {"error": "não encontrado"})

    def log_message(self, fmt, *args):  # silencia log padrão
        pass


def main():
    print(f"\n  YVAKOR online → http://localhost:{PORT}\n  (Ctrl+C para sair)\n")
    # Inicia a auto-manutenção em segundo plano (consolida conhecimento +
    # verifica atualização de código, conforme settings.yaml → maintenance).
    try:
        get_agent().maintenance.start_background()
    except Exception as e:
        print(f"  [aviso] auto-manutenção não iniciou: {e}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
