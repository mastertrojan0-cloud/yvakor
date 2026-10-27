"""Extensão "estilo Claude no Chrome": Parar, permissões, abas, atalhos…

Cada bloco cobre uma etapa. O que roda DENTRO da página (banner, motor de
ações) é verificado num Chrome real com tests/extensao/; aqui ficam a lógica do
núcleo e as verificações estáticas.
"""
from __future__ import annotations

import http.client
import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EXT = ROOT / "chrome-extension"


# --------------------------------------------------------------------------- #
# Etapa A — botão Parar
# --------------------------------------------------------------------------- #
def test_cancelar_pendentes_acorda_quem_espera_a_extensao_na_hora():
    """Antes, um comando esperando o navegador só soltava após até 45s."""
    from yvakor.extensao_bridge import PonteExtensao
    p = PonteExtensao()
    saida = {}

    def esperar():
        t0 = time.time()
        saida["r"] = p.comando("click", {"alvo": "e1"}, espera=30)
        saida["dt"] = time.time() - t0

    t = threading.Thread(target=esperar)
    t.start()
    for _ in range(100):
        if p._comandos:
            break
        time.sleep(0.01)
    assert p.cancelar_pendentes() == 1
    t.join(5)
    assert not t.is_alive()
    assert saida["r"]["ok"] is False and "cancelado" in saida["r"]["erro"]
    assert saida["dt"] < 3
    assert p._comandos == {} and p._eventos == {}


def test_resultado_tardio_de_comando_cancelado_e_descartado():
    from yvakor.extensao_bridge import PonteExtensao
    p = PonteExtensao()
    p.resultado("fantasma", True, dados={"x": 1})      # ninguém espera por ele
    assert p._resultados == {}                         # não acumula órfão


def _orquestrador_falso(rodando=("S1",)):
    from yvakor.orchestrator import ConfirmationBroker
    eu = SimpleNamespace(
        progress={s: {"running": True, "steps": []} for s in rodando},
        _prog_lock=threading.Lock(), _cancel_lock=threading.Lock(),
        _cancelados=set(), confirm_broker=ConfirmationBroker(timeout=5),
        episodic=SimpleNamespace(active_id="S1", modo_privado=lambda p: None))
    eu.progress["S2"] = {"running": False, "steps": []}      # já terminou
    return eu


def test_cancelar_marca_so_quem_esta_rodando_e_nega_confirmacao_pendente():
    from yvakor.orchestrator import Orchestrator
    eu = _orquestrador_falso()
    resposta = {}
    t = threading.Thread(target=lambda: resposta.update(
        r=eu.confirm_broker.request("S1", "executar_shell", "dir")))
    t.start()
    for _ in range(100):
        if eu.confirm_broker.pending_for("S1"):
            break
        time.sleep(0.01)
    alvos = Orchestrator.cancelar(eu, None)            # Parar sem sessão = todas
    t.join(3)
    assert alvos == ["S1"] and "S2" not in eu._cancelados   # S2 já tinha acabado
    assert "S1" in eu._cancelados
    assert resposta["r"] is False                      # confirmação destravada e NEGADA
    assert Orchestrator.cancelar(eu, "S2") == ["S2"]   # com sessão explícita


def test_process_entrega_should_stop_que_enxerga_o_parar_e_limpa_ao_fim():
    from yvakor.orchestrator import Orchestrator
    eu = _orquestrador_falso()
    visto = {}

    def impl(msg, session_id=None, should_stop=None, **kw):
        visto["antes"] = should_stop()
        Orchestrator.cancelar(eu, "S1")                # usuário clica em Parar
        visto["depois"] = should_stop()
        return "ok"
    eu._process_impl = impl
    assert Orchestrator.process(eu, "oi", session_id="S1") == "ok"
    assert visto == {"antes": False, "depois": True}
    assert "S1" not in eu._cancelados                  # a próxima execução começa limpa
    # o should_stop de quem chamou (cowork) continua valendo junto
    eu._process_impl = lambda *a, should_stop=None, **k: should_stop()
    assert Orchestrator.process(eu, "x", session_id="S1", should_stop=lambda: True) is True


