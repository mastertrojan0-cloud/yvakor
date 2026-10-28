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
import threading
import time

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

## CONTROLE DO NAVEGADOR (tarefas na web)
Você tem navegadores REAIS — **Edge e Chrome**, cada um com perfil próprio
(logins separados). Escolha o motor pelo parâmetro `navegador` ("edge" ou
"chrome"); sem ele, usa o motor padrão ou o do contexto da tarefa.
1. `navegador_abrir` (primeira vez) ou `navegador_ir` para navegar.
2. `navegador_ver` SEMPRE antes de agir: devolve URL, texto visível e os
   elementos interativos com refs (e1, e2, …).
3. Aja pela ref: `navegador_clicar` {{"alvo":"e3"}} ·
   `navegador_preencher` {{"alvo":"e2","valor":"..."}} (enviar=true dá Enter).
4. Depois de clicar/navegar, chame `navegador_ver` de novo — as refs antigas
   expiram quando a página muda.
5. `navegador_motores` mostra o estado de cada navegador. Se precisar de uma
   janela já aberta pelo usuário, use `navegador_conectar` (CDP).

Regras do navegador:
- NUNCA invente refs. Se o alvo não existir, peça um novo `navegador_ver`.
- Para pesquisar use `navegador_pesquisar` (buscador=google|duckduckgo|bing|
  youtube) — mais rápido e estável do que abrir o site na mão.
- Escrever: `navegador_digitar` {{"alvo":"e2","texto":"..."}} acrescenta ao campo
  (limpar=true substitui; enviar=true envia o formulário). `navegador_preencher`
  substitui o conteúdo. Sem `alvo` usa o campo focado/de busca. Funciona em
  editores de texto rico (Gmail, Notion, chats). Caixa de marcar: preencher com
  "sim"/"não".
- Página grande? `navegador_procurar` {{"consulta":"campo de busca"}} acha só o
  elemento descrito (com ref), sem ler a página toda.
- Listas: `navegador_selecionar` {{"alvo":"e5","valor":"Portugal"}}.
- Anexar arquivo: `navegador_enviar_arquivo` {{"caminho":"C:/docs/cv.pdf","alvo":"e7"}} (o usuário confirma).
- Teclas: `navegador_pressionar` {{"tecla":"Enter"}} (aceita Control+A, Tab,
  Escape, ArrowDown…). Menus que abrem ao passar o mouse: `navegador_passar_mouse`.
- Página lenta: `navegador_esperar` {{"texto":"Resultados"}} ou {{"seletor":"#lista"}}.
  Voltar/avançar/recarregar: `navegador_historico`. Print: `navegador_captura`.
- Se uma ação devolver "aviso" ou "erro", rode `navegador_ver` e tente de novo
  com a ref correta.
- Leia páginas longas com `navegador_extrair` em vez de despejar tudo no
  contexto; role a página com `navegador_rolar` quando o conteúdo continua.
- Prefira o navegador ao `http_get` quando a página depende de JavaScript,
  login ou cookies.
- Login: o perfil é persistente entre execuções. Se pedir senha e você não
  tiver a credencial, PARE e peça ao usuário para entrar manualmente.
- CAPTCHA / 2FA: avise o usuário e espere intervenção humana. Não tente burlar.
- Só feche o navegador (`navegador_fechar`) se o usuário pedir.

## ACESSO AO SISTEMA (privilégios totais)
Você tem os MESMOS privilégios do usuário no computador. Use as ferramentas
`arquivos_*` para arquivos e pastas em qualquer lugar (fora do projeto também):
- `arquivos_listar`, `arquivos_ler`, `arquivos_buscar` para explorar;
- `arquivos_escrever` (modo=anexar), `arquivos_editar` (literal ou regex),
  `arquivos_criar_pasta`, `arquivos_copiar`, `arquivos_mover`;
- `arquivos_apagar` — por padrão vai para data/lixeira (recuperável). Só use
  `permanente=True` se o usuário pedir explicitamente;
- `arquivos_zipar` / `arquivos_extrair`.
Regras: use caminho ABSOLUTO e diga no final o caminho exato do que mudou.
Não mexa em pastas de sistema (Windows, Program Files) sem o usuário pedir.
Toda ação fica registrada em data/auditoria.jsonl.

## REDE LOCAL (câmeras, TVs, celulares, IoT)
Você alcança os dispositivos da rede local desta máquina. Antes de agir:
1. `rede_escanear` → descobre o que existe (câmera, tv, telefone, iot, roteador).
2. `rede_dispositivos` → inventário já conhecido (com nomes que o usuário deu).
3. Aja pela ferramenta certa:
   - câmera: `rede_camera_snapshot` (foto), `rede_camera_ptz` (mover),
     `rede_camera_gravar` (clipe), `rede_camera_info` (modelo/perfis).
   - TV: `rede_tv` (acao=ligar|desligar|tecla|volume|app|status).
   - Chromecast: `rede_cast` (acao=tocar|pausar|continuar|parar|volume|status).
   - celular Android: `rede_telefone_tela`, `rede_telefone_acao`.
   - IoT: `rede_http_dispositivo` (Tasmota/Shelly), `rede_mqtt_publicar/ler`,
     `rede_wol` (ligar PC/TV por rede).
4. Se a câmera pedir senha: NÃO tente adivinhar. Peça ao usuário e salve com
   `rede_camera_credenciais` (fica em data/rede.json, fora do git).
