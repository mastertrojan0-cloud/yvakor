"""Aprendizado com erros e correções (yvakor/licoes.py) e a execução que
não perde dados já ditos. Casos tirados das conversas de 28/10/2026."""
import json

from yvakor import licoes, raciocinio
from yvakor.licoes import Licoes, tipo_feedback


def test_detecta_correcao_e_preferencia():
    for msg in ("ja esta na conversa, aprenda", "já mandei o cep na conversa",
                "não era isso", "continua sem mostrar"):
        assert tipo_feedback(msg) == "correcao", msg
    for msg in ("tem que mostrar sempre na tela", "de agora em diante responda curto"):
        assert tipo_feedback(msg) == "preferencia", msg
    for msg in ("verifica para mim clínicas ABA perto da Nova República", "2", "69076472"):
        assert tipo_feedback(msg) is None, msg


def test_registra_reforca_e_seleciona(tmp_path):
    L = Licoes(tmp_path / "l.json")
    a = L.registrar("Quando o site só mostra o preço depois do CEP, digite o CEP "
                    "no campo em vez de extrair a página de novo.", "erro",
                    exemplo="planos de internet na minha cidade")
    b = L.registrar("Se o site só mostra o preço depois do CEP, digite o CEP no "
                    "campo e não extraia a página de novo.", "correcao")
    assert a["id"] == b["id"] and b["vezes"] == 2 and b["origem"] == "correcao"
    L.registrar("Mostre sempre o resultado na tela (gráfico/arquivo), não só texto.",
                "preferencia")
    L.registrar("Para clínicas e endereços, pesquise no Google Maps antes de listar.",
                "erro", exemplo="clínicas ABA perto de casa")
    rel = [x["texto"] for x in L.relevantes("quanto custa o plano de internet com meu CEP", k=2)]
    assert rel[0].startswith("Mostre sempre")             # preferência entra sempre
    assert any("CEP" in t for t in rel) and not any("Maps" in t for t in rel)
    # vaga sobrando: entra a lição sem palavra em comum (regra de comportamento)
    assert len(L.relevantes("assunto sem relação nenhuma", k=3)) == 3
    bloco = L.bloco("clínicas perto de mim")
    assert "LIÇÕES APRENDIDAS" in bloco and "Maps" in bloco and "preferência" in bloco
    assert L.remover(a["id"]) and not L.remover("nao-existe")
    assert Licoes(tmp_path / "vazio.json").bloco("x") == ""


def test_limite_de_licoes_tira_os_erros_menos_reforcados(tmp_path, monkeypatch):
    monkeypatch.setattr(licoes, "MAX_LICOES", 3)
    L = Licoes(tmp_path / "l.json")
    L.registrar("Preferência fixa do usuário sobre o formato das respostas.", "preferencia")
    for i, tema in enumerate(("alfa beta gama", "delta epsilon zeta", "eta teta iota")):
        L.registrar(f"Regra numero {i} sobre {tema} para tarefas distintas.", "erro")
    textos = [x["texto"] for x in L.todas()]
    assert len(textos) == 3 and any("Preferência" in t for t in textos)


def test_avaliador_recebe_contexto_ferramentas_e_devolve_licao():
    from yvakor.colaboracao import avaliar_resposta
    visto = {}

    class R:
        def complete_messages(self, task, msgs, **k):
            visto["prompt"] = msgs[-1]["content"]
            return json.dumps({"nota": 2, "problemas": ["inventou"],
                               "licao": "Pesquise antes de listar endereços."})
    r = avaliar_resposta(R(), "2", "Lista…", "USUÁRIO: planos de internet\nAGENTE: 1 ou 2?",
                         ["navegador_ver"])
    assert r["licao"].startswith("Pesquise") and r["nota"] == 2
    p = visto["prompt"]
    assert "CONVERSA ANTERIOR" in p and "1 ou 2?" in p
    assert "FERRAMENTAS USADAS NESTA RESPOSTA: navegador_ver" in p
    assert "continuação" in p                              # "2" não é "ambíguo"
    avaliar_resposta(R(), "oi", "olá")
    assert "FERRAMENTAS USADAS NESTA RESPOSTA: NENHUMA" in visto["prompt"]


def test_destila_feedback_sem_dados_pessoais_no_pedido():
    class R:
        def complete_messages(self, task, msgs, **k):
            R.prompt = msgs[-1]["content"]
            return '{"licao": "Use os dados que o usuário já deu na conversa."}'
    t = licoes.destilar_feedback(R(), "correcao", "consulta o CPF", "me passa a data",
                                 "ja esta na conversa, aprenda")
    assert t.startswith("Use os dados") and "Não inclua dados pessoais" in R.prompt


def test_dados_da_conversa_inteira_entram_no_prompt():
    sessao = ["preciso da segunda via do cpf da minha mae",
              "Fulana de Tal, nome da mae Beltrana de Tal",
              "01/02/1960", "12345678901", "69076472", "sim",
              "explica de novo como funciona a fila de espera do posto de saúde"]
    bloco = raciocinio.dados_informados([], mensagens_sessao=sessao)
    assert "nome da mae Beltrana" in bloco                 # longa, mas tem dado
    assert '"01/02/1960" (data)' in bloco and '"12345678901" (provável CPF)' in bloco
    assert '"69076472" (provável CEP)' in bloco and '"sim"' in bloco
    assert "fila de espera" not in bloco                   # pedido comum, sem dado


def test_prompt_nativo_nao_manda_escrever_json():
    from yvakor.agent import AgentLoop
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    ag = AgentLoop(None, ToolRegistry(load_settings()))
    json_ = ag.system_with_tools("base")
    nativo = ag.system_with_tools("base", nativo=True)
    assert "PROTOCOLO DE RESPOSTA" in json_ and "usar_ferramenta" in json_
    assert "PROTOCOLO DE RESPOSTA" not in nativo and "usar_ferramenta" not in nativo
    assert "chamada de função nativa" in nativo and "Regras:" in nativo


def test_chamada_valida_escrita_como_texto_e_executada_sempre():
    """No nativo, a 3ª chamada em JSON-texto virava a resposta final crua."""
    from yvakor.agent import AgentLoop
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    feitos = []
    reg = ToolRegistry(load_settings())
    reg.register("ler", lambda caminho="": feitos.append(caminho) or {"ok": True, "c": 1},
                 "Lê.", {"caminho": "str"})
    respostas = [{"content": '{"acao":"usar_ferramenta","ferramenta":"ler",'
                             f'"args":{{"caminho":"{i}"}}}}'} for i in range(4)]
    respostas.append({"content": "Li os 4 arquivos."})

    class R:
        def complete_tools(self, *a, **k):
            return "fake", respostas.pop(0)
    saida = AgentLoop(R(), reg, max_iterations=8, nativo=True, roteador=False,
                      raciocinio={"verificar": False}).run(
        "t", [{"role": "user", "content": "leia"}])
    assert feitos == ["0", "1", "2", "3"] and saida == "Li os 4 arquivos."


def test_dsml_com_tag_quebrada_nao_engole_o_proximo_parametro():
    from yvakor.agent import _parse_acoes
    raw = ('<｜｜DSML｜｜invoke name="navegador_preencher">\n'
           '<｜｜DSML｜｜parameter name="aba">658616230</\n｜｜DSML｜｜parameter>\n'
           '<｜｜DSML｜｜parameter name="valor">01/01/2000</｜｜DSML｜｜parameter>\n'
           '</｜｜DSML｜｜invoke>')
    args = _parse_acoes(raw)[0]["args"]
    assert args == {"aba": "658616230", "valor": "01/01/2000"}
