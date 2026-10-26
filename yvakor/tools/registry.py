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
            always_confirm=settings["tools"].get("always_confirm"),
            total=str(settings["tools"].get("privilegios", "")).lower() == "total")
        self.tools: dict = {}  # nome -> callable
        self.specs: dict = {}  # nome -> {desc, args}

    def register(self, name: str, fn, desc: str = "", args: dict | None = None):
        self.tools[name] = fn
        self.specs[name] = {"desc": desc, "args": args or {}}

    def manifest(self, nomes: list[str] | None = None) -> str:
        """Descrição das ferramentas p/ injetar no prompt do agente."""
        linhas = []
        for nome, spec in self.specs.items():
            if nomes is not None and nome not in nomes:
                continue
            guard = " (PROTEGIDA: exige confirmação)" \
                if self.guard.requires_confirmation(nome) else ""
            args = ", ".join(f"{k}: {v}" for k, v in spec["args"].items()) or "—"
            linhas.append(f"- {nome}({args}){guard} → {spec['desc']}")
        return "\n".join(linhas)

    # ------------------------------------------------------------------ #
    # Function calling nativo (OpenAI/Ollama): schema + coerção
    # ------------------------------------------------------------------ #
    _TIPOS = {"int": "integer", "float": "number", "bool": "boolean",
              "str": "string"}
    _PY = {"int": int, "float": float, "bool": lambda v: str(v).lower() in
           ("1", "true", "sim", "yes", "on"), "str": str}

    def schemas(self, nomes: list[str] | None = None) -> list[dict]:
        ferramentas = []
        for nome, spec in self.specs.items():
            if nomes is not None and nome not in nomes:
                continue
            propriedades, obrigatorios = {}, []
            for arg, tipo in (spec.get("args") or {}).items():
                opcional = str(tipo).endswith("?")
                base = str(tipo).rstrip("?") or "str"
                propriedades[arg] = {"type": self._TIPOS.get(base, "string")}
                if not opcional:
                    obrigatorios.append(arg)
            ferramentas.append({
                "type": "function",
                "function": {"name": nome, "description": spec.get("desc", ""),
                             "parameters": {"type": "object",
                                            "properties": propriedades,
                                            "required": obrigatorios}}})
        return ferramentas

    def coagir(self, nome: str, args: dict) -> dict:
        """Converte tipos simples e ignora argumentos desconhecidos."""
        spec = (self.specs.get(nome) or {}).get("args") or {}
        saida = {}
        for chave, valor in (args or {}).items():
            if chave not in spec:
                continue
            base = str(spec[chave]).rstrip("?") or "str"
            try:
                saida[chave] = self._PY.get(base, str)(valor)
            except Exception:
                saida[chave] = valor
        return saida

    def run(self, name: str, **kwargs) -> dict:
        if name not in self.tools:
            return {"ok": False, "error": f"ferramenta desconhecida: {name}"}
        if self.guard.requires_confirmation(name):
            if not self.guard.confirm(name, str(kwargs)[:200]):
                return {"ok": False, "error": "cancelado pelo usuário"}
        try:
            valor = self.tools[name](**kwargs)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        # Ferramentas que já devolvem {"ok": ...} não são embrulhadas de novo:
        # evita aninhamento ({"ok":true,"result":{"ok":false,...}}) que escondia
        # falhas do agente e inchava o contexto.
        if isinstance(valor, dict) and "ok" in valor:
            return valor
        return {"ok": True, "result": valor}
