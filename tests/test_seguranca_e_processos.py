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
class _AgenteFalso:
    """Agente mínimo para os testes de servidor: NÃO instancia o Orchestrator
    real (que abriria o banco/tarefas cowork reais dentro do pytest)."""

    def __init__(self, router=None):
        from yvakor.config import load_settings
        self.settings = load_settings()
        self.router = router


def _servidor(agente=None):
    import yvakor.server as S
    S._get_agent_original = getattr(S, "_get_agent_original", S.get_agent)
    S.get_agent = lambda: agente or _AgenteFalso()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return S, srv, srv.server_address[1]


def _fechar(S, srv):
    srv.shutdown()
    S.get_agent = S._get_agent_original


class _PrefsTemporarias:
    """Isola data/preferencias.json: o teste nunca lê/escreve o arquivo real."""

    def __enter__(self):
        import tempfile
        import yvakor.llm.router as R
        self.R, self.antigo = R, R.ARQ_PREFS
        R.ARQ_PREFS = Path(tempfile.mkdtemp()) / "preferencias.json"
        return R.ARQ_PREFS

    def __exit__(self, *a):
        self.R.ARQ_PREFS = self.antigo


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
        _fechar(S, srv)


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
        _fechar(S, srv)


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


def _router(deepseek, ollama, modo="auto"):
    from yvakor.llm.router import LLMRouter
    with _PrefsTemporarias():           # não lê o preferencias.json real
        r = LLMRouter({"llm": {"default_provider": "ollama", "providers": {},
                               "routing": {"local": [],
                                           "external": ["analise_complexa"],
                                           "fallback_order": ["deepseek", "ollama"]}}})
    r.modo = modo
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


# --------------------------------------------------------------------------- #
# Seletor de modelo: Local (padrão) / Automático / DeepSeek
# --------------------------------------------------------------------------- #
class _NuvemProibida(_Prov):
    """Falha o teste se for chamada: prova que o modo local nunca usa a nuvem."""

    def chat_messages(self, msgs, timeout=None, max_tokens=None):
        self.chamadas += 1
        raise AssertionError("o modo local chamou a nuvem")


def test_padrao_de_instalacao_nova_e_o_modelo_local():
    import yaml
    from yvakor.config import load_settings
    from yvakor.llm.router import LLMRouter
    cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert cfg["llm"]["modo_padrao"] == "local"
    assert cfg["llm"]["default_provider"] == "ollama"
    with _PrefsTemporarias():                 # sem preferência salva
        assert LLMRouter(load_settings()).modo == "local"


def test_modo_local_nunca_chama_a_nuvem():
    ds, ol = _NuvemProibida("deepseek"), _Prov("ollama")
    r = _router(ds, ol, modo="local")
    msg = [{"role": "user", "content": "oi"}]
    assert r.complete_messages("analise_complexa", msg) == "resposta do ollama"
    # nem um forcar="deepseek" explícito (absorção etc.) escapa para a nuvem
    assert r.complete_messages("analise_complexa", msg, forcar="deepseek") \
        == "resposta do ollama"
    assert r.verificar_externos() is False and r.sem_externos() is True
    assert ds.chamadas == 0 and r.info()["efetivo"] == "ollama"


def test_modos_auto_e_deepseek_escolhem_o_provedor_certo():
    auto = _router(_Prov("deepseek"), _Prov("ollama"), modo="auto")
    assert auto.pick_provider("resposta_simples").name == "ollama"
    assert auto.pick_provider("analise_complexa").name == "deepseek"
    nuvem = _router(_Prov("deepseek"), _Prov("ollama"), modo="deepseek")
    assert nuvem.pick_provider("resposta_simples").name == "deepseek"
    assert nuvem.pick_provider("analise_complexa").name == "deepseek"
    # DeepSeek primeiro, mas o local entra se ele falhar
    cai = _router(_Prov("deepseek", "HTTP 402", fatal=True), _Prov("ollama"),
                  modo="deepseek")
    assert cai.complete_messages("analise_complexa",
                                 [{"role": "user", "content": "x"}]) == "resposta do ollama"


