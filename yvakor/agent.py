"""
YVAKOR — Loop de Agente (function-calling estilo Claude Code)

A IA principal recebe o manifesto de ferramentas e decide, a cada passo, se
USA uma ferramenta ou RESPONDE ao usuário. Protocolo JSON (portável: funciona
com DeepSeek hoje e com Ollama local depois — sem depender da API nativa de
"tools" de nenhum fornecedor).

Cada passo:
  IA → {"acao":"usar_ferramenta","ferramenta":"...","args":{...}}
       → registry executa (ações perigosas passam pelo Confirmation Guard)
       → resultado volta como OBSERVAÇÃO
  IA → {"acao":"responder","texto":"..."}  → encerra e devolve ao usuário
"""
from __future__ import annotations
import json
import re

PROTOCOLO = """
## FERRAMENTAS DISPONÍVEIS
Você é um agente que EXECUTA tarefas reais no computador do usuário usando as
ferramentas abaixo. Use-as de verdade; não invente ferramentas.

{manifesto}

## POSTURA (MUITO IMPORTANTE)
- AJA POR PADRÃO. O usuário quer ações, não perguntas. Prefira executar a perguntar.
- OBEDEÇA O PEDIDO EXATAMENTE COMO FOI FEITO. NÃO reinterprete, NÃO "melhore",
  NÃO adicione o que não foi pedido. Se o usuário pediu X, faça X.
- NÃO faça perguntas de esclarecimento, exceto se for IMPOSSÍVEL agir sem um dado
  específico (ex.: um caminho que não dá para descobrir). Nesses casos, primeiro
  TENTE descobrir sozinho com as ferramentas (listar_diretorio, ler_arquivo_local).
- Quando faltar um detalhe não-crítico, ASSUMA um padrão sensato, AJA e diga
  no final qual suposição você fez.
- Tarefa que envolve criar/editar arquivo ou rodar comando → USE a ferramenta
  correspondente imediatamente. Não peça permissão (o sistema já trata segurança).
- Só use resposta em texto quando a ação estiver concluída ou quando o pedido for
  realmente apenas conversa/informação.
- NÃO crie nem edite arquivos para pedidos que são apenas conversa, confirmação,
  saudação ou para lembrar/repetir algo que já está no histórico. Nesses casos
  responda direto em texto. Só mexa em arquivos quando o usuário pedir um
  artefato concreto (gerar/salvar/editar algo) ou quando for indispensável para
  cumprir a tarefa.

## PROTOCOLO DE RESPOSTA (OBRIGATÓRIO)
Há apenas DUAS formas de responder:

1) Para USAR UMA FERRAMENTA — responda com UM ÚNICO objeto JSON e NADA mais:

   {{"acao":"usar_ferramenta","ferramenta":"nome_exato","args":{{...}},"motivo":"curto"}}

   EXEMPLOS REAIS (observe o formato exato dos campos):
   {{"acao":"usar_ferramenta","ferramenta":"listar_diretorio","args":{{"caminho":"."}},"motivo":"ver arquivos"}}
   {{"acao":"usar_ferramenta","ferramenta":"ler_arquivo_local","args":{{"caminho":"C:\\\\projeto\\\\readme.md"}},"motivo":"ler"}}
   {{"acao":"usar_ferramenta","ferramenta":"executar_shell","args":{{"comando":"dir"}},"motivo":"listar"}}

   REGRAS DO JSON DA FERRAMENTA:
   - O campo "acao" é SEMPRE a string exata "usar_ferramenta"
   - O campo "ferramenta" é SEMPRE um nome da lista acima (copie exatamente)
   - O campo "args" é SEMPRE um objeto {{}} com os parâmetros da ferramenta
   - NÃO invente ferramentas que não estão na lista
   - NÃO coloque texto antes ou depois do JSON — apenas o JSON puro

2) Para RESPONDER AO USUÁRIO — escreva sua resposta final em TEXTO NORMAL
   (português, markdown livre). NÃO use JSON na resposta final.

Regras:
- Um passo por vez. Após cada ferramenta você verá a OBSERVAÇÃO e decide o próximo.
- Quando for chamar ferramenta, o JSON deve ser a ÚNICA coisa na mensagem.
- Não repita uma ferramenta que já falhou do mesmo jeito; mude de abordagem.
- Encadeie ferramentas até concluir a tarefa; só então escreva a resposta final.
- A resposta final resume o que você FEZ e o resultado concreto.
- **SEMPRE indique o caminho absoluto de qualquer arquivo gerado** (ex.: imagens, PDFs,
  planilhas, documentos). Exemplo: "Imagem salva em E:\\YVAKOR\\yvakor\\data\\downloads\\..."
- O sistema é WINDOWS: em executar_shell use comandos do Windows (cmd/PowerShell),
  ex.: `dir`, `type`, `findstr`. NÃO use bash (`ls`, `wc`, `2>/dev/null`).
- Prefira as ferramentas próprias (listar_diretorio, ler_arquivo_local) ao shell
  quando elas já resolvem — são mais confiáveis.

## GERAÇÃO DE IMAGENS
Quando o usuário pedir uma imagem, use a ferramenta `gerar_imagem_higgsfield` (preferida)
ou `gerar_imagem`. REGRAS CRÍTICAS:

- O prompt da imagem DEVE SER EXATAMENTE o que o usuário escreveu.
  NÃO reescreva, NÃO "melhore", NÃO adicione adjetivos nem estilos.
  Se o usuário escreveu "gato preto", o prompt é "gato preto". PONTO.
- Se for preciso traduzir para inglês, traduza LITERALMENTE, sem floreios.
  "cachorro no parque" → "dog in the park". NÃO vire "golden retriever playing
  happily in a sunlit green park with butterflies".
- SÓ adicione qualidade/estilo se o usuário NÃO especificou nenhum.
  Nesse caso, adicione APENAS: ", photorealistic, high quality".
- Se o usuário já descreveu estilo (ex.: "anime", "3d", "desenho"), NÃO adicione
  "photorealistic" por cima. Respeite o estilo que ele pediu.
- Após gerar, SEMPRE informe o caminho absoluto onde a imagem foi salva.
- Se `gerar_imagem_higgsfield` falhar, use `gerar_imagem`.
"""


