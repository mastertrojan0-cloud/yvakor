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