def test_escolha_do_modo_e_salva_e_trocar_zera_o_breaker():
    from yvakor.config import load_settings
    from yvakor.llm.router import LLMRouter
    with _PrefsTemporarias() as arq:
        r = LLMRouter(load_settings())
        r._cooldown["deepseek"] = __import__("time").time() + 1800   # "sem saldo"
        r.definir_modo("deepseek")
        assert json.loads(arq.read_text(encoding="utf-8"))["modelo_modo"] == "deepseek"
        assert r._cooldown == {}                    # voltou a tentar a nuvem
        assert LLMRouter(load_settings()).modo == "deepseek"   # persistiu
        r.definir_modelo_local("qwen2.5:3b")
        assert LLMRouter(load_settings()).providers["ollama"].model == "qwen2.5:3b"
        try:
            r.definir_modo("xyz")
            assert False, "modo inválido deveria ser rejeitado"
        except ValueError:
            pass


def test_api_modelo_get_post_exige_token_e_valida():
    from yvakor.config import load_settings
    from yvakor.llm.router import LLMRouter
    with _PrefsTemporarias() as arq:
        agente = _AgenteFalso(LLMRouter(load_settings()))
        S, srv, port = _servidor(agente)
        S._modelos_locais_original = getattr(S, "_modelos_locais_original", S._modelos_locais)
        S._modelos_locais = lambda ag: ["qwen2.5:3b", "llama3.2:3b"]
        try:
            st, corpo = _req(port, "GET", "/api/modelo")
            info = json.loads(corpo)
            assert st == 200 and info["modo"] == "local"
            assert [m["id"] for m in info["modos"]] == ["local", "auto", "deepseek", "gemini"]
            assert info["locais"] == ["qwen2.5:3b", "llama3.2:3b"]
            # POST sem token: barrado
            assert _req(port, "POST", "/api/modelo", body={"modo": "auto"})[0] == 403
            assert agente.router.modo == "local"
            # POST com token: troca e persiste
            st, corpo = _req(port, "POST", "/api/modelo", token=S.TOKEN,
                             body={"modo": "deepseek"})
            assert st == 200 and agente.router.modo == "deepseek"
            assert json.loads(arq.read_text(encoding="utf-8"))["modelo_modo"] == "deepseek"
            # entradas inválidas → 400 e nada muda
            assert _req(port, "POST", "/api/modelo", token=S.TOKEN,
                        body={"modo": "xyz"})[0] == 400
            assert _req(port, "POST", "/api/modelo", token=S.TOKEN,
                        body={"local": "nao-existe:1b"})[0] == 400
            assert agente.router.modo == "deepseek"
            # modelo local instalado: aceito
            st, _ = _req(port, "POST", "/api/modelo", token=S.TOKEN,
                         body={"local": "llama3.2:3b"})
            assert st == 200 and agente.router.providers["ollama"].model == "llama3.2:3b"
        finally:
            S._modelos_locais = S._modelos_locais_original
            _fechar(S, srv)