def _extrair_resposta_final(raw: str) -> str:
    """Se o modelo respondeu no formato JSON {"acao":"responder", ...} em vez
    de texto puro (acontece com alguns modelos), extrai só o texto. Caso
    contrário devolve o conteúdo original intacto."""
    raw = raw.strip()
    candidatos = [raw]
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        candidatos.append(m.group(0))
    for c in candidatos:
        try:
            obj = json.loads(c)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("acao") == "responder":
            for chave in ("texto", "conteudo", "resposta", "content", "text"):
                val = obj.get(chave)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return raw


def _parse_acao(raw: str, registry=None) -> dict | None:
    """Detecta uma chamada de ferramenta. Aceita 3 formatos:
    1) {"acao":"usar_ferramenta","ferramenta":"X","args":{...},"motivo":"..."}
    2) {"acao":"X","args":{...},"motivo":"..."}  (shorthand: acao=nome ferramenta)
    3) {"ferramenta":"X","args":{...}}           (formato simplificado)"""
    raw = raw.strip()
    candidatos = [raw]
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        candidatos.append(m.group(0))
    for c in candidatos:
        try:
            obj = json.loads(c)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        acao = obj.get("acao", "")
        ferramenta = obj.get("ferramenta", "")
        args = obj.get("args")
        if acao == "usar_ferramenta" and ferramenta:
            if registry and ferramenta not in registry.tools:
                continue  # ferramenta inventada: ignora, vai para texto
            return obj
        if ferramenta and args is not None:
            if registry and ferramenta not in registry.tools:
                continue
            obj["acao"] = "usar_ferramenta"
            return obj
        if acao and acao != "usar_ferramenta" and acao != "responder" \
                and args is not None:
            if registry and acao not in registry.tools:
                continue  # acao que nao e ferramenta real: ignora
            obj = {"acao": "usar_ferramenta", "ferramenta": acao,
                   "args": args, "motivo": obj.get("motivo", "")}
            return obj
    return None


class AgentLoop:
    def __init__(self, router, registry, max_iterations: int = 8):
        self.router = router
        self.registry = registry
        self.max_iterations = max_iterations

    def system_with_tools(self, base_system: str) -> str:
        return base_system + "\n\n" + PROTOCOLO.format(
            manifesto=self.registry.manifest())

    def run(self, base_system: str, history: list[dict], on_event=None) -> str:
        """history = lista de {"role":"user"|"assistant","content":...}.
        on_event(tipo, dado) opcional p/ logar passos (ferramenta, observação)."""
        messages = [{"role": "system", "content": self.system_with_tools(base_system)}]
        messages += history

        for _ in range(self.max_iterations):
            raw = (self.router.complete_messages("analise_complexa", messages) or "").strip()
            acao = _parse_acao(raw, self.registry)

            # Não é chamada de ferramenta → é a resposta final.
            if acao is None:
                return _extrair_resposta_final(raw) or "(sem resposta do modelo)"

            nome = acao.get("ferramenta", "")
            args = acao.get("args", {}) or {}
            if on_event:
                on_event("ferramenta", {"nome": nome, "args": args,
                                        "motivo": acao.get("motivo", "")})
            resultado = self.registry.run(nome, **args) \
                if isinstance(args, dict) else \
                {"ok": False, "error": "args inválidos"}
            if on_event:
                on_event("observacao", {"nome": nome, "resultado": resultado})
            obs = json.dumps(resultado, ensure_ascii=False)[:4000]
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"OBSERVAÇÃO ({nome}): {obs}"})

        # Esgotou os passos: pede uma síntese final em texto puro do que já foi feito.
        messages.append({"role": "user", "content":
                         "Pare de usar ferramentas e escreva agora a resposta "
                         "final em texto puro, resumindo o que foi feito."})
        final = (self.router.complete_messages("analise_complexa", messages) or "").strip()
        return _extrair_resposta_final(final) or \
            "Concluí os passos possíveis, mas não obtive resposta final."
