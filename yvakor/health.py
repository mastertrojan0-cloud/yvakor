"""YVAKOR — saúde do sistema com cache curto (para monitoramento externo)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_INICIO = time.time()
_CACHE = {"em": 0.0, "dados": {}}
_LOCK = threading.Lock()


def _db_ok(caminho: Path) -> str:
    try:
        c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=2)
        r = c.execute("PRAGMA quick_check").fetchone()[0]
        c.close()
        return r
    except Exception as exc:
        return f"erro: {exc}"


def _ollama() -> bool:
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:11434/api/tags", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def coletar(agente=None, forcar: bool = False, build: str = "") -> dict:
    agora = time.time()
    with _LOCK:
        if not forcar and _CACHE["dados"] and agora - _CACHE["em"] < 30:
            return _CACHE["dados"]

    bancos = {}
    for nome in ("cerebro.db", "cowork.db", "rede.db", "skills.db",
                 "telemetria.db", "yvakor_memory.db"):
        p = ROOT / "data" / nome
        if p.exists():
            bancos[nome] = _db_ok(p)
    sem = ROOT / "data" / "semantic" / "facts.db"
    if sem.exists():
        bancos["semantic/facts.db"] = _db_ok(sem)

    telemetria = {}
    monitor = {}
    if agente is not None:
        try:
            telemetria = agente.telemetria.resumo(7)
        except Exception:
            pass
        try:
            monitor = agente.monitor_rede.status() if agente.monitor_rede else {}
        except Exception:
            pass

    try:
        from yvakor import banco as _banco
        ciclo = _banco.estado()
    except Exception:
        ciclo = {}
    dados = {
        "banco_ultimo_ciclo": ciclo.get("quando") or ciclo.get("inicio"),
        "ok": all(v == "ok" for v in bancos.values()) if bancos else False,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "build": build or "v0.7",
        "pid": os.getpid(),
        "threads": threading.active_count(),
        "uptime_s": int(time.time() - _INICIO),
        "bancos": bancos,
        "monitor_rede": {"ativo": monitor.get("ativo", False),
                         "dispositivos": (monitor.get("ultima") or {}).get("total", 0),
                         "intervalo_s": monitor.get("intervalo_s")},
        "telemetria": {k: telemetria.get(k) for k in
                       ("total", "sem_ia", "economia_pct")},
        "provedores": {
            "deepseek_configurado": bool(os.getenv("DEEPSEEK_API_KEY")),
            "ollama": _ollama(),
        },
    }
    with _LOCK:
        _CACHE["em"], _CACHE["dados"] = agora, dados
    return dados
