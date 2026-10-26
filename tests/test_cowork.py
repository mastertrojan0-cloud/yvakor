"""Teste do Cowork 2.0 (sem LLM, sem rede).

Usa um orquestrador falso para validar: fila, concorrência, passos ao vivo,
persistência em SQLite, cancelamento e recuperação de tarefas interrompidas.

    python tests/test_cowork.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from yvakor.cowork import CoworkManager  # noqa: E402


class FakeEpisodic:
    def __init__(self):
        self.n = 0
        self.criadas = []

    def create_session(self, title="", activate=False, kind="task"):
        self.n += 1
        sid = f"sess-{self.n}"
        self.criadas.append((sid, title, kind))
        return sid


class FakeOrch:
    """Substitui o Orchestrator: devolve resultado previsível."""

    def __init__(self):
        self.episodic = FakeEpisodic()
        self.chamadas = []

    def _rotulo_passo(self, dado):
        return f"🔧 {dado.get('nome', '')}"

    def process(self, mensagem, session_id=None, should_stop=None,
                extra_context=None):
        self.chamadas.append({"msg": mensagem, "sid": session_id,
                              "ctx": extra_context})
        iteracoes = 6 if "longa" in mensagem else 2
        for _ in range(iteracoes):
            if should_stop and should_stop():
                return "⏹ cancelada"
            time.sleep(0.12)
        return f"resultado de: {mensagem}"


def esperar(cond, timeout=8.0):
    fim = time.time() + timeout
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_cowork() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="yvk-cowork-"))
    db = tmp / "cowork.db"
    ws = tmp / "workspace"
    orch = FakeOrch()
    mgr = CoworkManager(orch, {"cowork": {"max_concurrent_tasks": 1,
                                          "max_steps": 40},
                               "agent": {"max_iterations": 25}},
                        db_path=db, workspace_root=ws)

    # 1) tarefa simples conclui, grava resultado.md e usa sessão isolada
    t1 = mgr.submit("tarefa simples de teste")
    assert t1["status"] in ("na_fila", "executando"), t1
    assert esperar(lambda: mgr.get(t1["id"])["status"] == "concluida"), \
        mgr.get(t1["id"])
    d1 = mgr.get(t1["id"])
    assert "resultado de: tarefa simples de teste" in d1["result"]
    assert Path(d1["workspace"]).is_dir()
    assert (Path(d1["workspace"]) / "resultado.md").exists()
    assert d1["session_id"] == "sess-1"
    assert orch.chamadas[0]["sid"] == "sess-1"
    assert "Diretório de trabalho" in orch.chamadas[0]["ctx"]

    # 2) fila + concorrência: a 2ª só começa quando a 1ª termina
    t2 = mgr.submit("tarefa longa A")
    t3 = mgr.submit("tarefa longa B")
    assert esperar(lambda: mgr.get(t2["id"])["status"] == "executando"), \
        mgr.get(t2["id"])
    # enquanto t2 roda (1 vaga), t3 tem que estar na fila
    assert mgr.get(t3["id"])["status"] in ("na_fila", "executando")
    assert mgr.get(t3["id"])["status"] == "na_fila", mgr.get(t3["id"])

    # 3) cancelar a que está na fila
    r = mgr.cancel(t3["id"])
    assert r["ok"], r
    d3 = mgr.get(t3["id"])
    assert d3["status"] == "cancelada", d3

    # 4) cancelar a que está rodando (cooperativo, entre passos)
    r = mgr.cancel(t2["id"])
    assert r["ok"], r
    assert esperar(lambda: mgr.get(t2["id"])["status"] == "cancelada", 10), \
        mgr.get(t2["id"])

    # 5) os passos ficam registrados
    d1 = mgr.get(t1["id"])
    assert any("tarefa" in p["texto"] for p in d1["steps"]), d1["steps"]

    # 6) persistência: novo manager, mesmo banco, mesma tarefa
    mgr2 = CoworkManager(orch, {"cowork": {"max_concurrent_tasks": 1}},
                         db_path=db, workspace_root=ws)
    assert [t["id"] for t in mgr2.list()].count(t1["id"]) == 1
    assert mgr2.get(t1["id"])["status"] == "concluida"
    texto = mgr2.status()
    assert t1["id"] in texto
    assert "resultado de" in mgr2.result(t1["id"])

    # 7) recuperação: tarefa que "estava rodando" vira interrompida
    mgr2.store.insert({
        "id": "crashed1", "description": "tarefa que morreu",
        "status": "executando", "created_at": "2026-01-01 00:00:00",
        "started_at": "2026-01-01 00:00:01", "finished_at": None,
        "result": None, "error": None, "steps": [],
        "session_id": None, "workspace": None,
    })
    mgr3 = CoworkManager(orch, {"cowork": {"max_concurrent_tasks": 1}},
                         db_path=db, workspace_root=ws)
    assert mgr3.get("crashed1")["status"] == "interrompida"

    print("  ✅ cowork ok — fila, cancelamento, persistência, recuperação")


def test_cowork_cancel_retomada() -> None:
    """Regressão: cancelar uma tarefa RETOMADA/recuperada tem de pará-la.
    Antes, retomar()/recover não repovoavam self._events, então _run criava um
    Event local e cancel()/shutdown() nunca sinalizavam a tarefa."""
    tmp = Path(tempfile.mkdtemp(prefix="yvk-cowork-ret-"))
    db = tmp / "cowork.db"
    ws = tmp / "workspace"
    orch = FakeOrch()
    cfg = {"cowork": {"max_concurrent_tasks": 1, "auto_resume": False}}

    # simula uma tarefa longa que "estava rodando" quando o processo caiu
    mgr = CoworkManager(orch, cfg, db_path=db, workspace_root=ws)
    mgr.store.insert({
        "id": "ret1", "description": "tarefa longa recuperada",
        "status": "executando", "created_at": "2026-01-01 00:00:00",
        "started_at": "2026-01-01 00:00:01", "finished_at": None,
        "result": None, "error": None, "steps": [],
        "session_id": None, "workspace": None,
    })

    # novo manager recupera -> interrompida
    mgr2 = CoworkManager(orch, cfg, db_path=db, workspace_root=ws)
    assert mgr2.get("ret1")["status"] == "interrompida"

    # retomar e deixar começar a rodar
    assert mgr2.retomar("ret1")["ok"]
    assert esperar(lambda: mgr2.get("ret1")["status"] == "executando"), \
        mgr2.get("ret1")

    # cancelar a tarefa RETOMADA deve efetivamente pará-la
    r = mgr2.cancel("ret1")
    assert r["ok"], r
    assert "ret1" in mgr2._events and mgr2._events["ret1"].is_set(), \
        "evento de cancelamento não registrado/sinalizado para tarefa retomada"
    assert esperar(lambda: mgr2.get("ret1")["status"] == "cancelada", 10), \
        mgr2.get("ret1")

    print("  ✅ cancelamento de tarefa retomada ok")


if __name__ == "__main__":
    test_cowork()
    test_cowork_cancel_retomada()