5. Fora da rede local o acesso é NEGADO por política. Não contorne: explique.
6. Nunca mexa em aparelho que o usuário não pediu. Descobrir ≠ autorizar uso.

## VOZ (falar e ouvir)
- `voz_falar` fala no alto-falante desta máquina. Use quando o usuário pedir
  "fale", "diga em voz alta" ou em tarefas de aviso.
- `voz_transcrever` converte um arquivo de áudio em texto.
- `voz_ouvir` só funciona com microfone e alguém falando agora (em tarefa de
  segundo plano prefira `voz_transcrever`).

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


# Protocolo ENXUTO para o modelo local (3B em CPU). O PROTOCOLO completo + o
# system prompt passam de ~7k caracteres e levam ~110s por passo neste hardware;
# este cabe em ~2k e mantém só o essencial do contrato JSON.
PROTOCOLO_COMPACTO = """## FERRAMENTAS
{manifesto}

## COMO RESPONDER
- Para usar uma ferramenta responda SOMENTE com um JSON neste formato, sem
  texto extra (use EXATAMENTE os nomes de argumentos da lista acima):
  {exemplo}
- Para responder ao usuário escreva texto normal em português (sem JSON).
- Uma ferramenta por vez; depois da OBSERVAÇÃO decida o próximo passo.
- Não invente ferramentas, caminhos nem resultados. O sistema é Windows.
"""


from yvakor.textos import sem_json_de_ferramenta  # noqa: E402
from yvakor import raciocinio  # noqa: E402

# Resposta que "desiste" sem ter tentado: o modelo via no histórico uma falha
# antiga da extensão ("não está respondendo") e repetia isso SEM chamar
# nenhuma ferramenta — a extensão estava conectada e nunca foi acionada.
_DESISTENCIA = re.compile(
    r"(n[aã]o (consigo|consegui|posso|tenho como)|sem (acesso|ferramenta)|"
    r"n[aã]o tenho (nenhuma )?(ferramenta|acesso)|indispon[ií]ve|"
    r"n[aã]o (est[aá] )?respond|sem responder|reative|reativ[ae]|"
    r"abra o painel|clique no [ií]cone)", re.I)
INSISTIR_NAVEGADOR = (
    "Você respondeu sem chamar NENHUMA ferramenta. As ferramentas de navegador "
    "estão disponíveis agora e a extensão do Chrome está conectada; falhas "
    "citadas em mensagens antigas desta conversa já foram resolvidas e não "
    "valem para agora. Chame a ferramenta adequada (ex.: navegador_ver para "
    "ler a página atual, navegador_ir para abrir um site) e só responda depois "
    "da observação.")


# "Preenchi o formulário…" sem nenhum preenchimento ter dado certo: a resposta
# afirma uma ação que as ferramentas não confirmaram.
_ALEGACOES = (
    (re.compile(r"\b(preenchi|preenchid[oa]s?|digitei|inseri)\b", re.I),
     ("navegador_preencher", "navegador_digitar"), "preencheu"),
    (re.compile(r"\b(cliquei|clicado|apertei)\b", re.I), ("navegador_clicar",), "clicou"),
    (re.compile(r"\b(selecionei)\b", re.I), ("navegador_selecionar",), "selecionou"),
    (re.compile(r"\b(enviei o formul|submeti)", re.I),
     ("navegador_clicar", "navegador_preencher", "navegador_pressionar"), "enviou"),
)


AVISO_SEM_PROVA = ("⚠️ Atenção: as ferramentas NÃO confirmaram a ação descrita "
                   "abaixo (as tentativas falharam). Confira na página antes de "
                   "confiar nesta resposta.\n\n")


def alegacao_sem_prova(texto: str, resultados: dict[str, list[bool]]) -> str | None:
    """Mensagem de correção se o texto final alega uma ação de navegador sem
    NENHUMA execução bem-sucedida da ferramenta correspondente nesta tarefa."""
    if not texto:
        return None
    for padrao, ferramentas, verbo in _ALEGACOES:
        if not padrao.search(texto):
            continue
        tentou = [ok for f in ferramentas for ok in resultados.get(f, [])]
        if not any(tentou):
            return (f"Sua resposta diz que {verbo}, mas nenhuma chamada de "
                    f"{' / '.join(ferramentas)} teve sucesso nesta tarefa "
                    f"({'todas falharam' if tentou else 'nenhuma foi feita'}). Não "
                    "afirme o que não aconteceu: tente de novo com os argumentos "
                    "certos (alvo = ref do navegador_ver, valor = texto) ou diga "
                    "claramente o que NÃO conseguiu fazer.")
    return None


def desistiu_sem_tentar(texto: str, nomes: list[str] | None,
                        ferramentas_usadas: int) -> bool:
    """True se a resposta final alega não conseguir usar o navegador sem que
    nenhuma ferramenta tenha rodado nesta execução, tendo navegador_* à mão."""
    if ferramentas_usadas or not texto:
        return False
    if not any(n.startswith("navegador_") for n in (nomes or [])):
        return False
    return bool(_DESISTENCIA.search(texto))


def _extensao_conectada() -> bool:
    try:
        from yvakor.extensao_bridge import PONTE
        return bool(PONTE.disponivel())
    except Exception:
        return False


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
    return sem_json_de_ferramenta(raw)


