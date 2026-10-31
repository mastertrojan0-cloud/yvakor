"""YVAKOR — notificações verbais globais (uma voz, todas as instâncias).

Qualquer módulo (monitor de rede, cowork, câmera, receitas, saúde) chama
`emitir(...)`. A notificação é registrada, aparece na API e é falada pelo
mesmo Falante do assistente — sem criar uma segunda voz.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
ARQUIVO = ROOT / "data" / "notificacoes.jsonl"
_GLOBAL: "Notificador | None" = None
_LOCK = threading.Lock()


class Notificador:
    def __init__(self, settings: dict):
        cfg = (settings or {}).get("notificacoes", {}) or {}
        self.ativo = bool(cfg.get("ativo", True))
        self.categorias = set(cfg.get("categorias") or
                              ["rede", "tarefa", "camera", "sistema",
                               "receita", "dispositivo"])
        self.silencio = tuple(cfg.get("silencio") or ("23:00", "07:00"))
        self.intervalo = float(cfg.get("intervalo_min_s", 8))
        self.eventos = deque(maxlen=300)
        self._ultimo: dict[tuple, float] = {}
        self.tts = None
        self._lock = threading.Lock()
        configurar(self)

    def configurar_voz(self, tts) -> None:
        self.tts = tts

    def _em_silencio(self) -> bool:
        try:
            ini, fim = self.silencio
            agora = datetime.now().strftime("%H:%M")
            return ini <= agora < fim if ini < fim else (agora >= ini or agora < fim)
        except Exception:
            return False

    def emitir(self, mensagem: str, categoria: str = "sistema",
               prioridade: int = 1, falar: bool = True,
               detalhe: str = "") -> dict:
        mensagem = (mensagem or "").strip()
        if not mensagem or not self.ativo or categoria not in self.categorias:
            return {"ok": False, "ignorado": "desativado/categoria"}
        agora = time.time()
        chave = (categoria, mensagem)
        with self._lock:
            if agora - self._ultimo.get(chave, 0) < self.intervalo:
                return {"ok": True, "ignorado": "repetido"}
            self._ultimo[chave] = agora
        if self._em_silencio() and prioridade < 2:
            falar = False
        evento = {"ts": datetime.now().isoformat(timespec="seconds"),
                  "categoria": categoria, "prioridade": prioridade,
                  "mensagem": mensagem, "detalhe": detalhe,
                  "falado": bool(falar and self.tts)}
        self.eventos.append(evento)
        try:
            ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
            with ARQUIVO.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evento, ensure_ascii=False) + "\n")
        except OSError:
            pass
        if falar and self.tts is not None:
            try:
                self.tts.falar(mensagem, assincrono=True,
                               prioridade=int(prioridade))
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        return {"ok": True, **evento}

    def recentes(self, limite: int = 20) -> list[dict]:
        return list(self.eventos)[-max(1, int(limite)):]

    def status(self) -> dict:
        return {"ativo": self.ativo, "categorias": sorted(self.categorias),
                "silencio": list(self.silencio),
                "voz": self.tts is not None,
                "eventos": len(self.eventos)}


def configurar(notificador: Notificador) -> None:
    global _GLOBAL
    _GLOBAL = notificador


def emitir(mensagem: str, categoria: str = "sistema",
           prioridade: int = 1, falar: bool = True,
           detalhe: str = "") -> dict:
    n = _GLOBAL
    if n is None:
        return {"ok": False, "erro": "notificador não inicializado"}
    return n.emitir(mensagem, categoria, prioridade, falar, detalhe)


def register_notificacoes_tools(registry, notificador: Notificador) -> list[str]:
    def notificar(mensagem: str, categoria: str = "sistema",
                  prioridade: int = 1) -> dict:
        return notificador.emitir(mensagem, categoria, int(prioridade))

    def notificacoes_status() -> dict:
        return notificador.status()

    registry.register("notificar", notificar,
                      "Envia uma notificação verbal/registrada.", 
                      {"mensagem": "str", "categoria": "str?",
                       "prioridade": "int?"})
    registry.register("notificacoes_status", notificacoes_status,
                      "Estado do sistema de notificações.", {})
    return ["notificar", "notificacoes_status"]
