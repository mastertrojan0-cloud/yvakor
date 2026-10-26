"""Teste do modo de voz com escopo de sessão + cache de TTS."""
from __future__ import annotations

import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class FakeTTS:
    def __init__(self):
        self.falas = []

    def falar(self, texto, **kw):
        self.falas.append(texto)
        return {"ok": True, "agendado": True}

    def gerar(self, texto, **kw):
        return {"ok": True, "arquivo": "x"}


class FakeSTT:
    def _carregar(self):
        pass


class FakeVoz:
    def __init__(self):
        self.tts = FakeTTS()
        self.stt = FakeSTT()


class FakeOrch:
    def __init__(self):
        self.chamadas = []

    def process(self, texto, on_event=None, **kw):
        self.chamadas.append(texto)
        if on_event:
            on_event("ferramenta", {"nome": "navegador_abrir"})
            on_event("ferramenta", {"nome": "navegador_ver"})
        return f"Feito: {texto}"


def test_sessao():
    from yvakor.voz.sessao import SessaoVoz
    voz = FakeVoz()
    orch = FakeOrch()
    s = SessaoVoz(orch, voz, {"voz": {"palavra_ativacao": "yvakor",
                                     "sessao_segundos": 45, "narrar": True}})
    s._aquecido = True

    r = s.processar("bom dia, tudo bem?")
    assert r.get("ignorado") and not orch.chamadas, r

    r = s.processar("yvakor, abra o site do banco")
    assert r["ok"] and not r.get("ignorado"), r
    assert r["resposta"].startswith("Feito:"), r
    assert s.aberta()

    # continuação sem repetir a palavra de ativação
    r2 = s.processar("agora tire uma foto da página")
    assert r2["ok"] and not r2.get("ignorado"), r2
    assert len(orch.chamadas) == 2

    # narração falada do trabalho
    assert any("Abrindo" in f for f in voz.tts.falas), voz.tts.falas
    # resposta também foi falada
    assert any("Feito:" in f for f in voz.tts.falas), voz.tts.falas

    # expirou a sessão → volta a exigir a palavra
    s.aberta_ate = time.time() - 1
    r3 = s.processar("e agora?")
    assert r3.get("ignorado"), r3

    s.acordar("yvakor")
    r4 = s.processar("feche o navegador")
    assert r4["ok"] and not r4.get("ignorado")
    s.fechar()
    assert not s.aberta()
    print("  ✅ sessão de voz — ativação, continuação, narração e expiração")


def test_cache_tts():
    from yvakor.config import load_settings
    from yvakor.voz.tts import TTS
    t = TTS(load_settings())
    a = t.gerar("Teste de cache de voz.", motor="sapi")
    if not a.get("ok"):
        print(f"  [skip] TTS indisponível: {a.get('erro')}")
        return
    b = t.gerar("Teste de cache de voz.", motor="sapi")
    assert b.get("ok") and b.get("cache") is True, b
    assert a["arquivo"] == b["arquivo"], (a, b)
    assert Path(a["arquivo"]).exists()
    est = t.estatisticas()
    assert est["cache_arquivos"] >= 1, est
    print(f"  ✅ cache de TTS — {est['cache_arquivos']} áudio(s), "
          f"segunda geração instantânea")


if __name__ == "__main__":
    test_sessao()
    test_cache_tts()
