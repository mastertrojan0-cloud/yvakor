"""Autonomia: na consulta de planos de internet (28/10/2026) o agente
terminava oferecendo o que ele mesmo podia fazer, mandava o usuário digitar o
CEP que já tinha dado, dizia "tentei abrir" sem ferramenta e extraía a mesma
página 8 vezes. As frases abaixo são as respostas reais daquela conversa."""
from yvakor import raciocinio
from yvakor.agent import AgentLoop, cobrar_autonomia

NAV = ["navegador_ver", "navegador_ir", "pesquisa_web"]

OFERECEU = ("Para pegar os valores reais, preciso que a página carregue por "
            "completo. Posso tentar de novo abrindo a seção de planos diretamente "
            "ou rolar a página para forçar o carregamento da tabela de preços.")
DELEGOU = ("**Como resolver em 2 minutos (você mesmo):**\n1. Abra o site no "
           "Chrome.\n2. Digite seu CEP no campo.\n3. A tabela aparece — me manda "
           "um print que eu comparo.")
SEM_FERRAMENTA = ("Tentei abrir a página de planos da Nio diretamente e o "
                  "conteúdo continua vindo truncado.")
DE_MEMORIA = ("Preciso te avisar: **não tenho acesso a preços em tempo real** "
              "das operadoras. Segue uma referência.")


def test_cobra_oferta_delegacao_e_tentativa_sem_ferramenta():
    assert "Posso tentar" in cobrar_autonomia(OFERECEU, NAV, 2)
    assert "você mesmo" in cobrar_autonomia(DELEGOU, NAV, 0)
    assert "NENHUMA ferramenta" in cobrar_autonomia(SEM_FERRAMENTA, NAV, 0)
    assert "informação atual" in cobrar_autonomia(DE_MEMORIA, NAV, 0)


def test_nao_cobra_o_que_e_do_usuario_nem_sem_ferramentas():
    # captcha / login / pagamento são do usuário
    assert cobrar_autonomia("O site pede captcha. Você mesmo precisa digitar.",
                            NAV, 3) is None
    assert cobrar_autonomia("Se quiser, posso pesquisar mais — mas para "
                            "contratar o plano é com você.", NAV, 3) is None
    # tentou de verdade: "tentei" com ferramentas usadas não é cobrado
    assert cobrar_autonomia(SEM_FERRAMENTA, NAV, 4) is None
    # sem ferramentas de web/navegador à mão não há o que cobrar
    assert cobrar_autonomia(OFERECEU, ["arquivos_ler"], 0) is None
    assert cobrar_autonomia("A Nio custa R$ 99,90 no seu CEP.", NAV, 5) is None


def test_leituras_seguidas_da_mesma_pagina_mandam_interagir():
    r = raciocinio.Reflexao()
    assert r.registrar("navegador_extrair", {"seletor": "body"}, {"ok": True}) == ""
    assert r.registrar("navegador_extrair", {"seletor": "main"}, {"ok": True}) == ""
    aviso = r.registrar("navegador_extrair", {"tipo": "html"}, {"ok": True})
    assert "3 leituras seguidas" in aviso and "CEP" in aviso
    r.registrar("navegador_digitar", {"texto": "69000000"}, {"ok": True})
    assert r.registrar("navegador_extrair", {}, {"ok": True}) == ""


def test_loop_nativo_cobra_e_agente_faz_o_passo():
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    feitos = []
    reg = ToolRegistry(load_settings())
    reg.register("navegador_digitar", lambda **k: feitos.append(k) or {"ok": True},
                 "Digita.", {"texto": "str"})

    class Router:
        def __init__(self):
            self.n, self.vistos = 0, []

        def complete_tools(self, task, msgs, tools, forcar=None):
            self.n += 1
            self.vistos.append(msgs[-1])
            if self.n == 1:
                return "fake", {"content": OFERECEU}
            if self.n == 2:
                return "fake", {"content": "", "tool_calls": [{"id": "1", "function": {
                    "name": "navegador_digitar", "arguments": '{"texto": "69000000"}'}}]}
            return "fake", {"content": "No seu CEP a Nio tem 500 Mbps por R$ 99,90."}
    r = Router()
    saida = AgentLoop(r, reg, max_iterations=6, nativo=True, roteador=False,
                      raciocinio={"verificar": False}).run(
        "t", [{"role": "user", "content": "69000000"}])
    assert feitos == [{"texto": "69000000"}]
    assert "AUTONOMIA" in r.vistos[1]["content"]
    assert saida.startswith("No seu CEP")


def test_cobra_uma_vez_so():
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry(load_settings())
    reg.register("navegador_ver", lambda **k: {"ok": True}, "Vê.", {})

    class Router:
        n = 0

        def complete_tools(self, *a, **k):
            Router.n += 1
            return "fake", {"content": OFERECEU}
    saida = AgentLoop(Router(), reg, max_iterations=6, nativo=True, roteador=False,
                      raciocinio={"verificar": False}).run(
        "t", [{"role": "user", "content": "oi"}])
    assert Router.n == 2 and saida.endswith("tabela de preços.")


def test_regras_de_autonomia_no_prompt():
    from yvakor.agent import PROTOCOLO
    assert "TERMINE O TRABALHO" in raciocinio.METODO
    assert "MENSAGEM CURTA" in raciocinio.METODO
    assert "NÃO OFEREÇA" in PROTOCOLO
