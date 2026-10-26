"""YVAKOR — cliente MCP (Model Context Protocol), padrão aberto.

Permite plugar servidores MCP locais (stdio/JSON-RPC) e expor as ferramentas
deles no mesmo registro usado pelo agente. Configuração em config/mcp.json.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from yvakor.config import ROOT

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
            self.proc = subprocess.Popen(
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
            pass

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
            pass
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
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass


class MCPManager:
    def __init__(self, tools, cfg_path: Path | None = None):
        self.tools = tools
        self.cfg_path = Path(cfg_path or CONFIG)
        self.clientes: dict[str, MCPClient] = {}
        self.mapa: dict[str, tuple[MCPClient, str]] = {}

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

    def iniciar(self) -> dict:
        servidores = (self._config().get("servers") or {})
        ativos = 0
        for nome, cfg in servidores.items():
            if not isinstance(cfg, dict) or not cfg.get("enabled"):
                continue
            cli = MCPClient(nome, cfg)
            if cli.iniciar():
                self.clientes[nome] = cli
                self._registrar(nome, cli)
                ativos += 1
        self._registrar_gestao()
        return {"ok": True, "servidores": ativos,
                "ferramentas": len(self.mapa),
                "erros": {n: c.erro for n, c in self.clientes.items() if c.erro}}

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

            def chamar(_nome=nome_remoto, _cli=cli, **kwargs):
                try:
                    return _cli.chamar(_nome, kwargs)
                except Exception as exc:
                    return {"ok": False, "erro": str(exc)}
            self.tools.register(seguro, chamar, desc, args)

    def _registrar_gestao(self):
        def status():
            return {"ok": True, "servidores": {
                n: {"vivo": bool(c.proc and c.proc.poll() is None),
                    "ferramentas": [t.get("name") for t in c.tools],
                    "erro": c.erro}
                for n, c in self.clientes.items()}}
        self.tools.register("mcp_status", status,
                            "Mostra servidores MCP conectados e ferramentas.", {})

    def parar(self):
        for c in self.clientes.values():
            c.parar()
        self.clientes.clear()
        self.mapa.clear()
