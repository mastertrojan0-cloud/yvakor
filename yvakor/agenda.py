"""YVAKOR — agenda e tarefas agendadas (lembretes/automações)."""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from yvakor import seguro
from yvakor.config import ROOT

ARQUIVO = ROOT / "data" / "agenda.json"


def _agora() -> datetime:
    return datetime.now()


def parse_quando(texto: str) -> datetime:
    """Aceita ISO, HH:MM, 'hoje 18:30', 'amanhã 09:00'."""
    t = (texto or "").strip().lower()
    agora = _agora()
    if not t:
        return agora + timedelta(hours=1)
    try:
        return datetime.fromisoformat(texto)
    except Exception:
        pass
    base = agora
    if "amanha" in t or "amanhã" in t:
        base = agora + timedelta(days=1)
        t = t.replace("amanha", "").replace("amanhã", "").strip()
    elif "hoje" in t:
        base = agora
        t = t.replace("hoje", "").strip()
    import re
    m = re.search(r"(\d{1,2})[:h](\d{2})", t)
    if m:
        return base.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                            second=0, microsecond=0)
    return agora + timedelta(hours=1)


class Agenda:
    def __init__(self, orquestrador, caminho: Path | None = None):
        self.orch = orquestrador
        self.path = Path(caminho or ARQUIVO)
        self._lock = threading.RLock()
        self.tarefas: list[dict] = []
        self._vivo = True
        self._carregar()
        threading.Thread(target=self._loop, daemon=True,
                         name="yvakor-agenda").start()

    def _carregar(self):
        data = seguro.ler_json(self.path, {})
        self.tarefas = data.get("tarefas", []) if isinstance(data, dict) else []

    def _salvar(self):
        seguro.gravar_json(self.path, {"tarefas": self.tarefas}, indent=1)

    def criar(self, titulo: str, quando: str, texto: str = "",
              tipo: str = "chat", repetir: str = "") -> dict:
        dt = parse_quando(quando)
        item = {
            "id": uuid.uuid4().hex[:8],
            "titulo": (titulo or texto or "tarefa")[:100],
            "quando": dt.isoformat(timespec="seconds"),
            "texto": texto or titulo,
            "tipo": "cowork" if tipo == "cowork" else "chat",
            "repetir": repetir if repetir in ("diario", "semanal") else "",
            "criado": _agora().isoformat(timespec="seconds"),
            "ultimo": None,
        }
        with self._lock:
            self.tarefas.append(item)
            self._salvar()
        return {"ok": True, "tarefa": item}

    def listar(self) -> list[dict]:
        with self._lock:
            return sorted(self.tarefas, key=lambda t: t["quando"])

    def cancelar(self, tid: str) -> dict:
        with self._lock:
            antes = len(self.tarefas)
            self.tarefas = [t for t in self.tarefas if t["id"] != tid]
            self._salvar()
            return {"ok": len(self.tarefas) < antes}

    def _loop(self):
        while self._vivo:
            try:
                agora = _agora()
                for t in list(self.listar()):
                    try:
                        quando = datetime.fromisoformat(t["quando"])
                    except Exception:
                        continue
                    if quando > agora:
                        continue
                    with self._lock:
                        if t.get("ultimo") == t["quando"]:
                            continue
                        t["ultimo"] = t["quando"]
                        self._salvar()
                    threading.Thread(target=self._executar, args=(t.copy(),),
                                     daemon=True).start()
            except Exception:
                pass
            time.sleep(15)

    def _executar(self, t: dict):
        try:
            if t.get("tipo") == "cowork":
                self.orch.cowork.submit(t.get("texto") or t.get("titulo"))
            else:
                resposta = self.orch.process(t.get("texto") or t.get("titulo"))
                try:
                    self.orch.notificador.emitir(
                        f"Agenda: {t.get('titulo')} — {str(resposta)[:300]}",
                        "agenda", 2)
                except Exception:
                    pass
        except Exception:
            pass
        with self._lock:
            if t.get("repetir") in ("diario", "semanal"):
                try:
                    dt = datetime.fromisoformat(t["quando"])
                    dt += timedelta(days=1 if t["repetir"] == "diario" else 7)
                    t["quando"] = dt.isoformat(timespec="seconds")
                except Exception:
                    pass
            else:
                self.tarefas = [x for x in self.tarefas
                                if x["id"] != t["id"]]
            self._salvar()

    def parar(self):
        self._vivo = False


def registrar_ferramentas(tools, agenda: Agenda):
    def criar(titulo: str, quando: str, texto: str = "",
              tipo: str = "chat", repetir: str = "") -> dict:
        return agenda.criar(titulo, quando, texto, tipo, repetir)

    def listar() -> dict:
        return {"ok": True, "tarefas": agenda.listar()}

    def cancelar(id: str) -> dict:
        return agenda.cancelar(id)

    tools.register("agenda_criar", criar,
                   "Agenda um lembrete/tarefa. quando aceita ISO, HH:MM, "
                   "hoje/amanhã. tipo=chat|cowork, repetir=diario|semanal.",
                   {"titulo": "str", "quando": "str", "texto": "str?",
                    "tipo": "str?", "repetir": "str?"})
    tools.register("agenda_listar", listar, "Lista tarefas agendadas.", {})
    tools.register("agenda_cancelar", cancelar,
                   "Cancela uma tarefa agendada pelo id.", {"id": "str"})
