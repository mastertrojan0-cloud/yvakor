"""
YVAKOR — Servidor da interface 3D
Stdlib pura (http.server): roda em qualquer computador, sem dependências web.

Uso:  python -m yvakor.server   →  http://localhost:7777

Endpoints:
  GET    /                          → interface 3D (interface/index.html)
  GET    /api/status                → estado do agente (inclui navegador)
  POST   /api/chat                  → {"message","session?"} → {"answer","session"}
  POST   /api/confirm               → {"session","allow"} responde a ação protegida
  GET    /api/sessions              → lista conversas + ativa
  POST   /api/sessions              → cria conversa {"title?"}
  GET    /api/sessions/<id>/messages→ histórico da conversa
  POST   /api/sessions/<id>/activate→ retoma conversa
  POST   /api/sessions/<id>/rename  → renomeia {"title"}
  DELETE /api/sessions/<id>         → apaga conversa
  GET    /api/progress?session=     → passos ao vivo + confirmação pendente
  GET    /api/cowork                → tarefas em segundo plano (lista)
  POST   /api/cowork                → {"description"} dispara tarefa
  GET    /api/cowork/<id>           → detalhe (passos, resultado, artefatos)
  GET    /api/cowork/<id>/artifacts → arquivos gerados pela tarefa
  POST   /api/cowork/<id>/cancel    → pede cancelamento
  GET    /api/browser               → estado do navegador controlado
  GET    /api/browser/screenshot    → frame JPEG ao vivo (painel da interface)
  POST   /api/browser/action        → {"action":"open|goto|close|visible|headless"}
  GET    /api/connectors            → lista de conectores + status
  POST   /api/connectors/<id>/connect    → {"fields": {...}} salva login
  POST   /api/connectors/<id>/disconnect → remove credenciais
  POST   /api/connectors/<id>/authorize  → inicia OAuth (devolve auth_url)
  GET    /api/oauth/callback             → redirect do Google (troca o code)
"""
from __future__ import annotations
import os
import sys
import json
import secrets
import subprocess
from yvakor import proc as _ywproc
import threading
import time
import urllib.parse
from datetime import datetime

# Console Windows usa cp1252 por padrão e quebra com emojis/acentos.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from yvakor.orchestrator import Orchestrator
from yvakor.health import coletar as _saude_health

import logging
from logging.handlers import RotatingFileHandler


def _configurar_log() -> None:
    pasta = Path(__file__).resolve().parent.parent / "data" / "logs"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    logger = logging.getLogger("yvakor")
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    arq = RotatingFileHandler(pasta / "yvakor.log", maxBytes=5 * 1024 * 1024,
                              backupCount=5, encoding="utf-8")
    arq.setFormatter(fmt)
    logger.addHandler(arq)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)
    logger.info("YVAKOR — log rotativo ativo")


_configurar_log()