# Nomes que o modelo inventa com frequência → a ferramenta real equivalente.
_ALIAS_FERRAMENTA = {
    "navegador_ler": "navegador_extrair", "navegador_texto": "navegador_extrair",
    "navegador_navegar": "navegador_ir", "navegador_buscar": "navegador_pesquisar",
    "navegador_screenshot": "navegador_captura", "navegador_scroll": "navegador_rolar",
    "navegador_click": "navegador_clicar", "navegador_type": "navegador_digitar",
}
# Argumentos com nome trocado ("query" em vez de "termo", "tab_id" em vez de
# "aba"): o coagir descartava e a ferramenta falhava por falta de argumento.
_ALIAS_ARGS = {"query": "termo", "q": "termo", "busca": "termo", "texto_busca": "termo",
               "tab_id": "aba", "tab": "aba", "tabId": "aba", "link": "url",
               # alvo de clique/preenchimento (o modelo usa a ref do navegador_ver)
               "ref": "alvo", "seletor": "alvo", "selector": "alvo", "elemento": "alvo",
               "element": "alvo", "target": "alvo", "campo": "alvo", "botao": "alvo",
               "value": "valor", "text": "texto", "key": "tecla"}


_CHAVES_PROTOCOLO = {"acao", "ferramenta", "tool", "name", "motivo", "args",
                     "arguments", "parametros", "texto", "pensamento"}


def _alias_args(registry, ferramenta: str, args: dict) -> dict:
    esperados = ((getattr(registry, "specs", {}) or {}).get(ferramenta) or {}).get("args") or {}
    if not esperados:
        return args
    novo = dict(args)
    for de, para in _ALIAS_ARGS.items():
        if de in novo and de not in esperados and para in esperados and para not in novo:
            novo[para] = novo.pop(de)
    return novo


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
        # {"tool": "x", "arguments": {...}} (formato de outros modelos)
        ferramenta = obj.get("ferramenta") or obj.get("tool") or obj.get("name") or ""
        args = next((obj[k] for k in ("args", "arguments", "parametros")
                     if k in obj), None)
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = None
        if args is None and (ferramenta or acao not in ("", "responder")):
            # argumentos "soltos" no objeto: {"ferramenta":"http_get","url":"…"}.
            # Antes viravam args=None e a ferramenta rodava VAZIA (http_get {}).
            soltos = {k: v for k, v in obj.items() if k not in _CHAVES_PROTOCOLO}
            if soltos:
                args = soltos
            elif ferramenta:
                args = {}
        if ferramenta and registry is not None and ferramenta not in registry.tools:
            ferramenta = _ALIAS_FERRAMENTA.get(ferramenta, ferramenta)
        alvo_args = ferramenta or (acao if acao not in ("", "usar_ferramenta", "responder") else "")
        if isinstance(args, dict) and alvo_args and registry is not None:
            args = _alias_args(registry, alvo_args, args)
        obj = {**obj, "ferramenta": ferramenta, "args": args}
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


_DSML_INVOKE = re.compile(
    r"<[^>\n]*DSML[^>\n]*invoke\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)"
    r"</[^>\n]*DSML[^>\n]*invoke>", re.S | re.I)
_DSML_PARAM = re.compile(
    r"<[^>\n]*DSML[^>\n]*parameter\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)"
    r"</[^>\n]*DSML[^>\n]*parameter>", re.S | re.I)


_MARCACAO_FERRAMENTA = re.compile(
    r"DSML|\"usar_ferramenta\"|\"(ferramenta|tool)\"\s*:\s*\"|<tool_\w+>")

# Formato XML que o DeepSeek às vezes usa:
# <tool_browser_navigate><url>https://…</url></tool_browser_navigate>
_TOOL_XML = re.compile(r"<tool_(\w+)>(.*?)</tool_\1>", re.S)
_TOOL_XML_ARG = re.compile(r"<(\w+)>(.*?)</\1>", re.S)
_ALIAS_XML = {
    "browser_navigate": "navegador_ir", "browser_open": "navegador_abrir",
    "browser_click": "navegador_clicar", "browser_type": "navegador_digitar",
    "browser_fill": "navegador_preencher", "browser_snapshot": "navegador_ver",
    "browser_read": "navegador_extrair", "browser_extract": "navegador_extrair",
    "browser_search": "navegador_pesquisar", "browser_scroll": "navegador_rolar",
    "browser_press": "navegador_pressionar", "browser_screenshot": "navegador_captura",
    "browser_wait": "navegador_esperar",
}


