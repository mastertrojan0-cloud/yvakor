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
        "prefixos": ("navegador_",),
        "palavras": ("site", "pagina", "página", "url", "navegar", "navegue",
                     "clique", "login", "web", "http", "pesquis", "baixar",
                     "download", "formulario", "formulário", "link", "aba"),
    },
    "arquivos": {
        "prefixos": ("arquivos_",),
        "palavras": ("arquivo", "pasta", "diretorio", "diretório", "ler",
                     "escrever", "editar", "apagar", "excluir", "mover",
                     "copiar", "zip", "compactar", "extrair", "pdf", "csv",
                     "xlsx", "planilha", "documento", "backup", "desfazer"),
    },
    "rede": {
        "prefixos": ("rede_",),
        "palavras": ("camera", "câmera", "tv", "televisao", "televisão",
                     "chromecast", "celular", "telefone", "dispositivo",
                     "rede", "wifi", "mqtt", "luz", "tomada", "onvif", "rtsp",
                     "roteador", "impressora", "casa"),
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
          "cerebro_buscar")


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
        if alvo & set(regra["palavras"]):
            casou_grupo = True
            adicionar([n for n in disponiveis
                       if n.startswith(regra["prefixos"])])

    if not casou_grupo:
        # ranking por nome/descrição quando não há grupo claro
        pontuados = []
        for nome in disponiveis:
            if nome in escolhidos:
                continue
            texto = normalizar(nome + " " +
                               str((registry.specs.get(nome) or {}).get("desc", "")))
            pontos = sum(1 for p in alvo if p in texto)
            if pontos:
                pontuados.append((pontos, nome))
        pontuados.sort(reverse=True)
        adicionar([n for _, n in pontuados])
        if len(escolhidos) <= len(NUCLEO):
            return disponiveis          # nada casou: mantém tudo

    return escolhidos[:max(3, int(max_tools))]
