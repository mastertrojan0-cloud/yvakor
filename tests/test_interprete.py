"""Intérprete: casos reais em que o agente parou por não entender o pedido."""
from yvakor import interprete

P1 = "preciso que busque no google earth a localizaçao de maturin venezuela"


def _hist(*pares):
    h = []
    for u, a in pares:
        h += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
    return h


def test_servico_citado_vira_url_e_proibe_imagem():
    it = interprete.interpretar(P1, [], usar_modelo=False)
    assert it.servicos[0]["url"] == "https://earth.google.com/web/search/maturin+venezuela"
    assert "NÃO use gerar_imagem" in it.bloco()


def test_errado_e_correcao_do_pedido_anterior():
    it = interprete.interpretar("errado", _hist((P1, "A imagem foi gerada.")),
                                usar_modelo=False)
    assert it.tipo == "correcao"
    assert it.pedido_anterior == P1
    assert "NÃO repita" in it.bloco() and it.servicos


def test_continuacao_herda_lugar_e_servico():
    h = _hist((P1, "x"), ("errado", "Maturín centralizada."))
    it = interprete.interpretar(
        "excenlente, busca a casa 6 na rua 26 c urbanizaçao bicentenario", h,
        usar_modelo=False)
    assert it.tipo == "continuacao"
    assert "excenlente→excelente" in it.correcoes
    assert it.pedido_anterior == P1          # pula o "errado"
    assert it.servicos[0]["url"].endswith("bicentenario+maturin+venezuela")
    assert "google earth" in it.texto_para_ferramentas()


def test_pedido_novo_claro_nao_gera_bloco():
    assert interprete.interpretar("me conte uma piada sobre gatos", [],
                                  usar_modelo=False).bloco() == ""


def test_modelo_so_e_chamado_quando_ambiguo():
    class Router:
        chamadas = 0

        def complete_messages(self, *a, **k):
            Router.chamadas += 1
            return '{"objetivo": "achar a casa 6 em Maturín", "passos": ["abrir earth"]}'

    interprete.interpretar("me conte uma piada", [], Router())
    assert Router.chamadas == 0
    it = interprete.interpretar("errado", _hist((P1, "imagem")), Router())
    assert Router.chamadas == 1 and it.usou_modelo
    assert "Maturín" in it.bloco()


def test_desistencia_apos_tentar():
    largou = ("Parei de insistir no navegador_js — a ferramenta não existe "
              "nesta instalação. Não vou repetir.")
    assert interprete.desistiu_apos_tentar(largou, passos=11)
    assert not interprete.desistiu_apos_tentar(largou, passos=0)
    assert not interprete.desistiu_apos_tentar("Pronto: Maturín no mapa.", passos=3)
    bloco = interprete.bloco_resgate(largou, ["navegador_js", "navegador_js"], ["comando desconhecido"])
    assert "OUTRO caminho" in bloco and bloco.count("navegador_js") >= 1


# Conversa 71: tudo com menos de 160 caracteres ia ao modelo local sem
# ferramentas. Agora o atalho local é só para papo.
PROPOSTA = [{"role": "user", "content": "deleta os temporarios"},
            {"role": "assistant", "content": "Quer apagar de maneira geral ou algum diretório?"}]


def test_pedidos_de_acao_e_aprovacoes_vao_ao_agente():
    assert not interprete.conversa_casual(
        "deleta todos os arquivos temporais do computador assim com os lixo")
    assert not interprete.conversa_casual(
        "verifica quais drivers do computador estao precisando ser atualizados")
    for aprovacao in ("sim", "eu estou autorizando, voce é a minha ferramenta",
                      "procede e mostra barra de progresso da tarefa"):
        assert not interprete.conversa_casual(aprovacao, PROPOSTA), aprovacao


def test_papo_continua_no_modelo_local():
    for papo in ("oi, tudo bem?", "obrigado!", "me conta uma piada"):
        assert interprete.conversa_casual(papo), papo
    # conhecimento vai ao modelo forte: o 3B inventava ("MCP da IBM")
    for pergunta in ("o que é MCP? responda em uma frase", "qual a capital da Venezuela?"):
        assert not interprete.conversa_casual(pergunta), pergunta


def test_decisao_nao_depende_do_tamanho_do_texto():
    assert not interprete.conversa_casual("apaga")          # curtíssimo, mas é ação
    longo = "oi, tudo bem? " + "espero que seu dia esteja ótimo " * 10
    assert interprete.conversa_casual(longo)


def test_resposta_completa_com_limitacoes_no_fim_nao_e_desistencia():
    completa = ("# Drivers do seu PC\n\n" + "| Driver | Status |\n|---|---|\n" * 20
                + "\n## O que não foi possível\n- versões exatas")
    assert not interprete.desistiu_apos_tentar(completa, passos=1)


def test_nucleo_indica_ferramentas_pela_intencao():
    """Exame de 29/10: com as ferramentas certas na lista, o modelo ia de shell."""
    casos = {
        "voce pode organizar as pastas de usuario deste computador e limpar o lixo":
            {"organizar pastas", "limpar temporários/lixo"},
        "deleta todos os arquivos temporais do computador assim com os lixo":
            {"limpar temporários/lixo"},
        "executa o que voce consegue fazer, preciso otimizar meu computador": {"otimizar o PC"},
        "verifica quais drivers do computador estao precisando ser atualizados":
            {"verificar drivers"},
        "atualiza os drivers": {"atualizar/reparar drivers"},
        "qual a capital da Venezuela?": set(),
        "atualiza o chrome": set(),
    }
    for pedido, esperado in casos.items():
        it = interprete.interpretar(pedido, [], usar_modelo=False)
        assert {n for n, _, _ in it.indicadas} == esperado, pedido
    it = interprete.interpretar("deleta os temporarios", [], usar_modelo=False)
    assert "limpar_temporarios()" in it.bloco() and "EXECUTE" in it.bloco()


def test_aprovacao_herda_a_intencao_do_pedido_anterior():
    hist = [{"role": "user", "content": "verifica quais drivers precisam ser atualizados"},
            {"role": "assistant", "content": "Encontrei 1 driver degradado."}]
    it = interprete.interpretar("voce escolha o melhor caminho e resolva", hist,
                                usar_modelo=False)
    assert it.tipo == "continuacao"
    assert [n for n, _, _ in it.indicadas] == ["atualizar/reparar drivers"]
