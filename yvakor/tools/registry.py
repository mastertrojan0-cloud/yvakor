"""Registro de ferramentas do agente.

TODO (implementar com Claude Code / DeepSeek V4):
  - web_search   : pesquisa (SearXNG local ou API) com citação de fontes
  - code_executor: roda código Python em data/sandbox/ com timeout
  - file_manager : ler/escrever arquivos do usuário (escrita protegida pelo guard)
  - http_client  : GET livre, POST protegido pelo guard
  - whatsapp/email: integração com Assistente Master (sempre via guard)

Cada ferramenta segue o contrato:
    def run(**kwargs) -> dict  # {"ok": bool, "result": ..., "error": ...}

O orquestrador evoluirá para function calling: o LLM devolve JSON
{"tool": "...", "args": {...}} e o registry executa.
"""
from __future__ import annotations
from yvakor.tools.guard import ConfirmationGuard


class ToolRegistry:
    def __init__(self, settings: dict):
        self.guard = ConfirmationGuard(
            settings["tools"]["guarded_actions"],
            auto_approve=settings["tools"].get("auto_approve", False),
            always_confirm=settings["tools"].get("always_confirm"))
        self.tools: dict = {}  # nome -> callable
        self.specs: dict = {}  # nome -> {desc, args}

    def register(self, name: str, fn, desc: str = "", args: dict | None = None):
        self.tools[name] = fn
        self.specs[name] = {"desc": desc, "args": args or {}}

    def manifest(self) -> str:
        """Descrição das ferramentas p/ injetar no prompt do agente."""
        linhas = []
        for nome, spec in self.specs.items():
            guard = " (PROTEGIDA: exige confirmação)" \
                if self.guard.requires_confirmation(nome) else ""
            args = ", ".join(f"{k}: {v}" for k, v in spec["args"].items()) or "—"
            linhas.append(f"- {nome}({args}){guard} → {spec['desc']}")
        return "\n".join(linhas)

    def run(self, name: str, **kwargs) -> dict:
        if name not in self.tools:
            return {"ok": False, "error": f"ferramenta desconhecida: {name}"}
        if self.guard.requires_confirmation(name):
            if not self.guard.confirm(name, str(kwargs)[:200]):
                return {"ok": False, "error": "cancelado pelo usuário"}
        try:
            return {"ok": True, "result": self.tools[name](**kwargs)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
