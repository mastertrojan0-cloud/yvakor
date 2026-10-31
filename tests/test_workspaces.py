"""Workspaces: criar com modelo, adicionar, ativar, detalhe e efeito no agente."""
import shutil

import pytest

from yvakor import workspaces as ws


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "ARQ", tmp_path / "workspaces.json")
    return tmp_path


def test_criar_python_gera_arquivos_git_e_ativa(base):
    r = ws.criar("Meu App", "python", "teste", settings={"workspaces": {
        "pasta_base": str(base / "ws")}})
    assert r["ok"], r
    pasta = base / "ws" / "meu-app"
    for arq in ("README.md", ".gitignore", "main.py", "requirements.txt", "tests/test_main.py"):
        assert (pasta / arq).exists(), arq
    assert "Meu App" in (pasta / "main.py").read_text(encoding="utf-8")
    if shutil.which("git"):
        assert (pasta / ".git").exists() and r["workspace"]["git"]
    assert ws.ativo()["nome"] == "Meu App"
    assert ws.caminho_ativo() == pasta.resolve()


def test_node_package_json_valido(base):
    import json
    ws.criar("api", "node", settings={"workspaces": {"pasta_base": str(base / "ws")}})
    dados = json.loads((base / "ws" / "api" / "package.json").read_text(encoding="utf-8"))
    assert dados["name"] == "api" and dados["scripts"]["start"] == "node index.js"


def test_nao_sobrescreve_pasta_com_conteudo(base):
    pasta = base / "ws" / "existente"
    pasta.mkdir(parents=True)
    (pasta / "meu.txt").write_text("importante")
    r = ws.criar("existente", "web", settings={"workspaces": {"pasta_base": str(base / "ws")}})
    assert not r["ok"] and "adicionar" in r["erro"]
    assert (pasta / "meu.txt").read_text() == "importante"


def test_adicionar_ativar_remover_sem_apagar(base):
    proj = base / "projeto"
    proj.mkdir()
    (proj / "package.json").write_text("{}")
    r = ws.adicionar(str(proj))
    wid = r["workspace"]["id"]
    assert r["workspace"]["stack"] == "Node" and ws.listar()["ativo"] == wid
    assert ws.ativar(None)["ativo"] is None and ws.ativo() is None
    assert ws.ativar("projeto")["ok"]                    # por nome
    assert ws.remover(wid)["ok"] and proj.exists()        # pasta continua
    assert ws.listar()["itens"] == [] and ws.ativo() is None


def test_detalhe_traz_arvore_sem_lixo(base):
    proj = base / "p"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "app.py").write_text("x")
    (proj / "node_modules" / "lib").mkdir(parents=True)
    (proj / "README.md").write_text("# P\nolá")
    ws.adicionar(str(proj))
    d = ws.detalhe()
    assert "src/" in d["arvore"] and "  app.py" in d["arvore"]
    assert not any("node_modules" in x for x in d["arvore"])
    assert d["readme"].startswith("# P")


def test_workspace_ativo_muda_caminho_relativo_e_prompt(base):
    from yvakor import arquivos
    proj = base / "p"
    proj.mkdir()
    ws.adicionar(str(proj))
    assert arquivos._p("src/app.py") == proj.resolve() / "src" / "app.py"
    bloco = ws.bloco_prompt()
    assert bloco.startswith("## WORKSPACE ATIVO: p") and str(proj.resolve()) in bloco
    ws.ativar(None)
    assert ws.bloco_prompt() == ""


def test_ferramentas_registradas(base):
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry({"tools": {"guarded_actions": []}})
    nomes = ws.register_workspaces_tools(reg, {"workspaces": {"pasta_base": str(base / "w")}})
    assert "workspace_criar" in nomes
    r = reg.run("workspace_criar", nome="via ferramenta", modelo="web")
    assert r.get("ok") and (base / "w" / "via-ferramenta" / "index.html").exists()