def _html_camera(ip: str) -> str:
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>YVAKOR · Câmera {ip}</title>
<style>
:root{{--agua:#3fbfae;--sol:#d9a441;--fundo:#070d12}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(120% 90% at 50% 0,#0d1a22,#050a0e 70%);color:#dceaf0;font-family:"Segoe UI",system-ui,sans-serif}}
header{{display:flex;gap:12px;align-items:center;padding:14px 20px;border-bottom:1px solid #1b2b35;background:#08121a}}
header b{{font-size:17px;letter-spacing:.5px}} .led{{width:10px;height:10px;border-radius:50%;background:var(--agua);box-shadow:0 0 10px var(--agua)}}
header .ip{{color:#7f96a3;font-size:12px}} header .dir{{margin-left:auto;color:#7f96a3;font-size:12px}}
main{{display:grid;grid-template-columns:1fr 320px;gap:16px;padding:16px;height:calc(100vh - 58px)}}
.tela{{position:relative;background:#000;border:1px solid #1b2b35;border-radius:12px;overflow:hidden;display:flex;align-items:center;justify-content:center;min-height:300px}}
.tela img,.tela video{{width:100%;height:100%;object-fit:contain;background:#000}}
.tela .aviso{{position:absolute;bottom:10px;left:12px;font-size:12px;color:#93a9b5;background:#000a;padding:4px 8px;border-radius:6px}}
aside{{background:#08121a;border:1px solid #1b2b35;border-radius:12px;padding:12px;overflow:auto}}
aside h3{{margin:4px 0 10px;font-size:13px;color:var(--sol);text-transform:uppercase;letter-spacing:.08em}}
.item{{width:100%;text-align:left;background:#0c1a22;border:1px solid #1b2b35;color:#cfe0e8;border-radius:8px;padding:8px 10px;margin-bottom:6px;cursor:pointer;font-size:12px}}
.item:hover{{border-color:var(--agua);transform:translateX(2px)}} .item small{{display:block;color:#7f96a3}}
.vazio{{color:#7f96a3;font-size:12px}}
</style>
<header><span class="led"></span><b>Câmera</b><span class="ip">{ip}</span>
<span class="dir" id="st">monitor YVAKOR</span></header>
<main>
  <div class="tela">
    <img id="live" alt="ao vivo (espelho Yoosee)" src="/camera/{ip}/espelho.mjpg">
    <img id="snap" alt="" style="display:none" src="/api/rede/camera/{ip}/snapshot?t=">
    <video id="player" controls playsinline style="display:none"></video>
    <span class="aviso" id="aviso">ao vivo · espelho do app Yoosee</span>
  </div>
  <aside><h3>Gravações</h3><div id="lista"><div class="vazio">carregando…</div></div></aside>
</main>
<script>
const IP = {ip!r};
const snap = document.getElementById('snap'), player = document.getElementById('player');
const live = document.getElementById('live');
live.onerror = () => {{ live.style.display = 'none'; snap.style.display = 'block';
  aviso.textContent = 'espelho indisponível — última imagem'; }};
const lista = document.getElementById('lista'), aviso = document.getElementById('aviso');
function tocar(nome) {{
  player.style.display = 'block'; snap.style.display = 'none';
  player.src = `/camera/${{IP}}/video?f=${{encodeURIComponent(nome)}}`;
  aviso.textContent = nome;
  player.play().catch(()=>{{}});
}}
async function carregar() {{
  try {{
    const r = await fetch(`/camera/${{IP}}/gravacoes`);
    const j = await r.json();
    if (!j.itens || !j.itens.length) {{ lista.innerHTML = '<div class="vazio">nenhuma gravação encontrada</div>'; return; }}
    lista.innerHTML = '';
    j.itens.forEach(g => {{
      const b = document.createElement('button');
      b.className = 'item';
      b.innerHTML = `<b>${{g.quando}}</b><small>${{g.mb}} MB · ${{g.nome}}</small>`;
      b.onclick = () => tocar(g.nome);
      lista.appendChild(b);
    }});
  }} catch (e) {{ lista.innerHTML = '<div class="vazio">falha ao listar</div>'; }}
}}
setInterval(() => {{ if (snap.style.display !== 'none') snap.src = `/api/rede/camera/${{IP}}/snapshot?t=${{Date.now()}}`; }}, 5000);
carregar();
</script></html>"""

ROOT = Path(__file__).resolve().parent.parent
INTERFACE = ROOT / "interface"
PORT = 7777
HOST = os.environ.get("YVAKOR_HOST", "127.0.0.1")

def _carregar_versao() -> dict:
    try:
        return json.loads((ROOT / "config" / "version.json").read_text(
            encoding="utf-8"))
    except Exception:
        return {"version": "0.0.0", "build": "dev"}


_VERSAO = _carregar_versao()
VERSAO = str(_VERSAO.get("version") or "0.0.0")
BUILD = f"v{VERSAO} · edge+chrome"   # selo p/ confirmar build no ar

_agent: Orchestrator | None = None
_lock_handle = None
_lock = threading.Lock()


# --------------------------------------------------------------------- #
# Segurança do servidor local
# --------------------------------------------------------------------- #
# Token por execução: exigido (header X-YVAKOR-Token) em TODAS as rotas que
# causam efeito (POST/DELETE). Como é um header customizado, o navegador força
# um preflight CORS que só aprovamos para origens confiáveis — logo um site
# qualquer aberto no navegador NÃO consegue disparar /api/chat & cia. O valor
# ainda é validado para clientes não-navegador. O token é gravado em
# data/.server_token (0600) para os clientes locais (GUI, voz) e injetado no
# index.html para a interface web.
def _gerar_token() -> str:
    tok = os.environ.get("YVAKOR_TOKEN") or secrets.token_urlsafe(32)
    try:
        pasta = ROOT / "data"
        pasta.mkdir(parents=True, exist_ok=True)
        arq = pasta / ".server_token"
        arq.write_text(tok, encoding="utf-8")
        try:
            os.chmod(arq, 0o600)
        except Exception:
            pass
    except Exception:
        pass
    return tok


TOKEN = _gerar_token()

# Extensão do YVAKOR: se YVAKOR_EXT_ID for definido, só essa extensão é aceita
# no CORS; sem ele, mantém compatibilidade aceitando extensões instaladas
# (confiança de nível de extensão — bem acima de "qualquer site").
_EXT_ID = os.environ.get("YVAKOR_EXT_ID", "").strip()
# Hosts aceitos (anti DNS-rebinding): só loopback na porta do servidor.
HOSTS_OK = {f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"{HOST}:{PORT}"}
ORIGENS_OK = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}


def _origem_permitida(origem: str) -> bool:
    if not origem:
        return False
    if origem in ORIGENS_OK:
        return True
    if origem.startswith("chrome-extension://"):
        return (not _EXT_ID) or origem == f"chrome-extension://{_EXT_ID}"
    return False


# Script injetado no index.html: publica o token e embrulha window.fetch para
# anexar X-YVAKOR-Token (e Content-Type JSON) em toda chamada a /api/*. Assim
# as ~28 chamadas existentes passam a autenticar sem precisar editar cada uma.
_FETCH_SHIM = """<script>
window.__YVAKOR_TOKEN__=%s;
(function(){var _f=window.fetch;window.fetch=function(u,o){o=o||{};try{
var p=(typeof u==='string')?u:(u&&u.url)||'';
if(p.indexOf('/api/')===0||p.indexOf(location.origin+'/api/')===0){
var h=new Headers(o.headers||((typeof u!=='string'&&u.headers)||{}));
h.set('X-YVAKOR-Token',window.__YVAKOR_TOKEN__);
if((o.method||'GET').toUpperCase()!=='GET'&&o.body&&!h.has('Content-Type'))
h.set('Content-Type','application/json');
o.headers=h;}}catch(e){}return _f(u,o);};})();
</script>"""


def _injetar_token(html: bytes) -> bytes:
    shim = (_FETCH_SHIM % json.dumps(TOKEN)).encode("utf-8")
    low = html.lower()
    pos = low.find(b"</head>")
    if pos == -1:
        pos = low.find(b"<body")
    if pos == -1:
        return shim + html
    return html[:pos] + shim + html[pos:]


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
        origem = self.headers.get("Origin", "")
        if _origem_permitida(origem):
            self.send_header("Access-Control-Allow-Origin", origem)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-YVAKOR-Token")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        origem = self.headers.get("Origin", "")
        if _origem_permitida(origem):
            self.send_header("Access-Control-Allow-Origin", origem)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-YVAKOR-Token")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    # ------------------------- autorização -------------------------- #
    def _host_ok(self) -> bool:
        """Anti DNS-rebinding: só aceita Host loopback na porta do servidor."""
        host = (self.headers.get("Host") or "").strip().lower()
        return host in HOSTS_OK

    def _token_ok(self) -> bool:
        enviado = self.headers.get("X-YVAKOR-Token", "")
        return bool(enviado) and secrets.compare_digest(enviado, TOKEN)

    def _autorizar_efeito(self) -> bool:
        """Barra rotas de efeito (POST/DELETE) sem Host válido ou sem token.
        Responde 403 e retorna False quando negado."""
        if not self._host_ok():
            self.close_connection = True
            self._json(403, {"error": "host não autorizado"})
            return False
        if not self._token_ok():
            self.close_connection = True
            self._json(403, {"error": "token ausente ou inválido"})
            return False
        return True

    def _json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    # ------------------------------ GET ------------------------------ #
    def _camera_janela(self):
        from pathlib import Path as _P
        from urllib.parse import parse_qs, unquote
        limpo = self.path.split("?", 1)[0]
        partes = [p for p in limpo.split("/") if p]
        if len(partes) < 2:
            return self._json(404, {"error": "câmera não informada"})
        ip = unquote(partes[1])
        raiz = _P.home() / "ACM_DIGITAL" / "recordings" / ip
        extra = _P(__file__).resolve().parent.parent / "data" / "rede_gravacoes"
        if len(partes) == 2:
            corpo = _html_camera(ip).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        acao = partes[2]
        if acao == "gravacoes":
            itens = []
            for base in (raiz, extra):
                if not base.is_dir():
                    continue
                for arq in base.rglob("*"):
                    if arq.suffix.lower() not in (".mkv", ".mp4", ".avi", ".mov"):
                        continue
                    try:
                        rel = arq.relative_to(raiz if base == raiz else extra)
                        itens.append({"nome": str(rel).replace("\\", "/"),
                                      "mb": round(arq.stat().st_size / 1048576, 1),
                                      "quando": time.strftime(
                                          "%d/%m %H:%M",
                                          time.localtime(arq.stat().st_mtime))})
                    except Exception:
                        continue
            itens.sort(key=lambda x: x["quando"], reverse=True)
            return self._json(200, {"ok": True, "total": len(itens),
                                    "itens": itens[:120]})
        if acao.startswith("espelho"):
            return self._espelho_yoosee(ip)
        if acao == "video":
            nome = unquote((parse_qs(self.path.split("?", 1)[1]).get("f") or [""])[0])
            for base in (raiz, extra):
                alvo = (base / nome).resolve()
                try:
                    alvo.relative_to(base.resolve())
                except ValueError:
                    continue
                if alvo.is_file():
                    return self._servir_video(alvo)
            return self._json(404, {"error": "gravação não encontrada"})
        return self._json(404, {"error": "rota de câmera desconhecida"})

    def _espelho_yoosee(self, ip: str):
        """Espelha a janela do app Yoosee (que já tem vídeo ao vivo) em MJPEG."""
        import shutil as _shutil
        if not _shutil.which("ffmpeg"):
            return self._json(503, {"error": "ffmpeg não encontrado no PATH — "
                                    "instale o ffmpeg para espelhar a câmera"})
        proc = _ywproc.popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "gdigrab", "-framerate", "10", "-i", "title=Yoosee",
             "-vf", "scale=1280:-2", "-f", "image2pipe",
             "-vcodec", "mjpeg", "-q:v", "6", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        buffer = b""
        try:
            while True:
                bloco = proc.stdout.read(4096)
                if not bloco:
                    break
                buffer += bloco
                while True:
                    a = buffer.find(b"\xff\xd8")
                    b = buffer.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                    if a < 0 or b < 0:
                        break
                    jpg = buffer[a:b + 2]
                    buffer = buffer[b + 2:]
                    try:
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(jpg)).encode()
                            + b"\r\n\r\n" + jpg + b"\r\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                if len(buffer) > 4_000_000:
                    buffer = buffer[-1_000_000:]
        finally:
            try:
                proc.terminate()
            except Exception:
                pass

    def _servir_video(self, arq):
        tamanho = arq.stat().st_size
        inicio, fim = 0, tamanho - 1
        faixa = self.headers.get("Range", "")
        if faixa.startswith("bytes="):
            try:
                a, b = faixa[6:].split("-", 1)
                inicio = int(a) if a else 0
                fim = int(b) if b else tamanho - 1
            except ValueError:
                inicio, fim = 0, tamanho - 1
            fim = min(fim, tamanho - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tamanho}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "video/x-matroska")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - inicio + 1))
        self.end_headers()
        with open(arq, "rb") as f:
            f.seek(inicio)
            restante = fim - inicio + 1
            while restante > 0:
                bloco = f.read(min(65536, restante))
                if not bloco:
                    break
                self.wfile.write(bloco)
                restante -= len(bloco)

    def do_GET(self):
        try:
            return self._do_get()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            self._erro_interno("GET", exc)

    def _erro_interno(self, metodo: str, exc: Exception):
        try:
            logging.getLogger("yvakor.http").exception(
                "falha não tratada em %s: %s", metodo, exc)
        except Exception:
            pass
        try:
            self._json(500, {"error": "falha interna",
                             "detalhe": str(exc)[:300]})
        except Exception:
            pass

    def _do_get(self):
        if self.path.startswith("/camera/"):
            return self._camera_janela()
        if self.path in ("/dispositivos", "/dispositivos/"):
            html = (INTERFACE / "dispositivos.html").read_bytes()
            return self._send(200, _injetar_token(html),
                              "text/html; charset=utf-8")
        if self.path in ("/galeria", "/galeria/"):
            html = (INTERFACE / "galeria.html").read_bytes()
            return self._send(200, _injetar_token(html),
                              "text/html; charset=utf-8")
        if self.path.startswith("/api/galeria"):
            import mimetypes
            itens = []
            for tipo, base in (("graficos", ROOT / "data" / "graficos"),
                               ("imagens", ROOT / "data" / "imagens")):
                if not base.is_dir():
                    continue
                for arq in base.iterdir():
                    if arq.suffix.lower() not in (".png", ".jpg", ".jpeg", ".svg"):
                        continue
                    itens.append({"tipo": tipo, "nome": arq.name,
                                  "url": f"/midia/{tipo}/{urllib.parse.quote(arq.name)}",
                                  "kb": round(arq.stat().st_size / 1024, 1),
                                  "quando": time.strftime(
                                      "%d/%m %H:%M",
                                      time.localtime(arq.stat().st_mtime))})
            itens.sort(key=lambda x: x["quando"], reverse=True)
            return self._json(200, {"ok": True, "total": len(itens), "itens": itens})
        if self.path.startswith("/api/galeria/zip"):
            import io
            import zipfile
            tipo = (urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query).get("tipo") or ["graficos"])[0]
            base = ROOT / "data" / tipo if tipo in ("graficos", "imagens") else None
            if base is None or not base.is_dir():
                return self._json(404, {"error": "tipo inválido"})
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for arq in base.iterdir():
                    if arq.is_file():
                        z.write(arq, arcname=arq.name)
            return self._send(200, buf.getvalue(), "application/zip")
        if self.path.startswith("/projetos/"):
            import mimetypes
            partes = urllib.parse.unquote(self.path).split("?")[0].split("/")
            # /projetos/<slug>[/arquivo]
            if len(partes) < 3:
                return self._json(404, {"error": "projeto inválido"})
            base = ROOT / "data" / "projetos"
            alvo = (base / partes[2] / ("/".join(partes[3:]) or "index.html")).resolve()
            try:
                alvo.relative_to(base.resolve())
            except ValueError:
                return self._json(404, {"error": "caminho inválido"})
            if alvo.is_dir():
                alvo = alvo / "index.html"
            if not alvo.is_file():
                return self._json(404, {"error": "não encontrado"})
            mime = mimetypes.guess_type(str(alvo))[0] or "application/octet-stream"
            return self._send(200, alvo.read_bytes(), mime)

        if self.path.startswith("/midia/"):
            import mimetypes
            partes = urllib.parse.unquote(self.path).split("/")
            if len(partes) != 4 or partes[2] not in ("graficos", "imagens"):
                return self._json(404, {"error": "mídia inválida"})
            base = ROOT / "data" / partes[2]
            alvo = (base / partes[3]).resolve()
            try:
                alvo.relative_to(base.resolve())
            except ValueError:
                return self._json(404, {"error": "caminho inválido"})
            if not alvo.is_file():
                return self._json(404, {"error": "não encontrado"})
            mime = mimetypes.guess_type(str(alvo))[0] or "application/octet-stream"
            return self._send(200, alvo.read_bytes(), mime)
        if self.path.startswith("/api/rede/dispositivo"):
            ag = get_agent()
            if ag.rede is None:
                return self._json(503, {"ok": False, "erro": "rede indisponível"})
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            alvo = (q.get("alvo") or [""])[0]
            dev = ag.rede.registro.obter(alvo)
            if not dev:
                return self._json(404, {"ok": False, "erro": "não encontrado"})
            return self._json(200, {"ok": True, "dispositivo": dev,
                                    "grupos": ag.rede.registro.grupos()})
        if self.path == "/api/rede/monitor":
            ag = get_agent()
            m = getattr(ag, "monitor_rede", None)
            return self._json(200, {"ok": True,
                                    **(m.status() if m else {"ativo": False})})
        if self.path.startswith("/api/notificacoes"):
            ag = get_agent()
            n = getattr(ag, "notificador", None)
            if n is None:
                return self._json(200, {"ok": False, "ativo": False})
            return self._json(200, {"ok": True, **n.status(),
                                    "recentes": n.recentes(30)})

        if self.path == "/api/version":
            return self._json(200, {
                "version": VERSAO,
                "build": _VERSAO.get("build", "dev"),
                "rotulo": BUILD,
                "extension": {
                    "path": str(ROOT / "chrome-extension"),
                    "synced": (ROOT / "chrome-extension" / "build.json").is_file()
                }})

        if self.path == "/api/ping":
            import os as _os
            return self._json(200, {"ok": True, "pid": _os.getpid(),
                                    "ts": time.time()})
        # Bootstrap do token para clientes de navegador (a extensão). O CORS
        # só deixa origens confiáveis LEREM esta resposta; um site qualquer
        # consegue disparar a requisição, mas não consegue ler o token.
        if self.path == "/api/token":
            if not self._host_ok():
                self.close_connection = True
                return self._json(403, {"error": "host não autorizado"})
            return self._json(200, {"token": TOKEN})
        if self.path.startswith("/api/health"):
            return self._json(200, _saude_health(get_agent(),
                                                forcar="refresh=1" in self.path,
                                                build=BUILD))
        if self.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")

        # Artefatos gerados (relatórios, planilhas, fotos, gráficos)
        if self.path.startswith("/artefatos/"):
            import mimetypes
            rel = urllib.parse.unquote(self.path.split("?")[0])[len("/artefatos/"):]
            base = (ROOT / "data" / "artefatos").resolve()
            alvo = (base / rel).resolve()
            try:
                alvo.relative_to(base)
            except ValueError:
                return self._json(404, {"error": "caminho inválido"})
            if not alvo.is_file():
                return self._json(404, {"error": "artefato não encontrado"})
            mime = mimetypes.guess_type(str(alvo))[0] or "application/octet-stream"
            corpo = alvo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(corpo)))
            if not mime.startswith("image/"):
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{alvo.name}"')
            self.end_headers()
            self.wfile.write(corpo)
            return

        # Fontes locais da interface (sem depender do Google Fonts)
        if self.path.startswith("/fonts/"):
            import mimetypes
            nome = urllib.parse.unquote(self.path.split("?")[0])[len("/fonts/"):]
            if "/" in nome or "\\" in nome or not nome.lower().endswith(".ttf"):
                return self._json(404, {"error": "fonte inválida"})
            alvo = INTERFACE / "fonts" / nome
            if not alvo.is_file():
                return self._json(404, {"error": "fonte não encontrada"})
            mime = mimetypes.guess_type(str(alvo))[0] or "font/ttf"
            corpo = alvo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "public, max-age=31536000")
            self.end_headers()
            self.wfile.write(corpo)
            return

        if self.path in ("/", "/index.html"):
            html = (INTERFACE / "index.html").read_bytes()
            return self._send(200, _injetar_token(html),
                              "text/html; charset=utf-8")

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
                "memoria": {
                    "episodios": episodes,
                    "fatos": agent.semantic.contar() if agent.semantic else 0,
                    "notas": (agent.cerebro.status()["notas"]
                              if agent.cerebro else 0),
                    "vault": str(agent.cerebro.dir) if agent.cerebro else "",
                },
                "browser": (agent.navegadores.status() if agent.navegadores else
                            {"aberto": False, "disponivel": False}),
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

        if self.path.startswith("/api/sessions/") and self.path.endswith("/export"):
            sid = self.path[len("/api/sessions/"):-len("/export")]
            msgs = get_agent().episodic.mensagens_da_conversa(sid)
            agora = datetime.now().strftime("%Y-%m-%d %H:%M")
            linhas = ["# Histórico YVAKOR", "", f"*Exportado em {agora}*", "",
                      f"*Sessão: {sid}*", ""]
            for m in msgs:
                rotulo = "Você" if m.get("role") == "user" else "YVAKOR"
                linhas.append(f"## {rotulo}\n\n{m.get('content') or ''}\n")
            pasta = ROOT / "data" / "exportados"
            pasta.mkdir(parents=True, exist_ok=True)
            alvo = pasta / f"historico_{sid}.md"
            alvo.write_text("\n".join(linhas), encoding="utf-8")
            return self._json(200, {"ok": True, "arquivo": str(alvo),
                                    "mensagens": len(msgs)})

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

        # ---- MCP: servidores e ferramentas conectadas ----
        if self.path == "/api/mcp":
            ag = get_agent()
            m = getattr(ag, "mcp", None)
            if m is None:
                return self._json(200, {"ok": False, "servidores": {}})
            return self._json(200, {
                "ok": True,
                "config": str(m.cfg_path),
                "servidores": {
                    n: {"vivo": bool(c.proc and c.proc.poll() is None),
                        "ferramentas": [t.get("name") for t in c.tools],
                        "erro": c.erro}
                    for n, c in m.clientes.items()}})

        # ---- Avaliações automáticas de qualidade ----
        if self.path == "/api/avaliacoes":
            arq = ROOT / "data" / "avaliacoes.jsonl"
            itens = []
            try:
                linhas = arq.read_text(encoding="utf-8").splitlines()[-30:]
                itens = [json.loads(l) for l in linhas if l.strip()]
            except Exception:
                pass
            return self._json(200, {"ok": True, "avaliacoes": itens})

        # ---- Agenda / tarefas agendadas ----
        if self.path == "/api/agenda":
            ag = get_agent()
            return self._json(200, {"ok": True,
                                    "tarefas": ag.agenda.listar()})

        # ---- Cowork (tarefas autônomas em segundo plano) ----
        if self.path == "/api/cowork":
            ag = get_agent()
            return self._json(200, {"tasks": ag.cowork.list(50),
                                    "texto": ag.cowork.status(),
                                    "pendentes": ag.cowork.pending_count()})

        if self.path.startswith("/api/cowork/"):
            resto = self.path[len("/api/cowork/"):]
            ag = get_agent()
            if resto.endswith("/artifacts"):
                tid = resto[:-len("/artifacts")]
                t = ag.cowork.get(tid)
                if not t:
                    return self._json(404, {"error": "tarefa não encontrada"})
                return self._json(200, {"id": tid,
                                        "artefatos": t.get("artefatos", [])})
            tarefa = ag.cowork.get(resto)
            if tarefa is None:
                return self._json(404, {"error": "tarefa não encontrada"})
            return self._json(200, tarefa)

        # ---- Rede local (dispositivos) ----
        if self.path == "/api/rede":
            ag = get_agent()
            if ag.rede is None:
                return self._json(200, {"disponivel": False,
                                        "erro": "módulo de rede indisponível"})
            return self._json(200, {
                "disponivel": True,
                "dispositivos": ag.rede.registro.listar(),
                "escopo": ag.rede.escopo.resumo(),
                "resumo": ag.rede.resumo(),
            })

        # Foto de uma câmera (o painel usa como <img>)
        rota_cam = self.path.split("?", 1)[0]
        if rota_cam.startswith("/api/rede/camera/") and rota_cam.endswith("/url"):
            ag = get_agent()
            if ag.rede is None:
                return self._json(503, {"error": "rede indisponível"})
            alvo = rota_cam[len("/api/rede/camera/"):-len("/url")]
            try:
                return self._json(200, ag.rede.cameras.url_ao_vivo(
                    urllib.parse.unquote(alvo)))
            except Exception as e:
                return self._json(502, {"error": str(e)})
        if rota_cam.startswith("/api/rede/camera/") and rota_cam.endswith("/snapshot"):
            ag = get_agent()
            if ag.rede is None:
                return self._json(503, {"error": "rede indisponível"})
            alvo = rota_cam[len("/api/rede/camera/"):-len("/snapshot")]
            try:
                r = ag.rede.cameras.snapshot(urllib.parse.unquote(alvo))
            except Exception as e:
                return self._json(502, {"error": str(e)})
            if not r.get("ok"):
                return self._json(502, r)
            try:
                dados = Path(r["arquivo"]).read_bytes()
            except Exception as e:
                return self._json(500, {"error": str(e)})
            return self._send(200, dados, "image/jpeg")

        # ---- Cérebro (vault markdown + índice FTS) ----
        if self.path.startswith("/api/cerebro"):
            ag = get_agent()
            if ag.cerebro is None:
                return self._json(200, {"disponivel": False,
                                        "erro": "cérebro indisponível"})
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            if self.path.startswith("/api/cerebro/buscar"):
                termo = (q.get("q", [""])[0] or "").strip()
                try:
                    limite = int(q.get("limite", ["10"])[0] or 10)
                except ValueError:
                    limite = 10
                return self._json(200, {"ok": True,
                                        "resultados": ag.cerebro.buscar(termo, limite)})
            if self.path.startswith("/api/cerebro/nota"):
                nome = (q.get("nome", [""])[0] or "").strip()
                n = ag.cerebro.nota(nome)
                return (self._json(200, n) if n else
                        self._json(404, {"error": "nota não encontrada"}))
            if self.path.startswith("/api/cerebro/grafo"):
                nome = (q.get("nome", [""])[0] or "").strip()
                try:
                    prof = int(q.get("profundidade", ["1"])[0] or 1)
                except ValueError:
                    prof = 1
                return self._json(200, {"ok": True,
                                        **ag.cerebro.grafo(nome, prof)})
            estado = ag.cerebro.status()
            estado["disponivel"] = True
            return self._json(200, estado)

        if self.path.startswith("/api/telemetria"):
            ag = get_agent()
            try:
                return self._json(200, {
                    "resumo": ag.telemetria.resumo(7),
                    "recentes": ag.telemetria.recentes(20)})
            except Exception as e:
                return self._json(500, {"error": str(e)})

        # ---- Ponte com a janela do Chrome da extensão ----
        if self.path.startswith("/api/ext/comandos"):
            from yvakor.extensao_bridge import PONTE
            from urllib.parse import parse_qs, urlparse
            tipo = (parse_qs(urlparse(self.path).query).get("tipo") or [None])[0]
            return self._json(200, {"ok": True,
                                    "comandos": PONTE.pendentes(tipo)})
        if self.path == "/api/ext/status":
            from yvakor.extensao_bridge import PONTE
            return self._json(200, {"ok": True, **PONTE.status()})

        # ---- Voz ----
        if self.path == "/api/voz/ativo":
            ativo = True
            try:
                pref = json.loads((ROOT / "data" / "preferencias.json").read_text(
                    encoding="utf-8"))
                ativo = bool(pref.get("voz_ativa", True))
            except Exception:
                pass
            return self._json(200, {"ok": True, "ativo": ativo})

        if self.path == "/api/voz/microfone":
            ag = get_agent()
            if ag.voz is None:
                return self._json(503, {"ok": False, "erro": "voz indisponível"})
            return self._json(200, ag.voz.stt.testar_microfone())

        if self.path == "/api/voz/status":
            ag = get_agent()
            if ag.voz is None:
                return self._json(200, {"disponivel": False})
            st = ag.voz.stt.status()
            st.update({"disponivel": True, "vozes": ag.voz.tts.vozes(),
                       "palavra_ativacao": ag.voz.palavra,
                       "sessao": ag.voz.sessao.estado(),
                       "tts": ag.voz.tts.estatisticas()})
            return self._json(200, st)

        if self.path == "/api/voz/sessao":
            ag = get_agent()
            if ag.voz is None:
                return self._json(503, {"error": "voz indisponível"})
            return self._json(200, {"ok": True, **ag.voz.sessao.estado()})

        # ---- Navegador ao vivo (painel da interface) ----
        if self.path == "/api/browser/google":
            ag = get_agent()
            if ag.navegadores is None:
                return self._json(503, {"error": "navegador indisponível"})
            sess = ag.navegadores.sessao(ag.navegadores.motor(None))
            return self._json(200, {"ok": True, **sess.google_status()})

        if self.path == "/api/browser":
            ag = get_agent()
            if ag.navegadores is None:
                return self._json(200, {
                    "disponivel": False,
                    "erro": "Playwright não instalado — rode: pip install playwright"})
            estado = ag.navegadores.status()
            estado["disponivel"] = True
            estado["resumo"] = ag.navegadores.resumo()
            return self._json(200, estado)

        if self.path.startswith("/api/browser/screenshot"):
            from urllib.parse import urlparse, parse_qs
            ag = get_agent()
            if ag.navegadores is None:
                return self._json(503, {"error": "navegador indisponível"})
            q = parse_qs(urlparse(self.path).query)
            motor = (q.get("motor", [None])[0]) or ag.navegadores.padrao
            sess = ag.navegadores.sessao(motor)
            if not sess.is_open():
                return self._json(409, {"error": "navegador fechado"})
            try:
                with sess.trilho:
                    sess.selecionar_aba("principal")
                    frame = sess.live_frame()
            except Exception as e:
                return self._json(500, {"error": str(e)})
            return self._send(200, frame, "image/jpeg")

        rota_up = self.path.split("?", 1)[0]
        if rota_up.startswith("/api/uploads/"):
            import mimetypes
            partes = urllib.parse.unquote(rota_up).split("/")
            if len(partes) != 5:
                return self._json(404, {"error": "upload inválido"})
            base = (ROOT / "data" / "uploads" / partes[3]).resolve()
            alvo = (base / partes[4]).resolve()
            try:
                alvo.relative_to(base)
            except ValueError:
                return self._json(404, {"error": "caminho inválido"})
            if not alvo.is_file():
                return self._json(404, {"error": "arquivo não encontrado"})
            mime = mimetypes.guess_type(str(alvo))[0] or "application/octet-stream"
            return self._send(200, alvo.read_bytes(), mime)

        return self._json(404, {"error": "não encontrado"})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        # Clientes Windows (PowerShell, curl antigo) às vezes mandam cp1252
        # mesmo dizendo application/json; não vale derrubar a requisição.
        try:
            texto = raw.decode("utf-8-sig")   # tolera BOM de clientes Windows
        except UnicodeDecodeError:
            texto = raw.decode("cp1252", errors="replace")
        return json.loads(texto)

    # ------------------------------ POST ----------------------------- #
    def do_POST(self):
        try:
            return self._do_post()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            self._erro_interno("POST", exc)

    def _do_post(self):
        if not self._autorizar_efeito():
            return
        # Só JSON em rotas de efeito: rejeita os content-types "CORS-safelisted"
        # (text/plain, form-urlencoded, multipart) que o truque de CSRF por
        # requisição simples usaria — além do token já exigido acima.
        if int(self.headers.get("Content-Length", 0) or 0):
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and ctype != "application/json":
                self.close_connection = True
                return self._json(400, {"error": "content-type não suportado"})
        ag = get_agent()
        try:
            data = self._body()

            if self.path == "/api/upload":
                import base64 as _b64
                import re as _re
                import uuid as _uuid
                nome = str(data.get("nome") or "arquivo")
                bruto = str(data.get("dados_b64") or "")
                if not bruto:
                    return self._json(400, {"error": "arquivo vazio"})
                if len(bruto) > 110_000_000:
                    return self._json(413, {"error": "arquivo grande demais"})
                seguro = _re.sub(r"[^A-Za-z0-9._-]+", "_", nome)[:120]
                if not seguro:
                    seguro = "arquivo"
                ext = Path(seguro).suffix.lower()
                imagens = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
                videos = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
                documentos = {".pdf", ".txt", ".md"}
                if ext not in imagens | videos | documentos:
                    return self._json(400, {"error": "formato não suportado"})
                try:
                    conteudo = _b64.b64decode(bruto, validate=False)
                except Exception:
                    return self._json(400, {"error": "base64 inválido"})
                pasta = ROOT / "data" / "uploads" / _uuid.uuid4().hex[:12]
                pasta.mkdir(parents=True, exist_ok=True)
                destino = pasta / seguro
                destino.write_bytes(conteudo)
                if ext in imagens:
                    tipo = "imagem"
                elif ext in videos:
                    tipo = "video"
                else:
                    tipo = "documento"
                texto = ""
                if tipo in ("imagem", "documento"):
                    try:
                        from yvakor.documentos import extrair_texto
                        texto = extrair_texto(destino)[:6000]
                    except Exception:
                        texto = ""
                uid = pasta.name
                return self._json(200, {
                    "ok": True, "nome": seguro, "tipo": tipo,
                    "caminho": str(destino),
                    "url": f"/api/uploads/{uid}/{seguro}",
                    "texto": texto,
                    "bytes": len(conteudo)})

            if self.path == "/api/chat":
                message = (data.get("message") or "").strip()
                if not message:
                    return self._json(400, {"error": "mensagem vazia"})
                privado = bool(data.get("private"))
                historico = None
                anexos = []
                for a in (data.get("attachments") or []):
                    if not isinstance(a, dict):
                        continue
                    caminho = str(a.get("caminho") or "")
                    try:
                        p = Path(caminho).resolve()
                        p.relative_to((ROOT / "data" / "uploads").resolve())
                    except Exception:
                        continue
                    if p.is_file():
                        texto_anexo = str(a.get("texto") or "")
                        if not texto_anexo and p.suffix.lower() in (
                                ".png", ".jpg", ".jpeg", ".webp", ".gif",
                                ".bmp", ".pdf", ".txt", ".md"):
                            try:
                                from yvakor.documentos import extrair_texto
                                texto_anexo = extrair_texto(p)[:6000]
                            except Exception:
                                texto_anexo = ""
                        anexos.append({"nome": a.get("nome") or p.name,
                                       "tipo": a.get("tipo") or "arquivo",
                                       "caminho": str(p),
                                       "texto": texto_anexo,
                                       "url": a.get("url") or ""})
                if privado:
                    sid_chat = data.get("session") or \
                        f"priv-{int(time.time() * 1000)}"
                    bruto = data.get("history") or []
                    if isinstance(bruto, list):
                        historico = []
                        for m in bruto[-12:]:
                            if not isinstance(m, dict) or not m.get("content"):
                                continue
                            papel = ("assistant" if m.get("role") == "assistant"
                                     else "user")
                            historico.append({"role": papel,
                                              "content": str(m["content"])[:2000]})
                else:
                    sid_chat = data.get("session") or ag.episodic.active_id
                    if data.get("session"):
                        ag.episodic.retomar_conversa(data["session"])
                marca = ROOT / "data" / "tarefa_em_andamento.json"
                if not privado:
                    try:
                        marca.write_text(json.dumps(
                            {"texto": message, "inicio": time.time()},
                            ensure_ascii=False), encoding="utf-8")
                    except OSError:
                        pass
                try:
                    pagina = str(data.get("page_context") or "").strip()
                    # OCR automático da tela, sem pedir print ao usuário.
                    imagem_b64 = str(data.get("page_image") or "")
                    if imagem_b64:
                        try:
                            import base64
                            import tempfile
                            bruto = imagem_b64.split(",", 1)[-1]
                            if len(bruto) <= 9_000_000:
                                with tempfile.NamedTemporaryFile(
                                        suffix=".jpg", delete=False) as tmp:
                                    tmp.write(base64.b64decode(bruto))
                                    caminho_img = Path(tmp.name)
                                try:
                                    from yvakor.documentos import extrair_texto
                                    ocr = extrair_texto(caminho_img)[:6000]
                                    if ocr.strip():
                                        pagina += ("\n\n## TEXTO VISÍVEL (OCR DA TELA)\n"
                                                   + ocr)
                                    from yvakor.visao import analisar as _visao
                                    import re as _re
                                    quer_visual = bool(_re.search(
                                        r"imagem|foto|visual|apar[eê]ncia|layout|"
                                        r"o que aparece|descrev|cor(es)?", message,
                                        _re.I)) and not bool(_re.search(
                                        r"texto|escrit|transcrev|ler", message, _re.I))
                                    if (not ocr.strip()) or quer_visual:
                                        v = _visao(caminho_img, message)
                                        if v.get("ok") and v.get("visao"):
                                            pagina += ("\n\n## ANÁLISE VISUAL DA TELA\n"
                                                       + str(v["visao"])[:4000])
                                finally:
                                    try:
                                        caminho_img.unlink()
                                    except OSError:
                                        pass
                        except Exception:
                            pass
                    bloco_anexos = ""
                    if anexos:
                        linhas = []
                        for a in anexos:
                            linhas.append(
                                f"- {a['tipo']}: {a['caminho']} (nome: {a['nome']})")
                            if a.get("texto"):
                                linhas.append("  texto extraído:\n  " +
                                              a["texto"][:2500].replace("\n", "\n  "))
                        bloco_anexos = ("## ANEXOS ENVIADOS PELO USUÁRIO\n"
                                        + "\n".join(linhas) +
                                        "\nOs arquivos acima estão no computador. Use "
                                        "ferramentas locais para inspecioná-los; não "
                                        "invente o conteúdo.")
                    if pagina or bloco_anexos:
                        from yvakor.contexto import preparar_contexto
                        ctx_anexos = preparar_contexto(
                            message, pagina, bloco_anexos,
                            max_chars=int(ag.settings.get("contexto", {}).get(
                                "max_caracteres", 9000)))
                        ctx_anexos += ("\nUse este conteúdo como contexto direto; "
                                       "se a resposta não estiver nele, diga.")
                    else:
                        ctx_anexos = None
                    resposta = ag.process(message, session_id=sid_chat,
                                          private=privado,
                                          history_override=historico,
                                          extra_context=ctx_anexos)
                except Exception as exc:
                    aviso = f"A tarefa parou por erro: {exc}"
                    if not privado:
                        try:
                            ag.episodic.log("conversa", message, aviso,
                                            session_id=sid_chat)
                        except Exception:
                            pass
                    try:
                        ag.notificador.emitir(aviso, "tarefa", 2)
                    except Exception:
                        pass
                    return self._json(200, {
                        "answer": aviso,
                        "session": sid_chat,
                        "private": privado,
                        "erro": str(exc)})
                finally:
                    if not privado:
                        try:
                            marca.unlink()
                        except OSError:
                            pass
                return self._json(200, {"answer": resposta,
                                        "session": sid_chat,
                                        "private": privado,
                                        "attachments": anexos,
                                        "artefatos": getattr(
                                            ag, "ultimos_artefatos", [])})

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

            if self.path == "/api/agenda":
                ag = get_agent()
                return self._json(200, ag.agenda.criar(
                    data.get("titulo") or data.get("texto") or "tarefa",
                    data.get("quando") or "",
                    data.get("texto") or data.get("titulo") or "",
                    data.get("tipo") or "chat",
                    data.get("repetir") or ""))

            # ---- Cowork: disparar / cancelar tarefa ----
            if self.path == "/api/cowork":
                desc = (data.get("description") or data.get("message") or "").strip()
                if not desc:
                    return self._json(400, {"error": "descrição vazia"})
                return self._json(200, {"task": ag.cowork.submit(desc)})

            if self.path.startswith("/api/cowork/") and self.path.endswith("/cancel"):
                tid = self.path[len("/api/cowork/"):-len("/cancel")]
                r = ag.cowork.cancel(tid)
                return self._json(200 if r.get("ok") else 400, r)

            if self.path.startswith("/api/cowork/") and self.path.endswith("/resume"):
                tid = self.path[len("/api/cowork/"):-len("/resume")]
                r = ag.cowork.retomar(tid)
                return self._json(200 if r.get("ok") else 400, r)

            # ---- Cérebro: sincronizar vault ----
            if self.path == "/api/cerebro/sincronizar":
                if ag.cerebro is None:
                    return self._json(503, {"error": "cérebro indisponível"})
                return self._json(200, ag.cerebro.sincronizar())

            # ---- Galeria: apagar ----
            if self.path == "/api/galeria/apagar":
                ag = get_agent()
                tipo = str(data.get("tipo") or "")
                nome = str(data.get("nome") or "")
                base = ROOT / "data" / tipo if tipo in ("graficos", "imagens") else None
                if base is None:
                    return self._json(400, {"ok": False, "erro": "tipo inválido"})
                alvo = (base / nome).resolve()
                try:
                    alvo.relative_to(base.resolve())
                except ValueError:
                    return self._json(400, {"ok": False, "erro": "caminho inválido"})
                if alvo.is_file():
                    alvo.unlink()
                    return self._json(200, {"ok": True, "apagado": nome})
                return self._json(404, {"ok": False, "erro": "não encontrado"})

            # ---- Rede: dispositivo (painel) ----
            if self.path == "/api/rede/dispositivo":
                ag = get_agent()
                if ag.rede is None:
                    return self._json(503, {"ok": False, "erro": "rede indisponível"})
                dados_rede = data
                acao = (dados_rede.get("acao") or "").lower()
                alvo = str(dados_rede.get("alvo") or "")
                if acao == "gerenciar":
                    from yvakor.rede.gerente import organizar
                    return self._json(200, organizar(ag.rede))
                dev = ag.rede.registro.obter(alvo)
                if not dev:
                    return self._json(404, {"ok": False, "erro": "não encontrado"})
                if acao == "testar":
                    from yvakor.ambiente import _probe
                    return self._json(200, {"ok": True,
                                            "testes": _probe(ag.rede, dev)})
                if acao == "esquecer":
                    ag.rede.registro.esquecer(alvo)
                    return self._json(200, {"ok": True, "esquecido": alvo})
                if acao == "devolver":
                    atualizado = ag.rede.registro.atualizar(alvo, manual=False)
                    return self._json(200, {"ok": True,
                                            "dispositivo": atualizado})
                if acao == "atualizar":
                    campos = {}
                    for chave in ("nome", "tipo", "grupo", "notas"):
                        if dados_rede.get(chave) is not None:
                            campos[chave] = str(dados_rede.get(chave) or "")
                    if "favorito" in dados_rede:
                        campos["favorito"] = bool(dados_rede.get("favorito"))
                    atualizado = ag.rede.registro.atualizar(
                        alvo, manual=True, **campos)
                    return self._json(200, {"ok": True,
                                            "dispositivo": atualizado})
                return self._json(400, {"ok": False, "erro": "ação inválida"})

            # ---- Rede: varredura sob demanda ----
            if self.path == "/api/rede/escanear":
                ag = get_agent()
                if ag.rede is None:
                    return self._json(503, {"error": "rede indisponível"})
                try:
                    devs = ag.rede.descobridor.escanear(
                        profundo=bool(data.get("profundo", True)))
                except Exception as e:
                    return self._json(500, {"error": str(e)})
                return self._json(200, {"ok": True, "total": len(devs),
                                        "dispositivos": devs,
                                        "resumo": ag.rede.resumo(),
                                        "escopo": ag.rede.escopo.resumo()})

            # ---- Voz: falar / transcrever ----
            if self.path == "/api/ext/ping":
                from yvakor.extensao_bridge import PONTE
                PONTE.ping()
                return self._json(200, {"ok": True})

            if self.path == "/api/ext/erro":
                from yvakor.extensao_bridge import PONTE
                PONTE.registrar_falha()
                return self._json(200, {"ok": True})

            if self.path == "/api/ext/resultado":
                from yvakor.extensao_bridge import PONTE
                PONTE.resultado(str(data.get("id") or ""),
                                bool(data.get("ok", False)),
                                str(data.get("erro") or ""),
                                data.get("tab_id"),
                                str(data.get("titulo") or ""),
                                data.get("dados") or {})
                return self._json(200, {"ok": True})

            if self.path == "/api/voz/audio":
                if ag.voz is None:
                    return self._json(503, {"error": "voz indisponível"})
                texto = (data.get("texto") or "").strip()
                if not texto:
                    return self._json(400, {"error": "texto vazio"})
                r = ag.voz.tts.gerar(texto)
                if not r.get("ok"):
                    return self._json(503, {"error": r.get("erro")})
                arq = Path(r.get("arquivo") or "")
                if not arq.is_file():
                    return self._json(503, {"error": "áudio não gerado"})
                mime = ("audio/mpeg" if arq.suffix.lower() == ".mp3"
                        else "audio/wav")
                return self._send(200, arq.read_bytes(), mime)

            if self.path == "/api/voz/ativo":
                ativo = bool(data.get("ativo", True))
                try:
                    arq = ROOT / "data" / "preferencias.json"
                    arq.parent.mkdir(parents=True, exist_ok=True)
                    atual = {}
                    try:
                        atual = json.loads(arq.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                    atual["voz_ativa"] = ativo
                    arq.write_text(json.dumps(atual, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
                except Exception as exc:
                    return self._json(500, {"error": str(exc)})
                return self._json(200, {"ok": True, "ativo": ativo})

            if self.path == "/api/voz/falar":
                if ag.voz is None:
                    return self._json(503, {"error": "voz indisponível"})
                texto = (data.get("texto") or "").strip()
                if not texto:
                    return self._json(400, {"error": "texto vazio"})
                return self._json(200, ag.voz.tts.falar(
                    texto, idioma=data.get("idioma")))

            if self.path == "/api/voz/comando":
                if ag.voz is None:
                    return self._json(503, {"error": "voz indisponível"})
                texto = (data.get("texto") or "").strip()
                if not texto:
                    return self._json(400, {"error": "texto vazio"})
                r = ag.voz.sessao.processar(
                    texto, falar=bool(data.get("falar", True)),
                    exigir_ativacao=bool(data.get("exigir_ativacao", False)),
                    idioma=data.get("idioma"))
                return self._json(200, r)

            if self.path == "/api/voz/sessao":
                if ag.voz is None:
                    return self._json(503, {"error": "voz indisponível"})
                acao = (data.get("acao") or "estado").lower()
                if acao == "fechar":
                    ag.voz.sessao.fechar()
                elif acao == "abrir":
                    ag.voz.sessao.acordar("")
                elif acao == "interromper":
                    ag.voz.sessao.interromper()
                return self._json(200, {"ok": True, **ag.voz.sessao.estado()})

            if self.path == "/api/voz/transcrever":
                if ag.voz is None:
                    return self._json(503, {"error": "voz indisponível"})
                import base64 as _b64
                bruto = (data.get("audio_b64") or "").strip()
                if not bruto:
                    return self._json(400, {"error": "audio_b64 vazio"})
                if len(bruto) > 26_000_000:
                    return self._json(413, {"error": "áudio grande demais"})
                ext = str(data.get("ext") or "webm").lstrip(".")
                destino = (Path(ag.voz.stt.dir_audio) /
                           f"web_{int(time.time())}.{ext}")
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(_b64.b64decode(bruto))
                return self._json(200, ag.voz.stt.transcrever_arquivo(
                    str(destino), idioma=data.get("idioma")))

            # ---- Navegador: comandos do painel da interface ----
            if self.path == "/api/browser/google-login":
                if ag.navegadores is None:
                    return self._json(503, {"error": "navegador indisponível"})
                sess = ag.navegadores.sessao(ag.navegadores.motor(data.get("motor")))
                tentativa = max(30, min(int(data.get("timeout") or 240), 600))
                threading.Thread(target=sess.login_google, args=(tentativa,),
                                 daemon=True, name="yvakor-google-login").start()
                return self._json(200, {"ok": True, "iniciado": True,
                                        "timeout_s": tentativa,
                                        "status_url": "/api/browser/google"})

            if self.path == "/api/browser/action":
                if ag.navegadores is None:
                    return self._json(503, {"error": "navegador indisponível"})
                acao = (data.get("action") or "").strip()
                motor = ag.navegadores.motor(data.get("motor"))
                sess = ag.navegadores.sessao(motor)
                try:
                    if acao in ("open", "goto"):
                        with sess.trilho:
                            sess.selecionar_aba("principal")
                            r = (sess.open(data.get("url", ""))
                                 if acao == "open" else
                                 sess.goto(data.get("url", "")))
                    elif acao == "close":
                        r = sess.close()
                    elif acao in ("visible", "headless"):
                        with sess.trilho:
                            sess.selecionar_aba("principal")
                            r = sess.set_mode(acao == "headless")
                    elif acao == "conectar":
                        r = ag.navegadores.conectar_cdp(motor,
                                                        data.get("url") or None)
                    elif acao in ("grupo_focar", "grupo_fechar"):
                        nome_grupo = data.get("grupo") or "principal"
                        with sess.trilho:
                            sess.selecionar_aba("principal")
                            r = (sess.focar_grupo(nome_grupo)
                                 if acao == "grupo_focar"
                                 else sess.fechar_grupo(nome_grupo))
                    else:
                        return self._json(400, {"error": f"ação inválida: {acao}"})
                except Exception as e:
                    return self._json(500, {"error": str(e)})
                return self._json(200, {"ok": True, "motor": motor,
                                        "resultado": r,
                                        "status": ag.navegadores.status()})

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
            msg = str(e)
            if "401" in msg or "unauthorized" in msg.lower():
                msg = ("A chave da IA foi recusada pelo provedor (HTTP 401). "
                       "Edite E:\\YVAKOR\\yvakor\\.env e coloque uma "
                       "DEEPSEEK_API_KEY válida, depois reinicie o YVAKOR. "
                       "O resto do sistema (navegador, rede, arquivos, voz, "
                       "cérebro) continua funcionando sem ela.")
            return self._json(500, {"error": msg})

    # ----------------------------- DELETE ---------------------------- #
    def do_DELETE(self):
        if not self._autorizar_efeito():
            return
        if self.path.startswith("/api/agenda/"):
            tid = self.path[len("/api/agenda/"):]
            return self._json(200, get_agent().agenda.cancelar(tid))
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
    import msvcrt
    from yvakor.robustez import instalar
    instalar()
    try:
        from yvakor.extensao import sincronizar
        _sync = sincronizar()
        if _sync.get("ok"):
            print(f"  Extensão Chrome sincronizada: v{_sync['version']}")
    except Exception as exc:
        print(f"  [aviso] sincronização da extensão: {exc}")
    # Instância única: evita dois servidores disputando SQLite e navegador.
    global _lock_handle
    try:
        _lock_handle = open(ROOT / "data" / "yvakor.lock", "a+")
        _lock_handle.seek(0)
        msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("  [aviso] já existe um YVAKOR em execução; saindo.")
        return
    print(f"\n  YVAKOR online → http://localhost:{PORT}\n  (Ctrl+C para sair)\n")
    # Inicia a auto-manutenção em segundo plano (consolida conhecimento +
    # verifica atualização de código, conforme settings.yaml → maintenance).
    try:
        get_agent().maintenance.start_background()
    except Exception as e:
        print(f"  [aviso] auto-manutenção não iniciou: {e}")
    servidor = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # Fecha o navegador controlado e sinaliza tarefas cowork em curso.
        try:
            if _agent is not None:
                _agent.shutdown()
        except Exception:
            pass
        servidor.server_close()
        print("\n  YVAKOR encerrado.")


if __name__ == "__main__":
    main()
