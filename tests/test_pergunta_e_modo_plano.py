"""perguntar_usuario (AskUserQuestion) e modo plano, pelo mesmo canal das
confirmações (ConfirmationBroker → /api/progress 'pending' → /api/confirm)."""
import threading
import time

from yvakor import interacao, raciocinio
from yvakor import ferramentas_claude as fc
from yvakor.agent import AgentLoop
from yvakor.orchestrator import ConfirmationBroker


def _responder_quando_pendente(broker, sid, allow, resposta=None, visto=None):
    def trabalho():
        for _ in range(200):
            p = broker.pending_for(sid)
            if p:
                if visto is not None:
                    visto.append(p)
                broker.resolve(sid, allow, resposta)
                return
            time.sleep(0.01)
    t = threading.Thread(target=trabalho, daemon=True)
    t.start()
    return t


def test_broker_pergunta_leva_tipo_opcoes_e_resposta():
    b = ConfirmationBroker(timeout=5)
    visto = []
    _responder_quando_pendente(b, "S", True, "Planilha", visto)
    res = b.perguntar("S", "pergunta", "Qual formato?", "", ["PDF", "Planilha"], timeout=5)
    assert res == {"allow": True, "resposta": "Planilha"}
    assert visto[0]["tipo"] == "pergunta" and visto[0]["opcoes"] == ["PDF", "Planilha"]
    assert b.pending_for("S") is None
    # confirmação antiga continua igual (bool; sem resposta = nega)
    _responder_quando_pendente(b, "S", True)
    assert b.request("S", "executar_shell", "dir") is True
    assert ConfirmationBroker(timeout=0.05).request("S", "x", "y") is False
    assert b.perguntar("S", "pergunta", "?", timeout=0.05) is None


def test_perguntar_usuario_sem_interface_e_com_interface():
    interacao.limpar()
    r = fc.perguntar_usuario("Qual cor?", '["Azul","Verde"]')
    assert not r["ok"] and "padrão mais sensato" in r["error"]
    chamadas = []
    interacao.definir(lambda *a: chamadas.append(a) or {"allow": True, "resposta": "Verde"})
    try:
        r = fc.perguntar_usuario("Qual cor?", "Azul | Verde")
        assert r["ok"] and r["resposta"] == "Verde"
        assert chamadas[0] == ("pergunta", "Qual cor?", "", ["Azul", "Verde"])
        interacao.definir(lambda *a: {"allow": False, "resposta": None})
        assert fc.perguntar_usuario("Qual cor?", "Azul|Verde")["pulou"]
        interacao.definir(lambda *a: None)                  # não respondeu a tempo
        assert "não respondeu" in fc.perguntar_usuario("Qual cor?")["error"]
        interacao.definir(lambda *a: {"allow": True, "resposta": None})
        assert fc.perguntar_usuario("Qual?", "A|B")["resposta"] == "A"   # UI antiga
    finally:
        interacao.limpar()
    assert not fc.perguntar_usuario("")["ok"]


def test_decisoes_do_modo_plano():
    assert raciocinio.pediu_modo_plano("me mostre o plano antes de executar")
    assert raciocinio.pediu_modo_plano("modo plano: organize meus downloads")
    assert raciocinio.pediu_modo_plano("só execute depois que eu aprovar")
    assert not raciocinio.pediu_modo_plano("pesquise voos para Manaus")
    assert raciocinio.plano_arriscado({"passos": ["apagar os arquivos antigos"]})
    assert raciocinio.plano_arriscado({"passos": ["ler"]}, "envie o e-mail para a Ana")
    assert not raciocinio.plano_arriscado({"passos": ["pesquisar", "extrair preço"]},
                                          "pesquise o preço")
    ler = raciocinio.ler_decisao
    assert ler(None) == ("sem_resposta", "")
    assert ler({"allow": True, "resposta": "Aprovar e executar"}) == ("aprovar", "")
    assert ler({"allow": True, "resposta": None}) == ("aprovar", "")
    assert ler({"allow": False, "resposta": "Cancelar"}) == ("cancelar", "")
    assert ler({"allow": True, "resposta": "não envie, só rascunho"}) == (
        "ajustar", "não envie, só rascunho")


class _Roteiro:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.vistos = []

    def complete_messages(self, task, msgs, **k):
        self.vistos.append(msgs[-1]["content"])
        return self.respostas.pop(0)


