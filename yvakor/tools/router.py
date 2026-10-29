"""
YVAKOR — Roteador de ferramentas

Envia ao modelo apenas as ferramentas relevantes para a mensagem. Reduz
tokens (prompt e function calling), melhora a escolha e destrava o modo
nativo, que ficava lento com as 60+ ferramentas.

Estratégia:
  1. grupos por assunto (navegador, arquivos, rede, voz, cérebro, sistema);
  2. núcleo sempre presente (shell, listar/ler arquivo, cérebro);
  3. se nenhum grupo casar, ranking por palavras do nome/descrição;
  4. fallback: todas (nunca perde capacidade por engano).
"""
from __future__ import annotations

import re

from yvakor.memory.db import normalizar

GRUPOS = {
    "navegador": {
        "prefixos": ("navegador_", "web_"),
        "palavras": ("site", "pagina", "página", "url", "navegar", "navegue",
                     "clique", "login", "web", "http", "pesquis", "baixar",
                     "download", "formulario", "formulário", "link", "aba",
                     "voo", "voos", "preco", "precos", "caixa", "captcha",
                     "consulta", "consultar", "receita", "cpf"),
        # Radicais: casam por INÍCIO da palavra. A lista acima só casava a
        # palavra inteira ("pesquis" nunca casava "pesquise"), então "pesquise
        # gatos no google" e "escreva olá no campo" não recebiam NENHUMA
        # ferramenta de navegador.
        "radicais": ("pesquis", "busc", "procur", "naveg", "clic", "digit",
                     "escrev", "preench", "formul", "googl", "youtube", "bing",
                     "duckduck", "abr", "aperte", "pression", "rol", "extens",
                     "chrome", "edge", "campo", "seleci", "marc", "espere",
                     "aguard", "volt", "recarreg", "avanc", "pagin", "site",
                     "link", "aba", "tecla", "enter", "login", "entrar", "anex", "upload",
                     "acess", "screenshot", "print", "captur",
                     # serviços que o usuário usa logado no Chrome
                     "gmail", "email", "mail", "inbox", "outlook", "hotmail",
                     "spam", "whatsapp", "instagr", "facebook", "linkedin",
                     "passage", "aeroport", "hotel", "amazon", "mercadoliv"),
        # Ordem de importância: o limite de ferramentas corta pelo FIM, e a
        # ordem de registro punha navegador_pesquisar na 11ª posição.
        "prioridade": ("navegador_ver", "navegador_procurar", "navegador_pesquisar",
                       "navegador_ir",
                       "navegador_clicar", "navegador_preencher",
                       "navegador_digitar", "navegador_pressionar",
                       "navegador_selecionar", "navegador_enviar_arquivo",
                       "navegador_esperar",
                       "navegador_extrair", "navegador_rede", "navegador_rolar",
                       "navegador_abrir", "navegador_historico",
                       "navegador_passar_mouse", "navegador_captura",
                       "navegador_aguardar_captcha", "navegador_js", "web_ler"),
    },
    "tela": {
        # tela do Windows (fora do navegador)
        "prefixos": ("tela_",),
        "palavras": ("tela", "monitor", "screen", "janela", "desktop"),
    },
    "web": {
        # leitura de páginas/documentação sem abrir o navegador
        "prefixos": ("web_",),
        "palavras": ("artigo", "documentacao", "documentação", "docs", "wiki",
                     "wikipedia", "noticia", "notícia", "blog", "url", "http",
                     "https", "leia", "ler"),
        "radicais": ("http", "www", "document", "notici", "artig"),
    },
    "mercado": {
        "prefixos": ("mercado_", "binance_", "tradingview_", "coingecko_", "cryptopanic_", "stocktwits_", "medo_"),
        "palavras": ("btc", "bitcoin", "eth", "ethereum", "cripto", "criptomoeda", "stocktwits",
                     "rsi", "macd", "candle", "candles", "cotacao", "cotação", "ativo", "ticker",
                     "binance", "solana", "zcash", "dogecoin", "bolsa", "acao", "ação", "acoes",
                     "ações", "tendencia", "tendência", "suporte", "resistencia", "resistência"),
        "radicais": ("bitco", "cripto", "ethere", "stockt", "cotac", "cota\u00e7"),
        "prioridade": ("mercado_analisar",),
    },
    "arquivos": {
        "prefixos": ("arquivos_",),
        "palavras": ("arquivo", "pasta", "diretorio", "diretório", "ler",
                     "escrever", "editar", "apagar", "excluir", "mover",
                     "copiar", "zip", "compactar", "extrair", "pdf", "csv",
                     "xlsx", "planilha", "documento", "backup", "desfazer",
                     "grep", "contem", "contém", "ocorrencia", "ocorrência",
                     "codigo", "código", "funcao", "função", "trecho",
                     "classe", "projeto", "variavel", "variável"),
        "radicais": ("grep", "codig", "defini", "ocorr"),
        "prioridade": ("arquivos_grep", "arquivos_buscar", "arquivos_ler",
                       "arquivos_editar"),
    },
    "rede": {
        "prefixos": ("rede_",),
        "palavras": ("camera", "câmera", "tv", "televisao", "televisão",
                     "chromecast", "celular", "telefone", "dispositivo",
                     "rede", "wifi", "mqtt", "luz", "tomada", "onvif", "rtsp",
                     "roteador", "impressora", "casa"),
    },
    "entorno": {
        "prefixos": ("entorno_", "ambiente_"),
        "palavras": ("ambiente", "entorno", "rotina", "costume", "habito",
                     "hábito", "normal", "anomalia", "estranho", "lento",
                     "trafego", "tráfego", "aprendeu", "padrao", "padrão"),
        "radicais": ("rotin", "costum", "habit", "hábit", "anomal", "estranh",
                     "entorn", "ambient"),
        "prioridade": ("entorno_resumo", "entorno_eventos", "entorno_perfil"),
    },
    "voz": {
        "prefixos": ("voz_",),
        "palavras": ("voz", "falar", "fale", "diga", "ouvir", "ouça", "audio",
                     "áudio", "microfone", "transcrever", "escute"),
    },
    "cerebro": {
        "prefixos": ("cerebro_",),
        "palavras": ("cerebro", "cérebro", "memoria", "memória", "lembra",
                     "nota", "obsidian", "skill", "receita", "conhecimento",
                     "aprendeu"),
    },
    "sistema": {
        "prefixos": ("executar_",),
        "palavras": ("shell", "comando", "powershell", "python", "processo",
                     "servico", "serviço", "instalar", "executar", "script",
                     "sistema", "programa"),
    },
    "capacidades": {
        "prefixos": ("cap_",),
        "palavras": ("calcule", "calcular", "conta", "matematica", "matemática",
                     "estatistica", "estatística", "media", "média", "mediana",
                     "desvio", "grafico", "gráfico", "planilha", "imagem",
                     "desenhe", "ilustracao", "ilustração", "redija", "redacao",
                     "redação", "escreva", "corrija", "correcao", "correção",
                     "resuma", "resumo", "codigo", "código", "programa",
                     "funcao", "função", "desenvolva", "calculadora",
                     "aplicativo", "app", "site", "frontend", "interface",
                     "jogo", "painel", "dashboard"),
    },
    "entregaveis": {
        "prefixos": ("entregar_", "gerar_planilha", "buscar_foto"),
        "palavras": ("relatorio", "relatório", "pdf", "docx", "word",
                     "planilha", "xlsx", "excel", "csv", "foto", "fotografia",
                     "imagem", "grafico", "gráfico", "entrega", "entregue",
                     "documento", "apresentacao", "apresentação", "slides",
                     "zip", "pacote", "arquivo"),
    },
}

