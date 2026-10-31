"""YVAKOR — cliente MCP (Model Context Protocol), padrão aberto.

Permite plugar servidores MCP e expor as ferramentas deles no mesmo registro
usado pelo agente. Configuração em config/mcp.json. Dois transportes:

  local (stdio)  {"enabled": true, "command": "npx", "args": [...], "env": {...}}
  remoto (HTTP)  {"enabled": true, "type": "http", "url": "https://…/mcp",
                  "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}}

O remoto usa o transporte "Streamable HTTP" do MCP (o dos conectores do
Claude): POST de JSON-RPC, resposta em JSON ou em SSE, sessão pelo cabeçalho
Mcp-Session-Id. ${VAR} e ${VAR:-padrão} nos headers/url vêm das variáveis de
ambiente (.env), para o token não ficar escrito no arquivo. Login OAuth no
navegador não é feito: use um token de acesso no header.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from yvakor import proc as _ywproc
import threading
import urllib.parse
from pathlib import Path

from yvakor.config import ROOT
import logging

_log = logging.getLogger(__name__)

CONFIG = ROOT / "config" / "mcp.json"
PROTOCOLO = "2024-11-05"
LOG = ROOT / "data" / "logs" / "mcp.log"


class MCPErro(RuntimeError):
    pass


class MCPClient:
    def __init__(self, nome: str, cfg: dict):
        self.nome = nome
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._pendentes: dict[int, dict] = {}
        self._seq = 0
        self._vivo = False
        self.tools: list[dict] = []
        self.erro = ""

    # ------------------------------------------------------------------ #
    def iniciar(self) -> bool:
        cmd = self.cfg.get("command")
        if not cmd:
            self.erro = "sem command"
            return False
        args = [str(a) for a in (self.cfg.get("args") or [])]
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (self.cfg.get("env") or {}).items()})
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self.proc = _ywproc.popen(
                [str(cmd), *args], cwd=str(self.cfg.get("cwd") or ROOT),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=env, creationflags=flags)
        except Exception as exc:
            self.erro = f"{type(exc).__name__}: {exc}"
            return False
        self._vivo = True
        threading.Thread(target=self._ler, daemon=True,
                         name=f"mcp-{self.nome}").start()
        threading.Thread(target=self._ler_erros, daemon=True,
                         name=f"mcp-err-{self.nome}").start()
        try:
            r = self.request("initialize", {
                "protocolVersion": PROTOCOLO,
                "capabilities": {},
                "clientInfo": {"name": "YVAKOR", "version": "1.0"}})
            if "error" in r:
                raise MCPErro(str(r["error"]))
            self.notificar("notifications/initialized", {})
            lista = self.request("tools/list", {})
            self.tools = (lista.get("result") or {}).get("tools") or []
            return True
        except Exception as exc:
            self.erro = f"{type(exc).__name__}: {exc}"
            self.parar()
            return False

    def _ler_erros(self):
        try:
            for linha in self.proc.stderr:
                LOG.parent.mkdir(parents=True, exist_ok=True)
                with LOG.open("a", encoding="utf-8") as f:
                    f.write(f"[{self.nome}] {linha.rstrip()}\n")
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

    def _ler(self):
        try:
            for linha in self.proc.stdout:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    msg = json.loads(linha)
                except Exception:
                    continue
                if "id" in msg and msg["id"] in self._pendentes:
                    self._pendentes[msg["id"]]["msg"] = msg
                    self._pendentes[msg["id"]]["evento"].set()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        self._vivo = False
        for pend in list(self._pendentes.values()):
            pend["evento"].set()

    # ------------------------------------------------------------------ #
    def _enviar(self, obj: dict):
        with self._lock:
            if not self.proc or self.proc.poll() is not None:
                raise MCPErro("servidor MCP encerrado")
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def notificar(self, metodo: str, params: dict):
        self._enviar({"jsonrpc": "2.0", "method": metodo, "params": params})

    def request(self, metodo: str, params: dict, timeout: float = 20) -> dict:
        evento = threading.Event()
        with self._lock:
            self._seq += 1
            rid = self._seq
            self._pendentes[rid] = {"evento": evento, "msg": None}
        self._enviar({"jsonrpc": "2.0", "id": rid, "method": metodo,
                      "params": params})
        if not evento.wait(timeout):
            raise MCPErro(f"{metodo}: timeout de {timeout:.0f}s")
        with self._lock:
            pend = self._pendentes.pop(rid, None)
        msg = (pend or {}).get("msg")
        if not msg:
            raise MCPErro(f"{metodo}: sem resposta")
        if "error" in msg:
            raise MCPErro(str(msg["error"]))
        return msg

    def chamar(self, ferramenta: str, argumentos: dict, timeout: float = 60) -> dict:
        r = self.request("tools/call", {"name": ferramenta,
                                        "arguments": argumentos or {}},
                         timeout=timeout)
        res = r.get("result") or {}
        partes = []
        for c in (res.get("content") or []):
            if isinstance(c, dict) and c.get("type") == "text":
                partes.append(str(c.get("text") or ""))
            else:
                partes.append(json.dumps(c, ensure_ascii=False))
        texto = "\n".join(partes).strip() or json.dumps(res, ensure_ascii=False)
        return {"ok": not bool(res.get("isError")), "resultado": texto[:8000]}

    def parar(self):
        self._vivo = False
        proc = self.proc
        self.proc = None
        if not proc:
            return
        try:
            _ywproc.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)


PROTOCOLO_HTTP = "2025-03-26"
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expandir_env(valor: str) -> str:
    """'Bearer ${TOKEN}' → valor da variável de ambiente (ou o padrão após ':-')."""
    return _VAR.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), str(valor))


def _vivo(cli) -> bool:
    if isinstance(cli, (MCPClienteHTTP, MCPClienteSSE)):
        return cli._vivo
    return bool(cli.proc and cli.proc.poll() is None)


def _transporte(cli) -> str:
    return ("sse" if isinstance(cli, MCPClienteSSE) else
            "http" if isinstance(cli, MCPClienteHTTP) else "stdio")


class PrecisaLogin(MCPErro):
    """401 num servidor sem token: o usuário precisa entrar (mcp_entrar)."""

    def __init__(self, msg: str, www_authenticate: str = ""):
        super().__init__(msg)
        self.www_authenticate = www_authenticate


class _ComOAuth:
    """Cabeçalho Authorization vindo do login OAuth (yvakor/mcp_oauth.py)."""

    def _preparar_oauth(self, cfg: dict) -> None:
        self.oauth = None
        self.www_authenticate = ""
        tem_token_fixo = any(k.lower() == "authorization" for k in self.headers)
        if cfg.get("oauth") or not tem_token_fixo:
            from yvakor.mcp_oauth import LoginOAuth
            self.oauth = LoginOAuth(self.nome, self.url,
                                    cfg.get("oauth") if isinstance(cfg.get("oauth"), dict) else {})

    def _cabecalho_auth(self) -> dict:
        if self.oauth is None:
            return {}
        tok = self.oauth.token()
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def _nao_autorizado(self, status: int, www: str, tentou_renovar: bool) -> bool:
        """True = renovou o token e vale tentar de novo."""
        self.www_authenticate = www or ""
        if self.oauth is not None and not tentou_renovar and self.oauth.conectado() \
                and self.oauth.renovar():
            return True
        if self.oauth is not None:
            raise PrecisaLogin(f"HTTP {status}: precisa entrar — use a ferramenta "
                               f"mcp_entrar(servidor='{self.nome}') para fazer login "
                               "no navegador", www)
        raise MCPErro(f"HTTP {status}: não autorizado — confira o token em headers "
                      "(config/mcp.json ou .env)")


class MCPClienteHTTP(_ComOAuth, MCPClient):
    """Servidor MCP remoto (Streamable HTTP)."""

    def __init__(self, nome: str, cfg: dict):
        super().__init__(nome, cfg)
        self.url = expandir_env(cfg.get("url") or "")
        self.headers = {str(k): expandir_env(v) for k, v in (cfg.get("headers") or {}).items()}
        self.sessao = ""
        self._preparar_oauth(cfg)

    def iniciar(self) -> bool:
        if not re.match(r"^https?://", self.url):
            self.erro = "url precisa começar com http:// ou https://"
            return False
        try:
            r = self.request("initialize", {
                "protocolVersion": PROTOCOLO_HTTP, "capabilities": {},
                "clientInfo": {"name": "YVAKOR", "version": "1.0"}})
            self._vivo = True
            versao = (r.get("result") or {}).get("protocolVersion")
            if versao:
                self.headers.setdefault("MCP-Protocol-Version", str(versao))
            self.notificar("notifications/initialized", {})
            self.tools = (self.request("tools/list", {}).get("result") or {}).get("tools") or []
            self.erro = ""
            return True
        except Exception as exc:
            self.erro = str(exc) if isinstance(exc, PrecisaLogin) \
                else f"{type(exc).__name__}: {exc}"
            self._vivo = False
            return False

    def _post(self, corpo: dict, timeout: float, rid=None, _renovou=False) -> dict | None:
        import requests
        cab = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream", **self.headers,
               **self._cabecalho_auth()}
        if self.sessao:
            cab["Mcp-Session-Id"] = self.sessao
        try:
            r = requests.post(self.url, json=corpo, headers=cab, timeout=timeout, stream=True)
        except requests.RequestException as exc:
            raise MCPErro(f"{type(exc).__name__}: {exc}") from exc
        with r:
            if r.headers.get("Mcp-Session-Id"):
                self.sessao = r.headers["Mcp-Session-Id"]
            if r.status_code in (401, 403):
                if self._nao_autorizado(r.status_code, r.headers.get("WWW-Authenticate", ""),
                                        _renovou):
                    return self._post(corpo, timeout, rid, _renovou=True)
            if r.status_code == 404 and self.sessao and corpo.get("method") != "initialize":
                raise MCPErro("sessão MCP expirou (HTTP 404); reinicie o YVAKOR")
            if r.status_code >= 400:
                raise MCPErro(f"HTTP {r.status_code}: {r.text[:300]}")
            if rid is None:          # notificação: 202 sem corpo
                return None
            tipo = r.headers.get("Content-Type", "")
            if "text/event-stream" in tipo:
                return self._ler_sse(r, rid)
            dados = r.json()
            if isinstance(dados, list):
                dados = next((d for d in dados if d.get("id") == rid), {})
            return dados

    @staticmethod
    def _linhas(resposta):
        """Linhas do stream assim que chegam. (iter_lines do requests junta
        blocos de 512 bytes: num SSE que fica aberto, a resposta só aparecia
        quando o servidor fechava a conexão.)"""
        resposta.raw.decode_content = True
        for bruta in iter(resposta.raw.readline, b""):
            yield bruta.decode("utf-8", errors="replace").rstrip("\r\n")

    @staticmethod
    def _eventos(linhas_iter):
        """Eventos SSE: (tipo, dados) a cada linha em branco."""
        tipo, dados = "message", []
        for bruta in linhas_iter:
            if bruta is None:
                continue
            if bruta.startswith("event:"):
                tipo = bruta[6:].strip()
            elif bruta.startswith("data:"):
                dados.append(bruta[5:].lstrip())
            elif bruta == "" and dados:
                yield tipo, "\n".join(dados)
                tipo, dados = "message", []
        if dados:
            yield tipo, "\n".join(dados)

    @classmethod
    def _ler_sse(cls, resposta, rid) -> dict:
        """Lê eventos 'data:' até achar a resposta com o id pedido."""
        for _, dados in cls._eventos(cls._linhas(resposta)):
            try:
                msg = json.loads(dados)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == rid:
                return msg
        raise MCPErro("resposta SSE sem o resultado pedido")

    def notificar(self, metodo: str, params: dict):
        self._post({"jsonrpc": "2.0", "method": metodo, "params": params}, 20)

    def request(self, metodo: str, params: dict, timeout: float = 20) -> dict:
        with self._lock:
            self._seq += 1
            rid = self._seq
        msg = self._post({"jsonrpc": "2.0", "id": rid, "method": metodo,
                          "params": params}, timeout, rid) or {}
        if "error" in msg:
            raise MCPErro(str(msg["error"]))
        if not msg:
            raise MCPErro(f"{metodo}: sem resposta")
        return msg

    def parar(self):
        if self._vivo and self.sessao:
            try:
                import requests
                requests.delete(self.url, headers={**self.headers, **self._cabecalho_auth(),
                                                   "Mcp-Session-Id": self.sessao}, timeout=5)
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        self._vivo = False


class MCPClienteSSE(_ComOAuth, MCPClient):
    """Transporte SSE antigo (MCP 2024-11-05): um GET fica aberto recebendo
    eventos; o primeiro ("endpoint") diz para onde fazer POST das mensagens, e
    as respostas voltam pelo mesmo stream."""

    def __init__(self, nome: str, cfg: dict):
        super().__init__(nome, cfg)
        self.url = expandir_env(cfg.get("url") or "")
        self.headers = {str(k): expandir_env(v) for k, v in (cfg.get("headers") or {}).items()}
        self.endpoint = ""
        self._pronto = threading.Event()
        self._resposta = None
        self._preparar_oauth(cfg)

    def iniciar(self) -> bool:
        if not re.match(r"^https?://", self.url):
            self.erro = "url precisa começar com http:// ou https://"
            return False
        import requests
        cab = {"Accept": "text/event-stream", **self.headers, **self._cabecalho_auth()}
        try:
            self._resposta = requests.get(self.url, headers=cab, stream=True,
                                          timeout=(15, None))
            if self._resposta.status_code in (401, 403):
                self._nao_autorizado(self._resposta.status_code,
                                     self._resposta.headers.get("WWW-Authenticate", ""), True)
            if self._resposta.status_code >= 400:
                raise MCPErro(f"HTTP {self._resposta.status_code}")
            self._vivo = True
            threading.Thread(target=self._ouvir, daemon=True,
                             name=f"mcp-sse-{self.nome}").start()
            if not self._pronto.wait(20):
                raise MCPErro("o servidor não enviou o evento 'endpoint'")
            self.request("initialize", {"protocolVersion": PROTOCOLO, "capabilities": {},
                                        "clientInfo": {"name": "YVAKOR", "version": "1.0"}})
            self.notificar("notifications/initialized", {})
            self.tools = (self.request("tools/list", {}).get("result") or {}).get("tools") or []
            self.erro = ""
            return True
        except Exception as exc:
            self.erro = str(exc) if isinstance(exc, PrecisaLogin) \
                else f"{type(exc).__name__}: {exc}"
            self.parar()
            return False

    def _ouvir(self):
        try:
            linhas = MCPClienteHTTP._linhas(self._resposta)
            for tipo, dados in MCPClienteHTTP._eventos(linhas):
                if tipo == "endpoint":
                    self.endpoint = urllib.parse.urljoin(self.url, dados.strip())
                    self._pronto.set()
                    continue
                try:
                    msg = json.loads(dados)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("id") in self._pendentes:
                    self._pendentes[msg["id"]]["msg"] = msg
                    self._pendentes[msg["id"]]["evento"].set()
        except Exception:
            _log.debug("stream SSE encerrado", exc_info=True)
        self._vivo = False
        for pend in list(self._pendentes.values()):
            pend["evento"].set()

    def _enviar(self, obj: dict):
        import requests
        if not self._vivo or not self.endpoint:
            raise MCPErro("servidor MCP (SSE) desconectado")
        try:
            r = requests.post(self.endpoint, json=obj, timeout=30,
                              headers={"Content-Type": "application/json", **self.headers,
                                       **self._cabecalho_auth()})
        except requests.RequestException as exc:
            raise MCPErro(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code >= 400:
            raise MCPErro(f"HTTP {r.status_code}: {r.text[:300]}")

    def parar(self):
        self._vivo = False
        resp, self._resposta = self._resposta, None
        if resp is not None:
            try:
                resp.close()
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)


def novo_cliente(nome: str, cfg: dict) -> MCPClient:
    tipo = (cfg.get("type") or "").lower()
    if tipo == "sse":
        return MCPClienteSSE(nome, cfg)
    if cfg.get("url") or tipo in ("http", "streamable-http"):
        return MCPClienteHTTP(nome, cfg)
    return MCPClient(nome, cfg)


class MCPManager:
    def __init__(self, tools, cfg_path: Path | None = None, extras=None):
        self.tools = tools
        self.cfg_path = Path(cfg_path or CONFIG)
        # servidores de plugins ativos: callable → {nome: cfg} (yvakor/plugins.py)
        self.extras = extras
        self.clientes: dict[str, MCPClient] = {}
        self.mapa: dict[str, tuple[MCPClient, str]] = {}
        self.falhas: dict[str, str] = {}          # servidor → por que não subiu
        self.configs: dict[str, dict] = {}
        self.logins: dict[str, str] = {}          # servidor → estado do login em curso

    def _config(self) -> dict:
        if not self.cfg_path.is_file():
            self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
            self.cfg_path.write_text(json.dumps({
                "servers": {},
                "_exemplo": {
                    "filesystem": {
                        "enabled": False,
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem",
                                 "E:\\\\YVAKOR"],
                        "cwd": str(ROOT)
                    }
                }
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"servers": {}}
        try:
            return json.loads(self.cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return {"servers": {}}

    def _servidores(self) -> dict[str, dict]:
        servidores = dict(self._config().get("servers") or {})
        if self.extras is not None:
            try:
                for nome, cfg in self.extras().items():
                    servidores.setdefault(nome, cfg)   # config/mcp.json manda
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        return {n: c for n, c in servidores.items() if isinstance(c, dict) and c.get("enabled")}

    def _subir(self, nome: str, cfg: dict) -> bool:
        cli = novo_cliente(nome, cfg)
        if cli.iniciar():
            self.clientes[nome] = cli
            self.falhas.pop(nome, None)
            self._registrar(nome, cli)
            return True
        self.falhas[nome] = cli.erro or "falhou ao iniciar"
        if getattr(cli, "www_authenticate", ""):
            self._www_auth = {**self._www, nome: cli.www_authenticate}
        return False

    def iniciar(self) -> dict:
        self.configs = self._servidores()
        ativos = sum(1 for nome, cfg in self.configs.items() if self._subir(nome, cfg))
        self._registrar_gestao()
        return {"ok": True, "servidores": ativos,
                "ferramentas": len(self.mapa), "erros": dict(self.falhas)}

    def _registrar(self, servidor: str, cli: MCPClient):
        for spec in cli.tools:
            nome_remoto = str(spec.get("name") or "")
            if not nome_remoto:
                continue
            seguro = re.sub(r"[^A-Za-z0-9_]+", "_",
                            f"mcp_{servidor}_{nome_remoto}")[:60]
            esquema = spec.get("inputSchema") or {}
            props = esquema.get("properties") or {}
            args = {k: str((v or {}).get("description")
                           or (v or {}).get("type") or "valor")
                    for k, v in props.items()}
            desc = f"[MCP:{servidor}] {spec.get('description') or nome_remoto}"
            self.mapa[seguro] = (cli, nome_remoto)
            if self._precisa_confirmar(cli.cfg, nome_remoto, spec):
                # ferramenta de terceiro que escreve/envia: popup, como shell e e-mail
                self.tools.guard.always_confirm.add(seguro)
                desc += " (PROTEGIDA)"

            def chamar(_nome=nome_remoto, _cli=cli, **kwargs):
                try:
                    return _cli.chamar(_nome, kwargs)
                except Exception as exc:
                    return {"ok": False, "erro": str(exc)}
            self.tools.register(seguro, chamar, desc, args)

    _ESCRITA = frozenset(
        "create update delete remove send post write edit merge push publish upload "
        "move rename close comment reply assign archive cancel pay transfer execute "
        "run set add insert drop patch put fork invite approve reject criar apagar "
        "enviar editar".split())

    @classmethod
    def _precisa_confirmar(cls, cfg: dict, nome: str, spec: dict) -> bool:
        """Ferramenta MCP que muda algo fora do PC pede confirmação.

        config/mcp.json → "confirmar": "escrita" (padrão: pelo nome/anotação),
        "todas", "nenhuma" ou uma lista de nomes."""
        regra = (cfg or {}).get("confirmar", "escrita")
        if isinstance(regra, list):
            return nome in regra
        regra = str(regra).lower()
        if regra in ("todas", "all"):
            return True
        if regra in ("nenhuma", "none", "false"):
            return False
        dicas = spec.get("annotations") or {}
        if dicas.get("readOnlyHint") is True:
            return False
        if dicas.get("destructiveHint") is True:
            return True
        palavras = re.split(r"[_\-.\s]+|(?<=[a-z])(?=[A-Z])", nome)
        return any(p.lower() in cls._ESCRITA for p in palavras)

    # ------------------------------------------------------------------ #
    def entrar(self, servidor: str = "", esperar: bool = False) -> dict:
        """Abre o login OAuth no navegador; ao concluir, sobe o servidor."""
        cfg = self.configs.get(servidor) or self._servidores().get(servidor)
        if not cfg or not cfg.get("url"):
            remotos = [n for n, c in (self.configs or self._servidores()).items()
                       if c.get("url")]
            return {"ok": False, "error": f"servidor remoto {servidor!r} não está ligado "
                    "no config/mcp.json", "remotos": remotos}
        if self.logins.get(servidor) == "aguardando":
            return {"ok": True, "result": "o login já está aberto no navegador"}
        from yvakor.mcp_oauth import LoginOAuth
        login = LoginOAuth(servidor, expandir_env(cfg["url"]),
                           cfg.get("oauth") if isinstance(cfg.get("oauth"), dict) else {})

        def fluxo():
            self.logins[servidor] = "aguardando"
            try:
                login.entrar(self._www.get(servidor, ""))
                antigo = self.clientes.pop(servidor, None)
                if antigo is not None:
                    antigo.parar()
                ok = self._subir(servidor, cfg)
                self.logins[servidor] = "conectado" if ok else \
                    f"login ok, mas o servidor falhou: {self.falhas.get(servidor)}"
            except Exception as exc:
                self.logins[servidor] = f"falhou: {exc}"
                _log.warning("login MCP %s falhou: %s", servidor, exc)

        if esperar:
            fluxo()
            estado = self.logins[servidor]
            return {"ok": estado == "conectado", "result": estado}
        threading.Thread(target=fluxo, daemon=True, name=f"mcp-login-{servidor}").start()
        return {"ok": True, "result": (
            f"Abri o login de {servidor} no navegador. Entre e autorize o YVAKOR; "
            "as ferramentas aparecem sozinhas em seguida (veja mcp_status).")}

    @property
    def _www(self) -> dict[str, str]:
        """WWW-Authenticate do último 401 (aponta onde fica o login)."""
        return getattr(self, "_www_auth", {})

    def sair(self, servidor: str = "") -> dict:
        from yvakor.mcp_oauth import LoginOAuth
        cfg = self.configs.get(servidor) or {}
        LoginOAuth(servidor, cfg.get("url") or "").sair()
        cli = self.clientes.pop(servidor, None)
        if cli is not None:
            cli.parar()
        for nome in [n for n, (c, _) in self.mapa.items() if c is cli]:
            self.mapa.pop(nome, None)
            self.tools.tools.pop(nome, None)
            self.tools.specs.pop(nome, None)
        return {"ok": True, "result": f"login de {servidor} removido"}

    def _registrar_gestao(self):
        def status():
            servidores = {
                n: {"vivo": _vivo(c), "transporte": _transporte(c),
                    "ferramentas": [t.get("name") for t in c.tools], "erro": c.erro}
                for n, c in self.clientes.items()}
            for n, erro in self.falhas.items():
                servidores.setdefault(n, {"vivo": False, "erro": erro})
            for n, estado in self.logins.items():
                servidores.setdefault(n, {})["login"] = estado
            return {"ok": True, "servidores": servidores}
        self.tools.register("mcp_status", status,
                            "Mostra servidores MCP conectados, erros e ferramentas.", {})
        self.tools.register(
            "mcp_entrar", lambda servidor="": self.entrar(servidor),
            "Faz login (OAuth, no navegador) num servidor MCP remoto que pede "
            "autorização. Use quando mcp_status mostrar 'precisa entrar'.",
            {"servidor": "str"})
        self.tools.register(
            "mcp_sair", lambda servidor="": self.sair(servidor),
            "Remove o login guardado de um servidor MCP remoto.", {"servidor": "str"})

    def parar(self):
        for c in self.clientes.values():
            c.parar()
        self.clientes.clear()
        self.mapa.clear()
