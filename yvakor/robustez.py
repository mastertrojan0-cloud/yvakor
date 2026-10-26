"""YVAKOR — antibug/anticrash: captura global de falhas e relatórios."""
from __future__ import annotations

import faulthandler
import json
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "data" / "logs"
FALHAS = LOGS / "falhas.jsonl"
_arquivo = None
_original_sys = sys.excepthook
_original_thread = threading.excepthook


def _gravar(tipo: str, exc_type, exc, tb) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    texto = "".join(traceback.format_exception(exc_type, exc, tb))
    with (LOGS / "crash.log").open("a", encoding="utf-8") as f:
        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {tipo}\n{texto}")
    try:
        with FALHAS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "tipo": tipo, "erro": str(exc)[:500],
                                "trace": texto[-2000:]},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
    try:
        from yvakor.notificacoes import emitir
        emitir(f"Falha interna registrada ({tipo}): {str(exc)[:120]}",
               "sistema", 2)
    except Exception:
        pass


def _hook_sys(exc_type, exc, tb):
    _gravar("sistema", exc_type, exc, tb)
    _original_sys(exc_type, exc, tb)


def _hook_thread(args):
    _gravar(f"thread:{getattr(args.thread, 'name', '?')}",
            args.exc_type, args.exc_value, args.exc_traceback)
    _original_thread(args)


def instalar() -> None:
    global _arquivo
    LOGS.mkdir(parents=True, exist_ok=True)
    if _arquivo is None:
        _arquivo = (LOGS / "faulthandler.log").open("a", buffering=1)
        faulthandler.enable(_arquivo)
    sys.excepthook = _hook_sys
    threading.excepthook = _hook_thread
