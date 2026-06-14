"""
YVAKOR — Cowork (tarefas autônomas em segundo plano)

Inspirado no Claude Cowork: o agente trabalha em tarefas de fundo
enquanto você continua a conversa principal. Cada tarefa roda em
uma thread separada e reporta seu status sob demanda.

Comandos no CLI:
  [cowork] <descrição>      → dispara tarefa em segundo plano
  [cowork-status] [id]      → lista tarefas ou detalha uma específica
  [cowork-resultado] <id>   → exibe o resultado completo da tarefa
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any


class CoworkManager:
    """Gerencia tarefas autônomas executadas em segundo plano."""

    def __init__(self, orchestrator, settings: dict):
        self._orch = orchestrator
        self._settings = settings
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._process_lock = threading.Lock()

        cowork_cfg = settings.get("cowork", {})
        self._max_concurrent = cowork_cfg.get("max_concurrent_tasks", 3)

    # ------------------------------------------------------------------ #
    # Submeter tarefa
    # ------------------------------------------------------------------ #
    def submit(self, description: str) -> str:
        tid = str(uuid.uuid4())[:8]

        with self._lock:
            running = sum(1 for t in self._tasks.values()
                          if t["status"] == "executando")
            status = "executando" if running < self._max_concurrent else "pendente"
            self._tasks[tid] = {
                "id": tid,
                "description": description,
                "status": status,
                "result": None,
                "error": None,
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
            }

        thread = threading.Thread(target=self._run, args=(tid,),
                                  daemon=True, name=f"cowork-{tid}")
        thread.start()
        return tid

    # ------------------------------------------------------------------ #
    # Worker thread
    # ------------------------------------------------------------------ #
    def _run(self, tid: str):
        with self._lock:
            entry = self._tasks.get(tid)
            if entry is None:
                return
            entry["status"] = "executando"
            desc = entry["description"]

        try:
            with self._process_lock:
                result = self._orch.process(desc)
            self._finish(tid, "concluída", result=result, error=None)
        except Exception as exc:
            self._finish(tid, "falha", result=None, error=str(exc))

        # Avança tarefas pendentes
        self._drain_queue()

    def _finish(self, tid: str, status: str, result: str | None,
                error: str | None):
        with self._lock:
            entry = self._tasks.get(tid)
            if entry:
                entry["status"] = status
                entry["result"] = result
                entry["error"] = error
                entry["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _drain_queue(self):
        """Inicia a próxima tarefa pendente, se houver."""
        with self._lock:
            running = sum(1 for t in self._tasks.values()
                          if t["status"] == "executando")
            for entry in self._tasks.values():
                if entry["status"] == "pendente" and running < self._max_concurrent:
                    entry["status"] = "executando"
                    thread = threading.Thread(target=self._run,
                                              args=(entry["id"],),
                                              daemon=True,
                                              name=f"cowork-{entry['id']}")
                    thread.start()
                    running += 1
                    break

    # ------------------------------------------------------------------ #
    # Consulta
    # ------------------------------------------------------------------ #
    def status(self, tid: str | None = None):
        """Retorna status das tarefas. Se tid=None, lista todas."""
        with self._lock:
            if tid:
                return self._task_summary(tid)

            # Lista resumida de todas
            items = []
            for entry in sorted(self._tasks.values(),
                                key=lambda t: t["started_at"]):
                items.append(f"  [{entry['id']}] {entry['status']:>10}  "
                             f"{entry['description'][:64]}")
            if not items:
                return "Nenhuma tarefa cowork registrada."
            return "Cowork tasks:\n" + "\n".join(items)

    def result(self, tid: str):
        """Exibe resultado completo de uma tarefa."""
        summary = self._task_summary(tid)
        if summary is None:
            return f"Tarefa '{tid}' não encontrada."
        with self._lock:
            entry = self._tasks[tid]
            if entry["result"]:
                return summary + "\n\nRESULTADO:\n" + entry["result"]
            return summary

    def _task_summary(self, tid: str):
        with self._lock:
            entry = self._tasks.get(tid)
            if not entry:
                return None

        status = entry["status"]
        emoji = {"executando": "🔄", "pendente": "⏳",
                 "concluída": "✅", "falha": "❌"}.get(status, "")

        lines = [
            f"{emoji} Tarefa: {entry['id']}",
            f"   Status:      {status}",
            f"   Descrição:   {entry['description']}",
            f"   Iniciada:    {entry['started_at']}",
        ]
        if entry["finished_at"]:
            lines.append(f"   Finalizada:  {entry['finished_at']}")
        if entry["error"]:
            lines.append(f"   Erro:        {entry['error']}")
        if entry["result"]:
            preview = entry["result"][:150]
            if len(entry["result"]) > 150:
                preview += "..."
            lines.append(f"   Preview:     {preview}")
        return "\n".join(lines)

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values()
                       if t["status"] in ("pendente", "executando"))
