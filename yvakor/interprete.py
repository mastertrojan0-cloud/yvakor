"""YVAKOR — intérprete de pedidos (entender antes de agir).

Nas conversas reais, o agente falhava por não entender o pedido, não por
falta de ferramenta:
  "busque no google earth a localização de Maturín" → gerou uma imagem;
  "errado"                                         → repetiu a resposta;
  "excelente, busca a casa 6 na rua 26 …"          → perdeu o contexto
                                                     (Maturín) e desistiu.

Antes do agente, este módulo:
  1. corrige erros de digitação que atrapalham a escolha de ferramenta;
  2. classifica o pedido: correção, continuação ou novo; nos dois primeiros
     herda o pedido e a resposta anteriores;
  3. traduz serviços citados pelo nome (Google Earth, Maps, YouTube…) no
     caminho certo, com a URL pronta;
  4. só quando ainda é ambíguo, pede ao modelo uma reescrita curta (1 chamada).

Depois do agente, `desistiu_apos_tentar` detecta a resposta que larga a
tarefa no meio e `bloco_resgate` monta a segunda tentativa por outro caminho.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote_plus
import logging

_log = logging.getLogger(__name__)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# ---------------------------------------------------------------------- #
# 1. Digitação
# ---------------------------------------------------------------------- #
# Palavras que decidem a ferramenta; erro nelas = ferramenta errada.
VOCABULARIO = """
localizacao endereco mapa mapas busque busca buscar pesquise pesquisar procure
procurar dispositivo dispositivos camera cameras celular telefone impressora
roteador internet rede wifi arquivo arquivos pasta documento planilha grafico
relatorio imagem imagens foto fotos video videos musica navegador pagina site
abrir abra excelente obrigado nenhum nenhuma identificar identifique melhor
calcular calcule conversa email mensagem enviar baixar download instalar
configurar computador programa aplicativo urbanizacao avenida bairro cidade
estado pais rua casa numero coordenadas satelite rota distancia
""".split()
_VOC = set(VOCABULARIO)


def corrigir_digitacao(texto: str) -> tuple[str, list[str]]:
    """Corrige só palavras longas que quase batem com o vocabulário."""
    correcoes = []

    def _troca(m: re.Match) -> str:
        palavra = m.group(0)
        n = _norm(palavra)
        if len(n) < 5 or n in _VOC:
            return palavra
        achou = difflib.get_close_matches(n, VOCABULARIO, n=1, cutoff=0.84)
        if not achou or achou[0] == n:
            return palavra
        correcoes.append(f"{palavra}→{achou[0]}")
        return achou[0]

    return re.sub(r"[A-Za-zÀ-ÿ]+", _troca, texto or ""), correcoes


# ---------------------------------------------------------------------- #
# 2. Tipo de pedido
# ---------------------------------------------------------------------- #
_CORRECAO = re.compile(
    r"^\s*(errado|errou|incorreto|nao (e|era|foi) (isso|assim|esse|essa)|"
    r"nao\b|ta errado|esta errado|de novo|nada a ver|nao funcionou|"
    r"nao deu certo|continua (errado|igual)|nao e o que (eu )?pedi)", re.I)
_CONTINUACAO = re.compile(
    r"^\s*(excelente|otimo|perfeito|beleza|show|massa|legal|ok|certo|isso|"
    r"agora|entao|e (agora|tambem|o|a|os|as)|tambem|depois|em seguida|"
    r"continua|continue|segue|siga|faz|faca|mais)\b", re.I)
_REFERENCIA = re.compile(
    r"\b(ele|ela|eles|elas|isso|isto|esse|essa|este|esta|la|ali|aqui|nele|"
    r"nela|dele|dela|mesmo lugar|mesma (cidade|pagina|pasta)|o mesmo|a mesma)\b",
    re.I)


def classificar(mensagem: str, tem_historico: bool) -> str:
    n = _norm(mensagem)
    if not tem_historico:
        return "novo"
    if _CORRECAO.search(n) and len(n.split()) <= 12:
        return "correcao"
    if (_CONTINUACAO.search(n) or _APROVACAO.search(n)
            or (_REFERENCIA.search(n) and len(n.split()) <= 15)):
        return "continuacao"
    return "novo"


# ---------------------------------------------------------------------- #
# Conversa casual × tarefa (decide o atalho do modelo local)
# ---------------------------------------------------------------------- #
# Antes o atalho decidia pelo TAMANHO do texto (até 160 caracteres = "simples")
# e mandava ao modelo local, sem ferramentas: "deleta os temporários",
# "verifica os drivers", "sim" e "eu estou autorizando" eram respondidos por
# ele com recusa, promessa vazia ou tutorial genérico (conversa 71).
_APROVACAO = re.compile(
    r"^\s*(sim|s|pode|pode sim|pode ir|procede|prossiga|prosseguir|vai|manda|"
    r"bora|dale|confirmo|confirmado|autoriz\w*|claro|faz|faca|executa|segue|"
    r"siga|aprovado|ok pode|com certeza)\b|\b(estou |te |lhe )?autoriz\w*|"
    # "você escolha o melhor caminho e resolva": aprova o que estava em curso
    r"\b(voce|vc) (escolh|decid)\w*|\bresolv(a|e)\b|\bde qualquer (forma|jeito)", re.I)
# Radicais de verbos de ação (pt/es), casados no INÍCIO da palavra.
_ACAO = re.compile(
    r"\b(delet|apag|limp|remov|exclu|elimin|borr|verific|cheq|chec|confer|"
    r"atualiz|actualiz|instal|desinstal|organiz|arrum|mov|copi|cri[ae]|abr[aei]|"
    r"execut|rod[ae]|proced|prossig|continu|fa[cz]|mostr|list|busc|procur|"
    r"pesquis|baix|descarg|envi|mand|configur|consert|corrig|repar|otimiz|"
    r"escane|monitor|ger[ae]|calcul|convert|compact|extra[ia]|salv|imprim|"
    r"deslig|lig[ue]|reinici|desativ|ativ|escrev|edit|renome|agend|lembr|"
    r"analis|compar|diagnost|test|med[ei]|acess|naveg|clic|preench|digit|"
    r"tir[ae]|grav|traduz|resum|tabel|planilh|relat)\w*", re.I)
# Coisas do computador/rede/arquivos: pedir sobre elas é tarefa, não papo.
_SISTEMA = re.compile(
    r"\b(arquivo|pasta|diretorio|driver|drivers|computador|pc|notebook|windows|"
    r"sistema|disco|hd|ssd|memoria|ram|cpu|processador|rede|wifi|internet|"
    r"roteador|programa|app|aplicativo|software|temp|temporari\w*|lixo|lixeira|"
    r"cache|navegador|chrome|edge|site|pagina|email|e-mail|whatsapp|camera|"
    r"impressora|celular|tela|janela|download\w*|backup|senha|usuario|"
    r"atualizac\w*|virus|antivirus|bateria|placa|bios|porta|servidor)\b", re.I)
# Só papo vai ao modelo local. Pergunta de conhecimento ("o que é MCP?") ia
# também, e o 3B inventava ("sistema operacional da IBM", exame de 29/10);
# o DeepSeek responde isso em 1–2 s.
_CASUAL = re.compile(
    r"^\s*(oi|ola+|e ai|eai|bom dia|boa tarde|boa noite|hey|hello|hola|"
    r"obrigad\w*|valeu|vlw|tmj|gracias|tudo bem|tudo certo|como (vai|voce esta|vc ta)|"
    r"quem e voce|conta uma piada|me conta uma piada|piada|kkk+|haha+|rs+)\b", re.I)


def conversa_casual(mensagem: str, historico: list[dict] | None = None) -> bool:
    """True só para papo/pergunta geral que o modelo local responde bem
    sem ferramentas. Na dúvida, False (vai ao agente com o modelo forte)."""
    n = _norm(mensagem).strip()
    if not n:
        return False
    hist = [m for m in (historico or []) if m.get("content")]
    if hist:
        # resposta a uma pergunta/proposta do agente, aprovação ou continuação
        ultima = next((m["content"] for m in reversed(hist)
                       if m.get("role") == "assistant"), "")
        if ultima.rstrip().endswith("?") or classificar(n, True) != "novo":
            return False
    if _APROVACAO.search(n) or _ACAO.search(n) or _SISTEMA.search(n):
        return False
    return bool(_CASUAL.search(n))


# ---------------------------------------------------------------------- #
# 3. Serviços citados pelo nome
# ---------------------------------------------------------------------- #
SERVICOS = (
    ("google earth", "https://earth.google.com/web/search/{q}",
     "Abra o Google Earth com navegador_ir nessa URL e confirme com "
     "navegador_ver/captura. NÃO use gerar_imagem: o usuário quer o mapa real."),
    ("google maps", "https://www.google.com/maps/search/{q}",
     "Abra o Google Maps com navegador_ir nessa URL; leia o resultado na página."),
    ("street view", "https://www.google.com/maps/search/{q}",
     "Abra o Maps nessa URL e entre no Street View pela página."),
    ("youtube", "https://www.youtube.com/results?search_query={q}",
     "Abra a busca do YouTube com navegador_ir nessa URL."),
    ("mercado livre", "https://lista.mercadolivre.com.br/{q}",
     "Abra a busca do Mercado Livre com navegador_ir nessa URL."),
    ("wikipedia", "https://pt.wikipedia.org/w/index.php?search={q}",
     "Leia com web_ler ou navegador_ir nessa URL."),
)
_LUGAR = re.compile(
    r"(?:localiza[cç][aã]o|endere[cç]o|mapa|rota|onde fica|busc\w*|procur\w*|"
    r"pesquis\w*|mostr\w*|abr[ae]|ach[ae])\s+(?:d[aeo]s?|em|no|na|por|para|o|a)?\s*(.+)",
    re.I)
_PREFIXO_SERV = re.compile(
    r"^(?:no|na|pelo|pela|o|a|em)?\s*(google earth|google maps|street view|"
    r"youtube|mercado livre|wikipedia)\s*(?:a|o|e|,)?\s*", re.I)


def _consulta(mensagem: str, nome: str) -> str:
    texto = re.sub(rf"\b{re.escape(nome)}\b", " ", mensagem, flags=re.I)
    m = _LUGAR.search(texto)
    alvo = (m.group(1) if m else texto)
    alvo = _PREFIXO_SERV.sub("", alvo.strip())
    alvo = re.sub(r"^(?:a|o)\s+(localiza[cç][aã]o|endere[cç]o)\s+d[aeo]\s+", "", alvo, flags=re.I)
    return re.sub(r"\s+", " ", alvo).strip(" .?!,")


def servicos(mensagem: str, contexto: str = "") -> list[dict]:
    n = _norm(mensagem)
    out = []
    for nome, url, instrucao in SERVICOS:
        if nome in n:
            q = _consulta(mensagem, nome) or contexto
            out.append({"servico": nome, "url": url.format(q=quote_plus(q)),
                        "consulta": q, "instrucao": instrucao})
    return out


# ---------------------------------------------------------------------- #
# 3b. Intenção → ferramentas indicadas (o YVAKOR comanda, o modelo executa)
# ---------------------------------------------------------------------- #
# Exame de 29/10: com as ferramentas certas na lista, o modelo ia de shell
# (ls -la no Windows, PowerShell de 7 passos), recusava "deleta os
# temporários" e trocava sistema_drivers por sistema_drivers_atualizar. Para
# as tarefas que o YVAKOR já sabe fazer, ele diz qual ferramenta e em que ordem.
INTENCOES = (
    ("organizar pastas",
     re.compile(r"\b(organiz\w*|arrum\w*|bagun\w*)\b.*\b(pasta|arquivo|download|"
                r"desktop|area de trabalho|documento|computador|pc)", re.I),
     ["organizar_analisar()", "organizar_plano()", "organizar_executar(plano_id)"],
     "só move (nada é apagado) e organizar_desfazer desfaz; Downloads/Documentos "
     "podem estar em outro disco — a ferramenta já sabe onde"),
    ("limpar temporários/lixo",
     re.compile(r"\b(temporari\w*|temporais|temp|lixo|lixeira|cache)\b", re.I),
     ["limpar_temporarios()", "esvaziar_lixeira() se pediram o lixo/lixeira"],
     "é seguro: arquivos em uso ficam; a confirmação vem sozinha na execução"),
    ("otimizar o PC",
     re.compile(r"\b(otimiz\w*|aceler\w*|mais rapido|pc lento|computador lento|"
                r"liberar espaco|libera espaco)\b", re.I),
     ["limpar_temporarios()", "esvaziar_lixeira()", "organizar_analisar()",
      "sistema_drivers()"],
     "execute a limpeza e reporte MB liberados; não devolva scripts ao usuário"),
    ("atualizar/reparar drivers",
     # imperativo: "atualiza/atualize/resolva" — "precisam ser atualizados" é
     # só verificar
     re.compile(r"(?=.*\bdrivers?\b).*\b(atualiz(a|e|ar|em)|resolv(a|e|er)|repar(a|e|ar)|"
                r"instal(a|e|ar)|corri(ja|ge|gir))\b", re.I),
     ["sistema_drivers()", "sistema_drivers_atualizar(acao=\"auto\")"],
     "o UAC do Windows é a confirmação; não chame sistema_drivers com 'acao'"),
    ("verificar drivers",
     re.compile(r"\bdrivers?\b", re.I),
     ["sistema_drivers()"],
     "uma chamada traz problemas, drivers antigos e Windows Update — não use shell"),
    ("o que está no VS Code",
     re.compile(r"\b(vs ?code|vscode|editor)\b|\b(selecionei|selecionad[ao]|"
                r"este arquivo|esse arquivo|arquivo aberto|esta funcao|essa funcao)\b", re.I),
     ["leia o bloco VS CODE do prompt (já traz arquivo e seleção)",
      "vscode_contexto() se precisar de mais", "vscode_abrir(arquivo, linha) para mostrar"],
     "NÃO use navegador nem a extensão do Chrome para isso"),
    ("verificar vírus",
     re.compile(r"\b(escane\w*|varr\w*|verific\w*|analis\w*|pass\w* o antivirus|"
                r"procur\w*)\b.*\b(virus|malware|ameaca|trojan)|"
                r"\b(virus|malware)\b.*\b(escane\w*|varr\w*|verific\w*|procur\w*)", re.I),
     ["guardiao_verificar()", "guardiao_escanear(tipo=\"rapida\")"],
     "o Windows Defender verifica em segundo plano e o guardião avisa ao terminar"),
    ("segurança do PC/rede",
     re.compile(r"\b(virus|malware|hacker|hack\w*|invad\w*|invasao|seguranca|"
                r"antivirus|ameaca|trojan|ransomware|espiao|guardiao|protecao)\b", re.I),
     ["guardiao_status()", "guardiao_verificar() se pedir para checar agora"],
     "só observa e avisa; nunca bloqueia nem apaga"),
    ("aparelhos da rede",
     re.compile(r"\b(dispositivos?|aparelhos?)\b.*\b(rede|wifi|conectad\w*)\b", re.I),
     ["rede_dispositivos()", "rede_escanear() se a lista estiver velha"], ""),
)


def ferramentas_indicadas(texto: str) -> list[tuple[str, list[str], str]]:
    """Intenções reconhecidas no texto, com as ferramentas na ordem de uso."""
    n = _norm(texto)
    achadas, vistas = [], set()
    for nome, rx, ferramentas, nota in INTENCOES:
        geral = {"verificar drivers": "atualizar/reparar drivers",
                 "segurança do PC/rede": "verificar vírus"}
        if rx.search(n) and geral.get(nome) not in vistas:
            achadas.append((nome, ferramentas, nota))
            vistas.add(nome)
    return achadas


# ---------------------------------------------------------------------- #
# 4. Interpretação completa
# ---------------------------------------------------------------------- #
@dataclass
class Interpretacao:
    original: str
    corrigido: str
    tipo: str = "novo"
    correcoes: list[str] = field(default_factory=list)
    pedido_anterior: str = ""
    resposta_anterior: str = ""
    servicos: list[dict] = field(default_factory=list)
    objetivo: str = ""
    passos: list[str] = field(default_factory=list)
    usou_modelo: bool = False
    indicadas: list[tuple[str, list[str], str]] = field(default_factory=list)

    def util(self) -> bool:
        return bool(self.correcoes or self.tipo != "novo" or self.servicos
                    or self.objetivo or self.indicadas)

    def bloco(self, limite: int = 1400) -> str:
        if not self.util():
            return ""
        linhas = ["## INTERPRETAÇÃO DO PEDIDO (leia antes de agir)"]
        if self.correcoes:
            linhas.append(f"- Leia como: \"{self.corrigido}\" "
                          f"(digitação corrigida: {', '.join(self.correcoes)}).")
        if self.tipo == "correcao":
            linhas += [
                "- É uma CORREÇÃO da sua resposta anterior, não um pedido novo.",
                f"- Pedido que ficou errado: \"{self.pedido_anterior[:300]}\"",
                f"- Sua resposta anterior (início): \"{self.resposta_anterior[:250]}\"",
                "- NÃO repita essa resposta. Descubra o que não atendeu ao pedido "
                "(ferramenta errada, dado inventado, ação não feita) e refaça por "
                "OUTRO caminho, com ferramentas.",
            ]
        elif self.tipo == "continuacao":
            linhas += [
                "- CONTINUA o pedido anterior: mesmo lugar, site, arquivo ou assunto.",
                f"- Pedido anterior: \"{self.pedido_anterior[:300]}\"",
                "- Complete o que faltar com esse contexto em vez de perguntar.",
            ]
        for s in self.servicos:
            linhas.append(f"- Serviço citado: {s['servico']} → {s['url']} — {s['instrucao']}")
        for nome, ferramentas, nota in self.indicadas:
            linhas.append(f"- Ferramentas indicadas ({nome}), nesta ordem: "
                          + " → ".join(ferramentas) + (f". {nota}." if nota else "."))
        if self.indicadas:
            linhas.append("- Use essas ferramentas em vez de executar_shell/python e "
                          "EXECUTE: o pedido do usuário já é a autorização.")
        if self.objetivo:
            linhas.append(f"- Objetivo provável: {self.objetivo}")
        for i, p in enumerate(self.passos[:5], 1):
            linhas.append(f"  {i}. {p}")
        return "\n".join(linhas)[:limite]

    def texto_para_ferramentas(self) -> str:
        """Pedido expandido usado na escolha de ferramentas."""
        partes = [self.corrigido]
        if self.tipo != "novo" and self.pedido_anterior:
            partes.append(self.pedido_anterior)
        partes += [s["servico"] + " navegador" for s in self.servicos]
        if self.objetivo:
            partes.append(self.objetivo)
        return " | ".join(partes)


def _anteriores(historico: list[dict]) -> tuple[str, str]:
    """Último pedido 'de verdade' (pula correções curtas) e última resposta."""
    resposta = next((m["content"] for m in reversed(historico)
                     if m.get("role") == "assistant"), "")
    pedidos = [m["content"] for m in historico if m.get("role") == "user"]
    for p in reversed(pedidos):
        if classificar(p, True) != "correcao":
            return p, resposta
    return (pedidos[-1] if pedidos else ""), resposta


PROMPT_MODELO = """Você interpreta pedidos de um usuário brasileiro para um agente com \
ferramentas (navegador, arquivos, rede, código). O texto pode ter erros de digitação, \
abreviações e depender da conversa anterior.

