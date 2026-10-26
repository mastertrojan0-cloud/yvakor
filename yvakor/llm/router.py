"""Roteador: decide qual provider atende cada tipo de tarefa.
É aqui que a independência de IA externa acontece gradualmente:
mova categorias de 'external' para 'local' no settings.yaml."""
from __future__ import annotations
from yvakor.llm.adapter import build_provider

KEYWORDS = {    "codigo": ["código", "codigo", "script", "função", "bug", "erro", "python",
               "javascript", "api", "sql", "implementa"],
    "prospeccao": ["cliente", "prospec", "proposta", "lead", "orçamento", "venda"],
    "pesquisa_sintese": ["pesquise", "pesquisa", "compare", "mercado", "tendência"],
    "analise_complexa": ["analise", "análise", "arquitetura", "planeje", "estratégia"],
    "resumo_curto": ["resuma", "resumo", "tldr"],
    "classificacao": ["classifique", "categorize"],
    "geracao_imagem": ["imagem", "imagens", "foto", "ilustração", "arte", "desenho",
                       "gerar imagem", "cria imagem", "gera imagem", "criar imagem",
                       "faça uma imagem", "gerar foto", "criar arte", "renderizar",
                       "image", "generate image", "picture", "draw"],
}


# Verbos de ação: exigem modelo forte (ferramentas, navegador, arquivos).
# Mensagens curtas sem ação vão para o modelo local (economia de API).
ACOES = ("abra", "abrir", "crie", "criar", "list", "edit", "apag", "mova",
         "mover", "copi", "baix", "instal", "execut", "rodar", "rode",
         "grav", "tire", "tirar", "ligu", "ligar", "deslig", "envi", "salv",
         "pesquis", "naveg", "clic", "preench", "analis", "compare",
         "organiz", "corrija", "refator", "implement")


class LLMRouter:
    def __init__(self, settings: dict):
        self.settings = settings
        llm = settings["llm"]
        self.providers = {name: build_provider(name, cfg)
                          for name, cfg in llm["providers"].items()}
        self.routing = llm["routing"]
        self.default = llm["default_provider"]

    def classify(self, message: str) -> str:
        """Classificação leve por keywords (zero custo).
        Regra de ouro: tarefa com AÇÃO ou longa vai para o modelo forte (API);
        conversa curta e pergunta simples vai para o local (fallback barato)."""
        low = message.lower()
        if any(a in low for a in ACOES):
            return "analise_complexa"
        for task_type, kws in KEYWORDS.items():
            if any(k in low for k in kws):
                return task_type
        if len(message) > 160:
            return "analise_complexa"
        return "resposta_simples"

    def pick_provider(self, task_type: str):
        # Política: LOCAL primeiro; DeepSeek só para tarefas mais profundas
        # (código, arquitetura, análise complexa, pesquisa, prospecção — e o
        # loop de ferramentas do agente, que usa 'analise_complexa'). Em ambos
        # os casos o outro provider entra como fallback.
        profundas = set(self.routing.get("external", []))
        if task_type in profundas:
            order = self.routing["fallback_order"]            # deepseek primeiro
        else:
            resto = [n for n in self.routing["fallback_order"] if n != "ollama"]
            order = ["ollama"] + resto                        # local primeiro
        for name in order:
            if name in self.providers:
                return self.providers[name]
        return self.providers[self.default]

    def complete(self, task_type: str, system: str, user: str) -> str:
        return self._dispatch(task_type, lambda p: p.chat(system, user))

    def complete_messages(self, task_type: str, messages: list[dict],
                          forcar: str | None = None) -> str:
        return self._dispatch(task_type, lambda p: p.chat_messages(messages),
                              forcar=forcar)

    def complete_tools(self, task_type: str, messages: list[dict],
                       tools: list[dict], forcar: str | None = None):
        """Function calling nativo; devolve (provider, mensagem)."""
        provider = self.providers.get(forcar) if forcar else None
        provider = provider or self.pick_provider(task_type)
        try:
            return provider.name, provider.chat_tools(messages, tools)
        except Exception:
            for nome in self.routing["fallback_order"]:
                p = self.providers.get(nome)
                if p and p is not provider:
                    try:
                        return p.name, p.chat_tools(messages, tools)
                    except Exception:
                        continue
            raise

    def _dispatch(self, task_type: str, call, forcar: str | None = None) -> str:
        provider = self.providers.get(forcar) if forcar else None
        provider = provider or self.pick_provider(task_type)
        erros = []
        try:
            return call(provider)
        except Exception as exc:
            erros.append(f"{provider.name}: {exc}")
        # fallback: tenta os demais providers na ordem (ex.: DeepSeek caiu →
        # usa o modelo local). Era o plano desde o início.
        for name in self.routing["fallback_order"]:
            p = self.providers.get(name)
            if p and p is not provider:
                try:
                    return call(p)
                except Exception as exc:
                    erros.append(f"{p.name}: {exc}")
                    continue
        raise RuntimeError("Todos os provedores de IA falharam — "
                           + " | ".join(erros))
