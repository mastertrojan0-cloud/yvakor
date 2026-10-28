"""Gemini (Google AI Studio) como provedor de nuvem: entra na rota só com
chave, tem modo próprio e manda os campos extras (reasoning_effort)."""
from yvakor.llm.adapter import build_provider
from yvakor.llm.router import LLMRouter, MODOS

CFG_GEMINI = {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
              "model": "gemini-flash-latest", "api_key_env": "GEMINI_API_KEY",
              "max_tokens": 8192, "extra": {"reasoning_effort": "low"}}


def _router(monkeypatch, com_chave=True, modo="deepseek"):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-teste")
    if com_chave:
        monkeypatch.setenv("GEMINI_API_KEY", "gm-teste")
    else:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(LLMRouter, "_ler_pref", staticmethod(lambda chave: None))
    settings = {"llm": {
        "modo_padrao": modo, "default_provider": "ollama",
        "providers": {
            "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat",
                         "api_key_env": "DEEPSEEK_API_KEY"},
            "gemini": CFG_GEMINI,
            "ollama": {"base_url": "http://localhost:11434", "model": "qwen2.5:3b"}},
        "routing": {"local": [], "external": ["analise_complexa"],
                    "fallback_order": ["deepseek", "gemini", "ollama"]},
        "otimizacao": {"ativo": False}}}
    return LLMRouter(settings)


def test_gemini_com_chave_e_reserva_do_deepseek(monkeypatch):
    r = _router(monkeypatch)
    assert [p.name for p in r._ordem("analise_complexa", None)] == \
        ["deepseek", "gemini", "ollama"]
    assert r.externos() == ["deepseek", "gemini"]


def test_sem_chave_fica_fora_da_rota(monkeypatch):
    r = _router(monkeypatch, com_chave=False)
    assert [p.name for p in r._ordem("analise_complexa", None)] == ["deepseek", "ollama"]
    assert r.externos() == ["deepseek"]
    assert r.info()["gemini"]["com_chave"] is False


def test_modo_gemini_poe_ele_primeiro(monkeypatch):
    assert "gemini" in MODOS
    r = _router(monkeypatch, modo="gemini")
    assert r.pick_provider("resposta_simples").name == "gemini"
    assert [p.name for p in r._ordem("resposta_simples", None)][:2] == ["gemini", "deepseek"]
    # modo gemini sem chave: cai no DeepSeek em vez de quebrar
    r = _router(monkeypatch, com_chave=False, modo="gemini")
    assert r.pick_provider("resposta_simples").name == "deepseek"