def test_endpoint_cancelar_exige_token_e_chama_o_agente():
    import yvakor.server as S
    chamado = []
    agente = SimpleNamespace(cancelar=lambda sid=None: chamado.append(sid) or ["S1"])
    original = S.get_agent
    S.get_agent = lambda: agente
    srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(token=None, corpo=None):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
        h = {"Host": "127.0.0.1:7777", "Content-Type": "application/json"}
        if token:
            h["X-YVAKOR-Token"] = token
        c.request("POST", "/api/chat/cancelar", body=json.dumps(corpo or {}), headers=h)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")
    try:
        assert post()[0] == 403 and chamado == []           # sem token: barrado
        st, j = post(S.TOKEN, {})
        assert st == 200 and j["cancelados"] == ["S1"] and chamado == [None]
        post(S.TOKEN, {"session": "S9"})
        assert chamado[-1] == "S9"
    finally:
        srv.shutdown()
        S.get_agent = original


def test_painel_e_background_tem_o_fluxo_do_botao_parar():
    painel = (EXT / "sidepanel.js").read_text(encoding="utf-8")
    assert "/api/chat/cancelar" in painel and "async function pararTarefa" in painel
    assert 'enviar.addEventListener("click", () => (ocupado ? pararTarefa() : enviarMensagem()))' in painel
    assert 'fim_tarefa' in painel
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert 'msg.tipo === "parar"' in bg and "/api/chat/cancelar" in bg
    assert "function bannerNaPagina" in bg and "indicadorLigar(t.id)" in bg
    assert "YVAKOR está controlando esta aba" in bg


# --------------------------------------------------------------------------- #
# Etapa B — permissões por site e ações sensíveis
# --------------------------------------------------------------------------- #
def _politica():
    import tempfile
    from yvakor.extensao_politica import PoliticaSites
    d = Path(tempfile.mkdtemp())
    return PoliticaSites(d / "s.json", d / "prefs.json")


def test_politica_hosts_subdominios_e_persistencia():
    from yvakor.extensao_politica import PoliticaSites, host_de
    assert host_de("https://www.Loja.com.br:8443/x?y=1") == "loja.com.br"
    assert host_de("") == ""
    p = _politica()
    assert p.modo == "perguntar"                       # padrão: pede por site
    assert not p.permitido("loja.com")
    p.permitir("https://www.loja.com/x")
    assert p.permitido("loja.com") and p.permitido("pay.loja.com")
    assert not p.permitido("lojax.com")                # domínio parecido não herda
    assert PoliticaSites(p.arquivo, p.prefs).permitido("loja.com")      # persistiu
    p.bloquear("temp.com", so_nesta_sessao=True)
    assert p.bloqueado("temp.com")
    assert not PoliticaSites(p.arquivo, p.prefs).bloqueado("temp.com")  # só a sessão
    assert p.remover("loja.com") and not p.permitido("loja.com")
    try:
        p.definir_modo("xyz")
        assert False, "modo inválido deveria ser rejeitado"
    except ValueError:
        pass


def test_navegar_site_novo_pergunta_buscador_livre_banco_sempre_pergunta():
    p = _politica()
    assert p.precisa_perguntar_navegacao("https://www.google.com/search?q=x") is None
    assert p.precisa_perguntar_navegacao("https://loja.com/a") == "loja.com"
    p.definir_modo("autonomo")
    assert p.precisa_perguntar_navegacao("https://blog.com") is None
    assert p.precisa_perguntar_navegacao("https://www.nubank.com.br") == "nubank.com.br"
    p.permitir("nubank.com.br")                        # depois de permitir, não pergunta
    assert p.precisa_perguntar_navegacao("https://www.nubank.com.br") is None


