"""
YVAKOR — Fala para texto (STT local, offline depois do download)

Motor: Vosk (Kaldi) — roda em CPU, sem nuvem, sem chave de API.
Modelo pequeno pt-BR (~31 MB) baixado uma vez em data/vosk/.

Duas portas de entrada:
  • ouvir()            — microfone (VAD simples: para no silêncio)
  • transcrever_arquivo() — qualquer WAV/MP3/OGG (converte com ffmpeg se preciso)

Sem microfone na máquina, `ouvir()` devolve erro explicando as alternativas
(transcrever arquivo ou usar o microfone do navegador na interface).
"""
from __future__ import annotations

import json
import math
import queue
import shutil
import subprocess
from yvakor import proc as _ywproc
import sys
import time
import urllib.request
import wave
import zipfile
from array import array
from pathlib import Path
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
URL_MODELO = "https://alphacephei.com/vosk/models/{}.zip"


class VozIndisponivel(RuntimeError):
    pass


class STT:
    def __init__(self, settings: dict):
        cfg = (settings or {}).get("voz", {}) or {}
        self.cfg = cfg
        self.idioma = cfg.get("idioma", "pt-BR")
        self.nome_modelo = cfg.get("modelo_vosk", "vosk-model-small-pt-0.3")
        self.dir_modelos = ROOT / (cfg.get("modelo_dir") or "data/vosk")
        self.dir_audio = ROOT / "data" / "voz"
        self.escuta_segundos = float(cfg.get("escuta_segundos", 7))
        self.dispositivo_entrada = cfg.get("dispositivo_entrada")
        self.silencio_rms = float(cfg.get("silencio_rms", 0.012))
        self.silencio_fim_ms = int(cfg.get("silencio_fim_ms", 900))
        self._modelo = None
        self._vosk_ok = True

    # ------------------------------------------------------------------ #
    # Modelo
    # ------------------------------------------------------------------ #
    @property
    def caminho_modelo(self) -> Path:
        return self.dir_modelos / self.nome_modelo

    def modelo_baixado(self) -> bool:
        return self.caminho_modelo.is_dir() and any(self.caminho_modelo.iterdir())

    def baixar_modelo(self, forcar: bool = False) -> dict:
        if self.modelo_baixado() and not forcar:
            return {"ok": True, "caminho": str(self.caminho_modelo),
                    "ja_baixado": True}
        if not self._vosk_ok:
            return {"ok": False, "erro": "vosk não instalado (pip install vosk)"}
        self.dir_modelos.mkdir(parents=True, exist_ok=True)
        destino_zip = self.dir_modelos / f"{self.nome_modelo}.zip"
        url = URL_MODELO.format(self.nome_modelo)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "YVAKOR/2.0"})
            with urllib.request.urlopen(req, timeout=300) as r, \
                    destino_zip.open("wb") as f:
                shutil.copyfileobj(r, f)
            with zipfile.ZipFile(destino_zip) as z:
                z.extractall(self.dir_modelos)
            destino_zip.unlink(missing_ok=True)
            if not self.modelo_baixado():
                return {"ok": False, "erro": "zip extraído sem a pasta do modelo"}
            return {"ok": True, "caminho": str(self.caminho_modelo),
                    "ja_baixado": False}
        except Exception as exc:
            return {"ok": False, "erro": f"falha ao baixar modelo: {exc}"}

    def _carregar(self):
        if self._modelo is not None:
            return self._modelo
        try:
            from vosk import Model, SetLogLevel
        except ImportError as exc:
            self._vosk_ok = False
            raise VozIndisponivel(
                "Vosk não instalado. Rode: pip install vosk") from exc
        if not self.modelo_baixado():
            r = self.baixar_modelo()
            if not r.get("ok"):
                raise VozIndisponivel(f"modelo de voz indisponível: {r.get('erro')}")
        SetLogLevel(-1)
        self._modelo = Model(str(self.caminho_modelo))
        return self._modelo

    # ------------------------------------------------------------------ #
    # Áudio: utilidades
    # ------------------------------------------------------------------ #
    @staticmethod
    def _ffmpeg() -> str | None:
        return shutil.which("ffmpeg")

    def _para_wav16k(self, origem: Path) -> Path:
        """Converte qualquer áudio para WAV 16 kHz mono PCM16."""
        destino = self.dir_audio / (origem.stem + "_16k.wav")
        self.dir_audio.mkdir(parents=True, exist_ok=True)
        ff = self._ffmpeg()
        if not ff:
            raise VozIndisponivel("ffmpeg não encontrado para converter o áudio")
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(origem), "-ar", "16000", "-ac", "1",
               "-c:a", "pcm_s16le", str(destino)]
        p = _ywproc.run(cmd, capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
        if not destino.exists():
            raise VozIndisponivel(f"falha ao converter áudio: {p.stderr[:200]}")
        return destino

    @staticmethod
    def _rms(bloco: bytes) -> float:
        if not bloco:
            return 0.0
        amostras = array("h")
        amostras.frombytes(bloco[: len(bloco) // 2 * 2])
        if not amostras:
            return 0.0
        soma = sum(a * a for a in amostras) / len(amostras)
        return math.sqrt(soma) / 32768.0

    # ------------------------------------------------------------------ #
    # Transcrição
    # ------------------------------------------------------------------ #
    def transcrever_wav(self, caminho: Path) -> str:
        from vosk import KaldiRecognizer
        modelo = self._carregar()
        with wave.open(str(caminho), "rb") as w:
            if (w.getframerate() != 16000 or w.getnchannels() != 1
                    or w.getsampwidth() != 2):
                caminho = self._para_wav16k(caminho)
                w.close()
                return self.transcrever_wav(caminho)
            rec = KaldiRecognizer(modelo, w.getframerate())
            rec.SetWords(False)
            partes: list[str] = []
            while True:
                dados = w.readframes(4000)
                if not dados:
                    break
                if rec.AcceptWaveform(dados):
                    partes.append(json.loads(rec.Result()).get("text", ""))
            partes.append(json.loads(rec.FinalResult()).get("text", ""))
        return " ".join(p for p in partes if p).strip()

    def transcrever_arquivo(self, caminho: str) -> dict:
        origem = Path(caminho).expanduser()
        if not origem.is_file():
            return {"ok": False, "erro": f"arquivo não encontrado: {caminho}"}
        try:
            wav = origem if origem.suffix.lower() == ".wav" else self._para_wav16k(origem)
            texto = self.transcrever_wav(wav)
            return {"ok": True, "texto": texto, "arquivo": str(origem.resolve()),
                    "idioma": self.idioma}
        except Exception as exc:
            return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------ #
    # Microfone
    # ------------------------------------------------------------------ #
    def microfone_disponivel(self) -> bool:
        try:
            import sounddevice as sd
            return any(d["max_input_channels"] > 0 for d in sd.query_devices())
        except Exception:
            return False

    def testar_microfone(self, segundos: float = 1.5) -> dict:
        """Testa captura em subprocesso; nunca trava o agente."""
        dev = repr(self.dispositivo_entrada)
        codigo = (
            "import sounddevice as sd, numpy as np\n"
            f"r=sd.rec(int({segundos}*16000),samplerate=16000,channels=1,"
            f"dtype='int16',device={dev})\n"
            "sd.wait()\n"
            "a=np.frombuffer(r.tobytes(),dtype=np.int16).astype(np.float32)\n"
            "print('RMS', round(float(np.sqrt((a*a).mean())),2))\n")
        try:
            p = _ywproc.run([sys.executable, "-c", codigo],
                               capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired:
            return {"ok": False, "dispositivo": self.dispositivo_entrada,
                    "erro": "o microfone abriu mas não respondeu (travou)"}
        if p.returncode != 0:
            return {"ok": False, "dispositivo": self.dispositivo_entrada,
                    "erro": (p.stderr or "falha ao abrir microfone")[-300:]}
        try:
            rms = float((p.stdout or "RMS 0").split()[-1])
        except Exception:
            rms = 0.0
        return {"ok": True, "dispositivo": self.dispositivo_entrada,
                "rms": rms, "sinal": rms > 0.5,
                "aviso": "" if rms > 0.5 else "microfone abre, mas sem sinal"}

    def ouvir(self, segundos: float | None = None, on_partial=None) -> dict:
        """Escuta o microfone até o silêncio e devolve o texto."""
        limite = float(segundos or self.escuta_segundos)
        if not self.microfone_disponivel():
            return {"ok": False,
                    "erro": "nenhum microfone detectado nesta máquina",
                    "alternativas": [
                        "voz_transcrever(arquivo) para transcrever um áudio",
                        "use o botão de microfone na interface (o navegador "
                        "capta o áudio do dispositivo onde ela está aberta)"]}
        teste = self.testar_microfone()
        if not teste.get("ok"):
            return {"ok": False, "erro": teste.get("erro"),
                    "microfone": teste,
                    "alternativas": [
                        "conecte/ative um microfone (headset ou entrada do PC)",
                        "use o microfone do celular pela interface via Tailscale"]}
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer
            modelo = self._carregar()
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}

        self.dir_audio.mkdir(parents=True, exist_ok=True)
        destino = self.dir_audio / f"escuta_{time.strftime('%Y%m%d_%H%M%S')}.wav"
        fila: queue.Queue = queue.Queue()
        blocos: list[bytes] = []
        rec = KaldiRecognizer(modelo, 16000)
        partes: list[str] = []

        def callback(indata, frames, tempo, status):
            fila.put(bytes(indata))

        inicio = time.time()
        silencio_desde = None
        falou = False
        try:
            with sd.RawInputStream(samplerate=16000, blocksize=4000,
                                   dtype="int16", channels=1,
                                   device=self.dispositivo_entrada,
                                   callback=callback):
                while True:
                    bloco = fila.get(timeout=limite + 2)
                    blocos.append(bloco)
                    if rec.AcceptWaveform(bloco):
                        partes.append(json.loads(rec.Result()).get("text", ""))
                    elif on_partial is not None:
                        try:
                            parcial = json.loads(rec.PartialResult()).get("partial", "")
                            if parcial:
                                on_partial(parcial)
                        except Exception:
                            _log.debug("exceção ignorada", exc_info=True)
                    nivel = self._rms(bloco)
                    if nivel >= self.silencio_rms:
                        falou = True
                        silencio_desde = None
                    else:
                        silencio_desde = silencio_desde or time.time()
                        ja_silencioso = (time.time() - silencio_desde) * 1000
                        if falou and ja_silencioso >= self.silencio_fim_ms:
                            break
                    if time.time() - inicio >= limite:
                        break
        except Exception as exc:
            return {"ok": False, "erro": f"falha ao captar áudio: {exc}"}

        partes.append(json.loads(rec.FinalResult()).get("text", ""))
        texto = " ".join(p for p in partes if p).strip()
        if blocos:
            with wave.open(str(destino), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"".join(blocos))
        return {"ok": True, "texto": texto, "segundos": round(time.time() - inicio, 1),
                "arquivo": str(destino.resolve()) if blocos else None}

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        try:
            import vosk  # noqa: F401
            vosk_ok = True
        except Exception:
            vosk_ok = False
        return {
            "ok": True,
            "motor": "vosk",
            "instalado": vosk_ok,
            "modelo": self.nome_modelo,
            "modelo_baixado": self.modelo_baixado(),
            "caminho_modelo": str(self.caminho_modelo),
            "microfone": self.microfone_disponivel(),
            "idioma": self.idioma,
            "ffmpeg": bool(self._ffmpeg()),
        }
