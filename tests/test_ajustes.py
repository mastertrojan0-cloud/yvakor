"""Central de configurações: chaves (.env), preferências, MCP, API e a página."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from yvakor import ajustes as A

RAIZ = Path(__file__).resolve().parent.parent
SEGREDO = "sk-SEGREDO-1234567890-ABCDEF"


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    """Tudo em pasta temporária: .env, ajustes.json, mcp.json e preferencias.json."""
    monkeypatch.setattr(A, "ARQ_ENV", tmp_path / ".env")
    monkeypatch.setattr(A, "ARQ_AJUSTES", tmp_path / "ajustes.json")
    monkeypatch.setattr(A, "ARQ_MCP", tmp_path / "mcp.json")
    monkeypatch.setattr(A, "ROOT", tmp_path)
    monkeypatch.setattr(A, "_cache_perfil", {"mtime": None, "texto": ""})
    antes = {k: os.environ.get(k) for k in A.CHAVES}
    for k in A.CHAVES:
        os.environ.pop(k, None)
    yield tmp_path
    for k, v in antes.items():                    # as chaves gravadas nos testes não vazam para os outros
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# --------------------------------------------------------------------------- #
# chaves
# --------------------------------------------------------------------------- #
def test_env_troca_insere_remove_e_preserva_comentarios(pasta):
    env = pasta / ".env"
    env.write_text("# minhas chaves\nDEEPSEEK_API_KEY=antiga\nOUTRA=1\n# GOOGLE_CLIENT_ID=exemplo\n", encoding="utf-8")
    A.definir_chave("DEEPSEEK_API_KEY", "nova-chave-123")
    A.definir_chave("BRAVE_API_KEY", "brave-abc")
    A.definir_chave("GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")        # descomenta a linha de exemplo
    txt = env.read_text(encoding="utf-8")
    assert "# minhas chaves" in txt and "OUTRA=1" in txt
    assert "DEEPSEEK_API_KEY=nova-chave-123" in txt and "antiga" not in txt
    assert "BRAVE_API_KEY=brave-abc" in txt and "\nGOOGLE_CLIENT_ID=id.apps" in txt
    assert os.environ["DEEPSEEK_API_KEY"] == "nova-chave-123"                      # vale na hora
    A.remover_chave("BRAVE_API_KEY")
    assert "BRAVE_API_KEY" not in env.read_text(encoding="utf-8") and "BRAVE_API_KEY" not in os.environ
    A.remover_chave("OPENAI_API_KEY")                                              # remover o que não existe: ok


def test_estado_das_chaves_nunca_devolve_o_segredo(pasta):
    A.definir_chave("DEEPSEEK_API_KEY", SEGREDO)
    est = {k["nome"]: k for k in A.estado_chaves()}
    assert est["DEEPSEEK_API_KEY"]["definida"] and est["BRAVE_API_KEY"]["definida"] is False
    assert SEGREDO not in json.dumps(est) and est["DEEPSEEK_API_KEY"]["mascara"].startswith("sk-")
    assert est["DEEPSEEK_API_KEY"]["mascara"].endswith(SEGREDO[-4:]) and "1234567890" not in est["DEEPSEEK_API_KEY"]["mascara"]


@pytest.mark.parametrize("nome,valor", [("NAO_EXISTE", "x"), ("DEEPSEEK_API_KEY", ""), ("DEEPSEEK_API_KEY", "a\nB=1"),
                                        ("DEEPSEEK_API_KEY", "x" * 600), ("PATH", "x")])
def test_chave_invalida_e_recusada_e_nao_injeta_linhas_no_env(pasta, nome, valor):
    with pytest.raises(ValueError):
        A.definir_chave(nome, valor)
    assert not (pasta / ".env").exists() or "B=1" not in (pasta / ".env").read_text(encoding="utf-8")


def test_chave_nova_chega_ao_provedor_vivo_e_zera_o_breaker(pasta):
    class R:
        modo = "auto"
        providers = {"deepseek": SimpleNamespace(api_key=None), "ollama": SimpleNamespace(api_key=None)}
        zerou = False
        def definir_modo(self, m):
            self.zerou = True
    ag = SimpleNamespace(router=R(), settings={"llm": {"providers": {"deepseek": {"api_key_env": "DEEPSEEK_API_KEY"},
                                                                     "ollama": {}}}})
    A.definir_chave("DEEPSEEK_API_KEY", "chave-nova")
    A.recarregar_provedores(ag)
    assert ag.router.providers["deepseek"].api_key == "chave-nova" and ag.router.zerou
    A.remover_chave("DEEPSEEK_API_KEY")
    A.recarregar_provedores(ag)
    assert ag.router.providers["deepseek"].api_key is None


def test_testar_chave_sem_chave_e_desconhecida(pasta):
    assert A.testar_chave("DEEPSEEK_API_KEY")["ok"] is False
    assert "desconhecida" in A.testar_chave("XYZ")["erro"]


def test_testar_deepseek_interpreta_saldo_e_erros(pasta, monkeypatch):
    import urllib.error
    import urllib.request

    class Resp:
        def __init__(self, d): self.d = d
        def read(self, *a): return json.dumps(self.d).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: Resp(
        {"is_available": True, "balance_infos": [{"currency": "USD", "total_balance": "4.50"}]}))
    r = A.testar_chave("DEEPSEEK_API_KEY", "k")
    assert r["ok"] and "4.50 USD" in r["detalhe"]
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: Resp({"is_available": False, "balance_infos": []}))
    assert A.testar_chave("DEEPSEEK_API_KEY", "k")["ok"] is False
    def erro401(req, timeout=0):
        raise urllib.error.HTTPError("u", 401, "x", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", erro401)
    assert "recusada" in A.testar_chave("DEEPSEEK_API_KEY", "k")["erro"]


# --------------------------------------------------------------------------- #
# preferências
# --------------------------------------------------------------------------- #
def test_secoes_validam_persistem_e_reaplicam_no_boot(pasta):
    A.salvar_secao("voz", {"tom": "-8Hz", "taxa": "+3%", "efeito": "nenhum", "voz_edge": "pt-PT-DuarteNeural"})
    A.salvar_secao("memoria", {"aprender_local": "true", "reter_operacionais_dias": "45"})
    A.salvar_secao("consumo", {"diario_usd": "1.25"})
    for sec, ruim in (("voz", {"tom": "grave"}), ("voz", {"voz_edge": "inventada"}), ("voz", {"nao_existe": 1}),
                      ("memoria", {"reter_operacionais_dias": 9999}), ("aparencia", {"tema": "neon"}),
                      ("secao_x", {"a": 1})):
        with pytest.raises(ValueError):
            A.salvar_secao(sec, ruim)
    obt = A.obter()
    assert obt["voz"]["tom"] == "-8Hz" and obt["voz"]["voz_edge"] == "pt-PT-DuarteNeural"
    assert obt["memoria"] == {"aprender_local": True, "reter_operacionais_dias": 45}
    assert obt["consumo"]["diario_usd"] == 1.25 and obt["consumo"]["mensal_usd"] == 8.0      # o resto fica no padrão
    cfg = A.aplicar_ao_settings({"voz": {"tom": "+0Hz", "vozes": {}}, "agent": {}, "maintenance": {},
                                 "llm": {"otimizacao": {"orcamento": {"mensal_usd": 99}}}})
    assert cfg["voz"]["tom"] == "-8Hz" and cfg["voz"]["vozes"]["pt-BR"] == "pt-PT-DuarteNeural"
    assert cfg["agent"]["aprender_local"] is True and cfg["maintenance"]["reter_operacionais_dias"] == 45
    assert cfg["llm"]["otimizacao"]["orcamento"]["diario_usd"] == 1.25


def test_aplicar_vivo_muda_voz_memoria_consumo_e_tema(pasta):
    tts = SimpleNamespace(motor_pref="auto", voz_edge="x", vozes_idioma={}, tom="-12Hz", taxa="-5%", efeito="assinatura")
    orc = {}
    otim = SimpleNamespace(definir_orcamento=lambda **k: orc.update(k))
    ag = SimpleNamespace(settings={}, voz=SimpleNamespace(tts=tts), router=SimpleNamespace(otim=otim))
    A.aplicar_vivo(ag, "voz", {"tom": "-3Hz", "tts": "edge", "voz_edge": "pt-BR-FranciscaNeural"})
    assert tts.tom == "-3Hz" and tts.motor_pref == "edge" and tts.vozes_idioma["pt-BR"] == "pt-BR-FranciscaNeural"
    A.aplicar_vivo(ag, "memoria", {"aprender_local": True})
    assert ag.settings["agent"]["aprender_local"] is True
    A.aplicar_vivo(ag, "consumo", {"diario_usd": 2.0})
    assert orc == {"diario_usd": 2.0}
    A.aplicar_vivo(ag, "aparencia", {"tema": "escuro"})
    assert json.loads((pasta / "data" / "preferencias.json").read_text(encoding="utf-8"))["tema"] == "escuro"


def test_preferencias_pessoais_entram_no_prompt(pasta):
    assert A.bloco_perfil() == ""
    A.salvar_secao("perfil", {"nome": "Antonio", "preferencias": "Responda sempre curto."})
    b = A.bloco_perfil()
    assert "Antonio" in b and "Responda sempre curto." in b and b.startswith("## PREFERÊNCIAS DO USUÁRIO")
    A.salvar_secao("perfil", {"nome": "", "preferencias": ""})
    assert A.bloco_perfil() == ""


# --------------------------------------------------------------------------- #
# MCP
# --------------------------------------------------------------------------- #
def test_mcp_salvar_listar_remover_e_mascara_env(pasta):
    A.mcp_salvar("filesystem", {"command": "npx", "args": "-y @modelcontextprotocol/server-filesystem C:/x",
                                "env": {"TOKEN": SEGREDO}, "enabled": True})
    lista = A.mcp_listar()
    assert lista[0]["nome"] == "filesystem" and lista[0]["args"][0] == "-y"
    assert SEGREDO not in json.dumps(lista) and lista[0]["env"]["TOKEN"].startswith("sk-")
    # editar devolvendo a máscara mantém o segredo original
    A.mcp_salvar("filesystem", {"command": "npx", "args": ["-y"], "env": {"TOKEN": lista[0]["env"]["TOKEN"]}})
    assert json.loads((pasta / "mcp.json").read_text(encoding="utf-8"))["servers"]["filesystem"]["env"]["TOKEN"] == SEGREDO
    for nome, cfg in (("Nome Ruim", {"command": "x"}), ("ok", {"command": ""}), ("ok", {"command": "x", "args": [1]}),
                      ("ok", {"command": "x", "env": {"1ruim": "v"}})):
        with pytest.raises(ValueError):
            A.mcp_salvar(nome, cfg)
    assert A.mcp_remover("filesystem")["removido"] is True and A.mcp_listar() == []


# --------------------------------------------------------------------------- #
# API + página
# --------------------------------------------------------------------------- #
def _servidor(pasta, monkeypatch):
    if str(RAIZ / "tests") not in sys.path:
        sys.path.insert(0, str(RAIZ / "tests"))
    import test_seguranca_e_processos as base
    from yvakor.config import load_settings
    from yvakor.llm.router import LLMRouter

    class Agente(base._AgenteFalso):
        def __init__(self):
            super().__init__(LLMRouter(load_settings()))
            self.connectors = SimpleNamespace(catalog=lambda: [{"id": "x", "name": "X", "icon": "🔌", "desc": "d", "fields": [],
                                                              "connected": False, "oauth": False, "can_signin": False}])
            self.politica_sites = SimpleNamespace(info=lambda: {"modo": "perguntar", "modos": [], "permitidos": [], "bloqueados": []})
            self.mcp = None
            self.voz = None
    return base, Agente()


def test_snapshot_e_endpoints_de_ajustes(pasta, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SEGREDO)
    base, ag = _servidor(pasta, monkeypatch)
    S, srv, port = base._servidor(ag)
    try:
        st, corpo = base._req(port, "GET", "/api/ajustes")
        assert st == 200 and SEGREDO not in corpo.decode()                           # o segredo NUNCA sai
        j = json.loads(corpo)
        assert {"perfil", "voz", "chaves", "conectores", "mcp", "modelo", "consumo", "sistema", "vozes_disponiveis"} <= set(j)
        assert next(k for k in j["chaves"] if k["nome"] == "DEEPSEEK_API_KEY")["definida"] is True
        # escrita exige token
        for caminho, corpo_req in (("/api/ajustes", {"secao": "perfil", "valores": {"nome": "x"}}),
                                   ("/api/ajustes/chave", {"nome": "BRAVE_API_KEY", "valor": "abc"}),
                                   ("/api/ajustes/mcp", {"acao": "remover", "nome": "x"})):
            assert base._req(port, "POST", caminho, body=corpo_req)[0] == 403
        st, c = base._req(port, "POST", "/api/ajustes", token=S.TOKEN, body={"secao": "perfil", "valores": {"nome": "Antonio"}})
        assert st == 200 and json.loads(c)["valores"]["nome"] == "Antonio"
        assert base._req(port, "POST", "/api/ajustes", token=S.TOKEN, body={"secao": "voz", "valores": {"tom": "x"}})[0] == 400
        st, c = base._req(port, "POST", "/api/ajustes/chave", token=S.TOKEN, body={"nome": "BRAVE_API_KEY", "valor": "brave-secreta-999"})
        assert st == 200 and "brave-secreta-999" not in c.decode() and json.loads(c)["ok"]
        assert os.environ["BRAVE_API_KEY"] == "brave-secreta-999"
        assert base._req(port, "POST", "/api/ajustes/chave", token=S.TOKEN, body={"nome": "PATH", "valor": "x"})[0] == 400
        st, c = base._req(port, "POST", "/api/ajustes/chave", token=S.TOKEN, body={"nome": "BRAVE_API_KEY", "remover": True})
        assert st == 200 and "BRAVE_API_KEY" not in os.environ
        st, c = base._req(port, "POST", "/api/ajustes/mcp", token=S.TOKEN, body={"acao": "salvar", "nome": "teste",
                          "config": {"command": "echo", "args": "oi"}})
        assert st == 200 and json.loads(c)["mcp"][0]["nome"] == "teste"
        assert base._req(port, "POST", "/api/ajustes/mcp", token=S.TOKEN, body={"acao": "salvar", "nome": "Ruim!", "config": {}})[0] == 400
        st, pagina = base._req(port, "GET", "/ajustes")
        assert st == 200 and b"Chaves de API" in pagina and b"__YVAKOR_TOKEN__" in pagina        # página com o token injetado
    finally:
        base._fechar(S, srv)


def test_pagina_de_ajustes_tem_todas_as_secoes_e_esta_ligada_nas_interfaces():
    html = (RAIZ / "interface" / "ajustes.html").read_text(encoding="utf-8")
    for pedaco in ("Chaves de API", "Conectores", "Integrações (MCP)", "Voz", "Navegador e extensão", "Memória e dados",
                   "Modelos e consumo", "Orçamento de API", "/api/ajustes/chave/testar", "/api/ajustes/mcp",
                   "/api/connectors/", "type=\"password\""):
        assert pedaco in html, pedaco
    assert "ajustes" in (RAIZ / "interface" / "index.html").read_text(encoding="utf-8")
    assert "/ajustes" in (RAIZ / "yvakor" / "desktop.py").read_text(encoding="utf-8")
    assert "/ajustes" in (RAIZ / "chrome-extension" / "sidepanel.js").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# núcleo antigo: a GUI atualizada não pode conviver com o servidor de ontem
# --------------------------------------------------------------------------- #
def test_nucleo_com_codigo_antigo_e_detectado_e_o_novo_nao():
    from yvakor import desktop as D
    assert D.nucleo_desatualizado({"version": "0.8.0"}, em_disco=1000.0) is True            # sem o campo: servidor antigo
    assert D.nucleo_desatualizado({"codigo": 900.0}, em_disco=1000.0) is True                # disco mais novo
    assert D.nucleo_desatualizado({"codigo": 1000.0}, em_disco=1000.0) is False              # igual
    assert D.nucleo_desatualizado({"codigo": 999.0}, em_disco=1000.5) is False               # diferença de relógio < 2 s
    assert D.nucleo_desatualizado(None) is False                                              # não deu para ler: não mexe


def test_api_version_informa_a_idade_do_codigo_carregado():
    import sys
    if str(RAIZ / "tests") not in sys.path:
        sys.path.insert(0, str(RAIZ / "tests"))
    import test_seguranca_e_processos as base
    S, srv, port = base._servidor()
    try:
        st, corpo = base._req(port, "GET", "/api/version")
        j = json.loads(corpo)
        assert st == 200 and j["codigo"] == S._CODIGO_MTIME > 0 and j["pid"] == os.getpid()
    finally:
        base._fechar(S, srv)
