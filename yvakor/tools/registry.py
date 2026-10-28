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

    def _reconciliar_args(self, name: str, kwargs: dict) -> dict:
        """Modelos pequenos erram os NOMES dos argumentos (ex.: numero1/numero2
        em vez de a/b). Se algum nome não existe na especificação: com a mesma
        quantidade de argumentos, mapeia por posição; senão descarta os
        desconhecidos. Só mexe em ferramentas com especificação declarada e só
        quando há divergência — chamadas corretas passam intactas."""
        spec = list(((self.specs.get(name) or {}).get("args") or {}))
        if not spec or all(k in spec for k in kwargs):
            return kwargs
        if len(kwargs) == len(spec):
            return dict(zip(spec, kwargs.values()))
        return {k: v for k, v in kwargs.items() if k in spec}

    def _obrigatorios_faltando(self, name: str, kwargs: dict) -> list[str]:
        """Argumento obrigatório (na especificação) ausente ou vazio, quando a
        falta NÃO geraria TypeError: funções com **kwargs (ferramentas da
        extensão) ou com padrão vazio (ex.: web_ler(url="")). Antes a chamada
        ia sem o alvo e o modelo seguia como se tivesse funcionado."""
        import inspect
        try:
            params = inspect.signature(self.tools[name]).parameters
        except (TypeError, ValueError):
            return []
        livre = any(p.kind == p.VAR_KEYWORD for p in params.values())
        spec = (self.specs.get(name) or {}).get("args") or {}

        def silencioso(k: str) -> bool:
            p = params.get(k)
            return livre if p is None else p.default in ("", None)

        return [k for k, t in spec.items()
                if not str(t).endswith("?") and kwargs.get(k) in (None, "")
                and silencioso(k)]

    def _varios_campos(self, name: str, kwargs: dict) -> dict | None:
        """{"campos": [{"seletor"/"alvo": …, "valor": …}, …]} — formato que o
        modelo usa para preencher vários campos de uma vez: um por um."""
        campos = kwargs.get("campos")
        spec = (self.specs.get(name) or {}).get("args") or {}
        if not isinstance(campos, list) or "campos" in spec or not {"alvo", "valor"} <= set(spec):
            return None
        extras = {k: v for k, v in kwargs.items() if k != "campos" and k in spec}
        resultados = []
        for c in campos[:20]:
            if not isinstance(c, dict):
                continue
            alvo = next((c[k] for k in ("alvo", "seletor", "selector", "ref", "campo")
                         if c.get(k)), "")
            valor = next((c[k] for k in ("valor", "value", "texto") if k in c), "")
            r = self.run(name, **{**extras, "alvo": alvo, "valor": valor})
            resultados.append({"alvo": alvo, "ok": bool(r.get("ok")),
                               "erro": r.get("error") or r.get("erro") or ""})
        ok = bool(resultados) and all(r["ok"] for r in resultados)
        return {"ok": ok, "campos": resultados,
                **({} if ok else {"error": "nem todos os campos foram preenchidos: "
                                  + "; ".join(f"{r['alvo']}: {r['erro'] or 'falhou'}"
                                              for r in resultados if not r["ok"])})}

    def run(self, name: str, **kwargs) -> dict:
        if name not in self.tools:
            return {"ok": False, "error": f"ferramenta desconhecida: {name}"}
        if self.guard.requires_confirmation(name):
            if not self.guard.confirm(name, str(kwargs)[:200], completo=str(kwargs)):
                return {"ok": False, "error": "cancelado pelo usuário"}
        varios = self._varios_campos(name, kwargs)
        if varios is not None:
            return varios
        kwargs = self._reconciliar_args(name, kwargs)
        faltando = self._obrigatorios_faltando(name, kwargs)
        if faltando:
            esperado = ", ".join((self.specs.get(name) or {}).get("args") or {})
            return {"ok": False, "error": (
                f"faltou o argumento obrigatório {', '.join(faltando)} — NADA foi "
                f"feito. Argumentos esperados: {esperado}")}
        try:
            valor = self.tools[name](**kwargs)
        except TypeError as e:
            # Argumento errado/faltando: diz ao modelo QUAIS eram esperados,
            # em vez de só "unexpected keyword argument" (que o 3B não corrige).
            esperado = list(((self.specs.get(name) or {}).get("args") or {}))
            dica = f" — argumentos esperados: {', '.join(esperado)}" if esperado else ""
            return {"ok": False, "error": f"{e}{dica}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        # Ferramentas que já devolvem {"ok": ...} não são embrulhadas de novo:
        # evita aninhamento ({"ok":true,"result":{"ok":false,...}}) que escondia
        # falhas do agente e inchava o contexto.
        if isinstance(valor, dict) and "ok" in valor:
            return valor
        return {"ok": True, "result": valor}
