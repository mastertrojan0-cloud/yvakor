"""Portão de qualidade do código: barra regressões que viram bug silencioso."""
import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PACOTE = RAIZ / "yvakor"


def _amplo(tipo) -> bool:
    if tipo is None:
        return True
    if isinstance(tipo, ast.Tuple):
        return any(_amplo(t) for t in tipo.elts)
    return isinstance(tipo, ast.Name) and tipo.id in ("Exception", "BaseException")


def test_nenhum_except_amplo_engole_erro_sem_rastro():
    """`except Exception: pass` esconde a falha; use _log.debug(..., exc_info=True)
    (fica no log com YVAKOR_DEBUG=1) ou trate o erro."""
    achados = []
    for arq in PACOTE.rglob("*.py"):
        arvore = ast.parse(arq.read_text(encoding="utf-8-sig"))
        for no in ast.walk(arvore):
            if (isinstance(no, ast.ExceptHandler) and _amplo(no.type)
                    and len(no.body) == 1 and isinstance(no.body[0], ast.Pass)):
                achados.append(f"{arq.relative_to(RAIZ)}:{no.lineno}")
    assert not achados, "except amplo sem rastro:\n" + "\n".join(achados)


def test_logger_definido_antes_de_usar_no_modulo():
    for arq in PACOTE.rglob("*.py"):
        arvore = ast.parse(arq.read_text(encoding="utf-8-sig"))
        definicoes = [n.lineno for n in arvore.body if isinstance(n, ast.Assign)
                      and any(getattr(t, "id", "") == "_log" for t in n.targets)]
        importa = [n.lineno for n in arvore.body if isinstance(n, ast.Import)
                   and any(a.name == "logging" for a in n.names)]
        if definicoes and importa:
            assert min(importa) < min(definicoes), f"{arq}: _log antes de import logging"


@pytest.mark.skipif(shutil.which("ruff") is None and
                    subprocess.run([sys.executable, "-m", "ruff", "--version"],
                                   capture_output=True).returncode != 0,
                    reason="ruff não instalado (pip install ruff)")
def test_ruff_sem_erros():
    r = subprocess.run([sys.executable, "-m", "ruff", "check", "yvakor",
                        "--output-format", "concise"],
                       cwd=RAIZ, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:]


def test_argumento_com_padrao_vazio_e_marcado_opcional():
    """Conversa 71: sistema_drivers_atualizar(acao="status") era recusado com
    "faltou o argumento obrigatório dispositivos" porque o spec não tinha "?"."""
    import inspect
    import tempfile
    from yvakor.drivers import register_drivers_tools
    from yvakor.entorno.motor import MotorEntorno, register_entorno_tools
    from yvakor.interprete import register_interprete_tools
    from yvakor.organizador import register_organizador_tools
    from yvakor.tools.registry import ToolRegistry

    r = ToolRegistry({"tools": {"guarded_actions": []}})
    register_organizador_tools(r)
    register_drivers_tools(r)
    register_interprete_tools(r)
    register_entorno_tools(r, MotorEntorno({"entorno": {}}, raiz=Path(tempfile.mkdtemp())))
    errados = []
    for nome, spec in r.specs.items():
        params = inspect.signature(r.tools[nome]).parameters
        for k, t in spec["args"].items():
            p = params.get(k)
            if (p is not None and p.default is not inspect.Parameter.empty
                    and not str(t).endswith("?")):
                errados.append(f"{nome}.{k}")
    assert not errados, errados
    r.guard.requires_confirmation = lambda nome: False
    erro = str(r.run("sistema_drivers_atualizar", acao="formatar"))
    assert "faltou o argumento" not in erro and "auto | windows_update" in erro
