"""YVAKOR — STT multi-idioma (um modelo Vosk por idioma, baixado sob demanda)."""
from __future__ import annotations

from yvakor.voz.stt import STT

MODELOS = {
    "pt-BR": "vosk-model-small-pt-0.3",
    "es-ES": "vosk-model-small-es-0.42",
}


class STTMulti:
    def __init__(self, settings: dict):
        cfg = (settings or {}).get("voz", {}) or {}
        self.cfg = cfg
        self.padrao = cfg.get("idioma") or "pt-BR"
        self.modelos = dict(MODELOS)
        self.modelos.update(cfg.get("modelos") or {})
        self._instancias: dict[str, STT] = {}

    def _inst(self, idioma: str | None = None) -> STT:
        from yvakor.voz.idiomas import normalizar_idioma
        lang = normalizar_idioma(idioma or self.padrao, self.padrao)
        inst = self._instancias.get(lang)
        if inst is None:
            cfg = dict(self.cfg)
            cfg["idioma"] = lang
            cfg["modelo_vosk"] = self.modelos.get(lang, cfg.get("modelo_vosk"))
            inst = STT({"voz": cfg})
            self._instancias[lang] = inst
        return inst

    # interface compatível com STT
    def _carregar(self, idioma: str | None = None):
        return self._inst(idioma)._carregar()

    def ouvir(self, segundos=None, on_partial=None, idioma=None):
        return self._inst(idioma).ouvir(segundos, on_partial=on_partial)

    def transcrever_arquivo(self, caminho: str, idioma: str | None = None):
        return self._inst(idioma).transcrever_arquivo(caminho)

    def modelo_baixado(self, idioma: str | None = None) -> bool:
        return self._inst(idioma).modelo_baixado()

    def baixar_modelo(self, forcar: bool = False, idioma: str | None = None):
        return self._inst(idioma).baixar_modelo(forcar=forcar)

    def microfone_disponivel(self) -> bool:
        return self._inst(self.padrao).microfone_disponivel()

    def testar_microfone(self, segundos: float = 1.5):
        return self._inst(self.padrao).testar_microfone(segundos)

    def status(self) -> dict:
        base = self._inst(self.padrao).status()
        base["idiomas"] = [{"idioma": lang,
                            "modelo": self.modelos.get(lang, ""),
                            "baixado": self._inst(lang).modelo_baixado()}
                           for lang in self.modelos]
        return base