Pedido anterior: {anterior}
Resposta anterior do agente (início): {resposta}
Mensagem atual: {atual}
Tipo detectado: {tipo}

Responda só JSON: {{"objetivo": "o que o usuário quer, completo e explícito, \
com o contexto herdado", "passos": ["até 4 passos concretos com ferramentas"]}}"""


def interpretar(mensagem: str, historico: list[dict] | None = None,
                router=None, usar_modelo: bool = True) -> Interpretacao:
    historico = [m for m in (historico or []) if m.get("content")]
    corrigido, correcoes = corrigir_digitacao(mensagem)
    tipo = classificar(corrigido, bool(historico))
    it = Interpretacao(original=mensagem, corrigido=corrigido, tipo=tipo,
                       correcoes=correcoes)
    if tipo != "novo":
        it.pedido_anterior, it.resposta_anterior = _anteriores(historico)
    # na continuação/correção vale a intenção herdada ("sim", "faz novamente")
    it.indicadas = ferramentas_indicadas(
        corrigido if tipo == "novo" else f"{corrigido} {it.pedido_anterior}")
    contexto = _consulta(it.pedido_anterior, "") if it.pedido_anterior else ""
    it.servicos = servicos(corrigido, contexto)
    if tipo != "novo" and not it.servicos and it.pedido_anterior:
        # serviço citado no pedido anterior vale para a continuação/correção
        anteriores = servicos(it.pedido_anterior)
        if anteriores and tipo == "correcao":
            it.servicos = anteriores
        elif anteriores and _LUGAR.search(corrigido):
            # "busca a casa 6 na rua 26" depois de "google earth … maturín":
            # mesma ferramenta, consulta atual + lugar herdado
            alvo = _consulta(_CONTINUACAO.sub("", _norm(corrigido), count=1)
                             .lstrip(" ,"), "")
            for s in anteriores:
                q = f"{alvo} {contexto}".strip()
                base = next(u for n, u, _ in SERVICOS if n == s["servico"])
                it.servicos.append({**s, "consulta": q,
                                    "url": base.format(q=quote_plus(q))})
    if usar_modelo and router is not None and tipo != "novo":
        try:
            raw = router.complete_messages(
                "formatacao",
                [{"role": "system", "content": "Responda apenas JSON válido."},
                 {"role": "user", "content": PROMPT_MODELO.format(
                     anterior=it.pedido_anterior[:500],
                     resposta=it.resposta_anterior[:400],
                     atual=corrigido[:500], tipo=tipo)}],
                forcar="deepseek", timeout=20)
            m = re.search(r"\{.*\}", raw or "", re.S)
            dados = json.loads(m.group(0)) if m else {}
            it.objetivo = str(dados.get("objetivo") or "")[:400]
            it.passos = [str(p)[:200] for p in (dados.get("passos") or [])][:4]
            it.usou_modelo = bool(it.objetivo)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
    return it


# ---------------------------------------------------------------------- #
# 5. Resgate: desistiu depois de tentar
# ---------------------------------------------------------------------- #
_LARGOU = re.compile(
    r"(parei de (insistir|tentar)|n[aã]o (consegui|foi poss[ií]vel|deu para)|"
    r"n[aã]o existe nesta instala|n[aã]o vou repetir|"
    r"(voc[eê]|vc) (pode|precisa|poderia) (copiar|colar|abrir|clicar|me (enviar|passar|dizer))|"
    r"copie (a|o) (url|link)|me (diga|informe|confirme) (qual|se|onde)|"
    r"qual (das )?op[cç](ão|ões|oes) (voc[eê] )?prefer)", re.I)


def desistiu_apos_tentar(resposta: str, passos: int, falhas: int = 0) -> bool:
    if not resposta or passos == 0:
        return False
    # Só a ABERTURA conta: resposta completa com uma seção "o que não foi
    # possível" no fim não é desistência (disparava 2ª tentativa à toa).
    return bool(_LARGOU.search(resposta[:350])) or (falhas >= 3 and passos >= 4)


def bloco_resgate(resposta: str, ferramentas: list[str], erros: list[str]) -> str:
    usadas = ", ".join(dict.fromkeys(ferramentas)) or "nenhuma"
    falhas = "; ".join(e[:120] for e in erros[:4]) or "—"
    return (
        "## RESGATE (2ª tentativa — a anterior desistiu)\n"
        f"- Ferramentas já tentadas: {usadas}\n"
        f"- Erros: {falhas}\n"
        f"- Onde parou: \"{resposta[:300]}\"\n"
        "- Siga por OUTRO caminho: troque de ferramenta (navegador_ir com a URL "
        "de busca, web_ler, pesquisa, executar_python), não repita a que falhou, "
        "e não peça ao usuário o que você mesmo pode fazer. Entregue o melhor "
        "resultado parcial verificável se o completo for impossível.")


def register_interprete_tools(registry, router=None, historico=None) -> list[str]:
    def entender_pedido(pedido: str) -> dict:
        hist = historico() if callable(historico) else []
        it = interpretar(pedido, hist, router)
        return {"ok": True, "tipo": it.tipo, "leia_como": it.corrigido,
                "objetivo": it.objetivo, "passos": it.passos,
                "servicos": it.servicos, "pedido_anterior": it.pedido_anterior}

    registry.register("entender_pedido", entender_pedido,
                      "Use quando o pedido estiver confuso, abreviado ou depender "
                      "da conversa: devolve o objetivo explícito, o contexto "
                      "herdado, URLs de serviços citados e passos sugeridos.",
                      {"pedido": "str"})
    return ["entender_pedido"]