def test_menu_de_modelo_da_janela_desktop():
    import pytest
    import tkinter as tk
    from types import SimpleNamespace
    import yvakor.desktop as D
    try:
        raiz = tk.Tk()
    except tk.TclError:
        pytest.skip("sem display gráfico")
    raiz.withdraw()
    escolhas = []
    info = {"modo": "local", "modos": [
                {"id": "local", "rotulo": "Local", "descricao": "só local"},
                {"id": "auto", "rotulo": "Automático", "descricao": "misto"},
                {"id": "deepseek", "rotulo": "DeepSeek", "descricao": "nuvem"}],
            "local": {"modelo": "qwen2.5:3b"}, "locais": ["qwen2.5:3b", "llama3.2:3b"]}
    antigo = D.api
    try:
        D.api = lambda *a, **k: info
        menu = tk.Menu(raiz, tearoff=0)
        eu = SimpleNamespace(_escolher_modelo=escolhas.append)
        D.App._montar_menu_modelo(eu, menu)
        rotulos = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
                   if menu.type(i) in ("command",)]
        assert any(r.startswith("● Local") for r in rotulos)          # atual marcado
        assert any("Automático" in r for r in rotulos) and any("llama3.2:3b" in r for r in rotulos)
        menu.invoke(1)                                                # "Automático"
        assert escolhas == [{"modo": "auto"}]
        # núcleo fora do ar: não quebra, mostra aviso
        def cai(*a, **k):
            raise RuntimeError("offline")
        D.api = cai
        menu2 = tk.Menu(raiz, tearoff=0)
        D.App._montar_menu_modelo(eu, menu2)
        assert "indisponível" in menu2.entrycget(0, "label")
    finally:
        D.api = antigo
        raiz.destroy()


# --------------------------------------------------------------------------- #
# "Sistema trava": seletor do modo compacto e confirmação que parava a conversa
# --------------------------------------------------------------------------- #
def _registry_grande():
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry({"tools": {"guarded_actions": [], "always_confirm": [
        "executar_shell", "arquivos_apagar", "arquivos_escrever"]}})
    nomes = (["executar_shell", "arquivos_listar", "arquivos_ler", "arquivos_apagar",
              "arquivos_escrever", "cerebro_buscar", "pesquisa_web", "http_get"]
             + [f"rede_x{i}" for i in range(140)])
    for n in nomes:
        reg.register(n, lambda **k: {"ok": True}, "descricao longa " * 12, {"a": "str"})
    return reg


def test_modo_compacto_respeita_o_limite_mesmo_quando_nada_casa():
    """Regressão: selecionar() devolvia TODAS as ferramentas quando nada casava
    (ignorando o limite) → prompt gigante no modelo local (~110s por 7k chars)."""
    from yvakor.agent import AgentLoop
    ag = AgentLoop(router=None, registry=_registry_grande(), roteador=True)
    for msg in ("como esta o mercado do btc?", "xyzabc qwerty"):
        nomes = ag._selecionar([{"role": "user", "content": msg}], 5)
        assert len(nomes) == 5
        assert len(ag.system_with_tools("base", nomes, compacto=True)) < 2000
        assert "pesquisa_web" in nomes                # base segura p/ cotação etc.


def test_modo_compacto_so_oferece_shell_e_apagar_em_pedido_explicito():
    """O 3B chamava `bitcoin-cli` no shell p/ uma pergunta de mercado."""
    from yvakor.agent import AgentLoop
    ag = AgentLoop(router=None, registry=_registry_grande(), roteador=True)
    perigosas = {"executar_shell", "arquivos_apagar", "arquivos_escrever"}
    for msg in ("como esta o mercado do btc?", "liste os arquivos da pasta interface",
                "quem foi Santos Dumont"):
        assert not perigosas & set(ag._selecionar([{"role": "user", "content": msg}], 5)), msg
    assert "executar_shell" in ag._selecionar(
        [{"role": "user", "content": "execute o comando dir"}], 5)
    assert "arquivos_apagar" in ag._selecionar(
        [{"role": "user", "content": "apague o arquivo x.txt"}], 5)


def test_confirmacao_sem_resposta_e_negada_no_prazo_configurado():
    import time
    from yvakor.orchestrator import ConfirmationBroker
    b = ConfirmationBroker(timeout=0.3)             # antes: 180s fixos
    t0 = time.time()
    assert b.request("S", "executar_shell", "dir") is False
    assert time.time() - t0 < 3
    assert b.pending_for("S") is None               # não deixa pendência fantasma


