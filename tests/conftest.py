"""Fixtures globais: nenhum teste escreve no data/ real."""
import os
import tempfile

import pytest

# Log do servidor fora de data/logs (configurado no import de yvakor.server).
os.environ.setdefault("YVAKOR_LOG_DIR", tempfile.mkdtemp(prefix="yvakor_logs_"))


@pytest.fixture(autouse=True)
def _consumo_em_pasta_temporaria(tmp_path, monkeypatch):
    """O otimizador de consumo grava data/consumo.db: redireciona para a pasta do teste."""
    from yvakor.llm import economia
    monkeypatch.setattr(economia, "ROOT", tmp_path)


@pytest.fixture(autouse=True)
def _workspaces_em_pasta_temporaria(tmp_path, monkeypatch):
    """Nenhum teste lê o workspace ativo real do usuário (data/workspaces.json):
    com um ativo, ler_arquivo/shell mudariam de pasta e os testes de sandbox
    dependeriam do que o usuário fez no app."""
    from yvakor import workspaces
    monkeypatch.setattr(workspaces, "ARQ", tmp_path / "_workspaces.json")


@pytest.fixture(autouse=True)
def _hooks_em_pasta_temporaria(tmp_path, monkeypatch):
    """Os hooks do usuário (config/hooks.json) nunca rodam nos testes."""
    from yvakor import hooks
    monkeypatch.setattr(hooks, "_PADRAO", hooks.Hooks(tmp_path / "_hooks.json"))


@pytest.fixture(autouse=True)
def _tokens_mcp_em_pasta_temporaria(tmp_path, monkeypatch):
    """Logins OAuth de MCP do usuário (data/mcp_oauth.json) ficam fora dos testes."""
    from yvakor import mcp_oauth
    monkeypatch.setattr(mcp_oauth, "ARQ", tmp_path / "_mcp_oauth.json")
