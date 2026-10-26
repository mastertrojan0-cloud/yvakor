"""Regressões de segurança, ponte da extensão, processos e qualidade de resposta.

Cobre o que a auditoria apontou como sem teste: Confirmation Guard, portão do
servidor (token/Host/Content-Type), ponte de comandos da extensão, janelas de
console no Windows e o controle de qualidade do caminho local.
"""
from __future__ import annotations

import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- #
# Confirmation Guard
# --------------------------------------------------------------------------- #
class _SemTTY:
    def isatty(self):
        return False


def test_guard_always_confirm_vale_mesmo_em_total():
    import yvakor.tools.guard as G
    g = G.ConfirmationGuard(["arquivos_copiar"], auto_approve=True,
                            always_confirm=["executar_shell", "arquivos_apagar"],
                            total=True)
    G.clear_thread_confirmer()
    with mock.patch.object(sys, "stdin", _SemTTY()):
        # ação de trabalho sob "total": liberada
        assert g.confirm("arquivos_copiar", "x") is True
        # crítica sob "total", sem humano para confirmar: NEGADA
        assert g.confirm("executar_shell", "rm -rf /") is False
        assert g.confirm("arquivos_apagar", "C:/x") is False
    assert g.requires_confirmation("executar_shell")
    G.set_thread_confirmer(lambda a, d: True)
    try:
        assert g.confirm("executar_shell", "ls") is True   # humano aprovou
    finally:
        G.clear_thread_confirmer()


def test_settings_protege_nomes_reais_das_ferramentas():
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    ferramentas = cfg["tools"]
    assert str(ferramentas["privilegios"]).lower() != "total"
    assert ferramentas["auto_approve"] is False
    for nome in ("arquivos_apagar", "arquivos_escrever", "arquivos_mover",
                 "executar_shell", "rede_mqtt_publicar", "rede_camera_credenciais"):
        assert nome in ferramentas["always_confirm"], nome


# --------------------------------------------------------------------------- #
# Servidor: token, Host, Content-Type
# --------------------------------------------------------------------------- #
def _servidor():
    import yvakor.server as S
    srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return S, srv, srv.server_address[1]


def _req(port, metodo, path, host="127.0.0.1:7777", token=None, body=None,
         ctype="application/json"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": host}
    if token:
        h["X-YVAKOR-Token"] = token
    dados = None
    if body is not None:
        dados = json.dumps(body).encode()
        h["Content-Type"] = ctype
    c.request(metodo, path, body=dados, headers=h)
    r = c.getresponse()
    corpo = r.read()
    c.close()
    return r.status, corpo


def test_servidor_portao_de_seguranca():
    S, srv, port = _servidor()
    try:
        assert _req(port, "GET", "/api/token")[0] == 200
        assert _req(port, "GET", "/api/token", host="evil.com")[0] == 403
        # leitura também protegida contra DNS-rebinding
        assert _req(port, "GET", "/api/ping", host="evil.com")[0] == 403
        assert _req(port, "POST", "/api/chat", body={"message": "oi"})[0] == 403
        assert _req(port, "POST", "/api/chat", host="evil.com", token=S.TOKEN,
                    body={"message": "oi"})[0] == 403
        assert _req(port, "POST", "/api/chat", token=S.TOKEN,
                    body={"message": "oi"}, ctype="text/plain")[0] == 400
        assert _req(port, "DELETE", "/api/sessions/abc")[0] == 403
        # comandos da extensão carregam o que o agente digita: exigem token
        assert _req(port, "GET", "/api/ext/comandos")[0] == 403
        assert _req(port, "GET", "/api/ext/comandos", token=S.TOKEN)[0] == 200
    finally:
        srv.shutdown()


# --------------------------------------------------------------------------- #
# Ponte da extensão: entrega única
# --------------------------------------------------------------------------- #
def test_ponte_entrega_comando_uma_unica_vez():
    from yvakor.extensao_bridge import PonteExtensao
    p = PonteExtensao()
    p._comandos["c1"] = {"id": "c1", "tipo": "newtab", "args": {}, "criado": 0}
    assert len(p.pendentes()) == 1
    # antes: reentregue após 10s (open/snapshot demoram) → aba duplicada
    assert p.pendentes() == []


def test_ponte_permitir_outro_e_por_thread():
    from yvakor.extensao_bridge import PonteExtensao
    p = PonteExtensao()
    p.permitir_outro = True
    visto = {}
    t = threading.Thread(target=lambda: visto.setdefault("v", p.permitir_outro))
    t.start()
    t.join()
    assert visto["v"] is False and p.permitir_outro is True


# --------------------------------------------------------------------------- #
# Processos: nada de janela de console piscando
# --------------------------------------------------------------------------- #
def test_proc_injeta_create_no_window():
    from yvakor import proc
    if proc._NT:
        with mock.patch("subprocess.run") as run:
            proc.run(["x"])
        assert run.call_args.kwargs["creationflags"] == proc.NO_WINDOW
        with mock.patch("subprocess.run") as run:   # respeita flag explícita
            proc.run(["x"], creationflags=1)
        assert run.call_args.kwargs["creationflags"] == 1


def test_nenhum_subprocess_cru_no_pacote():
    """subprocess.run/Popen direto abre janela de console no Windows (varredura
    de rede, OCR, TTS...). Tudo deve passar por yvakor.proc."""
    import re
    padrao = re.compile(r"\bsubprocess\.(run|Popen|call|check_output|check_call)\(")
    cruas = []
    for arq in (ROOT / "yvakor").rglob("*.py"):
        if arq.name == "proc.py" or "__pycache__" in arq.parts:
            continue
        for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
            if padrao.search(linha) and not linha.lstrip().startswith("#"):
                cruas.append(f"{arq.relative_to(ROOT)}:{n}")
    assert not cruas, "use yvakor.proc: " + ", ".join(cruas)


# --------------------------------------------------------------------------- #
# Respostas: caminho local e poda
# --------------------------------------------------------------------------- #
def test_resposta_local_so_passa_se_tiver_qualidade():
    from yvakor.orchestrator import Orchestrator as O
    assert O._resposta_local_ok("A capital da França é Paris.", "qual a capital da frança")
    assert O._resposta_local_ok("Oi! Em que posso ajudar?", "oi")
    assert not O._resposta_local_ok("", "oi")
    assert not O._resposta_local_ok('{"acao":"usar_ferramenta","ferramenta":"x"}', "abra")
    assert not O._resposta_local_ok("ok\nok\nok\nok\nok\nok", "como funciona isso agora")
    assert not O._resposta_local_ok("Sim.", "me explique como funciona o protocolo rtsp")
    assert not O._resposta_local_ok(
        "Como um modelo de linguagem, não tenho acesso a isso.", "cotação do dólar")


def test_poda_nao_mutila_explicacao_nem_lista():
    from yvakor.orchestrator import Orchestrator as O
    longa = ("Primeiro, o RTSP negocia a sessão. Depois o servidor envia RTP. "
             "O cliente decodifica. O TEARDOWN encerra. Esse é o fluxo.")
    assert O._podar_resposta(None, longa, "Como funciona o RTSP?",
                             "resposta_simples", []).count(".") >= 5
    lista = "Opções:\n- A\n- B\n- C\n- D\n- E\nTodas servem. Escolha. Boa sorte. Até."
    assert "- E" in O._podar_resposta(None, lista, "o que usar", "resposta_simples", [])
    casual = "Tudo bem. Estou ótimo. Obrigado. E você. Espero que bem."
    assert O._podar_resposta(None, casual, "tudo bem?",
                             "resposta_simples", []).count(".") <= 3


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print("ok", nome)
