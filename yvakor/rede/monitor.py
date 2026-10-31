"""YVAKOR — monitoramento contínuo da rede (thread de fundo)."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
EVENTOS = ROOT / "data" / "rede_monitor.jsonl"


class MonitorRede:
    def __init__(self, rede, settings: dict):
        cfg = (settings or {}).get("rede", {}) or {}
        self.rede = rede
        self.intervalo = max(30, int(cfg.get("intervalo_monitor_s", 180)))
        self.auto_gerenciar = bool(cfg.get("auto_gerenciar", True))
        self.ativo = False
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._anteriores: set[str] | None = None
        self.eventos = deque(maxlen=200)
        self.aprendiz = None
        self.ultima: dict = {}
        self.proxima = 0.0

    def iniciar(self) -> dict:
        if self._thread and self._thread.is_alive():
            return self.status()
        self.ativo = True
        self._parar.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="yvakor-rede-monitor")
        self._thread.start()
        return self.status()

    def parar(self) -> dict:
        self.ativo = False
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        return self.status()

    def _loop(self) -> None:
        while self.ativo:
            try:
                inicio = time.time()
                devs = self.rede.descobridor.escanear()
                atuais = {d.get("ip") for d in devs if d.get("ip")}
                with self._lock:
                    self.ultima = {
                        "em": datetime.now().isoformat(timespec="seconds"),
                        "total": len(devs),
                        "duracao_s": round(time.time() - inicio, 1),
                    }
                    if self._anteriores is not None:
                        for ip in atuais - self._anteriores:
                            dev = next((d for d in devs if d.get("ip") == ip), {})
                            self._evento("entrou", ip, dev)
                        for ip in self._anteriores - atuais:
                            self._evento("saiu", ip, {})
                    self._anteriores = atuais
                if self.auto_gerenciar:
                    try:
                        from yvakor.rede.gerente import organizar
                        self.ultima["gerente"] = organizar(self.rede)
                    except Exception:
                        _log.debug("exceção ignorada", exc_info=True)
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            self.proxima = time.time() + self.intervalo
            if self._parar.wait(self.intervalo):
                break

    def _aprender(self, dev: dict) -> None:
        try:
            if self.aprendiz is not None:
                self.aprendiz(dev)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

    def _evento(self, tipo: str, ip: str, dev: dict) -> None:
        ev = {"ts": datetime.now().isoformat(timespec="seconds"),
              "tipo": tipo, "ip": ip, "nome": dev.get("nome") or "",
              "tipo_dispositivo": dev.get("tipo") or ""}
        self.eventos.append(ev)
        try:
            from yvakor.notificacoes import emitir as _notificar
            if tipo == "entrou":
                _notificar(f"Novo dispositivo na rede: {dev.get('nome') or ip} ({ip})",
                           "rede", 1)
            elif tipo == "saiu":
                _notificar(f"Dispositivo saiu da rede: {ip}", "rede", 1)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        if tipo == "entrou" and self.aprendiz is not None:
            threading.Thread(target=self._aprender, args=(dev,),
                             daemon=True).start()
        try:
            EVENTOS.parent.mkdir(parents=True, exist_ok=True)
            with EVENTOS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def status(self) -> dict:
        return {"ativo": bool(self._thread and self._thread.is_alive()),
                "intervalo_s": self.intervalo,
                "ultima": self.ultima,
                "proxima_em_s": max(0, round(self.proxima - time.time())),
                "eventos": list(self.eventos)[-20:]}
