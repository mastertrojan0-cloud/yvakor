"""
YVAKOR — Cowork 2.0 (tarefas autônomas em segundo plano)

Inspirado no Claude Cowork: o agente recebe uma tarefa, trabalha nela por
conta própria (inclusive controlando o navegador) e entrega o resultado —
enquanto o usuário continua conversando no chat principal.

O que mudou em relação à v0.2:
  • Persistência em SQLite (data/cowork.db): sobrevive a reinício/crash.
  • Cada tarefa roda em sessão isolada → não mistura histórico nem progresso
    com a conversa do usuário.
  • Cancelamento cooperativo entre passos do agente.
  • Passos ao vivo (o que ela está fazendo agora) expostos à interface.
  • Workspace próprio por tarefa (data/cowork/<id>/) com os artefatos gerados.

Comandos no CLI (compatíveis com a v0.2):
  [cowork] <descrição>      → dispara tarefa em segundo plano
  [cowork-status] [id]      → lista tarefas ou detalha uma
  [cowork-resultado] <id>   → resultado completo + artefatos
  [cowork-cancelar] <id>    → pede o cancelamento
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

ICONES = {
    "na_fila": "⏳", "executando": "🔄", "concluida": "✅",
    "falha": "❌", "cancelada": "⏹", "interrompida": "⚠️",
}
FINALIZADAS = ("concluida", "falha", "cancelada", "interrompida")


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _rotulo(status: str) -> str:
    return f"{ICONES.get(status, '')} {status}".strip()


# ----------------------------------------------------------------------- #
# Persistência
# ----------------------------------------------------------------------- #
class CoworkStore:
    """Tabela de tarefas em SQLite (uma conexão, acesso serializado)."""

    _CAMPOS = ("description", "status", "created_at", "started_at",
               "finished_at", "result", "error", "steps", "session_id",
               "workspace", "plano", "progresso")

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        try:
            for _p in ("journal_mode=WAL", "synchronous=NORMAL", "busy_timeout=5000",
                       "journal_size_limit=33554432"):
                self.conn.execute(f"PRAGMA {_p}")
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        self._lock = threading.Lock()
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cowork_tasks (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                result TEXT,
                error TEXT,
                steps TEXT DEFAULT '[]',
                session_id TEXT,
                workspace TEXT,
                plano TEXT,
                progresso TEXT
            )""")
        for col in ("plano TEXT", "progresso TEXT"):
            try:
                self.conn.execute(f"ALTER TABLE cowork_tasks ADD COLUMN {col}")
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        self.conn.commit()

    def insert(self, task: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO cowork_tasks (id, description, status, created_at, "
                "started_at, finished_at, result, error, steps, session_id, "
                "workspace, plano, progresso) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task["id"], task["description"], task["status"],
                 task["created_at"], task.get("started_at"),
                 task.get("finished_at"), task.get("result"), task.get("error"),
                 json.dumps(task.get("steps") or [], ensure_ascii=False),
                 task.get("session_id"), task.get("workspace"),
                 json.dumps(task.get("plano"), ensure_ascii=False)
                 if task.get("plano") else None,
                 json.dumps(task.get("progresso"), ensure_ascii=False)
                 if task.get("progresso") else None))
            self.conn.commit()

    def update(self, tid: str, **campos) -> None:
        validos = {k: v for k, v in campos.items() if k in self._CAMPOS}
        if not validos:
            return
        if "steps" in validos and not isinstance(validos["steps"], str):
            validos["steps"] = json.dumps(validos["steps"], ensure_ascii=False)
        for campo in ("plano", "progresso"):
            if campo in validos and not isinstance(validos[campo], str):
                validos[campo] = json.dumps(validos[campo], ensure_ascii=False)
        sets = ", ".join(f"{k}=?" for k in validos)
        with self._lock:
            self.conn.execute(f"UPDATE cowork_tasks SET {sets} WHERE id=?",
                              (*validos.values(), tid))
            self.conn.commit()

    def get(self, tid: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT id, description, status, created_at, started_at, "
                "finished_at, result, error, steps, session_id, workspace, "
                "plano, progresso FROM cowork_tasks WHERE id=?", (tid,)).fetchone()
        return self._row(row) if row else None

    def all(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, description, status, created_at, started_at, "
                "finished_at, result, error, steps, session_id, workspace, "
                "plano, progresso FROM cowork_tasks ORDER BY created_at DESC "
                "LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def recover(self) -> int:
        """Marca como interrompidas as tarefas que estavam rodando num processo
        que morreu (o trabalho delas não sobrevive a um crash)."""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE cowork_tasks SET status='interrompida', finished_at=?, "
                "error=COALESCE(error, 'processo encerrado antes de concluir') "
                "WHERE status IN ('executando','na_fila')", (_agora(),))
            self.conn.commit()
            return cur.rowcount

    @staticmethod
    def _row(row) -> dict:
        try:
            steps = json.loads(row[8] or "[]")
        except Exception:
            steps = []
        def _js(v):
            try:
                return json.loads(v) if v else None
            except Exception:
                return None
        return {
            "id": row[0], "description": row[1], "status": row[2],
            "created_at": row[3], "started_at": row[4], "finished_at": row[5],
            "result": row[6], "error": row[7], "steps": steps,
            "session_id": row[9], "workspace": row[10],
            "plano": _js(row[11]), "progresso": _js(row[12]),
        }


