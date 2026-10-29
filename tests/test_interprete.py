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
