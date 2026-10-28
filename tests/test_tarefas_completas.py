"""Por que nenhuma tarefa terminava (conversas de 27–28/10/2026): ferramenta
escolhida só pela última frase, agente que "não tinha" a ferramenta, Python
errado no shell, argumentos perdidos e nenhum rastro do que falhou."""
import json
import sys

import pytest

from yvakor.agent import AgentLoop, _parse_acoes
from yvakor.config import load_settings
from yvakor.tools import builtin
from yvakor.tools.registry import ToolRegistry
from yvakor.tools.router import GERAL, selecionar


def _registro():
    reg = ToolRegistry(load_settings())
    nomes = (list(GERAL) + ["executar_shell", "arquivos_listar", "arquivos_ler",
             "cerebro_buscar", "pensar", "tarefas_checklist", "perguntar_usuario",
             "mercado_analisar", "rede_telefone_tela", "rede_gerenciar", "voz_falar",
             "voz_status", "cerebro_receitas"])
    for n in nomes:
        reg.register(n, lambda **k: {"ok": True}, f"ferramenta {n}", {"url": "str"})
    return reg


def _sel(reg, *falas):
    hist = []
    for i, f in enumerate(falas):
        hist += [{"role": "user", "content": f}, {"role": "assistant", "content": "ok"}]
    hist.pop()
    return AgentLoop(None, reg, max_ferramentas=22)._selecionar(hist)


def test_mensagem_curta_herda_o_assunto_e_tem_o_conjunto_geral():
    reg = _registro()
    sim = _sel(reg, "agora faça uma analise aprofundada do btc",
               "tem que mostrar sempre na tela", "sim")
    assert {"mercado_analisar", "executar_python", "cap_grafico"} <= set(sim)
    tela = _sel(reg, "o que esta na tela")
    assert "navegador_ver" in tela and "navegador_captura" in tela
    assert not {"rede_telefone_tela", "rede_gerenciar", "voz_falar"} & set(tela)
    assert len(_sel(reg, "resolva")) < len(reg.tools)       # não manda todas


def test_compacto_so_libera_risco_pelo_pedido_atual():
    reg = _registro()
    reg.register("arquivos_apagar", lambda **k: {}, "apaga", {"caminho": "str"})
    ag = AgentLoop(None, reg)
    hist = [{"role": "user", "content": "apague o arquivo x.txt"},
            {"role": "assistant", "content": "feito"},
            {"role": "user", "content": "qual a cotação do btc?"}]
    assert "arquivos_apagar" not in ag._selecionar(hist, limite=6)


def test_prompt_lista_as_ferramentas_fora_da_selecao():
    reg = _registro()
    ag = AgentLoop(None, reg)
    texto = ag.system_with_tools("base", ["pensar", "navegador_ver"])
    assert "OUTRAS FERRAMENTAS DISPONÍVEIS" in texto and "executar_python" in texto
    assert "Nunca diga que não tem uma ferramenta" in texto
    assert "OUTRAS FERRAMENTAS" not in ag.system_with_tools("base", list(reg.tools))


@pytest.mark.skipif(sys.platform != "win32", reason="mapeamento do cmd.exe")
def test_shell_usa_o_python_do_projeto_e_explica_linux():
    py = builtin._python_do_projeto()
    assert builtin._comando_windows('python3 -c "print(1)"').startswith(f'"{py}" -c')
    assert builtin._comando_windows("pip install x && python a.py") == \
        f'"{py}" -m pip install x && "{py}" a.py'
    assert builtin._comando_windows("echo python3") == "echo python3"
    r = builtin.executar_shell('python3 -c "import matplotlib; print(42)"', timeout=60)
    assert r["ok"] and "42" in r["stdout"]
    r = builtin.executar_shell("scrot /tmp/tela.png")
    assert not r["ok"] and "WINDOWS" in r["dica"]


def test_chamadas_que_perdiam_argumentos():
    reg = _registro()
    reg.register("navegador_ir", lambda url="": {"ok": True}, "vai", {"url": "str"})
    reg.register("executar_shell", lambda comando="": {"ok": True}, "sh",
                 {"comando": "str", "timeout": "int?"})
    assert _parse_acoes("<navegador_ir>\n<url>https://a.b/</url>\n</navegador_ir>",
                        reg)[0]["args"] == {"url": "https://a.b/"}
    assert _parse_acoes('{"ferramenta": "navegador_ir", "args": "https://a.b"}',
                        reg)[0]["args"] == {"url": "https://a.b"}
    assert _parse_acoes('{"ferramenta": "executar_shell", "args": {"cmd": "dir"}}',
                        reg)[0]["args"] == {"comando": "dir"}


def test_rastro_da_tarefa_mascara_dados(tmp_path, monkeypatch):
    from yvakor import orchestrator
    monkeypatch.setattr(orchestrator, "RASTROS", tmp_path / "r.jsonl")
    orchestrator._gravar_rastro("abc123456789", "consulta o cpf 123.456.789-00",
                                "Preenchi 12345678900", [
                                    {"nome": "navegador_ir", "ok": False,
                                     "erro": "faltou url"},
                                    {"nome": "navegador_ver", "ok": True}], 3.21, None)
    linha = json.loads((tmp_path / "r.jsonl").read_text(encoding="utf-8"))
    assert linha["falhas"] == 1 and linha["sessao"] == "23456789"
    assert "123" not in linha["pedido"] and "###" in linha["resposta"]
    assert orchestrator._mascarar("CEP 69000-000 em 01/02/1960") == "CEP ### em ###"