def _parse_acoes(raw: str, registry=None) -> list[dict]:
    """Extrai TODAS as chamadas de ferramenta: JSON e formato DSML."""
    dec = json.JSONDecoder()
    acoes, i = [], 0
    # 1) Formato DSML (DeepSeek): <｜｜DSML｜｜ invoke name="x"> ... </...>
    for m in _DSML_INVOKE.finditer(raw):
        nome = m.group(1).strip()
        args = {}
        for p in _DSML_PARAM.finditer(m.group(2)):
            args[p.group(1).strip()] = p.group(2).strip()
        if registry is not None:
            nome = nome if nome in getattr(registry, "tools", {}) else \
                _ALIAS_FERRAMENTA.get(nome, nome)
            # traduz nomes ANTES do coagir: ele descartava "ref"/"seletor" e o
            # clique ia sem alvo ("elemento não encontrado")
            args = _alias_args(registry, nome, args)
        if isinstance(args.get("campos"), str):          # vários campos (lista JSON)
            try:
                args["campos"] = json.loads(args["campos"])
            except Exception:
                pass
        if registry is not None and hasattr(registry, "coagir") and \
                not isinstance(args.get("campos"), list):
            args = registry.coagir(nome, args)
        norm = _parse_acao(json.dumps({"acao": "usar_ferramenta",
                                       "ferramenta": nome, "args": args},
                                      ensure_ascii=False), registry)
        if norm:
            acoes.append(norm)
    if acoes:
        return acoes
    # 1b) <tool_nome><arg>valor</arg></tool_nome>
    for m in _TOOL_XML.finditer(raw):
        nome = _ALIAS_XML.get(m.group(1), m.group(1))
        if registry is not None and nome not in registry.tools \
                and "navegador_" + m.group(1) in registry.tools:
            nome = "navegador_" + m.group(1)
        args = {a.group(1): a.group(2).strip() for a in _TOOL_XML_ARG.finditer(m.group(2))}
        norm = _parse_acao(json.dumps({"acao": "usar_ferramenta", "ferramenta": nome,
                                       "args": args}, ensure_ascii=False), registry)
        if norm:
            acoes.append(norm)
    if acoes:
        return acoes
    # 2) JSON no meio de prosa
    while True:
        j = raw.find("{", i)
        if j < 0:
            break
        try:
            obj, fim = dec.raw_decode(raw[j:])
        except Exception:
            i = j + 1
            continue
        i = j + fim
        if isinstance(obj, dict):
            norm = _parse_acao(json.dumps(obj, ensure_ascii=False), registry)
            if norm:
                acoes.append(norm)
    return acoes


