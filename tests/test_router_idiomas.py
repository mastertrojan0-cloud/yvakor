"""Teste do roteador de ferramentas + voz pt/es."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_roteador():
    from yvakor.tools.router import selecionar

    class Reg:
        tools = {n: None for n in (
            "navegador_abrir", "navegador_ver", "navegador_clicar",
            "arquivos_listar", "arquivos_escrever", "arquivos_ler",
            "rede_camera_snapshot", "rede_tv", "cerebro_buscar",
            "executar_shell", "voz_falar")}
        specs = {n: {"desc": "", "args": {}} for n in tools}

    web = selecionar(Reg(), "abra o site do banco e clique em entrar")
    assert "navegador_abrir" in web and "rede_camera_snapshot" not in web, web
    arq = selecionar(Reg(), "liste os arquivos da pasta e edite o relatorio")
    assert "arquivos_listar" in arq and "navegador_abrir" not in arq, arq
    assert "executar_shell" in arq, "núcleo deve estar sempre presente"
    assert len(web) <= 14
    print(f"  ✅ roteador — web={len(web)} ferramentas, arquivos={len(arq)}")


def test_deteccao():
    from yvakor.voz.idiomas import detectar
    assert detectar("hola, ¿cómo estás? abre la puerta") == "es-ES"
    assert detectar("olá, como você está? abra a porta") == "pt-BR"
    assert detectar("gracias por la ayuda") == "es-ES"
    assert detectar("obrigado pela ajuda") == "pt-BR"
    print("  ✅ detecção — espanhol e português")


_AUDIO = None


def test_tts_es():
    global _AUDIO
    from yvakor.config import load_settings
    from yvakor.voz.tts import TTS
    t = TTS(load_settings())
    r = t.gerar("Hola, ¿cómo estás? Esto es una prueba.", idioma="es-ES")
    if not r.get("ok"):
        print(f"  [skip] TTS es indisponível: {r.get('erro')}")
        return
    assert Path(r["arquivo"]).stat().st_size > 1000
    assert "Elvira" in r.get("voz", ""), r
    r2 = t.gerar("Hola, ¿cómo estás? Esto es una prueba.", idioma="es-ES")
    assert r2.get("cache") is True, r2
    print(f"  ✅ TTS espanhol — {r['voz']} ({Path(r['arquivo']).stat().st_size} bytes)")
    _AUDIO = r["arquivo"]


def test_stt_es():
    arquivo = _AUDIO
    if not arquivo:
        print("  [skip] STT es sem áudio de teste")
        return
    from yvakor.config import load_settings
    from yvakor.voz.stt_multi import STTMulti
    stt = STTMulti(load_settings())
    r = stt.transcrever_arquivo(arquivo, idioma="es-ES")
    if not r.get("ok"):
        print(f"  [skip] STT es: {r.get('erro')}")
        return
    texto = r["texto"].lower()
    assert any(p in texto for p in ("hola", "como", "estas", "prueba")), texto
    print(f"  ✅ STT espanhol — “{r['texto'][:70]}”")


if __name__ == "__main__":
    test_roteador()
    test_deteccao()
    test_tts_es()
    test_stt_es()
