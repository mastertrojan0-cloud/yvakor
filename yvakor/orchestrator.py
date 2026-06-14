"""
YVAKOR — Orquestrador (o cérebro do agente)

Fluxo por mensagem do usuário:
  1. Detecta comandos especiais ([perfil], [skill], [memoria])
  2. Monta contexto: identidade + princípios + skills relevantes + memórias
  3. Roteia para o provider certo (local vs externo)
  4. Executa resposta (futuramente: loop de ferramentas/function calling)
  5. Registra na memória episódica
  6. Reflexão pós-tarefa (se habilitada e a tarefa for relevante)
"""

from __future__ import annotations
import threading
from pathlib import Path
from datetime import datetime

from yvakor.llm.router import LLMRouter
from yvakor.memory.episodic import EpisodicMemory
from yvakor.memory.semantic import SemanticMemory
from yvakor.memory.procedural import SkillLibrary
from yvakor.reflection.loop import ReflectionLoop
from yvakor.learning.absorber import KnowledgeAbsorber
from yvakor.tools.registry import ToolRegistry
from yvakor.tools.builtin import register_builtins
from yvakor.connectors import ConnectorManager
from yvakor.agent import AgentLoop
from yvakor.cowork import CoworkManager
from yvakor.maintenance import Maintenance
from yvakor.config import load_settings

ROOT = Path(__file__).resolve().parent.parent


class ConfirmationBroker:
    """Handshake de confirmação servidor↔navegador, por conversa (sid).

    A thread que processa /api/chat chama request() e bloqueia num Event até
    que outra thread (endpoint /api/confirm) chame resolve(). A interface
    descobre a pendência via /api/progress (campo 'pending') e mostra o popup.
    """

    def __init__(self, timeout: float = 180.0):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}   # sid -> {id, action, detail}
        self._events: dict[str, threading.Event] = {}
        self._results: dict[str, bool] = {}
        self._seq = 0

    def request(self, sid: str, action: str, detail: str) -> bool:
        ev = threading.Event()
        with self._lock:
            self._seq += 1
            self._pending[sid] = {"id": self._seq, "action": action,
                                  "detail": str(detail)[:300]}
            self._events[sid] = ev
            self._results.pop(sid, None)
        aprovou = ev.wait(self.timeout)  # False se estourar o tempo → nega
        with self._lock:
            res = self._results.pop(sid, False) if aprovou else False
            self._pending.pop(sid, None)
            self._events.pop(sid, None)
        return res

    def pending_for(self, sid: str) -> dict | None:
        with self._lock:
            p = self._pending.get(sid)
            return dict(p) if p else None

    def resolve(self, sid: str, allow: bool) -> bool:
        with self._lock:
            ev = self._events.get(sid)
            if not ev:
                return False
            self._results[sid] = bool(allow)
            ev.set()
            return True


