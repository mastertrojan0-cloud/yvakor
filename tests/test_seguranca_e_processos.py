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


# --------------------------------------------------------------------------- #
# Token: não é regravado por um simples import; a GUI se autocura num 403
# --------------------------------------------------------------------------- #
def test_import_do_servidor_nao_sobrescreve_o_token():
    """Regressão: `import yvakor.server` regravava data/.server_token, e um
    teste/segundo processo deixava o servidor em execução com token diferente
    do arquivo lido pela interface (403 em tudo)."""
    import subprocess
    arq = ROOT / "data" / ".server_token"
    arq.parent.mkdir(parents=True, exist_ok=True)
    original = arq.read_text(encoding="utf-8") if arq.exists() else None
    arq.write_text("TOKEN-DO-SERVIDOR-EM-EXECUCAO", encoding="utf-8")
    try:
        subprocess.run([sys.executable, "-c", "import yvakor.server"],
                       cwd=str(ROOT), capture_output=True, timeout=60)
        assert arq.read_text(encoding="utf-8") == "TOKEN-DO-SERVIDOR-EM-EXECUCAO"
    finally:
        if original is None:
            arq.unlink(missing_ok=True)
        else:
            arq.write_text(original, encoding="utf-8")


def test_gui_renova_o_token_quando_recebe_403():
    import yvakor.desktop as D
    S, srv, port = _servidor()
    S.HOSTS_OK.add(f"127.0.0.1:{port}")
    base_antiga, token_antigo = D.BASE, D._TOKEN_VIVO
    try:
        D.BASE = f"http://127.0.0.1:{port}"
        D._TOKEN_VIVO = "token-velho-de-um-servidor-anterior"
        r = D.api("/api/ext/ping", {})        # 403 → renova via /api/token → ok
        assert r.get("ok") is True
        assert D._TOKEN_VIVO == S.TOKEN
    finally:
        D.BASE, D._TOKEN_VIVO = base_antiga, token_antigo
        srv.shutdown()


# --------------------------------------------------------------------------- #
# Roteador: circuit breaker (DeepSeek sem saldo → modelo local)
# --------------------------------------------------------------------------- #
class _Prov:
    def __init__(self, nome, erro=None, fatal=False):
        self.name, self.erro, self.fatal, self.chamadas = nome, erro, fatal, 0

    def chat_messages(self, msgs, timeout=None, max_tokens=None):
        self.chamadas += 1
        if self.erro:
            from yvakor.llm.adapter import ProviderErro
            raise ProviderErro(self.erro, fatal=self.fatal)
        return f"resposta do {self.name}"


def _router(deepseek, ollama):
    from yvakor.llm.router import LLMRouter
    r = LLMRouter({"llm": {"default_provider": "deepseek", "providers": {},
                           "routing": {"local": [], "external": ["analise_complexa"],
                                       "fallback_order": ["deepseek", "ollama"]}}})
    r.providers = {"deepseek": deepseek, "ollama": ollama}
    return r


def test_breaker_pula_o_deepseek_sem_saldo():
    ds = _Prov("deepseek", "deepseek HTTP 402: Payment Required", fatal=True)
    ol = _Prov("ollama")
    r = _router(ds, ol)
    msg = [{"role": "user", "content": "oi"}]
    assert r.complete_messages("analise_complexa", msg) == "resposta do ollama"
    assert ds.chamadas == 1 and r.sem_externos() is True
    # as próximas NÃO gastam uma ida ao DeepSeek (antes: 1 tentativa por passo)
    for _ in range(3):
        r.complete_messages("analise_complexa", msg)
    assert ds.chamadas == 1 and ol.chamadas == 4


def test_breaker_erro_transitorio_tem_cooldown_curto():
    ds = _Prov("deepseek", "deepseek indisponível: timeout", fatal=False)
    r = _router(ds, _Prov("ollama"))
    r.complete_messages("analise_complexa", [{"role": "user", "content": "x"}])
    restante = r._cooldown["deepseek"] - __import__("time").time()
    assert 0 < restante <= r.COOLDOWN_TRANSITORIO


def test_probe_detecta_nuvem_fora_sem_gastar_o_passo_do_agente():
    r = _router(_Prov("deepseek", "HTTP 402", fatal=True), _Prov("ollama"))
    assert r.verificar_externos() is False and r.sem_externos() is True
    r2 = _router(_Prov("deepseek"), _Prov("ollama"))
    assert r2.verificar_externos() is True and r2.sem_externos() is False


def test_todos_falham_mensagem_orienta_o_usuario():
    r = _router(_Prov("deepseek", "HTTP 402", fatal=True),
                _Prov("ollama", "ollama indisponível: recusada"))
    try:
        r.complete_messages("analise_complexa", [{"role": "user", "content": "x"}])
        assert False, "deveria falhar"
    except RuntimeError as exc:
        txt = str(exc)
        assert "deepseek" in txt and "ollama" in txt and "saldo" in txt


# --------------------------------------------------------------------------- #
# Agente local compacto e argumentos errados do modelo pequeno
# --------------------------------------------------------------------------- #
def test_registry_reconcilia_argumentos_inventados_pelo_modelo():
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry({"tools": {"guarded_actions": [], "always_confirm": []}})
    reg.register("somar", lambda a, b: {"ok": True, "r": int(a) + int(b)},
                 "soma", {"a": "int", "b": "int"})
    # nomes inventados (numero1/numero2): mapeados por posição
    assert reg.run("somar", numero1=17, numero2=25)["r"] == 42
    # chamada correta passa intacta
    assert reg.run("somar", a=1, b=2)["r"] == 3
    # faltando argumento: o erro diz quais eram esperados
    erro = reg.run("somar", a=1)
    assert erro["ok"] is False and "a, b" in erro["error"]


def test_prompt_compacto_do_agente_local_e_pequeno_e_tem_exemplo():
    from yvakor.agent import AgentLoop
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry({"tools": {"guarded_actions": [], "always_confirm": []}})
    reg.register("somar", lambda a, b: 0, "Soma dois inteiros. " * 30,
                 {"a": "int", "b": "int"})
    ag = AgentLoop(router=None, registry=reg)
    compacto = ag.system_with_tools("Você é o YVAKOR.", ["somar"], compacto=True)
    completo = ag.system_with_tools("Você é o YVAKOR.", ["somar"])
    assert len(compacto) < 1500 < len(completo)
    assert '"ferramenta": "somar"' in compacto and '"a": 0' in compacto


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print("ok", nome)