def _registro(chamadas):
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry(load_settings())
    reg.register("limpar_tmp_teste", lambda **k: chamadas.append(k) or {"ok": True},
                 "Apaga.", {"caminho": "str"})
    return reg


_PLANO = ('{"objetivo":"limpar downloads","pronto_quando":"pasta sem .tmp",'
          '"passos":["listar a pasta","apagar os .tmp"]}')
_CHAMADA = ('{"acao":"usar_ferramenta","ferramenta":"limpar_tmp_teste",'
            '"args":{"caminho":"C:/d/a.tmp"}}')
# O passo arriscado ("apagar os .tmp") vem do PLANO do agente, não do pedido:
# é aí que o modo plano para e pergunta (ordem direta do usuário não para).
_PEDIDO = [{"role": "user", "content": "liste meus downloads, organize e limpe a pasta"}]


def _loop(r, chamadas, modo="auto"):
    return AgentLoop(r, _registro(chamadas), max_iterations=6,
                     raciocinio={"planejar": True, "verificar": False,
                                 "aprovar_plano": modo})


def test_plano_arriscado_espera_aprovacao_e_executa():
    chamadas, perguntas, eventos = [], [], []
    interacao.definir(lambda *a: perguntas.append(a) or
                      {"allow": True, "resposta": raciocinio.OPCAO_APROVAR})
    try:
        r = _Roteiro([_PLANO, _CHAMADA, "Apaguei C:/d/a.tmp."])
        saida = _loop(r, chamadas).run("t", list(_PEDIDO),
                                       on_event=lambda t, d: eventos.append(t))
    finally:
        interacao.limpar()
    assert saida == "Apaguei C:/d/a.tmp." and chamadas == [{"caminho": "C:/d/a.tmp"}]
    tipo, titulo, detalhe, opcoes = perguntas[0]
    assert tipo == "plano" and "2. apagar os .tmp" in detalhe
    assert opcoes == raciocinio.OPCOES_PLANO
    assert "APROVADO PELO USUÁRIO" in r.vistos[1]
    assert eventos[:2] == ["plano", "aprovacao_plano"]


def test_plano_cancelado_nao_executa_nada():
    chamadas = []
    interacao.definir(lambda *a: {"allow": False, "resposta": "Cancelar"})
    try:
        r = _Roteiro([_PLANO])
        saida = _loop(r, chamadas).run("t", list(_PEDIDO))
    finally:
        interacao.limpar()
    assert saida.startswith("Ok, cancelei") and chamadas == [] and len(r.vistos) == 1


def test_sem_resposta_ao_plano_nao_executa():
    chamadas = []
    interacao.definir(lambda *a: None)
    try:
        saida = _loop(_Roteiro([_PLANO]), chamadas).run("t", list(_PEDIDO))
    finally:
        interacao.limpar()
    assert "não executei nada" in saida and chamadas == []


def test_ajuste_refaz_o_plano_e_respeita_o_pedido():
    chamadas, perguntas = [], []
    respostas = [{"allow": True, "resposta": "apague só os de 2023"},
                 {"allow": True, "resposta": raciocinio.OPCAO_APROVAR}]
    interacao.definir(lambda *a: perguntas.append(a) or respostas.pop(0))
    novo = ('{"objetivo":"limpar .tmp de 2023","passos":["listar","apagar só os .tmp '
            'de 2023"]}')
    try:
        r = _Roteiro([_PLANO, novo, "Nada de 2023 para apagar."])
        saida = _loop(r, chamadas).run("t", list(_PEDIDO))
    finally:
        interacao.limpar()
    assert "apague só os de 2023" in r.vistos[1]            # pediu o plano refeito
    assert "só os .tmp de 2023" in perguntas[1][2]         # mostrou o plano novo
    assert "Ajuste pedido pelo usuário: apague só os de 2023" in r.vistos[2]
    assert saida == "Nada de 2023 para apagar."


def test_sem_interface_ou_modo_nunca_executa_direto():
    for modo, com_interface in (("auto", False), ("nunca", True)):
        chamadas = []
        if com_interface:
            interacao.definir(lambda *a: {"allow": False})
        try:
            r = _Roteiro([_PLANO, _CHAMADA, "Feito."] if modo == "auto"
                         else [_CHAMADA, "Feito."])
            if modo == "nunca":                     # sem plano: planejar ligado,
                r.respostas.insert(0, _PLANO)       # mas sem pedir aprovação
            assert _loop(r, chamadas, modo).run("t", list(_PEDIDO)) == "Feito."
        finally:
            interacao.limpar()
        assert chamadas == [{"caminho": "C:/d/a.tmp"}]


