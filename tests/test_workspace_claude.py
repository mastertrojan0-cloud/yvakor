"""Workspace estilo Claude Code: conversa → workspace, YVAKOR.md, mudanças/diff,
e a ponte com o VS Code."""
import shutil
import subprocess
import threading
import time

import pytest

from yvakor import vscode
from yvakor import workspaces as ws
from yvakor.memory.episodic import EpisodicMemory


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "ARQ", tmp_path / "workspaces.json")
    return tmp_path


def test_conversa_guarda_o_workspace(tmp_path):
    m = EpisodicMemory(tmp_path / "mem.db")
    m.nova_conversa("no projeto", workspace="abc123")
    sid = m.active_id
    assert m.workspace_da_conversa(sid) == "abc123"
    conv = next(c for c in m.listar_conversas() if c["id"] == sid)
    assert conv["workspace"] == "abc123"
    m.nova_conversa("geral")
    assert m.workspace_da_conversa(m.active_id) is None
    assert m.definir_workspace(m.active_id, "xyz") and m.workspace_da_conversa(m.active_id) == "xyz"


def test_cada_conversa_trabalha_no_seu_workspace(base):
    a, b = base / "a", base / "b"
    a.mkdir()
    b.mkdir()
    wa = ws.adicionar(str(a))["workspace"]["id"]
    ws.adicionar(str(b))                                   # b fica como ativo global
    assert ws.caminho_ativo() == b.resolve()
    with ws.usar(wa):                                      # conversa do projeto A
        assert ws.caminho_ativo() == a.resolve()
    with ws.usar(""):                                      # conversa sem workspace? não:
        assert ws.caminho_ativo() is None                  # "" fixa NENHUM
    assert ws.caminho_ativo() == b.resolve()               # fora: volta ao global


def test_yvakor_md_vira_instrucao_do_projeto(base):
    p = base / "proj"
    p.mkdir()
    (p / "YVAKOR.md").write_text("Use tabs. Testes com pytest.", encoding="utf-8")
    ws.adicionar(str(p))
    bloco = ws.bloco_prompt()
    assert "Instruções do projeto (YVAKOR.md)" in bloco and "Use tabs" in bloco


@pytest.mark.skipif(not shutil.which("git"), reason="git ausente")
def test_mudancas_e_diff_num_repositorio_real(base):
    p = base / "repo"
    p.mkdir()

    def git(*a):
        subprocess.run(["git", "-C", str(p), *a], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (p / "app.py").write_text("print('v1')\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "v1")
    (p / "app.py").write_text("print('v2')\n", encoding="utf-8")
    (p / "novo.py").write_text("x = 1\n", encoding="utf-8")
    wid = ws.adicionar(str(p))["workspace"]["id"]
    m = ws.mudancas(wid)
    estados = {a["arquivo"]: a["estado"] for a in m["arquivos"]}
    assert estados == {"app.py": "alterado", "novo.py": "novo"}
    d = ws.diff(wid, "app.py")["diff"]
    assert "-print('v1')" in d and "+print('v2')" in d
    assert "+x = 1" in ws.diff(wid, "novo.py")["diff"]
    assert not ws.diff(wid, "../fora.txt")["ok"]          # não sai do workspace


def test_contexto_do_vscode_entra_no_prompt_e_expira(base, monkeypatch):
    pasta = str(base / "proj")
    vscode.registrar_contexto({"workspace": pasta, "arquivo": pasta + "/app.py",
                               "linguagem": "python", "linha": 12, "selecao": "def soma(a, b):",
                               "linha_inicio": 12, "linha_fim": 13,
                               "problemas": ["linha 13: 'b' não usado"]})
    bloco = vscode.bloco_prompt(pasta)
    assert "VS CODE" in bloco and "def soma" in bloco and "não usado" in bloco
    monkeypatch.setattr(vscode, "IDADE_MAX_S", -1)
    assert vscode.bloco_prompt(pasta) == ""


def test_fila_de_comandos_long_poll():
    vscode.pegar_comandos(0)                               # limpa
    resultado = {}
    t = threading.Thread(target=lambda: resultado.update(c=vscode.pegar_comandos(5)))
    t.start()
    time.sleep(0.2)
    vscode.enfileirar({"tipo": "abrir", "arquivo": "x", "linha": 3})
    t.join(3)
    assert resultado["c"] == [{"tipo": "abrir", "arquivo": "x", "linha": 3}]
    assert vscode.conectado()


def test_abrir_sem_extensao_usa_code_g(base, monkeypatch):
    arq = base / "a.py"
    arq.write_text("x")
    monkeypatch.setattr(vscode, "_ultimo_poll", 0.0)
    chamado = []
    monkeypatch.setattr(vscode.shutil, "which", lambda n: "code")
    monkeypatch.setattr(vscode.proc, "popen", lambda cmd: chamado.append(cmd))
    r = vscode.abrir(str(arq), 7)
    assert r["via"] == "code -g" and chamado[0][-1].endswith("a.py:7")


def test_pedido_sobre_o_vscode_nao_vira_navegador():
    from yvakor.agent import AgentLoop
    from yvakor.interprete import interpretar
    msg = "tem algum bug na função que eu selecionei no VS Code?"
    assert not AgentLoop.intencao_navegador(msg)
    assert AgentLoop.intencao_navegador("selecione a opção azul no site")
    it = interpretar(msg, [], usar_modelo=False)
    assert [n for n, _, _ in it.indicadas] == ["o que está no VS Code"]
    assert "NÃO use navegador" in it.bloco()


def test_ler_e_escrever_arquivo_usam_o_workspace_ativo(base):
    from yvakor.tools import builtin
    p = base / "proj"
    p.mkdir()
    (p / "calc.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
    ws.adicionar(str(p))
    assert "return a - b" in builtin.ler_arquivo("calc.py")["conteudo"]
    assert builtin.ler_arquivo_local("calc.py")["ok"]
    r = builtin.escrever_arquivo("novo.txt", "oi")
    assert r["ok"] and (p / "novo.txt").read_text() == "oi"
    with pytest.raises(ValueError):
        builtin.ler_arquivo("../fora.txt")
    ws.ativar(None)                                      # sem workspace: volta ao sandbox
    assert builtin._resolver_sandbox("x.txt").parent == builtin.SANDBOX.resolve()