def test_pendencia_informa_o_prazo_e_resposta_libera_a_conversa():
    from yvakor.orchestrator import ConfirmationBroker
    b = ConfirmationBroker(timeout=5)
    resultado = {}
    t = threading.Thread(target=lambda: resultado.update(
        r=b.request("S", "executar_shell", "dir")))
    t.start()
    for _ in range(50):
        if b.pending_for("S"):
            break
        threading.Event().wait(0.02)
    pend = b.pending_for("S")
    assert pend["action"] == "executar_shell" and pend["timeout"] == 5
    assert b.resolve("S", True) is True
    t.join(2)
    assert resultado["r"] is True


def test_ollama_deixa_um_nucleo_livre_e_a_nuvem_nao_muda():
    from unittest import mock
    from yvakor.llm import adapter
    with mock.patch("os.cpu_count", return_value=4):
        assert adapter._threads_ollama({}) == 3                 # auto = núcleos-1
        assert adapter._threads_ollama({"num_thread": 2}) == 2   # fixo
        assert adapter._threads_ollama({"num_thread": 0}) is None   # desligado
    with mock.patch("os.cpu_count", return_value=2):
        assert adapter._threads_ollama({}) is None               # máquina pequena
    with mock.patch("os.cpu_count", return_value=8):
        assert adapter._threads_ollama({}) == 7
    cfg_ds = {"base_url": "https://api.deepseek.com", "model": "m"}
    assert adapter.build_provider("deepseek", cfg_ds).num_thread is None


def test_ollama_usa_api_nativa_com_num_thread_e_a_nuvem_usa_v1():
    from yvakor.llm.adapter import LLMProvider
    capturado = {}

    def falso(url, payload, timeout=None):
        capturado.update(url=url, payload=payload)
        return {"message": {"content": "olá"}, "choices": [
            {"message": {"content": "olá"}}]}

    local = LLMProvider("ollama", "http://localhost:11434", "qwen2.5:3b",
                        num_thread=3, max_tokens=512)
    local._post_bruto = falso
    assert local.chat_messages([{"role": "user", "content": "oi"}]) == "olá"
    assert capturado["url"].endswith("/api/chat")
    assert capturado["payload"]["options"]["num_thread"] == 3
    assert capturado["payload"]["options"]["num_predict"] == 512
    assert capturado["payload"]["stream"] is False

    nuvem = LLMProvider("deepseek", "https://api.deepseek.com", "deepseek-chat")
    nuvem._post_bruto = falso
    assert nuvem.chat_messages([{"role": "user", "content": "oi"}]) == "olá"
    assert capturado["url"].endswith("/chat/completions")        # inalterado
    assert "options" not in capturado["payload"]


def test_ha_registro_de_quem_abre_o_chrome_do_agente():
    from yvakor.browser import chrome_cdp
    assert hasattr(chrome_cdp, "_registrar_abertura")
    assert "_registrar_abertura(porta)" in Path(chrome_cdp.__file__).read_text(encoding="utf-8")


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print("ok", nome)


def test_json_de_ferramenta_nao_vaza_na_resposta_final():
    from yvakor.agent import _extrair_resposta_final
    bruto = ('Vou tentar outra coisa.\n\n{"acao": "usar_ferramenta", "ferramenta": '
             '"pesquisa_web", "args": {"limite": 5}}\n\nNão consegui o resultado.')
    r = _extrair_resposta_final(bruto)
    assert "usar_ferramenta" not in r and "pesquisa_web" not in r
    assert "Vou tentar outra coisa." in r and "Não consegui o resultado." in r
    assert "\n\n\n" not in r
    # JSON legítimo da resposta (sem 'acao') é preservado
    assert '{"a": 1}' in _extrair_resposta_final('Veja: {"a": 1} ok')
    # só protocolo → devolve o original (melhor que resposta vazia)
    so = '{"acao":"usar_ferramenta","ferramenta":"x","args":{}}'
    assert _extrair_resposta_final(so) == so
    # formato responder continua extraindo o texto
    assert _extrair_resposta_final('{"acao":"responder","texto":"oi"}') == "oi"
