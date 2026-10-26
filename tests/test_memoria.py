"""Teste da memória otimizada + cérebro Obsidian (offline).

Valida: schema, índices/FTS, desempenho com volume, poda, dedup semântica,
índice de skills, vault markdown (links/backlinks/grafo) e backup.

    python tests/test_memoria.py
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


def test_episodico_desempenho():
    from yvakor.memory.episodic import EpisodicMemory
    tmp = Path(tempfile.mkdtemp(prefix="yvk-mem-"))
    m = EpisodicMemory(tmp / "mem.db")
    assert m.estatisticas()["schema"] == "2"
    assert m.estatisticas()["fts"] is True

    sid = m.nova_conversa("Teste de volume").split()[0]
    t0 = time.perf_counter()
    m.log_many([("ferramenta", f"navegador_clicar {i}", "ok") for i in range(5000)])
    m.log_many([("conversa", f"pergunta {i} sobre camera intelbras",
                 f"resposta {i} da camera") for i in range(500)])
    insercao = time.perf_counter() - t0
    assert insercao < 60, f"inserção lenta: {insercao:.1f}s"

    t0 = time.perf_counter()
    for _ in range(200):
        m.history_messages(10, sid)
    historico = (time.perf_counter() - t0) / 200 * 1000
    assert historico < 5, f"histórico lento: {historico:.2f} ms"

    t0 = time.perf_counter()
    for _ in range(200):
        m.listar_conversas()
    listagem = (time.perf_counter() - t0) / 200 * 1000
    assert listagem < 5, f"listagem lenta: {listagem:.2f} ms"

    t0 = time.perf_counter()
    achados = m.buscar("camera intelbras", 10)
    busca = (time.perf_counter() - t0) * 1000
    assert achados and busca < 50, f"busca lenta: {busca:.1f} ms"
    assert "[" in achados[0]["trecho"], achados[0]

    # poda remove operacionais antigos e PRESERVA conversas
    removidos = m.podar(dias=0, max_operacionais=1000)["removidos"]
    assert removidos > 0
    restantes = m.estatisticas()
    assert restantes["conversas"] >= 500, restantes
    assert restantes["por_tipo"].get("ferramenta", 0) <= 1000, restantes

    destino = m.backup(tmp / "backup.db")
    assert Path(destino).stat().st_size > 0
    print(f"  ✅ episódico — {insercao:.1f}s p/ 5.500 registros · "
          f"histórico {historico:.2f} ms · lista {listagem:.2f} ms · "
          f"busca {busca:.1f} ms · poda {removidos}")


def test_semantico():
    from yvakor.memory.semantic import SemanticMemory
    tmp = Path(tempfile.mkdtemp(prefix="yvk-sem-"))
    s = SemanticMemory(tmp / "semantic")
    assert s.store("Usuário prefere relatórios em PDF") is True
    assert s.store("usuario prefere relatorios em pdf") is False   # dedup
    s.store_many(["Cliente ACM usa câmeras Intelbras",
                  "Projeto Atlas usa FastAPI e Postgres"])
    achados = s.search("relatorio pdf")
    assert achados and "PDF" in achados[0], achados
    assert s.search("intelbras"), "busca deveria achar Intelbras"
    assert len(s.todos(10)) >= 3
    s.substituir(["Fato consolidado único"])
    assert s.contar() == 1
    assert Path(s.exportar_jsonl()).exists()
    print("  ✅ semântico — dedup por hash, FTS com plural, substituição, export")


def test_skills():
    from yvakor.memory.procedural import SkillLibrary
    tmp = Path(tempfile.mkdtemp(prefix="yvk-skills-"))
    pasta = tmp / "skills"
    pasta.mkdir()
    (pasta / "camera-onvif.md").write_text(
        "<!-- skill: Configurar camera ONVIF | tags: camera, onvif -->\n"
        "# Configurar camera ONVIF\n## Passos\nabra o ip e use o protocolo onvif\n",
        encoding="utf-8")
    (pasta / "pdf.md").write_text(
        "<!-- skill: Gerar PDF | tags: pdf, relatorio -->\n"
        "# Gerar PDF\n## Passos\nuse reportlab para gerar o relatorio\n",
        encoding="utf-8")
    lib = SkillLibrary(pasta, tmp / "skills.db")
    achados = lib.find_relevant("protocolo onvif da camera", top_k=1)
    assert achados and "onvif" in achados[0].lower(), achados
    assert lib.estatisticas()["skills"] == 2
    lib.save("Nova skill", "<!-- skill: Nova | tags: teste -->\n# Nova\nconteudo")
    assert lib.estatisticas()["skills"] == 3
    print("  ✅ skills — índice FTS, ranking e atualização ao salvar")


def test_cerebro():
    from yvakor.memory.episodic import EpisodicMemory
    from yvakor.memory.semantic import SemanticMemory
    from yvakor.memory.procedural import SkillLibrary
    from yvakor.cerebro import Cerebro

    tmp = Path(tempfile.mkdtemp(prefix="yvk-cerebro-"))
    m = EpisodicMemory(tmp / "mem.db")
    sem = SemanticMemory(tmp / "semantic")
    pasta = tmp / "skills"
    pasta.mkdir()
    (pasta / "camera.md").write_text(
        "<!-- skill: Instalar camera | tags: camera -->\n# Instalar camera\n"
        "## Passos\nacesse 192.168.0.10 e configure\n", encoding="utf-8")
    lib = SkillLibrary(pasta, tmp / "skills.db")
    sem.store("A câmera da garagem é Intelbras e fica no IP 192.168.15.7")
    sid = m.nova_conversa("Conversa sobre camera").split()[0]
    m.log("conversa", "como vejo a camera?", "use rede_camera_snapshot",
          session_id=sid)

    c = Cerebro({"cerebro": {"exportar_conversas": True}}, m, sem, lib,
                vault_dir=tmp / "vault", db_path=tmp / "cerebro.db")
    r = c.sincronizar()
    st = c.status()
    assert st["notas"] >= 4, st
    assert st["links"] >= 4, st
    assert (tmp / "vault" / "Home.md").exists()
    assert (tmp / "vault" / "Skills" / "camera.md").exists()

    achados = c.buscar("intelbras garagem")
    assert achados, "busca no vault deveria achar a memória"
    home = c.nota("Home")
    assert home and home["backlinks"], home
    assert c.nota("Skills/camera.md") is not None

    g = c.grafo("Home", 1)
    assert len(g["nos"]) > 2 and g["arestas"], g

    # segunda sincronização não reescreve o que não mudou
    r2 = c.sincronizar()
    assert r2["indexados"]["novos"] == 0, r2
    assert sum(r2["exportados"].values()) == 0, r2

    # escrita manual entra no índice e é linkável
    e = c.escrever("Ideia de automação", "Ligar a câmera quando o celular "
                   "chegar em casa. Ver [[Home]].", tags="ideia, automacao")
    assert Path(e["arquivo"]).exists()
    assert c.buscar("celular chegar em casa"), "nota nova deveria indexar"
    print(f"  ✅ cérebro — {st['notas']} notas, {st['links']} links, "
          "busca/backlinks/grafo e escrita incremental")


if __name__ == "__main__":
    test_episodico_desempenho()
    test_semantico()
    test_skills()
    test_cerebro()