def test_ordem_direta_de_acao_arriscada_nao_para_no_plano():
    """Política de 29/10: "apague os .tmp" é a própria autorização; a
    confirmação fica no guard (popup da ferramenta), não numa 2ª pergunta."""
    chamadas, perguntas = [], []
    interacao.definir(lambda *a: perguntas.append(a))
    try:
        r = _Roteiro([_CHAMADA, "Apaguei C:/d/a.tmp."])
        saida = AgentLoop(r, _registro(chamadas), raciocinio={
            "planejar": True, "verificar": False, "aprovar_plano": "auto"}).run(
            "t", [{"role": "user", "content": "apague os arquivos .tmp da pasta C:/d"}])
    finally:
        interacao.limpar()
    assert perguntas == [] and chamadas == [{"caminho": "C:/d/a.tmp"}]
    assert saida == "Apaguei C:/d/a.tmp."
    assert not raciocinio.pedido_arriscado("pesquise voos para Manaus")


def test_pedido_de_modo_plano_forca_plano_mesmo_em_tarefa_simples():
    perguntas = []
    interacao.definir(lambda *a: perguntas.append(a) or {"allow": False})
    try:
        r = _Roteiro(['{"objetivo":"x","passos":["ler o arquivo"]}'])
        saida = AgentLoop(r, _registro([]), raciocinio={
            "planejar": False, "aprovar_plano": "auto"}).run(
            "t", [{"role": "user", "content": "modo plano: leia o readme"}])
    finally:
        interacao.limpar()
    assert r.vistos[0] == raciocinio.PEDIR_PLANO and perguntas and "cancelei" in saida


def test_usuario_ja_autorizou_plano_arriscado_segue_sem_esperar():
    """Conversa 71: "resolva de qualquer forma" e o plano ficou 8 min parado
    esperando aprovação, terminando em "não executei nada"."""
    chamadas, perguntas = [], []
    interacao.definir(lambda *a: perguntas.append(a))
    autorizado = [{"role": "user", "content":
                   "liste meus downloads e apague os .tmp, pode executar de qualquer forma"}]
    try:
        r = _Roteiro([_PLANO, _CHAMADA, "Apaguei C:/d/a.tmp."])
        saida = _loop(r, chamadas).run("t", autorizado)
    finally:
        interacao.limpar()
    assert perguntas == [] and chamadas == [{"caminho": "C:/d/a.tmp"}]
    assert saida == "Apaguei C:/d/a.tmp."


def test_pedir_para_ver_o_plano_continua_valendo_mesmo_autorizado():
    perguntas = []
    interacao.definir(lambda *a: perguntas.append(a))
    pedido = [{"role": "user", "content":
               "me mostre o plano antes e depois pode executar: apague os .tmp"}]
    try:
        _loop(_Roteiro([_PLANO]), []).run("t", pedido)
    finally:
        interacao.limpar()
    assert perguntas and perguntas[0][0] == "plano"


def test_tempo_esgotado_resume_o_que_foi_feito():
    """Antes: só "Interrompi… está no histórico" e o que foi descoberto sumia."""
    import time as _t

    class _Lento(_Roteiro):
        def complete_messages(self, task, msgs, **k):
            if not self.vistos:
                _t.sleep(1.2)               # 1º passo estoura o limite de 1 s
            return super().complete_messages(task, msgs, **k)

    chamadas = []
    r = _Lento([_CHAMADA, "Limpei a.tmp; faltou o resto. Mande continua."])
    loop = AgentLoop(r, _registro(chamadas), max_iterations=6, timeout_s=1,
                     raciocinio={"planejar": False, "verificar": False})
    saida = loop.run("t", [{"role": "user", "content": "apague o a.tmp"}])
    assert chamadas == [{"caminho": "C:/d/a.tmp"}]
    assert saida.startswith("⏱ Tempo da tarefa esgotado") and "a.tmp" in saida
    assert "OBSERVAÇÕES" in r.vistos[-1]          # resumo feito a partir do que rodou
