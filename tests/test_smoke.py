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
    # v0.4 — navegador + cowork
    from yvakor.browser.session import BrowserSession
    from yvakor.browser.tools import register_browser_tools
    from yvakor.cowork import CoworkManager
    # v0.5 — rede + voz
    from yvakor.rede import Rede
    from yvakor.rede.tools import register_rede_tools
    from yvakor.voz.stt import STT
    from yvakor.voz.tts import TTS
    # v0.6 — memória otimizada + cérebro
    from yvakor.memory.db import conectar, fts_query
    from yvakor.cerebro import Cerebro
    s = load_settings()
    assert s["agent"]["name"] == "YVAKOR"
    assert "browser" in s and "cowork" in s
    assert "rede" in s and "voz" in s
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
