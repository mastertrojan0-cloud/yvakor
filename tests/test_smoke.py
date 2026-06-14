"""Smoke test: estrutura carrega sem rede."""
from pathlib import Path
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_imports():
    from yvakor.config import load_settings
    from yvakor.memory.episodic import EpisodicMemory
    from yvakor.memory.semantic import SemanticMemory
    from yvakor.memory.procedural import SkillLibrary
    s = load_settings()
    assert s["agent"]["name"] == "YVAKOR"
    mem = EpisodicMemory(ROOT / "data" / "test.db")
    mem.log("conversa", "teste", "ok")
    assert mem.last_interactions(1)
    sem = SemanticMemory(ROOT / "data" / "semantic_test")
    sem.store("Usuário prefere relatórios em PDF")
    assert sem.search("relatórios PDF")
    lib = SkillLibrary(ROOT / "skills_library")
    assert lib.find_relevant("relatório pdf para P&G")
    print("✅ smoke test ok")


if __name__ == "__main__":
    test_imports()
