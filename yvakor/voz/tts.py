"""
YVAKOR — Texto para fala (TTS)

Dois motores:
  • edge-tts  — voz masculina pt-BR-AntonioNeural (amigável/profissional)
  • SAPI      — vozes do Windows (masculina quando disponível), offline

`falar()` escolhe automaticamente: tenta edge (qualidade), cai para SAPI se
falhar ou se o usuário pedir offline.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import threading
import wave
from yvakor import proc as _ywproc
import time
from pathlib import Path
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent


# Perfil "assinatura": voz masculina grave, calma e presente (estilo locutor).
PERFIL_ASSINATURA = {"tom": "-12Hz", "taxa": "-5%"}
# Calor nos graves, um respiro a menos nos agudos, compressão leve (voz "cheia")
# e nível constante entre falas.
FILTRO_ASSINATURA = (
    "highpass=f=70,"
    "equalizer=f=130:t=q:w=1.0:g=3.5,"
    "equalizer=f=280:t=q:w=1.2:g=1.5,"
    "equalizer=f=4200:t=q:w=1.5:g=-2,"
    "acompressor=threshold=0.125:ratio=3:attack=6:release=90:makeup=1.6,"
    "loudnorm=I=-16:TP=-1.5:LRA=9,"
    "aresample=24000"           # o loudnorm sobe para 192 kHz: volta ao nativo da voz
)


class TTS:
    def __init__(self, settings: dict):
        cfg = (settings or {}).get("voz", {}) or {}
        self.cfg = cfg
        self.motor_pref = str(cfg.get("tts") or "auto").lower()
        self.voz_edge = cfg.get("voz_edge") or "pt-BR-AntonioNeural"
        self.voz_sapi = cfg.get("voz_sapi") or ""
        self.idioma_padrao = cfg.get("idioma") or "pt-BR"
        self.vozes_idioma = cfg.get("vozes") or {
            "pt-BR": self.voz_edge, "es-ES": "es-ES-AlvaroNeural"}
        self.velocidade = int(cfg.get("velocidade") or 0)
        self.tom = str(cfg.get("tom") or PERFIL_ASSINATURA["tom"])
        # Voz de assinatura do YVAKOR: o Antonio (único pt-BR masculino neural)
        # mais grave e pausado + acabamento de estúdio. `taxa` e `efeito` mandam
        # nas configurações; "nenhum" devolve a voz crua.
        self.taxa = str(cfg.get("taxa") or "")
        self.efeito = str(cfg.get("efeito") or "assinatura").lower()
        self.dir = ROOT / "data" / "voz"
        self.cache_dir = self.dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_hits = 0
        self._cache_miss = 0
        # Pausar precisa interromper a fala JÁ começada: a reprodução síncrona
        # (PlaySound sem SND_ASYNC) não parava com SND_PURGE e ia até o fim.
        self._parar_evento = threading.Event()
        self._ffplay = None
        self._pref_cache: tuple[float, bool] = (0.0, True)

    # ------------------------------------------------------------------ #
    # Pausa (botão 🔇 VOZ do app → preferencias.json "voz_ativa")
    # ------------------------------------------------------------------ #
    def pausada(self) -> bool:
        """True se o usuário desligou a voz. Vale para TODA fala do servidor
        (respostas, narração de tarefa, avisos), não só a do app."""
        arq = ROOT / "data" / "preferencias.json"
        try:
            mtime = arq.stat().st_mtime
        except OSError:
            return False
        if mtime != self._pref_cache[0]:
            try:
                ativa = bool(json.loads(arq.read_text(encoding="utf-8")).get("voz_ativa", True))
            except (OSError, ValueError):
                ativa = True
            self._pref_cache = (mtime, ativa)
        return not self._pref_cache[1]
        self.ultimo_erro = ""

    def _voz_para(self, idioma: str | None) -> str:
        from yvakor.voz.idiomas import normalizar_idioma
        lang = normalizar_idioma(idioma or self.idioma_padrao, self.idioma_padrao)
        return self.vozes_idioma.get(lang) or self.voz_edge

    def _cache_path(self, texto: str, motor: str, voz: str = "") -> Path:
        chave = (f"{motor}|{voz or self.voz_edge}|{self.voz_sapi}|"
                 f"{self.velocidade}|{self.tom}|{self.taxa}|{self.efeito}|{texto}")
        h = hashlib.sha1(chave.encode("utf-8")).hexdigest()[:20]
        return self.cache_dir / f"{h}.wav"

    @staticmethod
    def _naturalizar(texto: str) -> str:
        """Remove ruído visual para a fala soar humana, não robótica."""
        import re
        t = str(texto or "")
        t = re.sub(r"```.*?```", " ", t, flags=re.S).replace("```", " ")
        t = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", t)
        t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
        t = re.sub(r"https?://\S+", " ", t)
        t = re.sub(r"[*_#`>|~]", " ", t)
        t = re.sub(r"\b(?:vc|vcs|pq|q|td|hj|amnh|blz)\b",
                   lambda m: {"vc": "você", "vcs": "vocês", "pq": "porque",
                              "q": "que", "td": "tudo", "hj": "hoje",
                              "amnh": "amanhã", "blz": "beleza"}[m.group(0).lower()],
                   t, flags=re.I)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #
    @staticmethod
    def _ffmpeg() -> str | None:
        return shutil.which("ffmpeg")

    @staticmethod
    def _duracao_wav(caminho: Path) -> float:
        try:
            with wave.open(str(caminho), "rb") as w:
                return w.getnframes() / float(w.getframerate() or 1)
        except (wave.Error, OSError, EOFError):
            return 120.0

    def _tocar_arquivo(self, caminho: Path) -> bool:
        """Toca e devolve True se foi até o fim; False se parar() interrompeu."""
        if not caminho.exists():
            return False
        self._parar_evento.clear()
        try:
            import winsound
            winsound.PlaySound(str(caminho), winsound.SND_FILENAME
                               | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            fim = time.time() + self._duracao_wav(caminho) + 0.3
            while time.time() < fim:
                if self._parar_evento.wait(0.1):
                    winsound.PlaySound(None, winsound.SND_PURGE)
                    return False
            return True
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        # Fallback: ffplay (processo que parar() mata)
        ffplay = shutil.which("ffplay")
        if ffplay:
            try:
                self._ffplay = _ywproc.popen([ffplay, "-nodisp", "-autoexit", "-loglevel",
                                              "quiet", str(caminho)])
                fim = time.time() + 120
                while self._ffplay.poll() is None and time.time() < fim:
                    if self._parar_evento.wait(0.1):
                        self._ffplay.kill()
                        return False
                return True
            except Exception:
                return False
            finally:
                self._ffplay = None
        return False

    # ------------------------------------------------------------------ #
    # SAPI (Windows, offline)
    # ------------------------------------------------------------------ #
    def _sapi_wav(self, texto: str, idioma: str = "pt-BR") -> Path | None:
        self.dir.mkdir(parents=True, exist_ok=True)
        txt = self.dir / "_fala.txt"
        txt.write_text(texto, encoding="utf-8")
        destino = self.dir / f"fala_sapi_{time.strftime('%Y%m%d_%H%M%S')}.wav"
        voz = self.voz_sapi
        cultura = "es" if str(idioma).lower().startswith("es") else "pt"
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            + (f"$s.SelectVoice('{voz}');" if voz else
               f"$vs = $s.GetInstalledVoices();"
               f"$v = $vs | Where-Object {{"
               f"$_.VoiceInfo.Culture.Name -like '{cultura}-*' -and "
               f"$_.VoiceInfo.Gender -eq 'Male' }} | Select-Object -First 1;"
               f"if (-not $v) {{ $v = $vs | Where-Object {{"
               f"$_.VoiceInfo.Culture.Name -like '{cultura}-*' }} | "
               "Select-Object -First 1; }"
               "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) };")
            + f"$s.Rate = {max(-10, min(10, self.velocidade))};"
            f"$t = Get-Content -Raw -Encoding UTF8 '{txt}';"
            f"$s.SetOutputToWaveFile('{destino}');"
            "$s.Speak($t); $s.Dispose()")
        try:
            p = _ywproc.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace")
            if destino.exists() and destino.stat().st_size > 1000:
                return destino
            self.ultimo_erro = (p.stderr or "")[:300]
        except Exception as exc:
            self.ultimo_erro = str(exc)
        return None

    # ------------------------------------------------------------------ #
    # edge-tts (neural, online)
    # ------------------------------------------------------------------ #
    def _edge_mp3(self, texto: str, voz: str | None = None) -> Path | None:
        try:
            import edge_tts
        except ImportError:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        destino = self.dir / f"fala_edge_{time.strftime('%Y%m%d_%H%M%S')}.mp3"
        taxa = self.taxa or (PERFIL_ASSINATURA["taxa"] if self.efeito == "assinatura"
                             and not self.velocidade else
                             f"{'+' if self.velocidade >= 0 else ''}{self.velocidade * 10}%")

        async def gerar():
            try:
                com = edge_tts.Communicate(texto, voz or self.voz_edge,
                                           rate=taxa, pitch=self.tom)
            except TypeError:
                com = edge_tts.Communicate(texto, voz or self.voz_edge,
                                           rate=taxa)
            await com.save(str(destino))

        try:
            asyncio.run(gerar())
            if destino.exists() and destino.stat().st_size > 1000:
                return destino
        except Exception as exc:
            self.ultimo_erro = str(exc)[:200]
        return None

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    def gerar(self, texto: str, motor: str | None = None,
              idioma: str | None = None) -> dict:
        """Gera o áudio e devolve o caminho (não toca)."""
        texto = (texto or "").strip()
        if not texto:
            return {"ok": False, "erro": "texto vazio"}
        texto = self._naturalizar(texto)
        if not texto:
            return {"ok": False, "erro": "texto vazio"}
        motor = (motor or self.motor_pref).lower()
        voz = self._voz_para(idioma)
        self.ultimo_erro = ""

        cache = self._cache_path(texto, motor, voz)
        if cache.exists() and cache.stat().st_size > 1000:
            self._cache_hits += 1
            return {"ok": True, "motor": "cache", "arquivo": str(cache),
                    "voz": voz, "cache": True}

        candidatos = (["edge", "sapi"] if motor in ("auto", "edge")
                      else ["sapi"] if motor == "sapi" else ["edge", "sapi"])
        for m in candidatos:
            if m == "edge":
                mp3 = self._edge_mp3(texto, voz)
                if mp3:
                    wav = self.dir / (mp3.stem + ".wav")
                    ff = self._ffmpeg()
                    if ff:
                        try:
                            filtro = (["-af", FILTRO_ASSINATURA]
                                      if self.efeito == "assinatura" else [])
                            r = _ywproc.run([ff, "-hide_banner", "-loglevel", "error",
                                             "-y", "-i", str(mp3), *filtro, str(wav)],
                                            capture_output=True, timeout=60)
                            if filtro and (r.returncode != 0 or not wav.exists()):
                                # filtro recusado pelo ffmpeg: converte sem efeito
                                _ywproc.run([ff, "-hide_banner", "-loglevel", "error",
                                             "-y", "-i", str(mp3), str(wav)],
                                            capture_output=True, timeout=60)
                        except Exception:
                            _log.debug("exceção ignorada", exc_info=True)
                    if wav.exists():
                        self._cache_miss += 1
                        shutil.copy2(wav, cache)
                        return {"ok": True, "motor": "edge",
                                "voz": voz, "arquivo": str(cache)}
                    return {"ok": True, "motor": "edge", "voz": voz,
                            "arquivo": str(mp3.resolve())}
            else:
                wav = self._sapi_wav(texto, idioma or self.idioma_padrao)
                if wav:
                    self._cache_miss += 1
                    shutil.copy2(wav, cache)
                    return {"ok": True, "motor": "sapi", "arquivo": str(cache)}
        return {"ok": False, "erro": "nenhum motor de voz funcionou",
                "detalhe": getattr(self, "ultimo_erro", "")}

    def falar(self, texto: str, motor: str | None = None,
              tocar: bool = True, assincrono: bool = False,
              prioridade: int = 1, idioma: str | None = None) -> dict:
        if tocar and self.pausada():
            return {"ok": True, "pausada": True, "falou": False}
        if assincrono:
            # fila única: nunca duas vozes ao mesmo tempo
            if not hasattr(self, "falante"):
                from yvakor.voz.falante import Falante
                self.falante = Falante(self.gerar, self._tocar_arquivo)
            return self.falante.falar(texto, prioridade=prioridade,
                                      idioma=idioma)
        r = self.gerar(texto, motor, idioma)
        if not r.get("ok") or not tocar:
            return r
        r["tocou"] = self._tocar_arquivo(Path(r["arquivo"]))
        return r

    def parar(self) -> dict:
        """Interrompe a fala atual na hora e limpa a fila (barge-in/pausa)."""
        removidos = 0
        self._parar_evento.set()
        try:
            if hasattr(self, "falante"):
                removidos = self.falante.interromper()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        try:
            if self._ffplay is not None:
                self._ffplay.kill()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        return {"ok": True, "fila_limpa": removidos}

    def estatisticas(self) -> dict:
        arquivos = list(self.cache_dir.glob("*.wav")) if self.cache_dir.exists() else []
        return {"cache_arquivos": len(arquivos),
                "cache_mb": round(sum(f.stat().st_size for f in arquivos)
                                  / 1048576, 2),
                "hits": self._cache_hits, "miss": self._cache_miss}

    def vozes(self) -> dict:
        saida = {"sapi": [], "edge": [self.voz_edge]}
        try:
            script = ("Add-Type -AssemblyName System.Speech;"
                      "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                      ".GetInstalledVoices() | ForEach-Object { "
                      "$_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name }")
            p = _ywproc.run(["powershell", "-NoProfile", "-NonInteractive",
                                "-Command", script], capture_output=True,
                               text=True, timeout=30, encoding="utf-8",
                               errors="replace")
            for linha in (p.stdout or "").splitlines():
                if "|" in linha:
                    nome, cultura = linha.strip().split("|", 1)
                    saida["sapi"].append({"nome": nome, "cultura": cultura})
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        return saida
