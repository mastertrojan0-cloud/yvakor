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
- Para pesquisar use `navegador_pesquisar` (DuckDuckGo) — mais rápido e
  estável do que abrir o Google na mão.
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


_DSML_INVOKE = re.compile(
    r"<[^>\n]*DSML[^>\n]*invoke\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)"
    r"</[^>\n]*DSML[^>\n]*invoke>", re.S | re.I)
_DSML_PARAM = re.compile(
    r"<[^>\n]*DSML[^>\n]*parameter\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)"
    r"</[^>\n]*DSML[^>\n]*parameter>", re.S | re.I)


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
        if registry is not None and hasattr(registry, "coagir"):
            args = registry.coagir(nome, args)
        norm = _parse_acao(json.dumps({"acao": "usar_ferramenta",
                                       "ferramenta": nome, "args": args},
                                      ensure_ascii=False), registry)
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
                 max_ferramentas: int = 14, timeout_s: int = 300):
        self.router = router
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

    def _selecionar(self, history: list[dict]) -> list[str] | None:
        if not self.roteador:
            return None
        mensagem = ""
        for item in reversed(history):
            if item.get("role") == "user":
                mensagem = item.get("content") or ""
                break
        from yvakor.tools.router import selecionar
        self.ultima_selecao = selecionar(self.registry, mensagem,
                                         self.max_ferramentas)
        return self.ultima_selecao

    def system_with_tools(self, base_system: str,
                          nomes: list[str] | None = None) -> str:
        return base_system + "\n\n" + PROTOCOLO.format(
            manifesto=self.registry.manifest(nomes))

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

    def run(self, base_system: str, history: list[dict], on_event=None,
            should_stop=None, forcar_provider=None) -> str:
        """history = lista de {"role":"user"|"assistant","content":...}.
        on_event(tipo, dado) opcional p/ logar passos (ferramenta, observação).
        should_stop() opcional: retorna True para interromper (cancelamento de
        tarefa em segundo plano) entre um passo e outro."""
        self.artefatos = []   # zera a lista desta thread (ver properties acima)
        nomes = self._selecionar(history)
        messages = [{"role": "system",
                     "content": self.system_with_tools(base_system, nomes)}]
        messages += history

        # 1ª tentativa: function calling nativo (schema + validação).
        # Se o provedor não suportar, cai no protocolo JSON abaixo.
        if self.nativo and forcar_provider != "ollama":
            try:
                return self._run_nativo(messages, on_event, should_stop,
                                        forcar_provider, nomes)
            except Exception:
                pass

        inicio_run = time.time()
        for _ in range(self.max_iterations):
            if should_stop is not None and should_stop():
                return "⏹ Tarefa interrompida a pedido do usuário."
            if time.time() - inicio_run > self.timeout_s:
                aviso = (f"⏹ Interrompi a tarefa: excedi o limite de "
                         f"{self.timeout_s}s. O que já foi feito está no histórico.")
                try:
                    from yvakor.notificacoes import emitir
                    emitir(aviso, "tarefa", 2)
                except Exception:
                    pass
                return aviso
            raw = (self.router.complete_messages(
                "analise_complexa", messages, forcar=forcar_provider) or "").strip()
            acoes = _parse_acoes(raw, self.registry)

            # Nenhuma ferramenta reconhecida → resposta final (ou erro claro).
            if not acoes:
                texto = _extrair_resposta_final(raw)
                if '"usar_ferramenta"' in raw or '"ferramenta"' in raw:
                    aviso = ("Não consegui executar: vieram chamadas de "
                             "ferramenta em formato inválido. Tente de novo ou "
                             "peça em passos menores.")
                    try:
                        from yvakor.notificacoes import emitir
                        emitir(aviso, "tarefa", 2)
                    except Exception:
                        pass
                    return aviso
                return texto or "(sem resposta do modelo)"

            messages.append({"role": "assistant", "content": raw})
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
                if on_event:
                    on_event("observacao", {"nome": nome, "resultado": resultado})
                obs = json.dumps(resultado, ensure_ascii=False)[:2000]
                messages.append({"role": "user",
                                 "content": f"OBSERVAÇÃO ({nome}): {obs}"})

        # Esgotou os passos: pede uma síntese final em texto puro do que já foi feito.
        messages.append({"role": "user", "content":
                         "Pare de usar ferramentas e escreva agora a resposta "
                         "final em texto puro, resumindo o que foi feito."})
        final = (self.router.complete_messages(
            "analise_complexa", messages, forcar=forcar_provider) or "").strip()
        return _extrair_resposta_final(final) or \
            "Concluí os passos possíveis, mas não obtive resposta final."

    # ------------------------------------------------------------------ #
    # Function calling nativo
    # ------------------------------------------------------------------ #
    def _run_nativo(self, messages: list[dict], on_event, should_stop,
                    forcar_provider, nomes: list[str] | None = None) -> str:
        msgs = list(messages)
        esquemas = self.registry.schemas(nomes)
        for _ in range(self.max_iterations):
            if should_stop is not None and should_stop():
                return "⏹ Tarefa interrompida a pedido do usuário."
            _, msg = self.router.complete_tools(
                "analise_complexa", msgs, esquemas, forcar=forcar_provider)
            chamadas = msg.get("tool_calls") or []
            if not chamadas:
                texto = (msg.get("content") or "").strip()
                if texto:
                    return _extrair_resposta_final(texto)
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
                args = self.registry.coagir(nome, args if isinstance(args, dict) else {})
                if on_event:
                    on_event("ferramenta", {"nome": nome, "args": args})
                resultado = self.registry.run(nome, **args)
                self._coletar(resultado)
                if on_event:
                    on_event("observacao", {"nome": nome, "resultado": resultado})
                msgs.append({"role": "tool",
                             "tool_call_id": tc.get("id", "yvakor"),
                             "content": json.dumps(resultado, ensure_ascii=False)[:4000]})
        msgs.append({"role": "user", "content": "Resuma em texto o que foi feito."})
        return (self.router.complete_messages(
            "analise_complexa", msgs, forcar=forcar_provider) or "").strip()