def test_payload_leva_extra_e_url_compativel(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gm-teste")
    p = build_provider("gemini", CFG_GEMINI)
    assert p._url() == ("https://generativelanguage.googleapis.com/v1beta/openai"
                        "/chat/completions")
    enviados = []

    def _post(payload, timeout=None):
        enviados.append(payload)
        data = {"choices": [{"message": {"content": "oi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
        p._anotar_uso(data)
        return data
    p._post = _post
    assert p.chat_messages([{"role": "user", "content": "x"}]) == "oi"
    p.chat_tools([{"role": "user", "content": "x"}], [])
    assert all(e["reasoning_effort"] == "low" and e["model"] == "gemini-flash-latest"
               for e in enviados)


class _Falha(Exception):
    pass


def test_429_por_minuto_nao_e_fatal_e_respeita_retry_delay():
    import io
    import urllib.error
    from yvakor.llm.adapter import ProviderErro
    p = build_provider("gemini", {**CFG_GEMINI, "api_key_env": "X_NAO_EXISTE"})
    detalhe = '{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}'

    def _erro(corpo):
        def _abrir(*a, **k):
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {},
                                         io.BytesIO(corpo.encode()))
        return _abrir
    import yvakor.llm.adapter as ad
    original = ad.urllib.request.urlopen
    try:
        ad.urllib.request.urlopen = _erro(
            '[{"error": {"code": 429, "message": "You exceeded your current quota, '
            'please check your plan and billing details. ' + "x" * 300 + '", '
            '"status": "RESOURCE_EXHAUSTED", "details": [' + detalhe + ']}}]')
        try:
            p.ping()
            assert False
        except ProviderErro as exc:
            assert exc.codigo == 429 and exc.espera_s == 37 and not exc.fatal
            assert LLMRouter._fatal(exc) is False       # "quota" no texto não basta
        ad.urllib.request.urlopen = _erro('{"error": {"message": "quota '
                                          'GenerateRequestsPerDayPerProjectPerModel"}}')
        try:
            p.ping()
            assert False
        except ProviderErro as exc:
            assert exc.fatal and LLMRouter._fatal(exc)  # cota do dia: cooldown longo
    finally:
        ad.urllib.request.urlopen = original


def test_teste_de_conexao_nao_refaz_nem_exige_texto(monkeypatch):
    """max_tokens=1 sempre volta 'length' (e vazio no Gemini, que pensa antes):
    o probe não pode virar chamada cheia nem pôr o provedor em cooldown."""
    r = _router(monkeypatch)
    enviados = []
    for nome in ("deepseek", "gemini"):
        p = r.providers[nome]

        def _post(payload, timeout=None, p=p):
            enviados.append((p.name, payload["max_tokens"]))
            data = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            p._anotar_uso(data)
            return data
        p._post = _post
    assert r.verificar_externos(forcar=True) is True
    assert enviados == [("deepseek", 1)] and not r._cooldown


def test_ferramentas_nao_caem_no_modelo_local_e_seguem_a_prioridade(monkeypatch):
    r = _router(monkeypatch, modo="deepseek")
    r.otim = None
    chamados = []
    for nome, p in r.providers.items():
        def _tools(msgs, tools, max_tokens=None, nome=nome):
            chamados.append(nome)
            raise _Falha(f"{nome} HTTP 500")
        p.chat_tools = _tools
    try:
        r.complete_tools("analise_complexa", [{"role": "user", "content": "x"}], [])
        assert False
    except _Falha:
        pass
    assert chamados == ["deepseek", "gemini"]           # sem o 3B no loop de ferramentas


def test_modo_escolhido_nao_e_reordenado_pelo_custo(monkeypatch, tmp_path):
    from yvakor.llm import economia
    r = _router(monkeypatch, modo="deepseek")
    o = economia.Otimizador({"precos_usd_por_milhao": {
        "deepseek": {"entrada": 0.28, "cache": 0.028, "saida": 0.42},
        "gemini": {"entrada": 0.0, "cache": 0.0, "saida": 0.0}}},
        r.providers, caminho_db=tmp_path / "c.db")
    ordem = r._ordem("analise_complexa", None)
    msgs = [{"role": "user", "content": "x"}]
    assert [p.name for p in o.planejar("analise_complexa", msgs, ordem, "deepseek").ordem][:2] \
        == ["deepseek", "gemini"]
    # no Automático o mais barato por sucesso (Gemini grátis) vem antes
    assert o.planejar("analise_complexa", msgs, ordem, "auto").ordem[0].name in ("gemini", "ollama")
    # e nas ferramentas vale sempre a prioridade declarada
    assert o.planejar("analise_complexa", msgs, ordem, "auto",
                      ranquear=False).ordem[0].name in ("deepseek", "ollama")


def test_modelo_sobrecarregado_cede_para_a_reserva(monkeypatch):
    from yvakor.llm.adapter import ProviderErro
    monkeypatch.setenv("GEMINI_API_KEY", "gm-teste")
    p = build_provider("gemini", {**CFG_GEMINI,
                                  "modelos_reserva": ["gemini-3.5-flash", "gemini-flash-lite-latest"]})
    tentados = []

    def _bruto(url, payload, timeout=None):
        tentados.append(payload["model"])
        if payload["model"] != "gemini-flash-lite-latest":
            raise ProviderErro("gemini HTTP 503: high demand", codigo=503)
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    p._post_bruto = _bruto
    assert p.chat_messages([{"role": "user", "content": "x"}]) == "ok"
    assert tentados == ["gemini-flash-latest", "gemini-3.5-flash", "gemini-flash-lite-latest"]
    assert p.modelo_usado == "gemini-flash-lite-latest"
    # erro de chave (401) não troca de modelo: sobe direto para o roteador
    tentados.clear()

    def _negado(url, payload, timeout=None):
        tentados.append(payload["model"])
        raise ProviderErro("gemini HTTP 401", codigo=401, fatal=True)
    p._post_bruto = _negado
    try:
        p.chat_messages([{"role": "user", "content": "x"}])
        assert False
    except ProviderErro:
        pass
    assert tentados == ["gemini-flash-latest"]


def test_assinatura_de_pensamento_na_troca_de_provedor(monkeypatch):
    """DeepSeek → Gemini no meio da tarefa dava HTTP 400 ("Function call is
    missing a thought_signature"); Gemini → DeepSeek leva um campo que só o
    Google entende."""
    monkeypatch.setenv("GEMINI_API_KEY", "gm-teste")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-teste")
    g = build_provider("gemini", CFG_GEMINI)
    d = build_provider("deepseek", {"base_url": "https://api.deepseek.com",
                                    "model": "deepseek-chat", "api_key_env": "DEEPSEEK_API_KEY"})
    do_deepseek = {"id": "c0", "type": "function",
                   "function": {"name": "navegador_ir", "arguments": "{}"}}
    do_gemini = {**do_deepseek, "extra_content": {"google": {"thought_signature": "ABC"}}}
    hist = [{"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": [do_deepseek, do_gemini]},
            {"role": "tool", "tool_call_id": "c0", "content": "{}"}]
    ida = g._mensagens_para_o_provedor(hist)[1]["tool_calls"]
    assert ida[0]["extra_content"]["google"]["thought_signature"] == g.ASSINATURA_NEUTRA
    assert ida[1]["extra_content"]["google"]["thought_signature"] == "ABC"   # a real fica
    volta = d._mensagens_para_o_provedor(hist)[1]["tool_calls"]
    assert all("extra_content" not in tc for tc in volta)
    assert hist[1]["tool_calls"][1]["extra_content"]          # original intacto


def test_chave_aparece_nos_ajustes(tmp_path):
    from yvakor import ajustes
    arq = tmp_path / ".env"
    arq.write_text("GEMINI_API_KEY=AIzaSyTESTE1234567890\n", encoding="utf-8")
    item = next(c for c in ajustes.estado_chaves(arq) if c["nome"] == "GEMINI_API_KEY")
    assert item["definida"] and item["testavel"] and "TESTE1234" not in item["mascara"]