NUCLEO = ("executar_shell", "arquivos_listar", "arquivos_ler",
          "cerebro_buscar", "pensar", "tarefas_checklist", "perguntar_usuario",
          "entender_pedido")

# Quando nenhum grupo casa: um conjunto geral e estável (navegar, pesquisar,
# rodar Python, gerar gráfico/relatório). Antes eram TODAS as 146 ferramentas
# ("2", "ja", "resolva") ou o ranking por descrição, que casava palavras
# vazias ("o que esta na tela" → rede_telefone_tela, voz_falar…).
GERAL = ("navegador_ver", "navegador_ir", "navegador_pesquisar", "navegador_clicar",
         "navegador_preencher", "navegador_extrair", "navegador_captura",
         "tela_ver", "pesquisa_web", "web_ler", "executar_python", "cap_grafico",
         "entregar_relatorio", "arquivos_escrever")

# Palavras que não dizem nada sobre a ferramenta (o ranking casava "que",
# "esta", "para" com descrições quaisquer).
_VAZIAS = set("""que esta este essa esse isso isto para pra por com sem mim meu minha
voce vc faz faca fazer favor agora sempre tem ter tudo mais muito como onde quando
qual quais uma uns umas dos das nos nas aqui ali ela ele eles elas sua seu suas seus
foi ser sim nao ja tambem preciso quero queria pode poderia vamos mostra mostre
mostrar ver veja verifica verificar novamente continua continue resolva resolve""".split())


