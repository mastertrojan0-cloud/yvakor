"""Teste da voz: TTS gera áudio e o STT transcreve de volta (ponta a ponta).

Requer Windows com voz pt-BR (SAPI) e o modelo Vosk (baixado no 1º uso).

    python tests/test_voz.py
"""
from __future__ import annotations

import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_tts_stt_roundtrip() -> None:
    from yvakor.config import load_settings
    from yvakor.voz.tts import TTS
    from yvakor.voz.stt import STT

    settings = load_settings()
    tts = TTS(settings)
    frase = "Teste de reconhecimento de voz do sistema."
    r = tts.gerar(frase, motor="sapi")
    if not r.get("ok"):
        print(f"  [skip] TTS indisponível: {r.get('erro')}")
        return
    arquivo = Path(r["arquivo"])
    assert arquivo.exists() and arquivo.stat().st_size > 1000, r

    stt = STT(settings)
    if not stt.modelo_baixado():
        baixou = stt.baixar_modelo()
        if not baixou.get("ok"):
            print(f"  [skip] modelo Vosk indisponível: {baixou.get('erro')}")
            return
    tr = stt.transcrever_arquivo(str(arquivo))
    assert tr.get("ok"), tr
    texto = tr["texto"].lower()
    assert "teste" in texto or "reconhecimento" in texto, texto
    print(f"  ✅ voz — TTS gerou {arquivo.stat().st_size} bytes e o STT "
          f"transcreveu: “{tr['texto'][:70]}”")


def test_limpeza_para_fala() -> None:
    from yvakor.voz.assistente import limpar_para_fala, contem_ativacao
    t = limpar_para_fala("## Título\n**Pronto!** Veja [aqui](http://x.com).")
    assert "##" not in t and "**" not in t and "aqui" in t
    assert contem_ativacao("olá eva coruja, tudo bem?", "yvakor")
    assert contem_ativacao("yvakor abra a câmera", "yvakor")
    assert not contem_ativacao("bom dia", "yvakor")
    print("  ✅ voz — limpeza de markdown e palavra de ativação tolerante")


if __name__ == "__main__":
    test_limpeza_para_fala()
    test_tts_stt_roundtrip()