class AgentLoop:
    def __init__(self, router, registry, max_iterations: int = 8,
                 nativo: bool = False, roteador: bool = True,
                 max_ferramentas: int = 14, timeout_s: int = 300,
                 raciocinio: dict | None = None):
        self.router = router
        # Método de raciocínio (ver yvakor/raciocinio.py): plano explícito
        # antes de tarefas de vários passos e conferência antes da resposta
        # final. Desligado por padrão aqui; o orquestrador liga pelo settings.
        cfg = raciocinio or {}
        self.planejar = bool(cfg.get("planejar", False))
        self.verificar = bool(cfg.get("verificar", False))
        self.registry = registry
        self.max_iterations = max_iterations
        self.nativo = nativo
        self.roteador = roteador
        self.max_ferramentas = max_ferramentas
        self.timeout_s = timeout_s
        # Estado por-requisição em thread-local: uma mesma instância de
        # AgentLoop é usada pelo chat E por tarefas cowork em paralelo. Guardar
        # artefatos/seleção em atributos simples fazia uma execução vazar na
        # outra (entregáveis trocados). Com thread-local cada run() é isolado.
        self._tl = threading.local()

    @property
    def artefatos(self) -> list[dict]:
        lst = getattr(self._tl, "artefatos", None)
        if lst is None:
            lst = []
            self._tl.artefatos = lst
        return lst

    @artefatos.setter
    def artefatos(self, valor: list[dict]) -> None:
        self._tl.artefatos = valor

    @property
    def ultima_selecao(self) -> list[str]:
        v = getattr(self._tl, "ultima_selecao", None)
        if v is None:
            v = []
            self._tl.ultima_selecao = v
        return v

    @ultima_selecao.setter
    def ultima_selecao(self, valor: list[str]) -> None:
        self._tl.ultima_selecao = valor

    def _selecionar(self, history: list[dict],
                    limite: int | None = None) -> list[str] | None:
        if not self.roteador and limite is None:
            return None
        mensagem = ""
        for item in reversed(history):
            if item.get("role") == "user":
                mensagem = item.get("content") or ""
                break
        from yvakor.tools.router import selecionar
        if limite is not None and self._INTENCAO_NAVEGADOR.search(mensagem or ""):
            # Tarefa de navegador precisa de mais ferramentas juntas (ver +
            # pesquisar + ir + clicar + preencher + digitar + pressionar…).
            limite = max(limite, self.COMPACTO_MAX_FERRAMENTAS_NAVEGADOR)
        self.ultima_selecao = selecionar(self.registry, mensagem,
                                         limite or self.max_ferramentas)
        if limite is not None:           # modo compacto (modelo local)
            self.ultima_selecao = self._limitar_compacto(
                self.ultima_selecao, mensagem, limite)
        elif self._conversa_de_navegador(history) and _extensao_conectada():
            # Continuação de uma conversa sobre o navegador ("analisa a
            # página", "e o spam?"): sem isto o modelo ficava sem navegador_*.
            nucleo = [n for n in self.NUCLEO_NAVEGADOR
                      if n in self.registry.tools and n not in self.ultima_selecao]
            self.ultima_selecao = nucleo + list(self.ultima_selecao)
        return self.ultima_selecao

    NUCLEO_NAVEGADOR = ("navegador_ver", "navegador_extrair", "navegador_ir",
                        "navegador_pesquisar", "navegador_clicar",
                        "navegador_digitar")

    def _conversa_de_navegador(self, history: list[dict]) -> bool:
        """A mensagem atual ou um dos turnos recentes envolve o navegador."""
        for item in history[-5:]:
            texto = item.get("content") or ""
            if isinstance(texto, str) and (
                    self._INTENCAO_NAVEGADOR.search(texto)
                    or re.search(r"\b(gmail|e-?mail|extens[aã]o|navegador)\b",
                                 texto, re.I)):
                return True
        return False

    COMPACTO_MAX_FERRAMENTAS_NAVEGADOR = 8
    # Pedido que envolve o navegador (pesquisar, digitar, clicar, abrir site…).
    _INTENCAO_NAVEGADOR = re.compile(
        r"\b(pesquis|busc|procur|naveg|clic|digit|escrev|preench|formul|googl|"
        r"youtube|abr[aeio]|aperte|pression|rol[ae]|chrome|edge|campo|seleci|"
        r"marc[ae]|espere|aguard|volt[ae]|recarreg|avanc|p[aá]gina|site|link|"
        r"aba\b|tecla|enter|login|entrar|acess|captur|print)", re.I)

    # Pedido que cita ação de risco de forma explícita (rodar/apagar/mover/
    # escrever/instalar/enviar…): só então o modelo local recebe essas ferramentas.
    _ACAO_EXPLICITA = re.compile(
        r"\b(execut|rod[ae]r?\b|shell|comando|cmd\b|powershell|terminal|apag|"
        r"delet|remov|exclu|mov[ae]r?\b|renome|escrev|salv|edit|instal|baix|"
        r"envi|manda|publi)", re.I)
    # Conjunto mínimo e SEGURO quando nada casa com a mensagem.
    _BASE_SEGURA = ("pesquisa_web", "cerebro_buscar", "arquivos_listar",
                    "arquivos_ler", "http_get")

    def _limitar_compacto(self, nomes: list[str], mensagem: str,
                          limite: int) -> list[str]:
        """O seletor devolve TODAS as ferramentas quando nada casa, ignorando o
        limite — no modelo local isso viraria um prompt gigantesco (~110s por
        7k caracteres). E 'executar_shell' entra sempre como núcleo, então o 3B
        chamava shell para qualquer coisa (ex.: `bitcoin-cli` p/ cotação).
        Aqui: respeita o limite, usa uma base segura se nada casou e só libera
        ferramentas que exigem confirmação se o pedido for explícito."""
        disponiveis = set(self.registry.tools)
        perigosas = set(getattr(getattr(self.registry, "guard", None),
                                "always_confirm", ()) or ())
        if len(nomes) >= len(disponiveis) > limite:
            nomes = []                           # nada casou: não é "tudo"
        if not self._ACAO_EXPLICITA.search(mensagem or ""):
            nomes = [n for n in nomes if n not in perigosas]
        if self._INTENCAO_NAVEGADOR.search(mensagem or ""):
            # ferramentas de navegador na frente: o corte por limite não pode
            # trocá-las por arquivos_listar/cerebro_buscar (núcleo).
            nomes = sorted(nomes, key=lambda n: 0 if n.startswith("navegador_") else 1)
        for n in self._BASE_SEGURA:              # completa com o seguro
            if len(nomes) >= limite:
                break
            if n in disponiveis and n not in nomes:
                nomes.append(n)
        return nomes[:limite]

    def system_with_tools(self, base_system: str,
                          nomes: list[str] | None = None,
                          compacto: bool = False) -> str:
        if compacto:
            # Manifesto enxuto: 1 linha curta por ferramenta (o texto completo
            # de ~14 ferramentas é o que mais pesa no prompt do modelo local).
            manifesto = "\n".join(
                linha[:170] for linha in self.registry.manifest(nomes).splitlines())
            # Exemplo CONCRETO com a 1ª ferramenta e os nomes reais dos
            # argumentos: o 3B inventava nomes ("numero1") quando só via um
            # molde genérico, e a chamada falhava.
            primeira = (nomes or list(self.registry.specs))[:1]
            args_ex = {}
            if primeira:
                for arg, tipo in (self.registry.specs.get(primeira[0], {})
                                  .get("args") or {}).items():
                    args_ex[arg] = 0 if str(tipo).rstrip("?") in (
                        "int", "float") else "..."
            exemplo = json.dumps(
                {"acao": "usar_ferramenta",
                 "ferramenta": primeira[0] if primeira else "nome_exato",
                 "args": args_ex}, ensure_ascii=False)
            texto = PROTOCOLO_COMPACTO.format(manifesto=manifesto, exemplo=exemplo)
            if any(n.startswith("navegador_") for n in (nomes or [])):
                texto += ("- Navegador: primeiro navegador_ver (mostra refs e1, e2…), "
                          "depois aja pela ref com navegador_clicar / "
                          "navegador_digitar / navegador_preencher; para buscar use "
                          "navegador_pesquisar. Depois de clicar ou navegar, chame "
                          "navegador_ver de novo. Em página grande, "
                          "navegador_procurar acha só o elemento descrito.\n")
            return base_system + "\n\n" + texto + raciocinio.METODO_COMPACTO
        return base_system + "\n\n" + PROTOCOLO.format(
            manifesto=self.registry.manifest(nomes)) + raciocinio.METODO

    def _planejar(self, messages: list[dict], history: list[dict], on_event,
                  forcar_provider, compacto: bool) -> dict | None:
        """Plano explícito antes de uma tarefa de vários passos (1 chamada
        extra ao modelo, só quando a heurística indica vários passos)."""
        if not self.planejar or compacto:
            return None
        pedido = next((h.get("content") or "" for h in reversed(history)
                       if h.get("role") == "user"), "")
        if not isinstance(pedido, str) or not raciocinio.precisa_planejar(pedido):
            return None
        try:
            raw = self.router.complete_messages(
                "analise_complexa",
                messages + [{"role": "user", "content": raciocinio.PEDIR_PLANO}],
                forcar=forcar_provider) or ""
        except Exception:
            return None
        plano = raciocinio.ler_plano(raw)
        if plano and on_event:
            on_event("plano", plano)
        return plano

    @staticmethod
    def _janela(messages: list[dict], base: int, manter: int = 14) -> list[dict]:
        """Janela deslizante: em tarefas longas o contexto crescia sem limite
        (a cada passo + observação), estourava a janela do modelo (HTTP 400) e
        caía no fallback 3B, que 'concluía' a tarefa com lixo silencioso.
        Mantém o system + o histórico original (base) e os últimos `manter`
        passos, resumindo os do meio."""
        if len(messages) <= base + manter:
            return messages
        cabeca = messages[:base]
        cauda = messages[-manter:]
        nota = {"role": "user",
                "content": "(… passos intermediários omitidos para caber no "
                           "contexto; use a observação mais recente …)"}
        return cabeca + [nota] + cauda

    def _coletar(self, resultado) -> None:
        """Guarda imagens, relatórios, planilhas e fotos geradas."""
        if isinstance(resultado, list):
            for item in resultado:
                self._coletar(item)
            return
        if not isinstance(resultado, dict):
            return
        for chave in ("fotos", "arquivos", "artefatos"):
            if isinstance(resultado.get(chave), list):
                for item in resultado[chave]:
                    self._coletar(item)
        from pathlib import Path
        from urllib.parse import quote
        from yvakor.config import ROOT
        url = str(resultado.get("url") or "")
        caminho = str(resultado.get("arquivo") or resultado.get("caminho") or "")
        tipo = ""
        if url.startswith("http://127.0.0.1:7777"):
            url = url.split("7777", 1)[1]
        if "/projetos/" in url:
            tipo = "projeto"
        if caminho:
            p = Path(caminho)
            ext = p.suffix.lower()
            try:
                rel = p.resolve().relative_to((ROOT / "data").resolve())
                partes = rel.parts
            except Exception:
                partes = ()
            if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif") and partes:
                if partes[0] in ("imagens", "graficos"):
                    url = f"/midia/{partes[0]}/{quote(p.name)}"
                    tipo = "imagem"
                elif partes[0] == "artefatos":
                    url = f"/artefatos/{quote('/'.join(partes[1:]))}"
                    tipo = "imagem"
            elif partes and partes[0] == "artefatos":
                url = f"/artefatos/{quote('/'.join(partes[1:]))}"
                tipo = {".pdf": "pdf", ".xlsx": "planilha", ".csv": "planilha",
                        ".docx": "documento", ".html": "relatorio",
                        ".zip": "pacote", ".md": "texto"}.get(ext, "arquivo")
            elif ext in (".html", ".htm") and "projetos" in p.parts:
                slug = p.parent.name
                url = f"/projetos/{slug}/index.html"
                tipo = "projeto"
        if not (url and tipo):
            return
        if any(a.get("url") == url for a in self.artefatos):
            return
        self.artefatos.append({
            "tipo": tipo, "url": url,
            "titulo": resultado.get("titulo") or
                      (Path(caminho).name if caminho else ""),
            "caminho": caminho,
            "nome": Path(caminho).name if caminho else "",
            "fonte": resultado.get("fonte") or "",
            "autor": resultado.get("autor") or "",
            "licenca": resultado.get("licenca") or "",
            "url_origem": resultado.get("url_origem") or ""})

    # Modo compacto (modelo local): cada passo é lento, então menos passos e
    # um teto de tempo bem maior; cada chamada ao modelo ganha timeout próprio.
    COMPACTO_MAX_PASSOS = 8
    COMPACTO_TIMEOUT_TOTAL_S = 900
    COMPACTO_TIMEOUT_CHAMADA_S = 240
    COMPACTO_MAX_FERRAMENTAS = 5

    def run(self, base_system: str, history: list[dict], on_event=None,
            should_stop=None, forcar_provider=None,
            compacto: bool = False) -> str:
        """history = lista de {"role":"user"|"assistant","content":...}.
        on_event(tipo, dado) opcional p/ logar passos (ferramenta, observação).
        should_stop() opcional: retorna True para interromper (cancelamento de
        tarefa em segundo plano) entre um passo e outro."""
        self.artefatos = []   # zera a lista desta thread (ver properties acima)
        nomes = self._selecionar(
            history, self.COMPACTO_MAX_FERRAMENTAS if compacto else None)
        messages = [{"role": "system",
                     "content": self.system_with_tools(base_system, nomes,
                                                       compacto)}]
        messages += history
        plano = self._planejar(messages, history, on_event, forcar_provider,
                               compacto)
        if plano:
            messages.append({"role": "user",
                             "content": raciocinio.bloco_plano(plano)})
        base = len(messages)   # system + histórico (+ plano): nunca podados

        # 1ª tentativa: function calling nativo (schema + validação).
        # Se o provedor não suportar, cai no protocolo JSON abaixo — MAS só se
        # nenhuma ferramenta já tiver rodado, para não re-executar ações com
        # efeito colateral (ex.: enviar e-mail duas vezes). A exceção é logada,
        # não engolida em silêncio (A4).
        if self.nativo and forcar_provider != "ollama" and not compacto:
            estado = {"ferramentas": 0}
            try:
                return self._run_nativo(messages, on_event, should_stop,
                                        forcar_provider, nomes, estado, plano)
            except Exception as exc:
                import logging
                logging.getLogger("yvakor.agent").warning(
                    "loop nativo falhou (%s); %s", exc,
                    "abortando (ferramentas já executadas)"
                    if estado["ferramentas"] else "caindo para o protocolo JSON")
                if estado["ferramentas"]:
                    return ("⚠️ A tarefa foi interrompida por um erro no modo "
                            "nativo após já executar ferramentas; não repeti "
                            "as ações para evitar efeitos duplicados. "
                            f"Detalhe: {str(exc)[:200]}")

        inicio_run = time.time()
        max_passos = (min(self.max_iterations, self.COMPACTO_MAX_PASSOS)
                      if compacto else self.max_iterations)
        limite_s = (max(self.timeout_s, self.COMPACTO_TIMEOUT_TOTAL_S)
                    if compacto else self.timeout_s)
        kw_modelo = ({"timeout": self.COMPACTO_TIMEOUT_CHAMADA_S}
                     if compacto else {})
        usadas = 0
        insistiu = False
        correcoes = 0
        feitos: dict[str, list[bool]] = {}     # ferramenta → sucesso de cada chamada
        cobrou_prova = False
        reflexao = raciocinio.Reflexao()
        verificou = False
        for _ in range(max_passos):
            if should_stop is not None and should_stop():
                return "⏹ Tarefa interrompida a pedido do usuário."
            if time.time() - inicio_run > limite_s:
                aviso = (f"⏹ Interrompi a tarefa: excedi o limite de "
                         f"{limite_s}s. O que já foi feito está no histórico.")
                try:
                    from yvakor.notificacoes import emitir
                    emitir(aviso, "tarefa", 2)
                except Exception:
                    pass
                return aviso
            raw = (self.router.complete_messages(
                "analise_complexa", self._janela(messages, base),
                forcar=forcar_provider, **kw_modelo) or "").strip()
            acoes = _parse_acoes(raw, self.registry)

            # Nenhuma ferramenta reconhecida → resposta final (ou erro claro).
            if not acoes:
                texto = _extrair_resposta_final(raw)
                if _MARCACAO_FERRAMENTA.search(raw) and correcoes < 2:
                    # Marcação quebrada ou ferramenta inventada: antes a tarefa
                    # inteira abortava com "formato inválido" (mesmo após 11
                    # ferramentas certas). Agora pede a chamada de novo.
                    correcoes += 1
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": (
                        "Chamada de ferramenta inválida (formato errado ou "
                        "ferramenta inexistente). Use exatamente o JSON "
                        '{"acao":"usar_ferramenta","ferramenta":"<nome>","args":{...}} '
                        "com uma destas ferramentas: "
                        + ", ".join(nomes or list(self.registry.tools)[:40])
                        + ". Se já tem o que precisa, escreva a resposta final "
                        "em texto puro.")})
                    continue
                if _MARCACAO_FERRAMENTA.search(raw) and usadas:
                    break           # já trabalhou: pede a síntese final abaixo
                if _MARCACAO_FERRAMENTA.search(raw):
                    aviso = ("Não consegui executar: vieram chamadas de "
                             "ferramenta em formato inválido. Tente de novo ou "
                             "peça em passos menores.")
                    try:
                        from yvakor.notificacoes import emitir
                        emitir(aviso, "tarefa", 2)
                    except Exception:
                        pass
                    return aviso
                if not insistiu and desistiu_sem_tentar(texto, nomes, usadas):
                    insistiu = True
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": INSISTIR_NAVEGADOR})
                    continue
                cobranca = alegacao_sem_prova(texto, feitos)
                if cobranca and not cobrou_prova:
                    cobrou_prova = True
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": cobranca})
                    continue
                if self._deve_verificar(verificou, usadas, plano):
                    verificou = True
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user",
                                     "content": raciocinio.pedido_verificacao(plano)})
                    continue
                if cobranca:
                    texto = AVISO_SEM_PROVA + texto
                return texto or "(sem resposta do modelo)"

            messages.append({"role": "assistant", "content": raw})
            usadas += len(acoes)
            for acao in acoes:
                nome = acao.get("ferramenta", "")
                args = acao.get("args", {}) or {}
                if on_event:
                    on_event("ferramenta", {"nome": nome, "args": args,
                                            "motivo": acao.get("motivo", "")})
                resultado = self.registry.run(nome, **args) \
                    if isinstance(args, dict) else \
                    {"ok": False, "error": "args inválidos"}
                self._coletar(resultado)
                feitos.setdefault(nome, []).append(
                    bool(isinstance(resultado, dict) and resultado.get("ok")))
                if on_event:
                    on_event("observacao", {"nome": nome, "resultado": resultado})
                obs = (json.dumps(resultado, ensure_ascii=False, default=str)[:2000]
                       + reflexao.registrar(nome, args, resultado))
                messages.append({"role": "user",
                                 "content": f"OBSERVAÇÃO ({nome}): {obs}"})

        # Esgotou os passos: pede uma síntese final em texto puro do que já foi feito.
        messages.append({"role": "user", "content":
                         "Pare de usar ferramentas e escreva agora a resposta "
                         "final em texto puro, resumindo o que foi feito."})
        final = (self.router.complete_messages(
            "analise_complexa", self._janela(messages, base),
            forcar=forcar_provider, **kw_modelo) or "").strip()
        final = _extrair_resposta_final(final)
        if final and alegacao_sem_prova(final, feitos):
            final = AVISO_SEM_PROVA + final
        return final or "Concluí os passos possíveis, mas não obtive resposta final."

    # ------------------------------------------------------------------ #
    # Function calling nativo
    # ------------------------------------------------------------------ #
    # Conferência final só quando houve trabalho de verdade: tarefa planejada
    # ou várias ferramentas. Pergunta simples não paga a chamada extra.
    VERIFICAR_A_PARTIR_DE = 3

    def _deve_verificar(self, verificou: bool, usadas: int,
                        plano: dict | None) -> bool:
        return (self.verificar and not verificou and usadas > 0
                and (plano is not None or usadas >= self.VERIFICAR_A_PARTIR_DE))

    def _run_nativo(self, messages: list[dict], on_event, should_stop,
                    forcar_provider, nomes: list[str] | None = None,
                    estado: dict | None = None,
                    plano: dict | None = None) -> str:
        msgs = list(messages)
        esquemas = self.registry.schemas(nomes)
        inicio_run = time.time()
        usadas = 0
        insistiu = False
        vazamentos = 0
        feitos: dict[str, list[bool]] = {}
        cobrou_prova = False
        reflexao = raciocinio.Reflexao()
        verificou = False
        for _ in range(self.max_iterations):
            if should_stop is not None and should_stop():
                return "⏹ Tarefa interrompida a pedido do usuário."
            if time.time() - inicio_run > self.timeout_s:
                return (f"⏹ Interrompi a tarefa: excedi o limite de "
                        f"{self.timeout_s}s. O que já foi feito está no histórico.")
            _, msg = self.router.complete_tools(
                "analise_complexa", msgs, esquemas, forcar=forcar_provider)
            chamadas = msg.get("tool_calls") or []
            if not chamadas:
                texto = (msg.get("content") or "").strip()
                if _MARCACAO_FERRAMENTA.search(texto) and vazamentos < 3:
                    # Chamada escrita como TEXTO (DSML/JSON) em vez de
                    # tool_calls: antes virava a "resposta final" com a
                    # marcação crua. Executa se for válida; senão pede de novo.
                    vazamentos += 1
                    acoes = _parse_acoes(texto, self.registry)
                    msgs.append({"role": "assistant", "content": texto})
                    if not acoes:
                        msgs.append({"role": "user", "content": (
                            "Sua chamada de ferramenta veio como texto e/ou com "
                            "ferramenta inexistente. Use a chamada de função "
                            "nativa, só com estas ferramentas: "
                            + ", ".join(nomes or list(self.registry.tools)[:40])
                            + ". Para ler campos de formulário use navegador_ver.")})
                        continue
                    for acao in acoes:
                        nome = acao.get("ferramenta", "")
                        args = acao.get("args", {}) or {}
                        if on_event:
                            on_event("ferramenta", {"nome": nome, "args": args})
                        if estado is not None:
                            estado["ferramentas"] += 1
                        usadas += 1
                        resultado = self.registry.run(nome, **args) \
                            if isinstance(args, dict) else \
                            {"ok": False, "error": "args inválidos"}
                        self._coletar(resultado)
                        feitos.setdefault(nome, []).append(bool(resultado.get("ok")))
                        if on_event:
                            on_event("observacao", {"nome": nome, "resultado": resultado})
                        msgs.append({"role": "user", "content": (
                            f"OBSERVAÇÃO ({nome}): "
                            + json.dumps(resultado, ensure_ascii=False, default=str)[:4000]
                            + reflexao.registrar(nome, args, resultado))})
                    continue
                if not insistiu and desistiu_sem_tentar(texto, nomes, usadas):
                    insistiu = True
                    msgs.append({"role": "assistant", "content": texto})
                    msgs.append({"role": "user", "content": INSISTIR_NAVEGADOR})
                    continue
                cobranca = alegacao_sem_prova(texto, feitos)
                if cobranca and not cobrou_prova:
                    cobrou_prova = True
                    msgs.append({"role": "assistant", "content": texto})
                    msgs.append({"role": "user", "content": cobranca})
                    continue
                if texto and self._deve_verificar(verificou, usadas, plano):
                    verificou = True
                    msgs.append({"role": "assistant", "content": texto})
                    msgs.append({"role": "user",
                                 "content": raciocinio.pedido_verificacao(plano)})
                    continue
                if texto:
                    return (AVISO_SEM_PROVA if cobranca else "") + \
                        _extrair_resposta_final(texto)
                return "(sem resposta do modelo)"
            msgs.append({"role": "assistant",
                         "content": msg.get("content") or "",
                         "tool_calls": chamadas})
            for tc in chamadas:
                fn = tc.get("function") or {}
                nome = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                args = _alias_args(self.registry, nome, args if isinstance(args, dict) else {})
                if "campos" not in args:            # o run expande "campos" (vários)
                    args = self.registry.coagir(nome, args)
                if on_event:
                    on_event("ferramenta", {"nome": nome, "args": args})
                if estado is not None:
                    estado["ferramentas"] += 1
                usadas += 1
                resultado = self.registry.run(nome, **args)
                self._coletar(resultado)
                feitos.setdefault(nome, []).append(bool(resultado.get("ok")))
                if on_event:
                    on_event("observacao", {"nome": nome, "resultado": resultado})
                msgs.append({"role": "tool",
                             "tool_call_id": tc.get("id", "yvakor"),
                             "content": json.dumps(resultado, ensure_ascii=False,
                                                   default=str)[:4000]
                                        + reflexao.registrar(nome, args, resultado)})
        msgs.append({"role": "user", "content": "Resuma em texto o que foi feito."})
        return (self.router.complete_messages(
            "analise_complexa", msgs, forcar=forcar_provider) or "").strip()