def _palavras(texto: str) -> set[str]:
    return {p for p in re.findall(r"\w+", normalizar(texto)) if len(p) >= 3}


def selecionar(registry, mensagem: str, max_tools: int = 14) -> list[str]:
    disponiveis = list(registry.tools.keys())
    if not disponiveis:
        return []
    alvo = _palavras(mensagem)
    escolhidos: list[str] = [n for n in NUCLEO if n in disponiveis]

    def adicionar(nomes):
        for n in nomes:
            if n not in escolhidos:
                escolhidos.append(n)

    casou_grupo = False
    # entregáveis primeiro: PDF/planilha/foto não podem ser cortados pelo
    # grupo de arquivos (que tem muitos utilitários).
    grupos = sorted(GRUPOS.items(),
                    key=lambda kv: 0 if kv[0] == "entregaveis" else 1)
    for grupo, regra in grupos:
        radicais = regra.get("radicais", ())
        if (alvo & set(regra["palavras"])
                or any(t.startswith(r) for t in alvo for r in radicais)):
            casou_grupo = True
            do_grupo = [n for n in disponiveis if n.startswith(regra["prefixos"])]
            # as mais importantes do grupo primeiro (e antes do que já foi
            # escolhido do núcleo, para o corte por limite não as descartar)
            prioridade = [n for n in regra.get("prioridade", ()) if n in do_grupo]
            if prioridade:
                escolhidos[:0] = [n for n in prioridade if n not in escolhidos]
            adicionar(do_grupo)

    if not casou_grupo:
        # conjunto geral primeiro; o ranking por nome/descrição só completa
        adicionar([n for n in GERAL if n in disponiveis])
        pontuados = []
        uteis = alvo - _VAZIAS
        for nome in disponiveis:
            if nome in escolhidos:
                continue
            texto = normalizar(nome + " " +
                               str((registry.specs.get(nome) or {}).get("desc", "")))
            pontos = sum(1 for p in uteis if p in texto)
            if pontos:
                pontuados.append((pontos, nome))
        pontuados.sort(reverse=True)
        adicionar([n for _, n in pontuados])
        if len(escolhidos) <= len(NUCLEO):
            return disponiveis          # registro sem as ferramentas gerais
    else:
        # vagas que sobram: o conjunto geral ("análise do BTC" + "mostra na
        # tela" casava só mercado_* e ficava sem Python/gráfico/navegador)
        adicionar([n for n in GERAL if n in disponiveis])

    return escolhidos[:max(3, int(max_tools))]
