"""
YVAKOR — Falante (fila única de áudio)

Um único worker reproduz tudo, em ordem, para nunca haver duas vozes ao mesmo
tempo (narração + resposta). Prioridade maior toca primeiro; a resposta (2)
descarta narrações pendentes (1). Textos repetidos em 8 s são ignorados.
"""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
import logging

_log = logging.getLogger(__name__)


class Falante:
    def __init__(self, gerar, tocar):
        self.gerar = gerar          # (texto) -> {"ok", "arquivo"}
        self.tocar = tocar          # (Path) -> bool
        self._fila: queue.PriorityQueue = queue.PriorityQueue()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._seq = 0
        self._recentes: dict[str, float] = {}
        self.ultimo_erro = ""
        self._epoca = 0             # muda a cada interromper(): descarta o que já estava saindo

    def _garantir_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name="yvakor-falante")
        self._thread.start()

    def falar(self, texto: str, prioridade: int = 1, **kwargs) -> dict:
        texto = (texto or "").strip()
        if not texto:
            return {"ok": False, "erro": "texto vazio"}
        agora = time.time()
        with self._lock:
            if agora - self._recentes.get(texto, 0) < 8:
                return {"ok": True, "ignorado": "repetido"}
            self._recentes[texto] = agora   # dedupe também na fila
            if prioridade >= 2:
                self.cancelar_abaixo(prioridade)  # resposta preempta narração
            self._seq += 1
            self._fila.put((-int(prioridade), self._seq, texto, kwargs))
        self._garantir_thread()
        return {"ok": True, "agendado": True, "prioridade": prioridade}

    def cancelar_abaixo(self, prioridade: int) -> int:
        """Descarta itens pendentes com prioridade menor (ex.: narrações)."""
        mantidos, removidos = [], 0
        with self._lock:
            while True:
                try:
                    item = self._fila.get_nowait()
                except queue.Empty:
                    break
                if -item[0] < prioridade:
                    removidos += 1
                else:
                    mantidos.append(item)
            for item in mantidos:
                self._fila.put(item)
        return removidos

    def interromper(self) -> int:
        """Pausa/parar: esvazia a fila e descarta o que estava sendo gerado."""
        with self._lock:
            self._epoca += 1
            return self.cancelar_abaixo(99)

    def _worker(self):
        while True:
            item = self._fila.get()
            if item is None:
                break
            _, _, texto, kwargs = item
            epoca = self._epoca
            try:
                r = self.gerar(texto, **(kwargs or {}))
                # parar() durante a geração (edge-tts leva 1–3 s): não toca
                if epoca != self._epoca:
                    continue
                if r.get("ok") and r.get("arquivo"):
                    self.tocar(Path(r["arquivo"]))
                    self._recentes[texto] = time.time()
                else:
                    self.ultimo_erro = r.get("erro", "")
            except Exception as exc:
                self.ultimo_erro = str(exc)

    def estado(self) -> dict:
        return {"fila": self._fila.qsize(),
                "ativa": bool(self._thread and self._thread.is_alive()),
                "recentes": len(self._recentes)}

    def parar(self) -> None:
        try:
            self._fila.put(None)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
