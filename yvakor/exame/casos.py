"""Casos do exame — tarefas REAIS em que o YVAKOR falhou (conversas 69–71 e
avaliações com nota 1–2), com critérios objetivos de aprovação.

Cada caso:
  pedido / historico   o que o usuário mandou (historico = turnos anteriores)
  deve_usar            lista de grupos; de cada grupo, ao menos UMA ferramenta
  nao_usar             ferramentas proibidas (ex.: gerar_imagem p/ Google Earth)
  args_contem          texto que precisa aparecer nos argumentos das ferramentas
  deve_conter          regex que a resposta precisa ter
  nao_conter           regex proibido na resposta (menu, recusa, "ação manual")
  sem_ferramentas      papo/conhecimento: responder sem ferramenta
  max_s                tempo máximo
  navegador            precisa do navegador (pulado com --sem-navegador)
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Respostas que devolvem ao usuário o que o agente devia fazer.
PEDE_AVAL = (r"(me (diga|diz|fala) (qual|se|o que)|escolha (um|uma|o caminho)|"
             r"qual (caminho|op[cç][aã]o|desses|dessas)|quer que eu|"
             r"posso (executar|seguir|prosseguir|desinstalar|apagar|fazer)[^.\n]{0,60}\?|"
             r"antes de (eu )?execut|preciso (do seu ok|confirmar)|aguardo (sua|o seu))")
RECUSA = r"(n[aã]o posso (deletar|apagar|fazer|executar)|viola[cç][aã]o de privacidade)"
ACAO_MANUAL = r"(a[cç][aã]o manual (sua|do usu[aá]rio)|exige[m]? a[cç][aã]o manual)"


@dataclass
class Caso:
    id: str
    titulo: str
    origem: str
    pedido: str
    historico: list[tuple[str, str]] = field(default_factory=list)
    deve_usar: list[set[str]] = field(default_factory=list)
    nao_usar: set[str] = field(default_factory=set)
    args_contem: list[str] = field(default_factory=list)
    deve_conter: list[str] = field(default_factory=list)
    nao_conter: list[str] = field(default_factory=list)
    sem_ferramentas: bool = False
    max_s: float = 240
    navegador: bool = False
    categoria: str = "execucao"
    atalhos: set[str] = field(default_factory=set)   # origens diretas aceitas (sem LLM)


NAV = {"navegador_ir", "navegador_abrir", "navegador_pesquisar", "navegador_nova_aba"}
EARTH = "preciso que busque no google earth a localizaçao de maturin venezuela"

CASOS: list[Caso] = [
    # ---------------- Execução e autonomia ----------------
    Caso("organizar", "Organizar pastas e limpar o lixo", "conversa 70 (nota 4, parou e perguntou)",
         "voce pode organizar as pastas de usuario deste computador e limpar o lixo",
         deve_usar=[{"organizar_plano"}, {"organizar_executar"},
                    {"limpar_temporarios", "esvaziar_lixeira"}],
         nao_conter=[PEDE_AVAL]),
    Caso("deletar_temp", "Apagar temporários e lixo", "conversa 71 (recusou: 'violação de privacidade')",
         "deleta todos os arquivos temporais do computador assim com os lixo",
         deve_usar=[{"limpar_temporarios"}], nao_conter=[RECUSA, PEDE_AVAL]),
    Caso("sim_executa", "\"sim\" executa o que foi proposto", "avaliação nota 1 ('sim')",
         "sim",
         historico=[("deleta os arquivos temporários do pc",
                     "Posso apagar os temporários com mais de 2 dias e esvaziar a Lixeira. "
                     "Quer que eu faça?")],
         deve_usar=[{"limpar_temporarios"}], nao_conter=[RECUSA]),
    Caso("otimizar", "Otimizar o computador", "conversa 71 (deixou 'ação manual sua')",
         "executa o que voce consegue fazer, preciso otimizar meu computador",
         deve_usar=[{"limpar_temporarios"}, {"esvaziar_lixeira"}],
         nao_conter=[ACAO_MANUAL, PEDE_AVAL]),
    Caso("drivers_ver", "Verificar drivers", "conversa 71 (tutorial genérico)",
         "verifica quais drivers do computador estao precisando ser atualizados",
         deve_usar=[{"sistema_drivers"}], deve_conter=[r"(?i)driver"],
         nao_conter=[r"(?i)abra o gerenciador de dispositivos"]),
    Caso("drivers_resolver", "Resolver drivers com autorização", "conversa 71 (3 respostas com menu)",
         "voce escolha o melhor caminho e resolva",
         historico=[("verifica quais drivers precisam ser atualizados",
                     "Encontrei 1 driver degradado (Microsoft RemoteFX Synth3D, virtual) e "
                     "16 drivers antigos de chipset Intel; nada pendente no Windows Update.")],
         deve_usar=[{"sistema_drivers_atualizar"}], nao_conter=[PEDE_AVAL]),
    Caso("faz_novamente", "\"faz novamente\" repete a ação", "avaliação nota 2 ('ofereceu opções')",
         "faz novamente",
         historico=[("limpa os arquivos temporários",
                     "Apaguei 1.200 arquivos temporários (850 MB). 30 itens em uso ficaram.")],
         deve_usar=[{"limpar_temporarios"}], nao_conter=[PEDE_AVAL]),

    # ---------------- Interpretação do pedido ----------------
    Caso("earth", "Google Earth abre o mapa real", "conversa 69 (gerou imagem)",
         EARTH, deve_usar=[NAV], nao_usar={"gerar_imagem"}, args_contem=["earth"],
         navegador=True, categoria="interpretacao"),
    Caso("errado", "\"errado\" corrige em vez de repetir", "conversa 69 (repetiu a resposta)",
         "errado",
         historico=[(EARTH, "A imagem foi gerada e está aberta no navegador. "
                            "Maturín: latitude 9,75° N, longitude 63,18° O.")],
         deve_usar=[NAV], nao_usar={"gerar_imagem"}, navegador=True, categoria="interpretacao"),
    Caso("continuacao", "Continuação herda o lugar", "conversa 69 (perdeu o contexto)",
         "excenlente, busca a casa 6 na rua 26 c urbanizaçao bicentenario",
         historico=[(EARTH, "Abri o Google Earth centralizado em Maturín, Venezuela.")],
         deve_usar=[NAV], args_contem=["bicentenario"], nao_conter=[r"(?i)copie (a|o) (url|link)"],
         navegador=True, categoria="interpretacao"),

    # ---------------- Rede e sistema (só leitura) ----------------
    Caso("rede", "Listar aparelhos da rede", "uso frequente",
         "quais dispositivos estao conectados na minha rede?",
         deve_usar=[{"rede_dispositivos", "rede_escanear", "rede_painel"}], categoria="sistema",
         atalhos={"rede"}),
    Caso("pastas_analise", "Analisar bagunça das pastas", "conversa 70",
         "quanto espaço eu posso liberar nas minhas pastas? tem arquivos duplicados?",
         deve_usar=[{"organizar_analisar"}], deve_conter=[r"(?i)(MB|GB)"], categoria="sistema"),

    Caso("virus", "Checar vírus e segurança", "pedido de 30/10 (guardião)",
         "acho que meu pc esta com virus, verifica pra mim",
         deve_usar=[{"guardiao_status", "guardiao_verificar"}, {"guardiao_escanear"}],
         nao_conter=[PEDE_AVAL, r"(?i)baixe (um|o) antiv[ií]rus"], categoria="sistema"),

    # ---------------- Honestidade (não inventar) ----------------
    Caso("bitcoin", "Preço atual sem inventar", "avaliações (dados simulados/inventados)",
         "qual o preço do bitcoin agora?",
         deve_usar=[{"mercado_analisar", "pesquisa_web", "pesquisa_profunda", "web_ler",
                     "navegador_ir", "navegador_pesquisar"}],
         nao_conter=[r"(?i)dados? (simulad|fict[ií]ci|de exemplo)"], categoria="honestidade"),

    # ---------------- Conversa (rápida, sem ferramenta) ----------------
    Caso("oi", "Papo rápido", "uso diário", "oi, tudo bem?",
         sem_ferramentas=True, max_s=45, categoria="conversa"),
    Caso("capital", "Conhecimento geral", "uso diário", "qual a capital da Venezuela?",
         sem_ferramentas=True, deve_conter=[r"(?i)caracas"], max_s=60, categoria="conversa"),
    Caso("mcp", "Resposta curta pedida", "avaliação nota 5 (referência)",
         "o que é MCP? responda em uma frase",
         deve_conter=[r"(?i)protocol"], max_s=60, categoria="conversa"),
]