class _PonteScript:
    """PONTE.comando falso: devolve as respostas na ordem e guarda o que recebeu."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def __call__(self, tipo, args=None, espera=45.0):
        self.chamadas.append((tipo, dict(args or {})))
        return self.respostas.pop(0) if self.respostas else {"ok": True}


def _eu_com_politica():
    import types
    from yvakor.orchestrator import Orchestrator
    if str(ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests"))
    from test_extensao_acoes import _orquestrador_falso
    eu, pw = _orquestrador_falso()
    eu.politica_sites = _politica()
    for nome in ("_confirmar_extensao", "_permitir_navegacao"):
        setattr(eu, nome, types.MethodType(getattr(Orchestrator, nome), eu))
    return eu, pw


def _com_confirmador(resposta, perguntas):
    import yvakor.tools.guard as G

    def fn(acao, detalhe):
        perguntas.append((acao, detalhe))
        return resposta
    G.set_thread_confirmer(fn)


def test_site_novo_aprovado_e_salvo_e_o_comando_e_reenviado_com_a_flag():
    import yvakor.tools.guard as G
    from yvakor.extensao_bridge import PONTE
    from unittest import mock
    eu, pw = _eu_com_politica()
    ponte = _PonteScript({"ok": False, "precisa_confirmar": {"tipo": "site", "host": "loja.com"}},
                         {"ok": True, "url": "https://loja.com"})
    perguntas = []
    _com_confirmador(True, perguntas)
    try:
        with mock.patch.object(PONTE, "comando", ponte):
            r = eu.tools.run("navegador_clicar", alvo="e1")
    finally:
        G.clear_thread_confirmer()
    assert r["ok"] is True and len(ponte.chamadas) == 2
    primeira, segunda = ponte.chamadas[0][1], ponte.chamadas[1][1]
    assert primeira["politica"]["modo"] == "perguntar" and "confirmado_site" not in primeira
    assert segunda["confirmado_site"] is True
    assert "loja.com" in segunda["politica"]["permitidos"]      # política atualizada
    assert "Permitir que o YVAKOR aja em loja.com" in perguntas[0][0]
    assert eu.politica_sites.permitido("loja.com")              # ficou salvo


def test_site_negado_nao_age_e_vale_so_ate_reiniciar():
    import yvakor.tools.guard as G
    from yvakor.extensao_bridge import PONTE
    from unittest import mock
    eu, pw = _eu_com_politica()
    ponte = _PonteScript({"ok": False, "precisa_confirmar": {"tipo": "site", "host": "spam.com"}})
    _com_confirmador(False, [])
    try:
        with mock.patch.object(PONTE, "comando", ponte):
            r = eu.tools.run("navegador_clicar", alvo="e1")
    finally:
        G.clear_thread_confirmer()
    assert r["ok"] is False and r.get("negado") is True and "não permitiu" in r["erro"]
    assert len(ponte.chamadas) == 1                              # não reenviou
    assert eu.politica_sites.bloqueado("spam.com") and not eu.politica_sites._dados["bloqueados"]


def test_sem_confirmador_na_duvida_nao_age():
    import yvakor.tools.guard as G
    from yvakor.extensao_bridge import PONTE
    from unittest import mock
    G.clear_thread_confirmer()
    eu, pw = _eu_com_politica()
    ponte = _PonteScript({"ok": False, "precisa_confirmar": {
        "tipo": "acao", "host": "loja.com", "descricao": "Clicar em «Comprar agora»",
        "motivo": "ação irreversível ou com custo"}})
    with mock.patch.object(PONTE, "comando", ponte):
        r = eu.tools.run("navegador_clicar", alvo="e1")
    assert r["ok"] is False and len(ponte.chamadas) == 1


def test_acao_sensivel_mostra_a_descricao_e_so_age_depois_de_aprovada():
    import yvakor.tools.guard as G
    from yvakor.extensao_bridge import PONTE
    from unittest import mock
    eu, pw = _eu_com_politica()
    eu.politica_sites.permitir("loja.com")
    ponte = _PonteScript({"ok": False, "precisa_confirmar": {
        "tipo": "acao", "host": "loja.com", "descricao": "Clicar em «Comprar agora»",
        "motivo": "ação irreversível ou com custo"}}, {"ok": True})
    perguntas = []
    _com_confirmador(True, perguntas)
    try:
        with mock.patch.object(PONTE, "comando", ponte):
            r = eu.tools.run("navegador_clicar", alvo="e1")
    finally:
        G.clear_thread_confirmer()
    assert r["ok"] is True
    assert perguntas[0][0] == "Clicar em «Comprar agora»"
    assert "loja.com" in perguntas[0][1] and "irreversível" in perguntas[0][1]
    assert ponte.chamadas[1][1]["confirmado_acao"] is True


def test_navegar_para_site_novo_pede_permissao_antes_de_enviar_o_comando():
    import yvakor.tools.guard as G
    from yvakor.extensao_bridge import PONTE
    from unittest import mock
    eu, pw = _eu_com_politica()
    ponte = _PonteScript()
    perguntas = []
    _com_confirmador(False, perguntas)
    try:
        with mock.patch.object(PONTE, "comando", ponte):
            r = eu.tools.run("navegador_ir", url="https://loja.com/produto")
            assert r["ok"] is False and ponte.chamadas == []     # negado: nada enviado
            eu.politica_sites.remover("loja.com")                # esquece o "negar da sessão"
            eu.politica_sites._bloqueados_sessao.clear()
            _com_confirmador(True, perguntas)
            r = eu.tools.run("navegador_ir", url="https://loja.com/produto")
            assert r["ok"] is True and len(ponte.chamadas) == 1
            r = eu.tools.run("navegador_ir", url="https://loja.com/outra")   # já permitido
            assert len(ponte.chamadas) == 2 and len(perguntas) == 2
            eu.tools.run("navegador_pesquisar", termo="gatos")               # buscador: livre
            assert len(perguntas) == 2
    finally:
        G.clear_thread_confirmer()


def test_politica_so_vai_junto_em_acoes_com_efeito():
    from yvakor.extensao_bridge import PONTE
    from unittest import mock
    eu, pw = _eu_com_politica()
    ponte = _PonteScript()
    with mock.patch.object(PONTE, "comando", ponte):
        eu.tools.run("navegador_ver")
        eu.tools.run("navegador_extrair", seletor="#x")
        eu.tools.run("navegador_digitar", alvo="e1", texto="oi")
    assert "politica" not in ponte.chamadas[0][1] and "politica" not in ponte.chamadas[1][1]
    assert "politica" in ponte.chamadas[2][1]


def test_endpoint_politica_get_post_com_token_e_validacao():
    import yvakor.server as S
    pol = _politica()
    agente = SimpleNamespace(politica_sites=pol)
    original = S.get_agent
    S.get_agent = lambda: agente
    srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def req(metodo, token=None, corpo=None):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
        h = {"Host": "127.0.0.1:7777", "Content-Type": "application/json"}
        if token:
            h["X-YVAKOR-Token"] = token
        c.request(metodo, "/api/extensao/politica",
                  body=json.dumps(corpo) if corpo is not None else None, headers=h)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")
    try:
        st, j = req("GET")
        assert st == 200 and j["modo"] == "perguntar"
        assert [m["id"] for m in j["modos"]] == ["perguntar", "autonomo"]
        assert req("POST", None, {"modo": "autonomo"})[0] == 403 and pol.modo == "perguntar"
        assert req("POST", S.TOKEN, {"modo": "autonomo"})[0] == 200 and pol.modo == "autonomo"
        assert req("POST", S.TOKEN, {"modo": "xyz"})[0] == 400
        st, j = req("POST", S.TOKEN, {"permitir": "https://www.exemplo.com/a"})
        assert st == 200 and j["permitidos"] == ["exemplo.com"]
        st, j = req("POST", S.TOKEN, {"remover": "exemplo.com"})
        assert st == 200 and j["permitidos"] == []
    finally:
        srv.shutdown()
        S.get_agent = original


def test_decisao_de_permissoes_do_background_no_node():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node não instalado")
    r = subprocess.run([node, str(ROOT / "tests" / "extensao" / "politica_background.js")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    assert r.returncode == 0, r.stderr[:400]
    casos = json.loads(r.stdout)["casos"]
    assert len(casos) >= 13
    assert [c["nome"] for c in casos if not c["ok"]] == []


def test_painel_tem_a_ui_de_permissoes():
    painel = (EXT / "sidepanel.js").read_text(encoding="utf-8")
    assert "/api/extensao/politica" in painel and "carregarPolitica" in painel
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    assert 'id="modo-acao"' in html and 'id="sites-lista"' in html
    pagina = (EXT / "pagina.js").read_text(encoding="utf-8")
    assert "descrever_acao" in pagina.split("window.__yvakorAcoes =")[-1]


# --------------------------------------------------------------------------- #
# Etapa E (parcial) — navegador_procurar (o "find" por descrição)
# --------------------------------------------------------------------------- #
def test_navegador_procurar_chega_a_extensao_e_e_oferecido_ao_modelo_local():
    from unittest import mock
    from yvakor.extensao_bridge import PONTE
    if str(ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests"))
    import test_extensao_acoes as base
    eu, pw = base._orquestrador_falso()
    ponte = _PonteScript({"ok": True, "itens": []})
    with mock.patch.object(PONTE, "comando", ponte):
        eu.tools.run("navegador_procurar", consulta="campo de busca", max=5)
    assert ponte.chamadas == [("find", {"consulta": "campo de busca", "max": 5})]
    assert pw == []
    ag = base._agente()
    nomes = base._sel(ag, "pesquise gatos fofos no google", 5)     # modo compacto
    assert "navegador_procurar" in nomes and len(nomes) == 8
    assert nomes.index("navegador_ver") < nomes.index("navegador_procurar") < nomes.index("navegador_pesquisar")


def test_background_e_motor_expoem_o_procurar():
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert 'c.tipo === "find"' in bg and 'acaoPagina("procurar"' in bg
    pagina = (EXT / "pagina.js").read_text(encoding="utf-8")
    assert "procurar }" in pagina.split("window.__yvakorAcoes =")[-1]


# --------------------------------------------------------------------------- #
# Etapa D — ponte rápida (long-poll)
# --------------------------------------------------------------------------- #
def test_longpoll_entrega_o_comando_assim_que_ele_chega():
    from yvakor.extensao_bridge import PonteExtensao
    p = PonteExtensao()
    saida = {}

    def consumir():
        t0 = time.time()
        saida["cmds"] = p.pendentes(espera=5)
        saida["dt"] = time.time() - t0
    t = threading.Thread(target=consumir)
    t.start()
    time.sleep(0.3)                                    # o consumidor já está esperando
    produtor = threading.Thread(target=lambda: p.comando("click", {"alvo": "e1"}, espera=3))
    produtor.start()
    t.join(5)
    assert [c["tipo"] for c in saida["cmds"]] == ["click"]
    assert saida["dt"] < 1.5, saida["dt"]              # ~0,3s (a espera), não 5s
    assert p.pendentes() == []                         # entregue uma única vez
    p.cancelar_pendentes()
    produtor.join(5)


def test_longpoll_sem_comando_devolve_vazio_no_prazo_e_sem_espera_nao_bloqueia():
    from yvakor.extensao_bridge import PonteExtensao
    p = PonteExtensao()
    t0 = time.time()
    assert p.pendentes(espera=0.4) == []
    assert 0.3 <= time.time() - t0 < 1.5
    t0 = time.time()
    assert p.pendentes() == [] and time.time() - t0 < 0.2     # comportamento antigo intacto


def test_endpoint_comandos_limita_e_valida_o_parametro_espera():
    import yvakor.server as S
    from unittest import mock
    from yvakor.extensao_bridge import PONTE
    visto = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def get(qs):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
        c.request("GET", "/api/ext/comandos" + qs,
                  headers={"Host": "127.0.0.1:7777", "X-YVAKOR-Token": S.TOKEN})
        r = c.getresponse()
        return r.status, json.loads(r.read())
    try:
        with mock.patch.object(PONTE, "pendentes",
                               lambda tipo=None, espera=0.0: visto.append(espera) or []):
            assert get("")[0] == 200
            get("?espera=999")                          # limitado a 25s
            get("?espera=abc")                          # inválido → 0
            get("?espera=-5")                           # negativo → 0
            get("?espera=12.5")
        assert visto == [0.0, 25.0, 0.0, 0.0, 12.5]
    finally:
        srv.shutdown()


def test_extensao_usa_laco_de_longpoll_e_nao_o_polling_de_1_2s():
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert "iniciarLacoPonte" in bg and "/api/ext/comandos?espera=" in bg
    assert "ponteComandos(20)" in bg                    # < 30s de ociosidade do service worker
    assert "setInterval(ponteComandos" not in bg        # o polling antigo saiu
    assert "AbortSignal.timeout" in bg                  # nenhuma volta pode pendurar


# --------------------------------------------------------------------------- #
# Etapa C — várias abas, id explícito e grupo YVAKOR
# --------------------------------------------------------------------------- #
def test_todas_as_ferramentas_aceitam_e_encaminham_o_id_da_aba():
    from unittest import mock
    from yvakor.extensao_bridge import PONTE
    if str(ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests"))
    eu, pw = _eu_com_politica()
    eu.politica_sites.definir_modo("autonomo")   # só mede o encaminhamento de `aba`
    ponte = _PonteScript()
    chamadas = {
        "navegador_ver": {}, "navegador_clicar": {"alvo": "e1"},
        "navegador_digitar": {"alvo": "e1", "texto": "x"},
        "navegador_preencher": {"alvo": "e1", "valor": "x"},
        "navegador_rolar": {"direcao": "fim"}, "navegador_procurar": {"consulta": "busca"},
        "navegador_extrair": {}, "navegador_ir": {"url": "https://x.com"},
    }
    with mock.patch.object(PONTE, "comando", ponte):
        for nome, args in chamadas.items():
            eu.tools.run(nome, aba=42, **args)
    assert [c[1].get("aba") for c in ponte.chamadas] == [42] * len(chamadas)
    for nome in chamadas:                               # e todas anunciam o argumento ao modelo
        assert eu.tools.specs[nome]["args"].get("aba") == "int?", nome


def test_sem_aba_o_argumento_nem_vai_junto_e_forcar_nunca_e_exposto_ao_modelo():
    from unittest import mock
    from yvakor.extensao_bridge import PONTE
    if str(ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests"))
    import test_extensao_acoes as base
    eu, pw = base._orquestrador_falso()
    ponte = _PonteScript()
    with mock.patch.object(PONTE, "comando", ponte):
        eu.tools.run("navegador_ver")
        eu.tools.run("navegador_fechar_aba", indice=3, forcar=True)   # tentativa de burlar
    assert "aba" not in ponte.chamadas[0][1]
    # `forcar` não é um campo encaminhado: só o núcleo, por código, poderia usá-lo
    assert "forcar" not in ponte.chamadas[1][1]
    assert "forcar" not in eu.tools.specs["navegador_fechar_aba"]["args"]
    assert "aba" in eu.tools.specs["navegador_fechar_aba"]["args"]
    assert "grupo YVAKOR" in eu.tools.specs["navegador_fechar_aba"]["desc"]


def test_manifest_pede_a_permissao_de_grupos_de_abas():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert "tabGroups" in m["permissions"] and "tabs" in m["permissions"]


def test_controle_de_abas_do_background_no_node():
    """Roda o background.js REAL num Chrome simulado em memória (22 casos)."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node não instalado")
    r = subprocess.run([node, str(ROOT / "tests" / "extensao" / "abas_background.js")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    assert r.returncode == 0, r.stdout[:300] + r.stderr[:300]
    j = json.loads(r.stdout)
    assert "erro" not in j, j.get("erro", "")[:300]
    assert len(j["casos"]) >= 22
    assert [c["nome"] for c in j["casos"] if not c["ok"]] == []


def test_atalhos_barra_no_node_e_ligados_ao_painel():
    """Lógica pura dos /comandos (21 casos) + a fiação no painel/manifest/background."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node não instalado")
    r = subprocess.run([node, str(ROOT / "tests" / "extensao" / "atalhos.test.js")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    assert r.returncode == 0, r.stdout[:300] + r.stderr[:300]
    j = json.loads(r.stdout)
    assert len(j["casos"]) >= 21
    assert [c["nome"] for c in j["casos"] if not c["ok"]] == []
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    assert html.index("atalhos.js") < html.index("sidepanel.js")
    js = (EXT / "sidepanel.js").read_text(encoding="utf-8")
    assert "YvakorAtalhos.expandir" in js and "message: mensagem" in js
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert "contextMenus" in m["permissions"] and "abrir-yvakor" in m["commands"]
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert "yvakor-selecao" in bg and "pedido_painel" in bg


def test_enviar_arquivo_manda_base64_e_recusa_segredos_e_arquivos_grandes(tmp_path):
    import base64
    from unittest import mock
    from yvakor.extensao_bridge import PONTE
    from yvakor.orchestrator import _checar_arquivo_envio, ENVIO_MAX_BYTES
    eu, pw = _eu_com_politica()
    eu.politica_sites.definir_modo("autonomo")
    ok = tmp_path / "curriculo.pdf"
    ok.write_bytes(b"%PDF-1.4 conteudo")
    ponte = _PonteScript()
    with mock.patch.object(PONTE, "comando", ponte):
        r = eu.tools.run("navegador_enviar_arquivo", caminho=str(ok), alvo="e7", aba=5)
    tipo, kw = ponte.chamadas[0][0], ponte.chamadas[0][1]
    assert tipo == "upload" and kw["alvo"] == "e7" and kw["aba"] == 5
    assert kw["nome"] == "curriculo.pdf" and kw["mime"] == "application/pdf"
    assert base64.b64decode(kw["b64"]) == b"%PDF-1.4 conteudo"
    assert "politica" in kw                      # ação com efeito: vai com a política
    assert r.get("arquivo")

    # recusas — a extensão nem é chamada
    segredo = tmp_path / ".env"
    segredo.write_text("CHAVE=1")
    grande = tmp_path / "grande.bin"
    grande.write_bytes(b"x" * (ENVIO_MAX_BYTES + 1))
    vazio = tmp_path / "vazio.txt"
    vazio.write_bytes(b"")
    assert "segredos" in _checar_arquivo_envio(str(segredo))
    assert "5 MB" in _checar_arquivo_envio(str(grande))
    assert "vazio" in _checar_arquivo_envio(str(vazio))
    assert "não encontrado" in _checar_arquivo_envio(str(tmp_path / "nao.txt"))
    assert "próprio YVAKOR" in _checar_arquivo_envio(str(ROOT / "config" / "settings.yaml"))
    assert _checar_arquivo_envio("") != ""
    ponte2 = _PonteScript()
    with mock.patch.object(PONTE, "comando", ponte2):
        r = eu.tools.run("navegador_enviar_arquivo", caminho=str(segredo))
    assert ponte2.chamadas == [] and not r.get("ok")


def test_upload_pergunta_sempre_e_esta_no_seletor_e_no_background():
    from yvakor.tools.router import GRUPOS
    assert "navegador_enviar_arquivo" in GRUPOS["navegador"]["prioridade"]
    bg = (EXT / "background.js").read_text(encoding="utf-8")
    assert '"enviar_arquivo"' in bg and 'c.tipo === "upload"' in bg
    pg = (EXT / "pagina.js").read_text(encoding="utf-8")
    assert "envia um arquivo do seu computador" in pg and "enviar_arquivo," in pg
