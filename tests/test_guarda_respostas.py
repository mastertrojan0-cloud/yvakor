"""Guarda contra os erros vistos na consulta da SEFAZ-AM (28/10/2026):
resposta final cortada no meio da frase (teto de saída aprendido em ~350
tokens), web_ler chamado sem url, e Parar acidental sem explicação."""
from yvakor.llm.adapter import LLMProvider


class _Prov(LLMProvider):
    """Provider com _post de mentira: devolve as respostas em ordem."""

    def __init__(self, respostas, nome="deepseek", **kw):
        super().__init__(nome, "https://api.exemplo", "m", max_tokens=4096, **kw)
        self.respostas = list(respostas)
        self.payloads = []

    def _post(self, payload, timeout=None):
        self.payloads.append(payload)
        conteudo, finish, extra = (self.respostas.pop(0) + (None,))[:3]
        data = {"choices": [{"message": {"content": conteudo, **(extra or {})},
                             "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        self._anotar_uso(data)
        return data


def test_resposta_cortada_refaz_com_teto_do_provedor():
    p = _Prov([("…e digitar o CNP", "length"), ("Resposta completa.", "stop")])
    assert p.chat_messages([{"role": "user", "content": "x"}], max_tokens=353) == \
        "Resposta completa."
    assert [x["max_tokens"] for x in p.payloads] == [353, 4096]
    assert p.ultimo_uso["saida"] == 10          # soma o custo das duas chamadas


def test_cortada_mesmo_no_teto_pede_continuacao_e_emenda():
    p = _Prov([("Primeira parte e digitar o CNP", "length"), ("J da empresa.", "stop")])
    r = p.chat_messages([{"role": "user", "content": "x"}])
    assert r == "Primeira parte e digitar o CNPJ da empresa."
    ultimo = p.payloads[-1]["messages"]
    assert ultimo[-2] == {"role": "assistant", "content": "Primeira parte e digitar o CNP"}
    assert ultimo[-1]["content"] == LLMProvider.PEDIDO_CONTINUAR


def test_continuacao_tem_limite():
    p = _Prov([("a", "length"), ("b", "length"), ("c", "length"), ("d", "stop")])
    assert p.chat_messages([{"role": "user", "content": "x"}]) == "abc"
    assert len(p.payloads) == 1 + LLMProvider.MAX_CONTINUACOES


def test_chat_tools_cortado_refaz_e_continua_texto():
    p = _Prov([("Dados do CNPJ: Raz", "length"), ("Dados do CNPJ: Raz", "length"),
               ("ão Social X.", "stop")])
    msg = p.chat_tools([{"role": "user", "content": "x"}], [], max_tokens=353)
    assert msg["content"] == "Dados do CNPJ: Razão Social X."
    assert [x["max_tokens"] for x in p.payloads] == [353, 4096, 4096]
    assert "tools" not in p.payloads[-1]        # a continuação é só texto


def test_resposta_normal_nao_gasta_chamada_extra():
    p = _Prov([("Tudo certo.", "stop")])
    assert p.chat_messages([{"role": "user", "content": "x"}], max_tokens=353) == "Tudo certo."
    assert len(p.payloads) == 1


def test_modelo_local_nao_refaz():
    p = _Prov([("curto", "length")], nome="ollama")
    assert p.chat_messages([{"role": "user", "content": "x"}], max_tokens=48) == "curto"
    assert len(p.payloads) == 1


def test_teto_aprendido_nunca_fica_abaixo_do_padrao():
    from yvakor.llm.economia import Otimizador, TETO_SAIDA_PADRAO
    o = Otimizador.__new__(Otimizador)

    class Livro:
        def historico_saida(self, nome, tarefa):
            return [40, 60, 80, 100, 120, 150, 200, 250, 270, 300]   # só chamadas curtas
    o._livro = Livro()
    assert o.max_saida("deepseek", "analise_complexa", 4096) == \
        TETO_SAIDA_PADRAO["analise_complexa"]
    Livro.historico_saida = lambda self, n, t: [3000] * 10          # tarefa que gasta muito
    assert o.max_saida("deepseek", "analise_complexa", 4096) == 3000 * 13 // 10 + 32


def test_web_ler_sem_url_nao_executa_e_url_sem_esquema_e_corrigida():
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    from yvakor.tools.builtin import normalizar_url
    chamadas = []

    def ler(url: str = "", inicio: int = 0):
        chamadas.append(url)
        return {"ok": True}
    reg = ToolRegistry(load_settings())
    reg.register("web_ler", ler, "Lê.", {"url": "str", "inicio": "int?"})
    r = reg.run("web_ler")
    assert not r["ok"] and "url" in r["error"] and chamadas == []
    assert reg.run("web_ler", url="https://a.com")["ok"]
    assert normalizar_url("www.sefaz.am.gov.br/") == "https://www.sefaz.am.gov.br/"
    assert normalizar_url("sefaz.am.gov.br/x?y=1") == "https://sefaz.am.gov.br/x?y=1"
    assert normalizar_url("http://a.com") == "http://a.com"
    assert normalizar_url("site da sefaz") is None and normalizar_url("") is None


def test_alias_de_url():
    from yvakor.agent import _alias_args

    class Reg:
        specs = {"web_ler": {"args": {"url": "str", "inicio": "int?"}}}
    for nome in ("endereco", "site", "link", "pagina", "href"):
        assert _alias_args(Reg(), "web_ler", {nome: "https://a.com"}) == {"url": "https://a.com"}


def test_argumentos_ilegiveis_nao_executam_a_ferramenta():
    """Chamada nativa com JSON cortado rodava a ferramenta com {}."""
    from yvakor.agent import AgentLoop
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    chamadas = []
    reg = ToolRegistry(load_settings())
    reg.register("ler_teste", lambda **k: chamadas.append(k) or {"ok": True},
                 "Lê.", {"url": "str"})

    class Router:
        def __init__(self):
            self.n, self.vistos = 0, []

        def complete_tools(self, task, msgs, tools, forcar=None):
            self.n += 1
            self.vistos.append(msgs[-1])
            if self.n == 1:
                return "fake", {"content": "", "tool_calls": [{"id": "1", "function": {
                    "name": "ler_teste", "arguments": '{"url": "https://sefaz.am.g'}}]}
            if self.n == 2:
                return "fake", {"content": "", "tool_calls": [{"id": "2", "function": {
                    "name": "ler_teste", "arguments": '{"url": "https://a.com"}'}}]}
            return "fake", {"content": "Li a página."}

        def complete_messages(self, *a, **k):
            return "ok"
    r = Router()
    saida = AgentLoop(r, reg, max_iterations=5, nativo=True,
                      raciocinio={"verificar": False}).run(
        "t", [{"role": "user", "content": "leia a pagina"}])
    assert chamadas == [{"url": "https://a.com"}], chamadas
    assert "NADA foi executado" in r.vistos[1]["content"] and saida == "Li a página."


def test_parar_explica_e_registra_origem(capsys):
    from yvakor.agent import AgentLoop, MSG_INTERROMPIDA
    from yvakor.orchestrator import Orchestrator, ConfirmationBroker
    assert "continue" in MSG_INTERROMPIDA and "Esc" in MSG_INTERROMPIDA

    class Router:
        def complete_tools(self, *a, **k):
            raise AssertionError("não devia chamar o modelo depois do Parar")
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    saida = AgentLoop(Router(), ToolRegistry(load_settings()), nativo=True).run(
        "t", [{"role": "user", "content": "oi"}], should_stop=lambda: True)
    assert saida == MSG_INTERROMPIDA

    import threading

    class Eu:
        _prog_lock = threading.Lock()
        _cancel_lock = threading.Lock()
        _cancelados = set()
        progress = {"S1": {"running": True, "steps": []}}
        confirm_broker = ConfirmationBroker(timeout=1)

        def _prog_step(self, sid, label):
            self.progress[sid]["steps"].append(label)
    eu = Eu()
    assert Orchestrator.cancelar(eu, "S1", origem="tecla Esc (2x)") == ["S1"]
    assert eu.progress["S1"]["steps"] == ["⏹ Parar recebido (tecla Esc (2x))"]
    assert "Parar recebido (tecla Esc (2x))" in capsys.readouterr().out
