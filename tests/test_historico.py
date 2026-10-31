"""Apagar todo o histórico de conversas SEM apagar o aprendizado."""
import json
import zipfile

import pytest

from yvakor import historico
from yvakor.memory.episodic import EpisodicMemory


@pytest.fixture
def ambiente(tmp_path):
    data = tmp_path / "data"
    (data / "vault" / "Conversas").mkdir(parents=True)
    (data / "vault" / "Skills").mkdir(parents=True)
    (data / "uploads").mkdir()
    m = EpisodicMemory(data / "yvakor_memory.db")
    m.nova_conversa("projeto secreto")
    sid = m.active_id
    m.log("conversa", "minha senha do banco é 1234", "anotado", session_id=sid)
    m.log("ferramenta", "arquivos_ler", "{}", session_id=sid)
    m.log("skill_destilada", "organizar pastas", "organizacao-pastas", session_id=sid)
    tarefa = m.create_session("tarefa cowork", kind="task")
    m.log("conversa", "etapa da tarefa", "ok", session_id=tarefa)
    (data / "vault" / "Conversas" / "abc-projeto-secreto.md").write_text("conversa")
    (data / "vault" / "Skills" / "organizar.md").write_text("skill")
    (data / "rastros.jsonl").write_text('{"pedido": "senha 1234"}\n')
    (data / "avaliacoes.jsonl").write_text(json.dumps(
        {"nota": 4, "correcao": 4, "pergunta": "senha 1234", "resposta": "x",
         "problemas": ["p"], "melhoria": "m"}) + "\n")
    (data / "uploads" / "foto.png").write_bytes(b"png")
    (data / "licoes.json").write_text('[{"texto": "não inventar dados"}]')
    return tmp_path, m, sid, tarefa


def test_exige_confirmacao(ambiente):
    raiz, m, _, _ = ambiente
    r = historico.apagar_historico(m, raiz=raiz, confirmar="sim")
    antes = historico.resumo(m, raiz)["conversas"]
    assert not r["ok"] and "APAGAR" in r["erro"]
    assert antes >= 1 and historico.resumo(m, raiz)["conversas"] == antes   # nada mudou


def test_apaga_historico_e_mantem_aprendizado(ambiente):
    raiz, m, sid, tarefa = ambiente
    data = raiz / "data"
    antes = historico.resumo(m, raiz)
    r = historico.apagar_historico(m, raiz=raiz, confirmar="APAGAR")
    assert r["ok"] and r["conversas_apagadas"] == antes["conversas"]
    assert r["mensagens_apagadas"] == 2                          # conversa + ferramenta

    # histórico: foi embora
    ids = {c["id"] for c in m.listar_conversas()}
    assert sid not in ids and r["nova_conversa"] in ids          # só a conversa nova
    assert not list((data / "vault" / "Conversas").glob("*.md"))
    assert not (data / "rastros.jsonl").exists() and not (data / "uploads").exists()
    assert m.buscar("senha") == [] or all("1234" not in str(x) for x in m.buscar("senha"))
    aval = json.loads((data / "avaliacoes.jsonl").read_text())
    assert aval == {"nota": 4, "correcao": 4}                    # nota fica, texto sai

    # aprendizado: ficou
    assert (data / "licoes.json").read_text() == '[{"texto": "não inventar dados"}]'
    assert (data / "vault" / "Skills" / "organizar.md").exists()
    kinds = dict(m.conn.execute("SELECT kind, COUNT(*) FROM episodes GROUP BY kind").fetchall())
    assert kinds.get("skill_destilada") == 1
    assert m.workspace_da_conversa(tarefa) is None and any(
        c["id"] == tarefa for c in m.listar_conversas(kind="task"))  # tarefa intacta

    # backup completo para desfazer
    with zipfile.ZipFile(r["backup"]) as z:
        nomes = set(z.namelist())
    assert {"yvakor_memory.db", "data/rastros.jsonl", "data/avaliacoes.jsonl",
            "data/vault/Conversas/abc-projeto-secreto.md", "data/uploads/foto.png"} <= nomes


def test_ferramenta_do_agente_sempre_pede_confirmacao():
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry(load_settings())
    assert reg.guard.requires_confirmation("historico_apagar_tudo")
    assert "historico_apagar_tudo" in reg.guard.always_confirm
