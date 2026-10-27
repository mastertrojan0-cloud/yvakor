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
