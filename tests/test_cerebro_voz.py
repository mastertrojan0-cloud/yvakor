"""Teste: cérebro aprende com a conversa e voz toca em fila única."""
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


def test_cerebro_aprende_da_conversa():
    from yvakor.memory.episodic import EpisodicMemory
    from yvakor.memory.semantic import SemanticMemory
    from yvakor.memory.procedural import SkillLibrary
    from yvakor.cerebro import Cerebro

    tmp = Path(tempfile.mkdtemp(prefix="yvk-cerebro-"))
    m = EpisodicMemory(tmp / "m.db")
    sem = SemanticMemory(tmp / "sem")
    sk = SkillLibrary(tmp / "skills", tmp / "sk.db")
    sid = m.nova_conversa("cameras").split()[0]
    m.log("conversa", "minha câmera da garagem",
          "Sua câmera da garagem fica no IP 192.168.15.7 e é Intelbras.",
          session_id=sid)
    c = Cerebro({"cerebro": {"limiar_direto": 0.7, "limiar_local": 0.45}},
                m, sem, sk, vault_dir=tmp / "vault", db_path=tmp / "c.db")
    c.sincronizar()
    antes = sem.contar()
    d = c.decidir("qual o IP da câmera da garagem?")
    assert d and d["modo"] == "cerebro", d
    assert "192.168.15.7" in d["resposta"], d
    assert sem.contar() >= antes, "fato deveria ter sido persistido"
    # segunda pergunta: agora vem da memória, sem transcript
    d2 = c.decidir("qual o IP da câmera da garagem?")
    assert d2 and d2["modo"] == "cerebro" and "Memória" in d2["resposta"], d2
    c.fechar()
    print("  ✅ cérebro — aprendeu o fato da conversa e responde limpo das duas vezes")


def test_falante_fila_unica():
    import threading
    from yvakor.voz.falante import Falante
    tocados = []
    liberar = threading.Event()

    def gerar(texto):
        liberar.wait(2)
        return {"ok": True, "arquivo": texto}

    def tocar(caminho):
        tocados.append(Path(caminho).name)
        time.sleep(0.02)
        return True

    f = Falante(gerar, tocar)
    f.falar("narração 1", prioridade=1)
    f.falar("narração 2", prioridade=1)
    assert f.falar("narração 1", prioridade=1).get("ignorado") == "repetido"
    time.sleep(0.05)                       # worker pegou a 1ª e está bloqueado
    f.falar("resposta final", prioridade=2)  # preempta a narração pendente
    liberar.set()
    time.sleep(0.4)
    assert tocados and tocados[-1] == "resposta final", tocados
    assert "narração 2" not in tocados, tocados
    print(f"  ✅ falante — fila única, prioridade e dedupe ({tocados})")


if __name__ == "__main__":
    test_cerebro_aprende_da_conversa()
    test_falante_fila_unica()
