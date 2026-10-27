"""Extensão do Chrome: o agente precisa ENXERGAR e USAR pesquisar/digitar/etc.

O motor que age na página (chrome-extension/pagina.js) é testado num Chrome de
verdade com tests/extensao/ (ver teste_acoes.js). Aqui ficam as regressões do
lado Python: quais ferramentas o agente recebe e como elas chegam à extensão.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NAVEGADOR_ESSENCIAL = ["navegador_pesquisar", "navegador_ver", "navegador_clicar",
                       "navegador_preencher", "navegador_pressionar", "navegador_ir"]
# ordem real de registro: navegador_pesquisar era a 11ª e caía fora do limite
_ORDEM_NAVEGADOR = ("abrir", "ir", "ver", "clicar", "preencher", "pressionar", "rolar",
                    "esperar", "extrair", "captura", "pesquisar", "abas", "nova_aba",
                    "trocar_aba", "fechar_aba", "fechar", "grupo", "motores",
                    "conectar", "google_login", "google_status", "digitar",
                    "selecionar", "historico", "passar_mouse")


def _registry():
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry({"tools": {"guarded_actions": [], "always_confirm": [
        "executar_shell", "arquivos_apagar", "arquivos_escrever"]}})
    nomes = (["executar_shell", "executar_python", "http_get", "pesquisa_web"]
             + [f"arquivos_{x}" for x in ("listar", "ler", "info", "buscar",
                                          "escrever", "editar", "apagar")]
             + ["cerebro_buscar", "cerebro_nota"]
             + [f"navegador_{x}" for x in _ORDEM_NAVEGADOR]
             + [f"rede_x{i}" for i in range(60)])
    for n in nomes:
        reg.register(n, lambda **k: {"ok": True}, "d", {"a": "str"})
    return reg


def _agente():
    from yvakor.agent import AgentLoop
    return AgentLoop(router=None, registry=_registry(), roteador=True,
                     max_ferramentas=14)


def _sel(ag, msg, limite):
    return ag._selecionar([{"role": "user", "content": msg}], limite)


PEDIDOS_DE_NAVEGADOR = [
    "pesquise gatos fofos no google",
    "escreva ola no campo de busca e aperte enter",
    "abra o youtube e procure musica",
    "digite meu nome no formulario e clique em enviar",
]


def test_pedidos_de_navegador_recebem_as_ferramentas_de_navegador():
    """Regressão: o seletor comparava a palavra INTEIRA ('pesquise' != 'pesquis'),
    então 'pesquise…' e 'escreva … no campo' não recebiam NENHUMA ferramenta
    de navegador — nem no modo normal nem no compacto."""
    ag = _agente()
    for msg in PEDIDOS_DE_NAVEGADOR:
        for limite in (None, 5):                 # normal e compacto (local)
            nomes = _sel(ag, msg, limite)
            faltam = [n for n in NAVEGADOR_ESSENCIAL if n not in nomes]
            assert not faltam, (msg, limite, faltam)


def test_modo_compacto_da_8_espacos_ao_navegador_e_5_ao_resto():
    ag = _agente()
    assert len(_sel(ag, "pesquise gatos fofos no google", 5)) == 8
    assert len(_sel(ag, "liste os arquivos da pasta interface", 5)) == 5
    # sem shell: pedido de navegador não é pedido de comando
    assert "executar_shell" not in _sel(ag, "pesquise gatos no google", 5)


def test_pesquisar_digitar_e_clicar_vem_antes_do_resto_no_navegador():
    ag = _agente()
    nomes = _sel(ag, "pesquise gatos fofos no google", None)
    # ordem de importância (a de registro punha 'pesquisar' em 11º e o corte
    # por limite o descartava); as raras (abas/fechar/grupo/…) ficam de fora.
    assert (nomes.index("navegador_ver") < nomes.index("navegador_pesquisar")
            < nomes.index("navegador_rolar"))
    assert "navegador_abas" not in nomes and len(nomes) == 14


# --------------------------------------------------------------------------- #
# Ligação das ferramentas à extensão
# --------------------------------------------------------------------------- #
def _orquestrador_falso():
    """Só o necessário para _usar_extensao_como_alvo: registry com ferramentas
    'Playwright' de mentira + estado por thread."""
    from types import SimpleNamespace
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry({"tools": {"guarded_actions": [], "always_confirm": []}})
    pw = []

    def original(nome, args):
        def f(**kw):
            pw.append((nome, kw))
            return {"ok": True, "via": "playwright"}
        # As ferramentas Playwright reais têm assinatura EXPLÍCITA (sem **kw):
        # o fake imita isso, senão o filtro de argumentos desconhecidos nunca
        # seria exercitado.
        import inspect
        f.__signature__ = inspect.Signature([
            inspect.Parameter(a, inspect.Parameter.KEYWORD_ONLY, default=None)
            for a in args])
        return f
    # espelha browser/tools.py (nomes e argumentos reais)
    specs = {
        "navegador_abrir": {"url": "str?", "navegador": "str?"},
        "navegador_ir": {"url": "str", "navegador": "str?"},
        "navegador_ver": {"navegador": "str?"},
        "navegador_clicar": {"alvo": "str", "navegador": "str?"},
        "navegador_preencher": {"alvo": "str", "valor": "str", "enviar": "bool?",
                                "navegador": "str?"},
        "navegador_pressionar": {"tecla": "str", "alvo": "str?", "navegador": "str?"},
        "navegador_rolar": {"direcao": "str?", "vezes": "int?", "navegador": "str?"},
        "navegador_esperar": {"segundos": "float?", "seletor": "str?", "navegador": "str?"},
        "navegador_extrair": {"seletor": "str?", "max_chars": "int?", "navegador": "str?"},
        "navegador_captura": {"pagina_inteira": "bool?", "navegador": "str?"},
        "navegador_pesquisar": {"termo": "str", "navegador": "str?"},
    }
    for nome, args in specs.items():
        reg.register(nome, original(nome, args), "d", args)
    eu = SimpleNamespace(tools=reg, _tl=threading.local())
    from yvakor.orchestrator import Orchestrator
    Orchestrator._usar_extensao_como_alvo(eu)
    return eu, pw


class _Ponte:
    def __init__(self, extra=None):
        self.chamadas = []
        self.extra = extra or {}

    def __call__(self, tipo, args=None, espera=45.0):
        self.chamadas.append((tipo, dict(args or {})))
        return {"ok": True, **self.extra}


def test_ferramentas_chegam_a_extensao_com_os_argumentos_certos():
    from yvakor.extensao_bridge import PONTE
    eu, pw = _orquestrador_falso()
    ponte = _Ponte()
    with mock.patch.object(PONTE, "comando", ponte):
        eu.tools.run("navegador_digitar", alvo="e2", texto="oi", enviar=True)
        eu.tools.run("navegador_preencher", alvo="e2", valor="x", limpar=False)
        eu.tools.run("navegador_selecionar", alvo="e5", valor="Portugal")
        eu.tools.run("navegador_pesquisar", termo="gatos", buscador="youtube")
        eu.tools.run("navegador_esperar", texto="Resultados", segundos=2)
        eu.tools.run("navegador_historico", acao="voltar")
        eu.tools.run("navegador_passar_mouse", alvo="e1")
        eu.tools.run("navegador_rolar", direcao="fim")
        eu.tools.run("navegador_pressionar", tecla="Control+A")
        eu.tools.run("navegador_extrair", seletor="#lista", max_chars=500)
    assert ponte.chamadas == [
        ("type", {"alvo": "e2", "texto": "oi", "enviar": True}),
        ("fill", {"alvo": "e2", "valor": "x", "limpar": False}),
        ("select", {"alvo": "e5", "valor": "Portugal"}),
        ("search", {"termo": "gatos", "buscador": "youtube"}),
        ("wait", {"segundos": 2, "texto": "Resultados"}),
        ("history", {"acao": "voltar"}),
        ("hover", {"alvo": "e1"}),
        ("scroll", {"direcao": "fim"}),
        ("press", {"tecla": "Control+A"}),
        # regressão: o mapeamento dizia "selector" e o seletor nunca chegava
        ("extract", {"seletor": "#lista", "max_chars": 500}),
    ]
    assert pw == []          # nada caiu no Playwright (que abriria OUTRO Chrome)


def test_esperar_e_captura_nao_abrem_outro_chrome_com_a_extensao_como_alvo():
    """navegador_esperar/captura não estavam mapeados: com a extensão como alvo
    elas ainda iam ao motor Playwright e abriam o Chrome do agente."""
    from yvakor.extensao_bridge import PONTE
    import yvakor.orchestrator as orq
    eu, pw = _orquestrador_falso()
    pasta = Path(tempfile.mkdtemp())
    import base64
    ponte = _Ponte({"imagem_b64": base64.b64encode(b"JPEGDATA").decode()})
    with mock.patch.object(PONTE, "comando", ponte), \
            mock.patch.object(orq, "ROOT", pasta):
        r = eu.tools.run("navegador_captura")
        eu.tools.run("navegador_esperar", seletor="#x")
    assert pw == []
    assert "imagem_b64" not in r                       # não estoura o contexto
    arq = Path(r["arquivo"])
    assert arq.parent == pasta / "data" / "browser_shots"
    assert arq.read_bytes() == b"JPEGDATA"


def test_com_outro_navegador_o_caminho_playwright_continua_valido():
    from yvakor.extensao_bridge import PONTE
    eu, pw = _orquestrador_falso()
    with mock.patch.object(PONTE, "comando", _Ponte()):
        # 'edge' explícito: digitar vira preencher no motor Playwright
        eu.tools.run("navegador_digitar", alvo="e2", texto="oi", navegador="edge")
        # argumento que o original não conhece é descartado (sem TypeError)
        r = eu.tools.run("navegador_pesquisar", termo="x", buscador="youtube",
                         navegador="edge")
        # ação exclusiva da extensão: erro claro, não exceção
        h = eu.tools.run("navegador_historico", acao="voltar", navegador="edge")
    assert pw[0][0] == "navegador_preencher"
    assert pw[0][1]["valor"] == "oi" and pw[0][1]["alvo"] == "e2"
    assert pw[1][0] == "navegador_pesquisar" and "buscador" not in pw[1][1]
    assert r["ok"] is True
    assert h["ok"] is False and "extensão" in h["error"]


# --------------------------------------------------------------------------- #
# JS da extensão
# --------------------------------------------------------------------------- #
def test_js_da_extensao_tem_sintaxe_valida():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node não instalado")
    for nome in ("background.js", "pagina.js", "overlay.js", "sidepanel.js"):
        r = subprocess.run([node, "--check", str(ROOT / "chrome-extension" / nome)],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{nome}: {r.stderr[:300]}"


def test_background_injeta_o_motor_e_nao_tem_mais_codigo_de_acao_embutido():
    fonte = (ROOT / "chrome-extension" / "background.js").read_text(encoding="utf-8")
    assert 'files: ["overlay.js", "pagina.js"]' in fonte
    assert "__yvakorAcoes" in fonte
    # o motor único está em pagina.js; nada de duplicata no background
    assert "deepText" not in fonte and "findByRef" not in fonte
    for comando in ("snapshot", "extract", "click", "fill", "type", "press", "select",
                    "hover", "wait", "scroll", "history", "screenshot", "search"):
        assert f'c.tipo === "{comando}"' in fonte or f'c.tipo === "{comando}" ||' in fonte, comando
    pagina = (ROOT / "chrome-extension" / "pagina.js").read_text(encoding="utf-8")
    for acao in ("snapshot", "extrair", "clicar", "escrever", "pressionar",
                 "selecionar", "passar_mouse", "esperar", "rolar"):
        assert acao in pagina.split("window.__yvakorAcoes =")[-1], acao


def test_roteiro_de_verificacao_no_chrome_real_acompanha_o_projeto():
    base = ROOT / "tests" / "extensao"
    assert (base / "pagina_teste.html").is_file()
    roteiro = (base / "teste_acoes.js").read_text(encoding="utf-8")
    assert "async function rodarTestes" in roteiro
    # os casos que motivaram o motor novo
    for caso in ("ENVIA o <form>", "editor rico", "shadow DOM", "campo de senha"):
        assert caso in roteiro, caso
