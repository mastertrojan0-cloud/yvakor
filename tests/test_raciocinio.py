"""Método de raciocínio: plano antes de agir, reflexão sobre falhas e
conferência antes da resposta final (yvakor/raciocinio.py)."""
from yvakor import raciocinio
from yvakor.agent import AgentLoop


def _registro(chamadas, falhar=False):
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry(load_settings())
    reg.register("navegador_pesquisar",
                 lambda **k: chamadas.append(("pesquisar", k)) or
                 ({"ok": False, "error": "timeout"} if falhar else {"ok": True}),
                 "Pesquisa.", {"termo": "str"})
    reg.register("navegador_extrair",
                 lambda **k: chamadas.append(("extrair", k)) or
                 {"ok": True, "texto": "Azul R$ 1.013"}, "Extrai.", {"aba": "int?"})
    return reg


class _Roteiro:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.vistos = []

    def complete_messages(self, task, msgs, **k):
        self.vistos.append(msgs[-1]["content"])
        return self.respostas.pop(0)


def test_heuristica_de_planejamento():
    assert not raciocinio.precisa_planejar("oi")
    assert not raciocinio.precisa_planejar("quanto é 2+2?")
    assert raciocinio.precisa_planejar(
        "pesquise voos de Manaus para Boa Vista, compare os preços e salve "
        "uma planilha")
    assert raciocinio.precisa_planejar("abra o gmail e depois resuma os e-mails")
    assert raciocinio.precisa_planejar(
        "abra o gmail, veja os e-mails de hoje e resuma os importantes")
    assert not raciocinio.precisa_planejar("qual a capital da Austrália hoje em dia?")


def test_ler_plano_tolera_texto_e_formatos():
    p = raciocinio.ler_plano('Plano:\n{"objetivo":"x","passos":["a","b"]} fim')
    assert p["passos"] == ["a", "b"] and p["objetivo"] == "x"
    p = raciocinio.ler_plano('{"objetivo":"x","passos":"a; b"}')
    assert p["passos"] == ["a", "b"]
    assert raciocinio.ler_plano('{"acao":"usar_ferramenta","passos":["a"]}') is None
    assert raciocinio.ler_plano("sem json") is None


def test_reflexao_orienta_sem_repetir_e_manda_parar():
    r = raciocinio.Reflexao()
    assert r.registrar("f", {"a": 1}, {"ok": True}) == ""
    assert "causa provável" in r.registrar("f", {"a": 1}, {"ok": False})
    assert "IDÊNTICA" in r.registrar("f", {"a": 1}, {"ok": False})
    assert "falhas seguidas" in r.registrar("g", {}, {"ok": False})
    assert r.registrar("g", {}, {"ok": True}) == "" and r.seguidas == 0


def test_metodo_entra_no_prompt():
    loop = AgentLoop(None, _registro([]))
    assert "MÉTODO DE TRABALHO" in loop.system_with_tools("base")
    assert "## MÉTODO" in loop.system_with_tools("base", compacto=True)


def test_planeja_executa_e_confere_antes_de_responder():
    chamadas, eventos = [], []
    r = _Roteiro([
        '{"objetivo":"preço do voo","pronto_quando":"preço lido na página",'
        '"passos":["pesquisar voos","extrair preço"]}',
        '{"acao":"usar_ferramenta","ferramenta":"navegador_pesquisar",'
        '"args":{"termo":"voos MAO BVB"}}',
        '{"acao":"usar_ferramenta","ferramenta":"navegador_extrair","args":{}}',
        "Achei.",                                     # 1ª tentativa de resposta
        "A Azul tem voo por R$ 1.013.",               # depois da conferência
    ])
    loop = AgentLoop(r, _registro(chamadas), max_iterations=8,
                     raciocinio={"planejar": True, "verificar": True})
    saida = loop.run("t", [{"role": "user", "content":
                            "pesquise voos de Manaus a Boa Vista e depois "
                            "extraia o preço mais barato"}],
                     on_event=lambda t, d: eventos.append(t))
    assert r.vistos[0] == raciocinio.PEDIR_PLANO
    assert "PLANO DE TRABALHO" in r.vistos[1] and "1. pesquisar voos" in r.vistos[1]
    assert "ANTES DE RESPONDER" in r.vistos[4] and "preço lido" in r.vistos[4]
    assert saida == "A Azul tem voo por R$ 1.013."
    assert [c[0] for c in chamadas] == ["pesquisar", "extrair"]
    assert eventos[0] == "plano"


def test_pergunta_simples_nao_paga_chamadas_extras():
    r = _Roteiro(["Olá! Tudo certo."])
    loop = AgentLoop(r, _registro([]), raciocinio={"planejar": True,
                                                   "verificar": True})
    assert loop.run("t", [{"role": "user", "content": "oi"}]) == "Olá! Tudo certo."
    assert len(r.vistos) == 1


def test_falha_vem_com_reflexao_na_observacao():
    r = _Roteiro([
        '{"acao":"usar_ferramenta","ferramenta":"navegador_pesquisar",'
        '"args":{"termo":"x"}}',
        "Não consegui: a pesquisa deu timeout.",
    ])
    loop = AgentLoop(r, _registro([], falhar=True), max_iterations=4)
    saida = loop.run("t", [{"role": "user", "content": "pesquise x"}])
    assert "REFLEXÃO" in r.vistos[1] and saida.startswith("Não consegui")