class Orchestrator:
    def __init__(self):
        self.settings = load_settings()
        self.router = LLMRouter(self.settings)
        self.episodic = EpisodicMemory(ROOT / self.settings["memory"]["episodic_db"])
        self.semantic = SemanticMemory(ROOT / self.settings["memory"]["semantic_index"])
        self.skills = SkillLibrary(ROOT / self.settings["skills"]["library_path"])
        self.reflection = ReflectionLoop(self.router, self.skills, self.episodic)
        self.absorber = KnowledgeAbsorber(self.router, self.semantic,
                                          self.skills, self.episodic)
        self.tools = ToolRegistry(self.settings)
        register_builtins(self.tools)
        # Conectores: injeta as ferramentas dos serviços já conectados (e-mail,
        # WhatsApp, GitHub, Telegram…). O agente passa a usá-las quando precisar.
        self.connectors = ConnectorManager(self.tools, ROOT / "data" / "connectors.json")
        self.agent = AgentLoop(self.router, self.tools,
                               max_iterations=self.settings["agent"]["max_iterations"])
        self.cowork = CoworkManager(self, self.settings)
        self.maintenance = Maintenance(self)
        self.identity_path = ROOT / "identity" / "core_identity.md"
        self.principles_path = ROOT / "identity" / "principles.md"
        # Progresso ao vivo das tarefas (por conversa) p/ a interface acompanhar
        self.progress: dict = {}
        self._prog_lock = threading.Lock()
        # Confirmação de ações protegidas via interface (popup no navegador)
        self.confirm_broker = ConfirmationBroker()

    # ------------------------------------------------------------------ #
    # Progresso ao vivo (a interface faz polling em /api/progress)
    # ------------------------------------------------------------------ #
    def _prog_start(self, sid: str):
        with self._prog_lock:
            self.progress[sid] = {"running": True, "steps": []}

    def _prog_step(self, sid: str, label: str):
        with self._prog_lock:
            p = self.progress.setdefault(sid, {"running": True, "steps": []})
            p["steps"].append(label)

    def _prog_done(self, sid: str):
        with self._prog_lock:
            if sid in self.progress:
                self.progress[sid]["running"] = False

    def get_progress(self, sid: str) -> dict:
        with self._prog_lock:
            p = dict(self.progress.get(sid, {"running": False, "steps": []}))
        # Anexa pendência de confirmação (se houver) para a interface mostrar o popup
        p["pending"] = self.confirm_broker.pending_for(sid)
        return p

    @staticmethod
    def _rotulo_passo(dado: dict) -> str:
        nome = dado.get("nome", "")
        a = dado.get("args", {}) or {}
        det = (a.get("caminho") or a.get("nome") or a.get("comando")
               or a.get("url") or a.get("doc") or "")
        det = str(det)[:60]
        icones = {
            "listar_diretorio": "📂 listando", "ler_arquivo_local": "📄 lendo",
            "ler_arquivo": "📄 lendo", "escrever_arquivo": "✍️ escrevendo",
            "escrever_arquivo_local": "✍️ escrevendo", "editar_arquivo_local": "✏️ editando",
            "executar_shell": "⌨️ shell", "executar_python": "🐍 python",
            "http_get": "🌐 baixando", "validar_documento": "🔎 validando",
            "converter_xlsx_para_json": "📊 convertendo",
            "gerar_proposta_html": "📝 gerando proposta",
            "extrair_log_docker": "🐳 logs docker",
        }
        base = icones.get(nome, f"🔧 {nome}")
        return f"{base} {det}".strip()

    # ------------------------------------------------------------------ #
    # Contexto
    # ------------------------------------------------------------------ #
    def build_system_prompt(self, user_message: str) -> str:
        identity = self.identity_path.read_text(encoding="utf-8")
        principles = self.principles_path.read_text(encoding="utf-8")
        relevant_skills = self.skills.find_relevant(user_message, top_k=2)
        memories = self.semantic.search(user_message,
                                        top_k=self.settings["memory"]["semantic_top_k"])

        parts = [identity, principles]
        if relevant_skills:
            parts.append("## SKILLS RELEVANTES (siga estes procedimentos)\n"
                         + "\n---\n".join(relevant_skills))
        if memories:
            parts.append("## MEMÓRIAS RELEVANTES\n" + "\n".join(f"- {m}" for m in memories))
        # O histórico da conversa NÃO entra mais aqui como texto truncado: agora
        # é enviado ao modelo como turnos user/assistant reais (ver process()).
        parts.append(f"## DATA ATUAL\n{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ #
    # Comandos especiais
    # ------------------------------------------------------------------ #
    def handle_special(self, msg: str) -> str | None:
        low = msg.strip().lower()

        if low.startswith("[perfil]"):
            instruction = msg.split("]", 1)[1].strip()
            return self._update_identity(instruction)

        if low.startswith("[skill]"):
            instruction = msg.split("]", 1)[1].strip()
            recent = self.episodic.last_interactions(20)
            return self.reflection.create_skill_from_context(instruction, recent)

        if low.startswith("[memoria]"):
            query = msg.split("]", 1)[1].strip()
            hits = self.semantic.search(query, top_k=10)
            return "Memórias encontradas:\n" + "\n".join(f"- {h}" for h in hits) \
                   if hits else "Nada encontrado na memória semântica."

        if low.startswith("[aprender]"):
            return self._run_bootstrap(msg.split("]", 1)[1].strip())

        if low.startswith("[ferramentas]"):
            nomes = ", ".join(self.tools.tools.keys()) or "(nenhuma)"
            return f"Ferramentas disponíveis: {nomes}"

        if low.startswith("[manutencao]") or low.startswith("[manutenção]"):
            r = self.maintenance.run_cycle()
            est = r["conhecimento"]["skills_estabilizadas"]
            cod = r["codigo"]
            return ("🔧 Manutenção concluída.\n"
                    f"- Skills promovidas a estáveis: {', '.join(est) or 'nenhuma'}\n"
                    f"- Memória: {r['conhecimento'].get('memoria', {})}\n"
                    f"- Código: {cod.get('estado')} — {cod.get('motivo')}")

        if low.startswith("[cowork-resultado]"):
            tid = msg.split("]", 1)[1].strip()
            return self.cowork.result(tid)

        if low.startswith("[cowork-status]"):
            tid = msg.split("]", 1)[1].strip() or None
            return self.cowork.status(tid)

        if low.startswith("[cowork]"):
            desc = msg.split("]", 1)[1].strip()
            if not desc:
                return "Uso: [cowork] <descrição da tarefa>"
            tid = self.cowork.submit(desc)
            return (f"🚀 Tarefa cowork disparada: {tid}\n"
                    f"   Descrição: {desc}\n"
                    f"   Use [cowork-status] para acompanhar.")

        # ---- Gestão de conversas ----
        if low.startswith("[nova]"):
            titulo = msg.split("]", 1)[1].strip()
            sid = self.episodic.nova_conversa(titulo)
            return f"✅ Nova conversa criada: {sid}"

        if low.startswith("[conversas]"):
            sess = self.episodic.listar_conversas()
            if not sess:
                return "Nenhuma conversa registrada."
            lines = ["Conversas:"]
            for s in sess:
                marker = " *" if s["active"] else "  "
                lines.append(
                    f"{marker} [{s['id']}] {s['title']}  "
                    f"({s['episodes']} msgs, {s['created_at']})")
            return "\n".join(lines)

        if low.startswith("[retomar]"):
            sid = msg.split("]", 1)[1].strip()
            if not sid:
                return "Uso: [retomar] <id-da-conversa>"
            ok = self.episodic.retomar_conversa(sid)
            if not ok:
                return f"Conversa '{sid}' não encontrada."
            # Nome da sessão ativa
            title = next((s["title"] for s in self.episodic.listar_conversas()
                          if s["active"]), sid)
            return f"✅ Conversa retomada: [{sid}] {title}"

        if low.startswith("[apagar-conversa]"):
            sid = msg.split("]", 1)[1].strip()
            if not sid:
                return "Uso: [apagar-conversa] <id-da-conversa>"
            ok, motivo = self.episodic.apagar_conversa(sid)
            return f"{'✅' if ok else '❌'} {motivo}"

        if low.startswith("[renomear]"):
            partes = msg.split("]", 1)[1].strip().split(maxsplit=1)
            if len(partes) < 2:
                return "Uso: [renomear] <id> <novo título>"
            sid, titulo = partes
            ok = self.episodic.renomear_conversa(sid, titulo)
            return (f"✅ Conversa renomeada para: {titulo}"
                    if ok else f"❌ Conversa '{sid}' não encontrada.")

        return None

    def _run_bootstrap(self, arg: str) -> str:
        """Dispara o autoaprendizado ativo (gera skills a partir do perfil)."""
        from yvakor.learning.bootstrap import LearningBootstrap
        n = 5
        m = __import__("re").search(r"\d+", arg)
        if m:
            n = max(1, min(12, int(m.group(0))))
        res = LearningBootstrap(self).run(n_skills=n)
        criadas = res["skills_criadas"]
        if not criadas:
            return "Autoaprendizado rodou, mas nenhuma skill nova (já cobertas?)."
        return ("✅ Autoaprendizado concluído. Skills criadas:\n"
                + "\n".join(f"- {s}" for s in criadas))

    def _update_identity(self, instruction: str) -> str:
        """Pede ao LLM para reescrever a identidade aplicando a instrução."""
        current = self.identity_path.read_text(encoding="utf-8")
        prompt = (
            "Você mantém o arquivo de identidade de um agente. Aplique a instrução "
            "do usuário ao arquivo abaixo, preservando estrutura e tudo que não "
            "conflita. Adicione a mudança também na seção 'Preferências aprendidas' "
            f"com a data {datetime.now():%Y-%m-%d}. Responda APENAS com o arquivo "
            "completo atualizado, sem comentários extras.\n\n"
            f"INSTRUÇÃO: {instruction}\n\nARQUIVO ATUAL:\n{current}"
        )
        updated = self.router.complete(task_type="formatacao",
                                       system="Você é um editor de arquivos preciso.",
                                       user=prompt)
        self.identity_path.write_text(updated.strip() + "\n", encoding="utf-8")
        self.episodic.log("perfil_atualizado", instruction, "ok")
        return f"✅ Identidade atualizada: {instruction}"

    # ------------------------------------------------------------------ #
    # Loop principal
    # ------------------------------------------------------------------ #
    def process(self, user_message: str) -> str:
        special = self.handle_special(user_message)
        if special is not None:
            return special

        system = self.build_system_prompt(user_message)
        task_type = self.router.classify(user_message)
        sid = getattr(self.episodic, "active_id", "default")
        self._prog_start(sid)

        # Loop de agente: a IA decide e executa ferramentas (Claude Code-like).
        # A continuidade vem do histórico REAL da conversa (turnos user/assistant),
        # não mais de um resumo truncado no system prompt.
        def _trace(tipo, dado):
            if tipo == "ferramenta":
                label = self._rotulo_passo(dado)
                self._prog_step(sid, label)
                self.episodic.log("ferramenta", dado.get("nome", ""),
                                  str(dado.get("args", ""))[:500])
                # Feedback ao vivo no terminal (CLI)
                try:
                    print(f"\n  {label}", flush=True)
                except Exception:
                    pass
            elif tipo == "observacao" and isinstance(dado, dict):
                res = dado.get("resultado", {})
                if isinstance(res, dict) and not res.get("ok", True):
                    try:
                        print(f"    ⚠ {res.get('error', res.get('erro', 'falha'))[:120]}",
                              flush=True)
                    except Exception:
                        pass

        history = self.episodic.history_messages(
            self.settings["memory"]["episodic_context_last_n"])
        history.append({"role": "user", "content": user_message})

        # Ações protegidas pedem confirmação via interface (popup no navegador),
        # roteadas pelo broker para ESTA conversa.
        from yvakor.tools.guard import set_thread_confirmer, clear_thread_confirmer
        set_thread_confirmer(
            lambda action, detail: self.confirm_broker.request(sid, action, detail))
        try:
            answer = self.agent.run(system, history=history, on_event=_trace)
        finally:
            clear_thread_confirmer()
            self._prog_done(sid)

        self.episodic.log("conversa", user_message, answer)
        self.episodic.maybe_autotitle(user_message)   # título estilo Claude

        # Absorção automática: extrai fatos + destila skills da IA principal
        if self.settings["agent"]["reflection_enabled"]:
            self.absorber.after_response(user_message, answer, task_type)

        return answer
