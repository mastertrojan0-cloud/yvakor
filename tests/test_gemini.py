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


def test_chave_aparece_nos_ajustes(tmp_path):
    from yvakor import ajustes
    arq = tmp_path / ".env"
    arq.write_text("GEMINI_API_KEY=AIzaSyTESTE1234567890\n", encoding="utf-8")
    item = next(c for c in ajustes.estado_chaves(arq) if c["nome"] == "GEMINI_API_KEY")
    assert item["definida"] and item["testavel"] and "TESTE1234" not in item["mascara"]