# ----------------------------------------------------------------------- #
# Gerente
# ----------------------------------------------------------------------- #
class CoworkManager:
    """Gerencia tarefas autônomas executadas em segundo plano."""

    def __init__(self, orchestrator, settings: dict, db_path: Path | None = None,
                 workspace_root: Path | None = None):
        self._orch = orchestrator
        self._settings = settings
        cfg = (settings or {}).get("cowork", {}) or {}
        self._max_concurrent = max(1, int(cfg.get("max_concurrent_tasks", 3)))
        self._max_steps = int(cfg.get("max_steps")
                              or (settings.get("agent", {}) or {}).get(
                                  "max_iterations", 25))

        self.workspace_root = Path(workspace_root
                                   or cfg.get("workspace_dir")
                                   or (ROOT / "data" / "cowork"))
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        db = Path(db_path) if db_path else (ROOT / "data" / "cowork.db")
        self.store = CoworkStore(db)

        self._lock = threading.RLock()
        self._events: dict[str, threading.Event] = {}
        self._steps: dict[str, list] = {}
        self._threads: dict[str, threading.Thread] = {}

        interrompidas = self.store.recover()
        if interrompidas:
            print(f"  [cowork] {interrompidas} tarefa(s) de execução anterior "
                  "marcada(s) como interrompida(s).")
        if cfg.get("auto_resume", True):
            threading.Timer(4.0, self._retomar_interrompidas).start()

    def _retomar_interrompidas(self) -> None:
        """Autonomia: continua tarefas paradas por queda/reinício."""
        try:
            paradas = [t for t in self.store.all(100)
                       if t.get("status") == "interrompida"]
            for t in paradas[:self._max_concurrent]:
                try:
                    self.retomar(t["id"])
                    print(f"  [cowork] retomando {t['id']}: "
                          f"{t.get('description', '')[:60]}")
                except Exception as exc:
                    print(f"  [cowork] falha ao retomar {t['id']}: {exc}")
        except Exception as exc:
            print(f"  [cowork] auto-resume indisponível: {exc}")

    # ------------------------------------------------------------------ #
    # Submissão
    # ------------------------------------------------------------------ #
    def _evento(self, tid: str) -> threading.Event:
        """Evento de cancelamento da tarefa, criado sob lock e SEMPRE guardado
        em self._events. Antes só `submit()` populava o dict; `retomar()` e a
        recuperação após queda não — então `_run` criava um Event local que
        `cancel()`/`shutdown()` nunca enxergavam e o cancelamento não parava a
        tarefa. Com setdefault, todo caminho (submit/retomar/recover) usa o
        mesmo evento registrado."""
        with self._lock:
            ev = self._events.get(tid)
            if ev is None:
                ev = threading.Event()
                self._events[tid] = ev
            return ev

    def submit(self, description: str) -> dict:
        desc = " ".join((description or "").split())
        if not desc:
            raise ValueError("descrição da tarefa vazia")

        tid = uuid.uuid4().hex[:8]
        ws = self.workspace_root / tid
        ws.mkdir(parents=True, exist_ok=True)
        try:
            sid = self._orch.episodic.create_session(
                f"Cowork · {desc[:46]}", activate=False, kind="task")
        except Exception:
            sid = None

        tarefa = {
            "id": tid, "description": desc, "status": "na_fila",
            "created_at": _agora(), "started_at": None, "finished_at": None,
            "result": None, "error": None, "steps": [],
            "session_id": sid, "workspace": str(ws),
        }
        self.store.insert(tarefa)
        self._evento(tid)
        with self._lock:
            self._steps[tid] = []
        self._drain()
        return self.get(tid) or tarefa

    # ------------------------------------------------------------------ #
    # Execução
    # ------------------------------------------------------------------ #
    def _drain(self) -> None:
        """Inicia tarefas da fila enquanto houver vaga."""
        with self._lock:
            rodando = sum(1 for t in self.store.all(200)
                          if t["status"] == "executando")
            if rodando >= self._max_concurrent:
                return
            fila = [t for t in self.store.all(200) if t["status"] == "na_fila"]
            fila.sort(key=lambda t: t["created_at"])
            for t in fila:
                if rodando >= self._max_concurrent:
                    break
                tid = t["id"]
                if tid in self._threads and self._threads[tid].is_alive():
                    continue
                self.store.update(tid, status="executando",
                                  started_at=_agora(), error=None)
                th = threading.Thread(target=self._run, args=(tid,),
                                      daemon=True, name=f"cowork-{tid}")
                self._threads[tid] = th
                th.start()
                rodando += 1

    def _anotar(self, tid: str, texto: str, tipo: str = "passo") -> None:
        with self._lock:
            passos = self._steps.setdefault(tid, [])
            passos.append({"ts": datetime.now().strftime("%H:%M:%S"),
                           "tipo": tipo, "texto": texto})
            if len(passos) > 200:
                del passos[:-200]
            snapshot = list(passos)
        self.store.update(tid, steps=snapshot)

    def _planejar(self, descricao: str) -> dict:
        """Plano estruturado: objetivo → etapas com critério de conclusão."""
        limite = max(2, min(int(
            ((self._settings or {}).get("cowork", {}) or {}).get(
                "max_etapas", 6)), int(self._max_steps)))
        prompt = (
            "Decomponha o objetivo em etapas executáveis por um agente com "
            "ferramentas (navegador, arquivos, shell, código, rede).\n"
            f"Máximo de {limite} etapas.\n"
            "Responda SOMENTE JSON:\n"
            '{"objetivo":"...","etapas":[{"id":1,"titulo":"...",'
            '"objetivo":"instrução concreta para esta etapa",'
            '"criterio":"como saber que ficou pronto"}]}\n\n'
            f"OBJETIVO: {descricao}")
        try:
            raw = self._orch.router.complete_messages(
                "analise_complexa",
                [{"role": "system", "content": "Responda apenas JSON válido."},
                 {"role": "user", "content": prompt}]) or ""
            ini, fim = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[ini:fim + 1]) if ini >= 0 and fim > ini else {}
            etapas = []
            for i, e in enumerate(data.get("etapas") or []):
                if not isinstance(e, dict):
                    continue
                obj = str(e.get("objetivo") or e.get("titulo") or "").strip()
                if not obj:
                    continue
                etapas.append({
                    "id": int(e.get("id") or i + 1),
                    "titulo": str(e.get("titulo") or f"Etapa {i + 1}"),
                    "objetivo": obj,
                    "criterio": str(e.get("criterio") or "resultado concreto"),
                })
            if etapas:
                return {"objetivo": str(data.get("objetivo") or descricao),
                        "etapas": etapas[:limite]}
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        return {"objetivo": descricao,
                "etapas": [{"id": 1, "titulo": "Executar a tarefa",
                            "objetivo": descricao,
                            "criterio": "resultado concreto e verificável"}]}

    def _verificar(self, descricao: str, resultados: list[dict]) -> dict:
        resumo = "\n".join(f"- {r.get('titulo')}: {str(r.get('resultado'))[:900]}"
                           for r in resultados)[:5000]
        try:
            raw = self._orch.router.complete_messages(
                "analise_complexa",
                [{"role": "system", "content": "Responda apenas JSON válido."},
                 {"role": "user", "content":
                  "Verifique se o objetivo foi cumprido. Responda "
                  '{"ok":true/false,"faltando":"..."}.\n\n'
                  f"OBJETIVO: {descricao}\n\nRESULTADOS:\n{resumo}"}]) or ""
            ini, fim = raw.find("{"), raw.rfind("}")
            data = json.loads(raw[ini:fim + 1]) if ini >= 0 and fim > ini else {}
            return {"ok": bool(data.get("ok", True)),
                    "faltando": str(data.get("faltando") or "")}
        except Exception:
            return {"ok": True, "faltando": ""}

    def _sintetizar(self, descricao: str, resultados: list[dict]) -> str:
        resumo = "\n\n".join(
            f"## {r.get('titulo')}\n{str(r.get('resultado'))[:2500]}"
            for r in resultados)
        try:
            texto = self._orch.router.complete_messages(
                "formatacao",
                [{"role": "system", "content":
                  "Sintetize o resultado final para o usuário, em português, "
                  "com o que foi feito, achados e caminhos de arquivos."},
                 {"role": "user", "content":
                  f"OBJETIVO: {descricao}\n\n{resumo[:7000]}"}]) or ""
            return texto.strip() or resumo
        except Exception:
            return resumo or "Tarefa concluída sem síntese."

    def retomar(self, tid: str) -> dict:
        t = self.store.get(tid)
        if not t:
            return {"ok": False, "erro": "tarefa não encontrada"}
        if t["status"] not in ("interrompida", "falha", "cancelada"):
            return {"ok": False, "erro": "tarefa não está parada"}
        # Evento limpo: uma tarefa cancelada/interrompida pode ter o evento
        # sinalizado de antes; ao retomar começamos com ele zerado.
        self._evento(tid).clear()
        self.store.update(tid, status="na_fila", error=None,
                          finished_at=None)
        self._drain()
        return {"ok": True, "task": self.get(tid)}

    def _run(self, tid: str) -> None:
        tarefa = self.store.get(tid)
        if not tarefa:
            return
        # Garante o evento no dict (setdefault) — inclui tarefas retomadas e
        # recuperadas após queda, para que cancel()/shutdown() as alcancem.
        ev = self._evento(tid)
        ws = Path(tarefa["workspace"] or (self.workspace_root / tid))
        ws.mkdir(parents=True, exist_ok=True)
        self._anotar(tid, "tarefa iniciada")
        # Cada tarefa ganha a própria aba no navegador (Edge/Chrome), então
        # duas tarefas simultâneas não disputam a mesma página.
        from yvakor.browser import contexto as nav_ctx
        nav_ctx.definir(aba=f"tarefa-{tid}")
        # Esta thread é de segundo plano: o navegador da extensão abre abas
        # sem ativá-las (não rouba a tela do usuário). Flag por thread.
        try:
            self._orch._tl.segundo_plano = True
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

        def on_event(tipo: str, dado: dict) -> None:
            if tipo == "ferramenta":
                try:
                    rotulo = self._orch._rotulo_passo(dado)
                except Exception:
                    rotulo = f"🔧 {dado.get('nome', '')}"
                self._anotar(tid, rotulo)
            elif tipo == "plano" and isinstance(dado, dict):
                try:
                    self._anotar(tid, self._orch._rotulo_plano(dado))
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            elif tipo == "aprovacao_plano":
                self._anotar(tid, "📋 esperando você aprovar o plano", tipo="aviso")
            elif tipo == "observacao" and isinstance(dado, dict):
                res = dado.get("resultado", {}) or {}
                if isinstance(res, dict):
                    erro = res.get("erro") or res.get("error")
                    if erro:
                        self._anotar(tid, f"⚠ {str(erro)[:200]}", tipo="aviso")

        contexto = (
            "## TAREFA EM SEGUNDO PLANO (COWORK)\n"
            "Você está executando isto sozinho; o usuário pode não estar "
            "olhando agora. Seja autônomo e objetivo.\n"
            f"- Diretório de trabalho da tarefa: {ws}\n"
            "- Salve TODO artefato que gerar (arquivos, planilhas, relatórios, "
            "PDFs, imagens) dentro desse diretório.\n"
            f"- Orçamento: até {self._max_steps} passos de ferramenta. Seja "
            "eficiente; não repita tentativas idênticas.\n"
            "- Termine com um RESULTADO objetivo: o que fez, o que encontrou e "
            "os caminhos absolutos dos arquivos.\n"
            "- Se precisar de decisão humana (login, captcha, pagamento, envio "
            "externo), explique claramente e pare."
        )

        status, resultado, erro = "falha", None, None
        try:
            plano = tarefa.get("plano") or self._planejar(tarefa["description"])
            progresso = tarefa.get("progresso") or {"concluidas": [],
                                                    "resultados": []}
            self.store.update(tid, plano=plano, progresso=progresso)
            etapas = plano.get("etapas") or []
            self._anotar(tid, f"plano com {len(etapas)} etapa(s)")
            for i, etapa in enumerate(etapas, 1):
                if ev.is_set():
                    break
                if etapa.get("id") in progresso["concluidas"]:
                    continue
                self._anotar(tid, f"▶ etapa {i}/{len(etapas)}: "
                                  f"{etapa.get('titulo')}")
                anteriores = "\n".join(
                    f"- {r.get('titulo')}: {str(r.get('resultado'))[:700]}"
                    for r in progresso["resultados"][-4:])
                ctx_etapa = (
                    "\n\n## GRANDE TAREFA — PLANO\n"
                    f"Objetivo geral: {plano.get('objetivo')}\n"
                    f"Etapa {i}/{len(etapas)}: {etapa.get('titulo')}\n"
                    f"Critério: {etapa.get('criterio')}\n"
                    f"Resultados anteriores:\n{anteriores or '(nenhum)'}\n"
                    "Execute SÓ esta etapa e devolva o resultado concreto.")
                etapa_res, etapa_erro = None, None
                for _tentativa in (1, 2):
                    if ev.is_set():
                        break
                    try:
                        etapa_res = self._orch.process(
                            etapa["objetivo"],
                            session_id=tarefa.get("session_id"),
                            should_stop=ev.is_set,
                            extra_context=contexto + ctx_etapa)
                    except Exception as exc:
                        etapa_erro = f"{type(exc).__name__}: {exc}"
                    texto_etapa = str(etapa_res or "").strip()
                    if texto_etapa and "Interrompi a tarefa" not in texto_etapa:
                        break
                if etapa_res and str(etapa_res).strip():
                    progresso["resultados"].append({
                        "id": etapa.get("id"),
                        "titulo": etapa.get("titulo"),
                        "resultado": str(etapa_res)[:3500]})
                    progresso["concluidas"].append(etapa.get("id"))
                    self._anotar(tid, f"✅ {etapa.get('titulo')}")
                else:
                    erro = etapa_erro or "etapa sem resultado"
                    self._anotar(tid, f"⚠ {etapa.get('titulo')}: {erro}",
                                 tipo="aviso")
                    break
                self.store.update(tid, progresso=progresso)

            if ev.is_set():
                status = "cancelada"
            elif erro:
                status = "falha"
            else:
                veredito = self._verificar(tarefa["description"],
                                           progresso["resultados"])
                if not veredito.get("ok") and veredito.get("faltando"):
                    self._anotar(tid, "🔎 verificação apontou pendência; "
                                      "tentando corrigir")
                    try:
                        correcao = self._orch.process(
                            "Corrija esta pendência da tarefa: "
                            + veredito["faltando"],
                            session_id=tarefa.get("session_id"),
                            should_stop=ev.is_set,
                            extra_context=contexto)
                        progresso["resultados"].append({
                            "id": "correcao", "titulo": "Correção",
                            "resultado": str(correcao)[:3500]})
                    except Exception as exc:
                        self._anotar(tid, f"⚠ correção falhou: {exc}",
                                     tipo="aviso")
                resultado = self._sintetizar(tarefa["description"],
                                             progresso["resultados"])
                status = "concluida" if resultado.strip() else "falha"
                if not resultado.strip():
                    erro = "não foi possível sintetizar o resultado"
        except Exception as exc:
            erro = f"{type(exc).__name__}: {exc}"
        finally:
            if resultado:
                try:
                    (ws / "resultado.md").write_text(
                        f"# Tarefa cowork {tid}\n\n**Pedido:** {tarefa['description']}\n\n"
                        f"**Status:** {status}\n\n---\n\n{resultado}\n",
                        encoding="utf-8")
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            if erro:
                # O erro já aparece no campo próprio do cartão; evita duplicar
                # como passo ("⚠ ..." duas vezes na interface).
                self.store.update(tid, error=erro)
            if status == "concluida":
                self._anotar(tid, "tarefa concluída")
            elif status == "cancelada":
                self._anotar(tid, "tarefa cancelada")

            self.store.update(tid, status=status, result=resultado,
                              error=erro, finished_at=_agora(),
                              steps=self._steps.get(tid, []))
            try:
                nav_ctx.limpar()
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            self._fechar_abas_da_tarefa(tid)
            with self._lock:
                self._threads.pop(tid, None)
            self._drain()

    def _fechar_abas_da_tarefa(self, tid: str) -> None:
        """Fecha o grupo de abas da tarefa (se configurado e o motor estiver aberto)."""
        if not self._settings.get("cowork", {}).get("fechar_abas", False):
            return
        navegadores = getattr(self._orch, "navegadores", None)
        if navegadores is None:
            return
        for nome in navegadores.nomes():
            try:
                sess = navegadores.sessao(nome)
                if not sess.is_open():
                    continue
                with sess.trilho:
                    sess.selecionar_aba("principal")
                    sess.fechar_grupo(f"tarefa-{tid}")
            except Exception:
                continue

    # ------------------------------------------------------------------ #
    # Cancelamento
    # ------------------------------------------------------------------ #
    def cancel(self, tid: str) -> dict:
        tarefa = self.store.get(tid)
        if not tarefa:
            return {"ok": False, "erro": f"tarefa '{tid}' não encontrada"}
        if tarefa["status"] in FINALIZADAS:
            return {"ok": False, "erro": f"tarefa já finalizada ({tarefa['status']})"}
        ev = self._events.get(tid)
        if ev:
            ev.set()
        if tarefa["status"] == "na_fila":
            self.store.update(tid, status="cancelada", finished_at=_agora(),
                              error="cancelada antes de iniciar")
            return {"ok": True, "id": tid, "status": "cancelada"}
        self._anotar(tid, "cancelamento solicitado — parando no próximo passo")
        return {"ok": True, "id": tid, "status": "cancelando"}

    # ------------------------------------------------------------------ #
    # Consulta
    # ------------------------------------------------------------------ #
    def get(self, tid: str) -> dict | None:
        tarefa = self.store.get(tid)
        if not tarefa:
            return None
        with self._lock:
            passos = self._steps.get(tid)
        if passos:
            tarefa["steps"] = list(passos)
        tarefa["icone"] = ICONES.get(tarefa["status"], "")
        tarefa["artefatos"] = self.artifacts(tid)
        if tarefa.get("session_id"):
            try:
                prog = self._orch.get_progress(tarefa["session_id"])
                tarefa["ao_vivo"] = (prog.get("steps") or [])[-6:]
                tarefa["pendente_confirmacao"] = prog.get("pending")
            except Exception:
                tarefa["ao_vivo"] = []
        return tarefa

    def list(self, limit: int = 100) -> list[dict]:
        itens = []
        for t in self.store.all(limit):
            with self._lock:
                passos = self._steps.get(t["id"])
            if passos:
                t["steps"] = list(passos)
            t["icone"] = ICONES.get(t["status"], "")
            t["artefatos"] = self.artifacts(t["id"])
            # Tarefa rodando pode estar travada esperando aprovação humana
            # (escrita em arquivo/shell). Expor para o painel mostrar o popup.
            if t["status"] == "executando" and t.get("session_id"):
                try:
                    prog = self._orch.get_progress(t["session_id"])
                    t["pendente_confirmacao"] = prog.get("pending")
                    t["ao_vivo"] = (prog.get("steps") or [])[-6:]
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            itens.append(t)
        return itens

    def artifacts(self, tid: str) -> list[dict]:
        tarefa = self.store.get(tid)
        if not tarefa or not tarefa.get("workspace"):
            return []
        ws = Path(tarefa["workspace"])
        if not ws.is_dir():
            return []
        out = []
        for f in sorted(ws.rglob("*")):
            if f.is_file():
                out.append({"nome": f.name,
                            "caminho": str(f),
                            "bytes": f.stat().st_size})
        return out

    def pending_count(self) -> int:
        return sum(1 for t in self.store.all(200)
                   if t["status"] in ("na_fila", "executando"))

    # ------------------------------------------------------------------ #
    # Texto (CLI / compatibilidade v0.2)
    # ------------------------------------------------------------------ #
    def status(self, tid: str | None = None) -> str:
        if tid:
            t = self.get(tid)
            if not t:
                return f"Tarefa '{tid}' não encontrada."
            linhas = [
                f"{_rotulo(t['status'])} Tarefa: {t['id']}",
                f"   Descrição:   {t['description']}",
                f"   Iniciada:    {t['started_at'] or '—'}",
                f"   Finalizada:  {t['finished_at'] or '—'}",
                f"   Workspace:   {t['workspace']}",
            ]
            if t.get("error"):
                linhas.append(f"   Erro:        {t['error']}")
            if t.get("steps"):
                linhas.append("   Passos:")
                for p in t["steps"][-8:]:
                    linhas.append(f"     {p['ts']} {p['texto'][:90]}")
            if t.get("result"):
                linhas.append(f"   Resultado:   {t['result'][:300]}")
            if t.get("artefatos"):
                linhas.append("   Artefatos:")
                for a in t["artefatos"]:
                    linhas.append(f"     {a['caminho']} ({a['bytes']} B)")
            return "\n".join(linhas)

        tarefas = self.list(50)
        if not tarefas:
            return "Nenhuma tarefa cowork registrada."
        linhas = ["Cowork tasks:"]
        for t in tarefas:
            linhas.append(f"  [{t['id']}] {_rotulo(t['status']):>18}  "
                          f"{t['description'][:60]}")
        return "\n".join(linhas)

    def result(self, tid: str) -> str:
        t = self.get(tid)
        if not t:
            return f"Tarefa '{tid}' não encontrada."
        partes = [self.status(tid)]
        if t.get("result"):
            partes.append("\nRESULTADO:\n" + t["result"])
        return "\n".join(partes)

    # ------------------------------------------------------------------ #
    # Encerramento
    # ------------------------------------------------------------------ #
    def shutdown(self) -> None:
        """Sinaliza cancelamento a todas as tarefas (usado ao desligar)."""
        with self._lock:
            eventos = list(self._events.values())
        for ev in eventos:
            ev.set()
