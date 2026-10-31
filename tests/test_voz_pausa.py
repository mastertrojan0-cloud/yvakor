"""Pausar a voz: interrompe a fala em andamento e silencia o servidor (30/10)."""
import json
import sys
import threading
import time
import wave

import pytest

from yvakor.voz import tts as tts_mod
from yvakor.voz.falante import Falante
from yvakor.voz.sessao import pediu_calar


def _wav_silencio(caminho, segundos=3.0):
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * segundos))
    return caminho


@pytest.fixture
def tts(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_mod, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    return tts_mod.TTS({"voz": {}})


def test_voz_desligada_nao_fala(tts, tmp_path):
    prefs = tmp_path / "data" / "preferencias.json"
    prefs.write_text(json.dumps({"voz_ativa": False}), encoding="utf-8")
    gerou = []
    tts.gerar = lambda *a, **k: gerou.append(a) or {"ok": True, "arquivo": "x.wav"}
    r = tts.falar("olá")
    assert r["pausada"] and not r["falou"] and gerou == []
    prefs.write_text(json.dumps({"voz_ativa": True}), encoding="utf-8")
    time.sleep(0.05)
    import os
    os.utime(prefs, None)                 # mtime novo: relê a preferência
    assert not tts.pausada()


@pytest.mark.skipif(sys.platform != "win32", reason="winsound só no Windows")
def test_parar_interrompe_a_fala_em_andamento(tts, tmp_path):
    """Antes a reprodução era síncrona e ia até o fim mesmo pausando."""
    arq = _wav_silencio(tmp_path / "fala.wav", 3.0)
    resultado = {}

    def tocar():
        t0 = time.time()
        resultado["fim"] = tts._tocar_arquivo(arq)
        resultado["s"] = time.time() - t0

    th = threading.Thread(target=tocar)
    th.start()
    time.sleep(0.4)
    tts.parar()
    th.join(timeout=3)
    assert resultado["fim"] is False and resultado["s"] < 1.2


def test_parar_durante_a_geracao_nao_toca():
    tocou, gerando = [], threading.Event()

    def gerar(texto, **k):
        gerando.set()
        time.sleep(0.3)                   # edge-tts levando 1–3 s
        return {"ok": True, "arquivo": "x.wav"}

    f = Falante(gerar, lambda p: tocou.append(p) or True)
    f.falar("uma resposta longa", prioridade=2)
    gerando.wait(2)
    f.interromper()
    time.sleep(0.6)
    assert tocou == []


def test_comando_de_voz_para_calar():
    for frase in ("para", "Pare!", "silêncio", "yvakor, chega", "para de falar",
                  "fica quieto"):
        assert pediu_calar(frase), frase
    for frase in ("para onde vai o voo?", "pare o vídeo da câmera", "chega de chuva hoje?"):
        assert not pediu_calar(frase), frase
