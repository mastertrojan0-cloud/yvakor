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
import json
import os
import re as _re
import threading
import time
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
from yvakor.extensao_politica import PoliticaSites, host_de
from yvakor.agent import AgentLoop
from yvakor.cowork import CoworkManager
from yvakor.maintenance import Maintenance
from yvakor.config import load_settings
from yvakor.browser import Navegadores, register_browser_tools
from yvakor.rede import Rede
from yvakor.rede.tools import register_rede_tools
from yvakor.voz.assistente import AssistenteVoz
from yvakor.voz.tools import register_voz_tools
from yvakor.cerebro import Cerebro
from yvakor.cerebro.tools import register_cerebro_tools
from yvakor.arquivos import register_arquivos_tools
from yvakor.telemetria import Telemetria

ROOT = Path(__file__).resolve().parent.parent

ENVIO_MAX_BYTES = 5 * 1024 * 1024
# Arquivos que nunca saem do computador por upload (segredos e dados do próprio YVAKOR).
_ENVIO_SECRETO = _re.compile(
    r"(^\.env|\.env$|id_rsa|id_ed25519|\.pem$|\.key$|\.pfx$|\.kdbx$|"
    r"credential|secret|senha|password|passwd|token|cookies|login data)", _re.I)


def _checar_arquivo_envio(caminho: str) -> str:
    """'' se o arquivo pode ser enviado a um site; senão, a mensagem de erro."""
    if not str(caminho or "").strip():
        return "informe o caminho do arquivo"
    try:
        p = Path(os.path.expandvars(str(caminho))).expanduser().resolve()
    except OSError:
        return "caminho inválido"
    if not p.is_file():
        return f"arquivo não encontrado: {caminho}"
    if _ENVIO_SECRETO.search(p.name):
        return "este arquivo parece conter segredos; não envio a sites"
    try:
        p.relative_to(ROOT.resolve())
        return "arquivos do próprio YVAKOR não são enviados a sites"
    except ValueError:
        pass
    if p.stat().st_size > ENVIO_MAX_BYTES:
        return "arquivo maior que 5 MB"
    if p.stat().st_size == 0:
        return "arquivo vazio"
    return ""


class ConfirmationBroker:
    """Handshake de confirmação servidor↔navegador, por conversa (sid).

    A thread que processa /api/chat chama request() e bloqueia num Event até
    que outra thread (endpoint /api/confirm) chame resolve(). A interface
    descobre a pendência via /api/progress (campo 'pending') e mostra o popup.

    Além da confirmação de ação protegida (tipo "confirmar"), o mesmo canal
    leva PERGUNTAS do agente ao usuário (tipo "pergunta", com opções) e o
    PLANO para aprovação (tipo "plano"). Interfaces que não conhecem o campo
    'tipo' continuam funcionando como antes (Permitir/Negar).
    """

    TIMEOUT_PERGUNTA = 300.0      # pergunta/plano: o usuário precisa ler e decidir

    def __init__(self, timeout: float = 180.0):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}   # sid -> {id, tipo, action, detail…}
        self._events: dict[str, threading.Event] = {}
        self._results: dict[str, dict] = {}
        self._seq = 0

    def _esperar(self, sid: str, dados: dict, timeout: float) -> dict | None:
        ev = threading.Event()
        with self._lock:
            self._seq += 1
            self._pending[sid] = {"id": self._seq, "tipo": "confirmar", **dados,
                                  "timeout": int(timeout)}
            self._events[sid] = ev
            self._results.pop(sid, None)
        respondeu = ev.wait(timeout)     # False se estourar o tempo
        with self._lock:
            res = self._results.pop(sid, None) if respondeu else None
            self._pending.pop(sid, None)
            self._events.pop(sid, None)
        return res

    def request(self, sid: str, action: str, detail: str) -> bool:
        res = self._esperar(sid, {"action": action, "detail": str(detail)[:300]},
                            self.timeout)
        return bool(res and res.get("allow"))   # sem resposta → nega

    def perguntar(self, sid: str, tipo: str, action: str, detail: str = "",
                  opcoes: list[str] | None = None,
                  timeout: float | None = None) -> dict | None:
        """Pergunta/plano: devolve {"allow", "resposta"} ou None (sem resposta)."""
        return self._esperar(sid, {
            "tipo": tipo, "action": str(action)[:300],
            "detail": str(detail)[:2000],
            "opcoes": [str(o)[:80] for o in (opcoes or [])][:6]},
            float(timeout or self.TIMEOUT_PERGUNTA))

    def pending_for(self, sid: str) -> dict | None:
        with self._lock:
            p = self._pending.get(sid)
            return dict(p, session=sid) if p else None

    def resolve(self, sid: str, allow: bool, resposta: str | None = None) -> bool:
        with self._lock:
            ev = self._events.get(sid)
            if not ev:
                return False
            self._results[sid] = {"allow": bool(allow),
                                  "resposta": (str(resposta).strip()[:1000]
                                               if resposta is not None else None)}
            ev.set()
            return True


class Orchestrator:
    def __init__(self):
        self.settings = load_settings()
        self.router = LLMRouter(self.settings)
        from yvakor.notificacoes import Notificador
        self.notificador = Notificador(self.settings)
        self.episodic = EpisodicMemory(ROOT / self.settings["memory"]["episodic_db"])
        self.semantic = SemanticMemory(ROOT / self.settings["memory"]["semantic_index"])
        self.skills = SkillLibrary(ROOT / self.settings["skills"]["library_path"])
        self.reflection = ReflectionLoop(self.router, self.skills, self.episodic)
        self.absorber = KnowledgeAbsorber(self.router, self.semantic,
                                          self.skills, self.episodic)
        self._abs_lock = threading.Lock()
        self._avaliacao_lock = threading.Lock()
        self.tools = ToolRegistry(self.settings)
        from yvakor.capacidades import register_capacidades_tools
        register_capacidades_tools(self.tools, self.router)
        from yvakor import mercado as _mercado
        from yvakor.mercado import registrar_ferramentas as _reg_mercado
        _reg_mercado(self.tools)
        _mercado.CONECTADO = lambda cid: bool(getattr(self, "connectors", None) and self.connectors.is_connected(cid))
        from yvakor.projetos import GerenciadorProjetos, registrar_ferramentas
        self.projetos = GerenciadorProjetos()
        registrar_ferramentas(self.tools, self.projetos)
        from yvakor.midia import Player, registrar_ferramentas as _reg_midia
        self.midia = Player()
        _reg_midia(self.tools, self.midia)
        from yvakor.mcp import MCPManager
        self.mcp = MCPManager(self.tools)
        try:
            self.mcp.iniciar()
        except Exception as e:
            print(f"  [aviso] MCP indisponível: {e}")
        from yvakor.pesquisa import registrar_ferramentas as _reg_pesquisa
        _reg_pesquisa(self.tools, self.router)
        from yvakor.documentos import registrar_ferramentas as _reg_docs
        _reg_docs(self.tools)
        from yvakor.agenda import Agenda, registrar_ferramentas as _reg_agenda
        self.agenda = Agenda(self)
        _reg_agenda(self.tools, self.agenda)
        from yvakor.colaboracao import registrar_ferramentas as _reg_colab
        _reg_colab(self.tools, self.router)
        from yvakor.entregaveis import registrar_ferramentas as _reg_entregas
        _reg_entregas(self.tools)
        from yvakor.visao import registrar_ferramentas as _reg_visao
        _reg_visao(self.tools)
        if self.projetos.precisa_escanear():
            threading.Thread(target=self.projetos.escanear, daemon=True,
                             name="yvakor-projetos").start()
        from yvakor.notificacoes import register_notificacoes_tools
        register_notificacoes_tools(self.tools, self.notificador)
        register_builtins(self.tools)
        register_arquivos_tools(self.tools)   # acesso total ao sistema de arquivos
        # pensar, checklist, grep e leitura web no estilo das ferramentas do Claude
        from yvakor.ferramentas_claude import register_ferramentas_claude
        register_ferramentas_claude(self.tools)
        # Navegador real (controle de Edge/Chrome). Se o Playwright não estiver
        # instalado, o agente continua funcionando — só sem as ferramentas web.
        # Navegadores reais (Edge + Chrome), cada um com perfil próprio.
        self.browser = None
        self.navegadores: Navegadores | None = None
        try:
            self.navegadores = Navegadores(self.settings)
            register_browser_tools(self.tools, self.navegadores)
            self._usar_extensao_como_alvo()
            self.browser = self.navegadores.sessao()   # compatibilidade
        except Exception as e:
            print(f"  [aviso] navegador indisponível: {e}")
        # Conectores: injeta as ferramentas dos serviços já conectados (e-mail,
        # WhatsApp, GitHub, Telegram…). O agente passa a usá-las quando precisar.
        self.connectors = ConnectorManager(self.tools, ROOT / "data" / "connectors.json")
        # Rede local: descoberta e controle de câmeras, TVs, celulares e IoT.
        self.rede: Rede | None = None
        try:
            self.rede = Rede(self.settings)
            self.monitor_rede = None
            from yvakor.rede.monitor import MonitorRede
            self.rede.monitor = MonitorRede(self.rede, self.settings)
            self.monitor_rede = self.rede.monitor
            if self.settings.get("rede", {}).get("monitoramento", True):
                self.monitor_rede.iniciar()
            register_rede_tools(self.tools, self.rede)
        except Exception as e:
            print(f"  [aviso] rede local indisponível: {e}")
        # Voz: STT local (Vosk) + TTS (edge/SAPI).
        self.voz: AssistenteVoz | None = None
        try:
            self.voz = AssistenteVoz(self, self.settings)
            register_voz_tools(self.tools, self.voz)
            if self.notificador is not None:
                self.notificador.configurar_voz(self.voz.tts)
        except Exception as e:
            print(f"  [aviso] voz indisponível: {e}")

        # Se o processo anterior morreu no meio de uma tarefa, avisa ao subir.
        try:
            marca = ROOT / "data" / "tarefa_em_andamento.json"
            if marca.exists():
                dados = json.loads(marca.read_text(encoding="utf-8"))
                self.notificador.emitir(
                    "Reiniciei e interrompi a tarefa anterior: "
                    + str(dados.get("texto", ""))[:100], "tarefa", 2)
                marca.unlink()
        except Exception:
            pass
        # Cérebro: vault markdown (Obsidian) indexado em FTS5.
        self.cerebro: Cerebro | None = None
        try:
            self.cerebro = Cerebro(self.settings, self.episodic,
                                   self.semantic, self.skills)
            register_cerebro_tools(self.tools, self.cerebro)
            self.cerebro.definir_executor(self.tools)
            from yvakor.ambiente import (
                aprender_equipamento, register_ambiente_tools)
            register_ambiente_tools(self.tools, self.rede, self.cerebro)
            if self.monitor_rede is not None:
                def _aprender_auto(dev, _self=self):
                    aprender_equipamento(_self.rede, _self.cerebro,
                                         dev.get("ip"), sincronizar=True)
                self.monitor_rede.aprendiz = _aprender_auto
            # mantém o vault fresco logo no boot (sem bloquear a subida)
            threading.Thread(target=self.cerebro.sincronizar, daemon=True,
                             name="yvakor-vault-boot").start()
        except Exception as e:
            print(f"  [aviso] cérebro indisponível: {e}")
        self.agent = AgentLoop(self.router, self.tools,
                               max_iterations=self.settings["agent"]["max_iterations"],
                               nativo=self.settings["agent"].get(
                                   "ferramentas_nativas", False),
                               roteador=self.settings["agent"].get(
                                   "router_ferramentas", True),
                               max_ferramentas=int(self.settings["agent"].get(
                                   "max_ferramentas", 14)),
                               timeout_s=int(self.settings["agent"].get(
                                   "timeout_s", 180)),
                               raciocinio=self.settings["agent"].get(
                                   "raciocinio") or {"planejar": True,
                                                     "verificar": True,
                                                     "aprovar_plano": "auto"})
        self.ultimos_artefatos: list[dict] = []
        self.cowork = CoworkManager(self, self.settings)
        self.maintenance = Maintenance(self)
        self.identity_path = ROOT / "identity" / "core_identity.md"
        self.principles_path = ROOT / "identity" / "principles.md"
        # Progresso ao vivo das tarefas (por conversa) p/ a interface acompanhar
        self.progress: dict = {}
        self._prog_lock = threading.Lock()
        # Botão Parar: sessões cuja execução o usuário mandou interromper.
        self._cancel_lock = threading.Lock()
        self._cancelados: set[str] = set()
        # Estado por-requisição (chat e cowork compartilham esta instância e
        # rodam em threads diferentes): a mensagem atual precisa ser isolada
        # por thread, senão os wrappers de navegador/shell de uma requisição
        # leem a mensagem de outra.
        self._tl = threading.local()
        # Confirmação de ações protegidas via interface (popup no navegador)
        # Permissões da extensão do navegador (por site, ações sensíveis).
        self.politica_sites = PoliticaSites()
        # Tempo para o usuário responder ao popup; sem resposta → ação negada.
        # (Era 180s fixos: a conversa ficava "travada" 3 min esperando um aviso
        # que a interface nem sempre mostra.)
        self.confirm_broker = ConfirmationBroker(timeout=float(
            (self.settings.get("tools") or {}).get("confirm_timeout_s", 90)))
        self.telemetria = Telemetria()

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
    def _rotulo_plano(plano: dict) -> str:
        passos = plano.get("passos") or []
        texto = " → ".join(str(p)[:60] for p in passos[:5])
        if len(passos) > 5:
            texto += " → …"
        return f"🧭 Plano: {texto}"

    @staticmethod
    def _rotulo_passo(dado: dict) -> str:
        nome = dado.get("nome", "")
        a = dado.get("args", {}) or {}
        if nome == "tarefas_checklist":
            from yvakor.ferramentas_claude import resumo_checklist
            return resumo_checklist(a.get("itens"))
        if nome == "pensar":
            return "💭 pensando"
        if nome == "perguntar_usuario":
            return f"❓ esperando sua resposta: {str(a.get('pergunta', ''))[:70]}"
        if nome == "arquivos_grep":
            return f"🔎 procurando \"{str(a.get('padrao', ''))[:40]}\" nos arquivos"
        det = (a.get("caminho") or a.get("nome") or a.get("comando")
               or a.get("url") or a.get("doc") or "")
        det = str(det)[:60]
        icones = {
            "listar_diretorio": "📂 listando", "ler_arquivo_local": "📄 lendo",
            "ler_arquivo": "📄 lendo", "escrever_arquivo": "✍️ escrevendo",
            "escrever_arquivo_local": "✍️ escrevendo", "editar_arquivo_local": "✏️ editando",
            "executar_shell": "⌨️ shell", "executar_python": "🐍 python",
            "http_get": "🌐 baixando", "web_ler": "🌐 lendo página",
            "validar_documento": "🔎 validando",
            "converter_xlsx_para_json": "📊 convertendo",
            "gerar_proposta_html": "📝 gerando proposta",
            "extrair_log_docker": "🐳 logs docker",
            "navegador_abrir": "🖥️ abrindo", "navegador_ir": "🖥️ navegando",
            "navegador_ver": "👁️ vendo página", "navegador_clicar": "🖱️ clicando",
            "navegador_preencher": "⌨️ preenchendo", "navegador_pesquisar": "🔍 buscando",
            "navegador_extrair": "📑 extraindo", "navegador_captura": "📸 capturando",
            "navegador_aguardar_captcha": "🧩 esperando você resolver o captcha",
            "navegador_rolar": "🖱️ rolando", "navegador_esperar": "⏱️ esperando",
            "navegador_abas": "🗂️ abas", "navegador_nova_aba": "🗂️ nova aba",
            "navegador_trocar_aba": "🗂️ trocando aba",
            "navegador_fechar_aba": "🗂️ fechando aba",
            "navegador_fechar": "🖥️ fechando navegador",
            "rede_escanear": "🌐 varrendo rede", "rede_dispositivos": "📋 inventário",
            "rede_camera_snapshot": "📷 foto da câmera", "rede_camera_ptz": "🎯 movendo câmera",
            "rede_camera_gravar": "🎥 gravando câmera", "rede_camera_info": "📷 info da câmera",
            "rede_camera_descobrir": "📷 procurando câmeras",
            "rede_cast": "📺 Chromecast", "rede_tv": "📺 TV",
            "rede_telefone_tela": "📱 print do celular", "rede_telefone_acao": "📱 celular",
            "rede_telefone_conectar": "📱 conectando celular",
            "rede_telefone_dispositivos": "📱 celulares",
            "rede_http_dispositivo": "🔌 aparelho HTTP", "rede_mqtt_publicar": "📡 MQTT",
            "rede_mqtt_ler": "📡 lendo MQTT", "rede_wol": "⏻ ligando por rede",
            "voz_falar": "🔊 falando", "voz_ouvir": "🎙️ ouvindo",
            "voz_transcrever": "🎙️ transcrevendo",
            "cerebro_buscar": "🧠 buscando no cérebro",
            "cerebro_sincronizar": "🧠 sincronizando cérebro",
            "cerebro_nota": "🧠 lendo nota", "cerebro_grafo": "🧠 grafo",
            "cerebro_escrever": "🧠 escrevendo nota",
            "arquivos_listar": "📂 listando", "arquivos_ler": "📄 lendo",
            "arquivos_escrever": "✍️ escrevendo", "arquivos_editar": "✏️ editando",
            "arquivos_buscar": "🔎 buscando arquivos", "arquivos_apagar": "🗑️ apagando",
            "arquivos_mover": "📦 movendo", "arquivos_copiar": "📋 copiando",
            "arquivos_zipar": "🗜️ compactando", "arquivos_extrair": "📦 extraindo",
        }
        base = icones.get(nome, f"🔧 {nome}")
        return f"{base} {det}".strip()

    # ------------------------------------------------------------------ #
    # Contexto
    # ------------------------------------------------------------------ #
    def _usar_extensao_como_alvo(self) -> None:
        """Abas padrão na janela do Chrome onde a extensão está aberta."""
        from yvakor.extensao_bridge import PONTE

        def alvo_ext(navegador: str) -> bool:
            # O argumento `navegador` era IGNORADO: as ferramentas dizem "use
            # navegador='edge' para outro navegador", mas só o texto da
            # mensagem decidia. Agora o argumento explícito vale.
            if str(navegador or "").strip().lower() in (
                    "edge", "msedge", "firefox", "playwright", "outro"):
                return False
            msg = getattr(self._tl, "msg_atual", "") or ""
            if _re.search(r"\b(edge|firefox|outro navegador|outra janela|"
                          r"playwright)\b", msg, _re.I):
                return False
            return True

        acoes_com_efeito = {"click", "fill", "type", "press", "select", "upload"}

        def chamar(tipo: str, _orig, **kw) -> dict:
            pol = getattr(self, "politica_sites", None)
            if pol is not None:
                if tipo == "goto":
                    veto = self._permitir_navegacao(pol, kw.get("url", ""))
                    if veto:
                        return veto
                if tipo in acoes_com_efeito:
                    kw["politica"] = pol.para_extensao()
            r = {}
            for _ in range(3):          # site novo e/ou ação sensível: até 2 perguntas
                r = PONTE.comando(tipo, kw)
                pc = r.get("precisa_confirmar")
                if not pc or pol is None:
                    break
                veto = self._confirmar_extensao(pol, pc)
                if veto:
                    return veto
                kw["confirmado_site" if pc.get("tipo") == "site"
                   else "confirmado_acao"] = True
                kw["politica"] = pol.para_extensao()   # a permissão acabou de mudar
            if r.get("precisa_confirmar"):
                return {"ok": False, "erro": "confirmação não concluída"}
            if r.get("ok"):
                r["engine"] = "chrome (extensão)"
            # Captura de tela: a extensão devolve a imagem em base64; vira um
            # arquivo (e some do resultado, para não estourar o contexto).
            if r.get("imagem_b64"):
                import base64
                pasta = ROOT / "data" / "browser_shots"
                pasta.mkdir(parents=True, exist_ok=True)
                arq = pasta / f"extensao_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                arq.write_bytes(base64.b64decode(r.pop("imagem_b64")))
                r["arquivo"] = str(arq)
                # o modelo recebia só o caminho e dizia "não consigo ver a imagem"
                r["dica"] = ("você não vê a imagem: para ler campos/texto da página "
                             "use navegador_ver; para analisar o visual, "
                             f"visao_analisar(caminho='{arq}').")
            return r

        def so_aceitos(fn, kwargs: dict) -> dict:
            """No caminho Playwright, descarta argumentos que a ferramenta
            original não conhece (ex.: 'texto', 'buscador') em vez de dar TypeError."""
            import inspect
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):
                return kwargs
            if any(p.kind == p.VAR_KEYWORD for p in params.values()):
                return kwargs
            return {k: v for k, v in kwargs.items() if k in params}

        # Operações de navegador no mesmo Chrome da extensão.
        # (comando da extensão, campos repassados)
        mapa = {
            "navegador_ir": ("goto", ("url",)),
            "navegador_ver": ("snapshot", ()),
            # era ("selector", …): o argumento da ferramenta é "seletor", então
            # o seletor nunca chegava à extensão.
            "navegador_extrair": ("extract", ("seletor", "max_chars")),
            "navegador_clicar": ("click", ("alvo",)),
            "navegador_preencher": ("fill", ("alvo", "valor", "enviar",
                                             "limpar", "humano")),
            "navegador_pressionar": ("press", ("tecla", "alvo")),
            "navegador_rolar": ("scroll", ("direcao", "vezes", "alvo")),
            "navegador_abas": ("tabs", ()),
            "navegador_pesquisar": ("search", ("termo", "buscador")),
            "navegador_trocar_aba": ("switch_tab", ("indice",)),
            "navegador_fechar_aba": ("close_tab", ("indice",)),
            # estavam no motor Playwright e abriam OUTRO Chrome (o do agente)
            # mesmo com a extensão como alvo:
            "navegador_esperar": ("wait", ("segundos", "seletor", "texto")),
            "navegador_captura": ("screenshot", ()),
        }
        # Argumentos novos de ferramentas que já existiam.
        args_extra = {
            "navegador_preencher": {
                "alvo": "str", "valor": "str", "enviar": "bool?",
                "limpar": "bool?", "humano": "bool?", "navegador": "str?"},
            "navegador_rolar": {"direcao": "str?", "vezes": "int?",
                                "alvo": "str?", "navegador": "str?"},
            "navegador_pesquisar": {
                "termo": "str", "buscador": "str?", "navegador": "str?"},
            "navegador_esperar": {
                "segundos": "float?", "seletor": "str?", "texto": "str?",
                "navegador": "str?"},
        }
        descr_extra = {
            "navegador_abas": " Lista as abas de TODAS as janelas com id, qual é a"
                              " controlada e quais são do grupo YVAKOR. Use o id"
                              " em `aba` de qualquer ferramenta para agir noutra aba.",
            "navegador_trocar_aba": " Passa a CONTROLAR essa aba (as próximas ações"
                                    " valem nela). Aceita indice ou aba (id).",
            "navegador_fechar_aba": " Sem alvo fecha a aba controlada. Só fecha abas"
                                    " do grupo YVAKOR (as que o agente abriu ou passou"
                                    " a controlar), nunca uma aba do usuário.",
            "navegador_pesquisar": " buscador=google|duckduckgo|bing|youtube "
                                   "(padrão google).",
            "navegador_preencher": " limpar=False acrescenta em vez de substituir;"
                                   " enviar=True envia o formulário; funciona em"
                                   " campos comuns, editores de texto rico,"
                                   " caixas de seleção e listas.",
            "navegador_esperar": " Também espera um texto aparecer (texto=...).",
        }
        for nome, (tipo, campos) in mapa.items():
            original = self.tools.tools.get(nome)
            if original is None:
                continue
            spec = self.tools.specs.get(nome, {})
            campos = tuple(campos) + ("aba",)      # id da aba (ver navegador_abas)

            def wrapper(*_args, _orig=original, _tipo=tipo,
                        _campos=campos, **kwargs):
                navegador = kwargs.get("navegador", "")
                if alvo_ext(navegador):
                    dados = {k: kwargs.get(k) for k in _campos
                             if kwargs.get(k) is not None}
                    return chamar(_tipo, _orig, **dados)
                return _orig(*_args, **so_aceitos(_orig, kwargs))

            self.tools.register(
                nome, wrapper,
                (spec.get("desc") or "Navegador.") + descr_extra.get(nome, "")
                + " Usa a janela do Chrome da extensão.",
                {**(args_extra.get(nome) or spec.get("args") or {}),
                 "aba": "int?"})

        # Ferramentas NOVAS (o motor Playwright não as tem): quem as executa é a
        # extensão. (comando, campos, descrição, argumentos, tradução p/ o
        # Playwright quando o usuário pede outro navegador)
        preencher_pw = self.tools.tools.get("navegador_preencher")
        novas = {
            "navegador_digitar": (
                "type", ("alvo", "texto", "enviar", "limpar", "humano"),
                "Digita texto num campo (ACRESCENTA ao que já há; limpar=True "
                "substitui). Sem alvo usa o campo focado/de busca. enviar=True "
                "envia o formulário (Enter). Funciona em editores de texto rico "
                "(Gmail, Notion, chats). humano=True digita letra a letra.",
                {"texto": "str", "alvo": "str?", "enviar": "bool?",
                 "limpar": "bool?", "humano": "bool?", "navegador": "str?"},
                (lambda **k: preencher_pw(
                    alvo=k.get("alvo", ""), valor=k.get("texto", ""),
                    enviar=bool(k.get("enviar")), navegador=k.get("navegador", ""))
                 ) if preencher_pw else None),
            "navegador_selecionar": (
                "select", ("alvo", "valor"),
                "Escolhe uma opção de uma lista <select> (pelo texto ou valor).",
                {"alvo": "str", "valor": "str", "navegador": "str?"},
                (lambda **k: preencher_pw(
                    alvo=k.get("alvo", ""), valor=k.get("valor", ""),
                    navegador=k.get("navegador", ""))
                 ) if preencher_pw else None),
            "navegador_procurar": (
                "find", ("consulta", "max"),
                "Acha elementos da página por DESCRIÇÃO (ex.: 'campo de busca', "
                "'botão comprar', 'link de contato') e devolve só os melhores, "
                "com refs (e1…) para clicar/digitar. Mais leve que navegador_ver "
                "em páginas grandes.",
                {"consulta": "str", "max": "int?", "navegador": "str?"}, None),
            "navegador_passar_mouse": (
                "hover", ("alvo",),
                "Passa o mouse sobre um elemento (abre menus e dicas).",
                {"alvo": "str", "navegador": "str?"}, None),
            "navegador_historico": (
                "history", ("acao",),
                "Voltar, avançar ou recarregar a aba: acao=voltar|avancar|recarregar.",
                {"acao": "str", "navegador": "str?"}, None),
        }
        for nome, (tipo, campos, desc, args, fallback) in novas.items():
            campos = tuple(campos) + ("aba",)
            args = {**args, "aba": "int?"}

            def wrapper_nova(*_args, _tipo=tipo, _campos=campos,
                             _fb=fallback, **kwargs):
                navegador = kwargs.get("navegador", "")
                if alvo_ext(navegador):
                    dados = {k: kwargs.get(k) for k in _campos
                             if kwargs.get(k) is not None}
                    return chamar(_tipo, None, **dados)
                if _fb is not None:
                    return _fb(**kwargs)
                return {"ok": False, "error":
                        "esta ação só existe na extensão do Chrome; o outro "
                        "navegador não a suporta."}

            self.tools.register(nome, wrapper_nova,
                                desc + " Usa a janela do Chrome da extensão.",
                                args)

        # Captcha: o agente NUNCA resolve. Traz a aba para a frente, destaca o
        # captcha, avisa o usuário e espera ELE resolver; aí devolve o controle
        # para o agente clicar em enviar (sem recarregar — isso invalida o captcha).
        def aguardar_captcha(segundos=180, aba=None, navegador: str = "") -> dict:
            if not alvo_ext(navegador):
                return {"ok": False, "error": "aguardar captcha só funciona pela "
                        "extensão do Chrome."}
            try:
                segundos = max(20, min(int(segundos or 180), 600))
            except (TypeError, ValueError):
                segundos = 180
            extra = {"aba": aba} if aba not in (None, "") else {}
            r = PONTE.comando("captcha", {"focar": True, **extra})
            if not r.get("ok", True) and not r.get("presente"):
                return r
            if not r.get("presente"):
                return {"ok": True, "presente": False,
                        "dica": "não há captcha nesta página; siga com o envio."}
            if r.get("resolvido"):
                return {"ok": True, "presente": True, "resolvido": True,
                        "dica": "captcha já resolvido: clique no botão de envio agora, "
                                "sem recarregar nem preencher de novo."}
            aviso = "Resolva o captcha na aba destacada do Chrome — eu continuo sozinho."
            try:
                from yvakor.notificacoes import emitir
                emitir(aviso, "tarefa", 2)
            except Exception:
                pass
            with self._prog_lock:                # aparece no painel de processo
                rodando = [s for s, p in self.progress.items() if p.get("running")]
            for s in rodando:
                self._prog_step(s, "🧩 " + aviso)
            fim = time.time() + segundos
            while time.time() < fim:
                time.sleep(2.0)
                r = PONTE.comando("captcha", extra, espera=20.0)
                if r.get("resolvido"):
                    return {"ok": True, "presente": True, "resolvido": True,
                            "dica": "o usuário resolveu o captcha: clique AGORA no botão "
                                    "de envio (não recarregue, não preencha de novo)."}
                if r.get("ok") and not r.get("presente"):
                    return {"ok": True, "presente": False, "url": r.get("url", ""),
                            "dica": "o captcha sumiu da página (talvez já enviado); "
                                    "use navegador_ver."}
            return {"ok": False, "presente": True, "resolvido": False,
                    "error": f"o captcha não foi resolvido em {segundos}s; peça ao "
                             "usuário para resolver e dizer 'continua'."}

        self.tools.register(
            "navegador_aguardar_captcha", aguardar_captcha,
            "Quando a página tem captcha: traz a aba para a frente, avisa o usuário "
            "e ESPERA ele resolver (você nunca resolve captcha). Chame depois de "
            "preencher os campos; quando voltar resolvido, clique no botão de envio "
            "sem recarregar a página.",
            {"segundos": "int?", "aba": "int?", "navegador": "str?"})

        # Anexar arquivo do computador num <input type=file>. O núcleo lê o arquivo
        # (a página não tem acesso ao disco) e manda em base64; a extensão pergunta
        # SEMPRE ao usuário antes de anexar (ação sensível, nos dois modos).
        def enviar_arquivo(caminho: str = "", alvo: str = "", aba=None,
                           navegador: str = "") -> dict:
            if not alvo_ext(navegador):
                return {"ok": False, "error": "enviar arquivo só funciona pela "
                        "extensão do Chrome."}
            erro = _checar_arquivo_envio(caminho)
            if erro:
                return {"ok": False, "error": erro}
            import base64
            import mimetypes
            p = Path(os.path.expandvars(str(caminho))).expanduser()
            mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            dados = {"alvo": alvo or "", "nome": p.name, "mime": mime,
                     "b64": base64.b64encode(p.read_bytes()).decode("ascii")}
            if aba is not None:
                dados["aba"] = aba
            r = chamar("upload", None, **dados)
            if r.get("ok"):
                r["arquivo"] = str(p)
            return r

        self.tools.register(
            "navegador_enviar_arquivo", enviar_arquivo,
            "Anexa um arquivo do computador a um campo de upload da página "
            "(<input type=file>). caminho = arquivo local (até 5 MB); alvo = ref do "
            "campo ou do botão 'anexar' (opcional se a página tem só um campo). "
            "O usuário sempre confirma. Usa a janela do Chrome da extensão.",
            {"caminho": "str", "alvo": "str?", "aba": "int?", "navegador": "str?"})

        for nome, comando_tipo in (("navegador_abrir", "open"),
                                   ("navegador_nova_aba", "newtab")):
            original = self.tools.tools.get(nome)
            if original is None:
                continue
            spec = self.tools.specs.get(nome, {})

            def wrapper(url: str = "", navegador: str = "",
                        _orig=original, _tipo=comando_tipo):
                if alvo_ext(navegador):
                    # Tarefa em segundo plano (cowork) não troca a aba que o
                    # usuário está vendo; chat interativo continua ativando.
                    ativo = not getattr(self._tl, "segundo_plano", False)
                    pol = getattr(self, "politica_sites", None)
                    if pol is not None and url:
                        veto = self._permitir_navegacao(pol, url)
                        if veto:
                            return {"ok": False, "error": veto["erro"]}
                    r = PONTE.comando(_tipo, {"url": url or "",
                                              "ativo": ativo})
                    if r.get("ok"):
                        r["engine"] = "chrome (extensão)"
                        return r
                    return {"ok": False, "error": r.get("erro") or
                            "a extensão não abriu a aba"}
                return _orig(url=url, navegador=navegador)

            self.tools.register(
                nome, wrapper,
                (spec.get("desc") or "Abre aba no navegador.") +
                " Prioriza a janela do Chrome onde a extensão está aberta; "
                "use navegador='edge' para outro navegador.",
                {"url": "str", "navegador": "str?"})

        # O modelo às vezes tenta abrir navegador via shell; isso furaria a
        # ordem de usar somente o Chrome da extensão. Redireciona para a ponte.
        shell_original = self.tools.tools.get("executar_shell")
        if shell_original is not None:
            def shell_wrapper(comando: str = "", timeout: int = 25,
                              cwd: str | None = None, _orig=shell_original):
                msg = getattr(self._tl, "msg_atual", "") or ""
                if _re.search(r"\b(edge|firefox|outro navegador|outra janela|"
                              r"playwright)\b", msg, _re.I):
                    return _orig(comando, timeout, cwd)
                if _re.search(r"\b(msedge|chrome|firefox|brave)\b", comando or "",
                              _re.I) or _re.search(r"\bstart\s+https?://",
                                                   comando or "", _re.I):
                    return {"ok": False, "error":
                            "Não abra navegador pelo shell. Use navegador_abrir "
                            "para abrir na janela da extensão."}
                return _orig(comando, timeout, cwd)
            self.tools.register("executar_shell", shell_wrapper,
                                "Executa shell. Bloqueia abrir navegador fora "
                                "da janela da extensão.",
                                {"comando": "str", "timeout": "int?",
                                 "cwd": "str?"})

    def build_system_prompt(self, user_message: str,
                            extra_context: str | None = None) -> str:
        identity = self.identity_path.read_text(encoding="utf-8")[:5000]
        principles = self.principles_path.read_text(encoding="utf-8")[:3000]
        relevant_skills = self.skills.find_relevant(user_message, top_k=2)
        memories = self.semantic.search(user_message, top_k=3)

        regras = (
            "## REGRAS DE RESPOSTA\n"
            "- Use o contexto apenas se ele responder DIRETAMENTE à pergunta; "
            "ignore o que for tangencial.\n"
            "- Se não houver informação suficiente, diga que não sabe. "
            "Nunca invente fatos, caminhos, resultados ou passos executados.\n"
            "- Para pedidos de ação, execute a ferramenta; não responda com "
            "instruções genéricas.\n"
            "- Seja autônomo: assuma o objetivo e execute até o fim. Não peça "
            "permissão para ler, pesquisar, navegar, gerar arquivo, gráfico ou "
            "imagem. Só confirme ações destrutivas/irreversíveis.\n"
            "- Se uma ferramenta falhar, tente uma alternativa sozinho (outra "
            "fonte, outro formato, fallback) antes de desistir.\n"
            "- Não pare no primeiro obstáculo nem entregue só um plano: "
            "entregue o resultado concreto.\n"
            "- Se o pedido estiver claro, aja imediatamente; não termine com "
            "“posso fazer?” nem peça autorização para o óbvio.\n"
            "- Só afirme que fez algo se houver observação de ferramenta "
            "confirmando.\n"
            "- Em conversa simples, responda em no máximo 3 frases. Não "
            "cumprimente, não repita a pergunta e não explique o que vai fazer.\n"
            "- Em análise/entrega, use no máximo 5 tópicos curtos + conclusão; "
            "detalhes vão no arquivo, não no chat.\n"
            "- Não termine com ofertas (“se quiser”, “posso...”, “fico à "
            "disposição”) nem faça perguntas que o usuário não pediu.\n"
            "- Quando pedirem foto, gráfico, planilha, relatório, documento ou "
            "arquivo, GERE o entregável com a ferramenta e entregue o link; não "
            "apenas descreva o que seria possível.\n"
            "- Você TEM a ferramenta buscar_foto para fotos reais; use-a em vez "
            "de dizer que não consegue buscar imagens. Se não houver foto, ela "
            "gera uma imagem de fallback.\n"
            "- Em entregas, feche com um resumo do que foi gerado e o link.\n"
            "- Conversa contínua: em mensagens curtas de continuação "
            "(“e agora?”, “isso”, “ele”, “sim”, “não”, “faça”), use os turnos "
            "anteriores; não peça ao usuário para repetir o contexto.")
        parts = [identity, principles, regras]
        try:
            from yvakor.ajustes import bloco_perfil
            if bloco_perfil():
                parts.append(bloco_perfil())
        except Exception:
            pass
        if relevant_skills:
            parts.append("## SKILLS RELEVANTES (siga estes procedimentos)\n"
                         + "\n---\n".join(s[:1200] for s in relevant_skills))
        if memories:
            parts.append("## MEMÓRIAS RELEVANTES\n"
                         + "\n".join(f"- {m[:300]}" for m in memories))
        if extra_context:
            orcamento = int(self.settings.get("contexto", {}).get(
                "max_caracteres", 9000))
            parts.append(extra_context[:orcamento])
            if "PÁGINA ATUAL DO CHROME" in extra_context:
                parts.append(
                    "## COMO RESPONDER SOBRE A PÁGINA\n"
                    "- Baseie a resposta no conteúdo acima; não invente o que "
                    "não está nele.\n"
                    "- Cite a seção/título quando ajudar a localizar a informação.\n"
                    "- Se a resposta não estiver na página, diga claramente e "
                    "ofereça o próximo passo.\n"
                    "- A página já foi lida automaticamente. NUNCA peça print, "
                    "screenshot ou para o usuário colar o conteúdo; analise o "
                    "contexto recebido.")
        if _re.search(r"\b(abre|abra|navegue|acesse|clique|preencha|pesquise|"
                      r"digite|site|p[aá]gina|navegador|chrome|youtube|preench\w*|"
                      r"consult\w*|captcha|formul[aá]rio)\b",
                      user_message or "", _re.I):
            parts.append(
                "## MODO NAVEGADOR\n"
                "- Execute a intenção INTEIRA (abrir + pesquisar + clicar + "
                "preencher), não pare na primeira ação.\n"
                "- Depois de cada ação, use navegador_ver ou leia o retorno para "
                "confirmar URL, título e conteúdo.\n"
                "- A interação é visível: cursor, clique e digitação acontecem "
                "na página.\n"
                "- Nunca use executar_shell para abrir navegador; use "
                "navegador_abrir. O padrão é a janela da extensão; só use Edge "
                "se o usuário pedir.\n"
                "- Só finalize quando o objetivo estiver confirmado; se um "
                "caminho falhar, tente outro sozinho.\n"
                "- CAPTCHA: você nunca resolve. Preencha os campos, chame "
                "navegador_aguardar_captcha e, quando voltar resolvido, clique no "
                "botão de envio. Depois de resolvido NÃO recarregue nem preencha de "
                "novo (isso invalida o captcha).")
        try:
            from yvakor.extensao_bridge import PONTE as _ponte_st
            if _ponte_st.disponivel():
                parts.append(
                    "## ESTADO DO NAVEGADOR (agora)\n"
                    "- A extensão YVAKOR do Chrome está CONECTADA: você controla o "
                    "Chrome do usuário, com os logins dele (Gmail, bancos de dados "
                    "web, redes sociais…), pelas ferramentas navegador_*.\n"
                    "- Nunca diga que a extensão não responde sem ter chamado uma "
                    "ferramenta NESTA resposta; falhas de mensagens antigas já "
                    "foram resolvidas.")
        except Exception:
            pass
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
            banco = r.get("banco", {})
            tamanhos = banco.get("tamanhos_mb", {})
            return ("🔧 Manutenção concluída.\n"
                    f"- Skills promovidas a estáveis: {', '.join(est) or 'nenhuma'}\n"
                    f"- Memória: {r['conhecimento'].get('memoria', {})}\n"
                    f"- Banco: {banco.get('podados', {}).get('removidos', 0)} "
                    f"registros podados · "
                    f"índices otimizados ({', '.join(f'{k} {v} MB' for k, v in tamanhos.items())})\n"
                    f"- Código: {cod.get('estado')} — {cod.get('motivo')}")

        if low.startswith("[cowork-resultado]"):
            tid = msg.split("]", 1)[1].strip()
            return self.cowork.result(tid)

        if low.startswith("[cowork-status]"):
            tid = msg.split("]", 1)[1].strip() or None
            return self.cowork.status(tid)

        if low.startswith("[cowork-cancelar]"):
            tid = msg.split("]", 1)[1].strip()
            if not tid:
                return "Uso: [cowork-cancelar] <id-da-tarefa>"
            r = self.cowork.cancel(tid)
            return ("⏹ Cancelamento solicitado." if r.get("ok")
                    else f"❌ {r.get('erro')}")

        if low.startswith("[cowork]"):
            desc = msg.split("]", 1)[1].strip()
            if not desc:
                return "Uso: [cowork] <descrição da tarefa>"
            t = self.cowork.submit(desc)
            return (f"🚀 Tarefa cowork disparada: {t['id']}\n"
                    f"   Descrição: {desc}\n"
                    f"   Workspace: {t.get('workspace')}\n"
                    f"   Use [cowork-status] {t['id']} para acompanhar.")

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
    def process(self, user_message: str, session_id: str | None = None,
                should_stop=None, extra_context: str | None = None,
                on_event=None, private: bool = False,
                history_override: list[dict] | None = None) -> str:
        """Processa uma mensagem; `private` não grava nada no histórico."""
        sid = session_id or getattr(self.episodic, "active_id", "default")
        with self._cancel_lock:
            self._cancelados.discard(sid)      # execução nova começa limpa

        def parar() -> bool:
            # botão Parar (cancelar(sid)) OU o should_stop de quem chamou (cowork)
            return (sid in self._cancelados) or bool(should_stop and should_stop())

        try:
            self.episodic.modo_privado(private)
            return self._process_impl(
                user_message, session_id=session_id, should_stop=parar,
                extra_context=extra_context, on_event=on_event,
                private=private, history_override=history_override)
        finally:
            with self._cancel_lock:
                self._cancelados.discard(sid)
            try:
                self.episodic.modo_privado(False)
            except Exception:
                pass

    def cancelar(self, sid: str | None = None) -> list[str]:
        """Botão Parar. Sem `sid`, interrompe TODA execução em andamento.

        Além de marcar a sessão (o agente confere entre os passos), destrava o
        que a deixaria parada: uma confirmação pendente (nega) e comandos
        esperando a extensão do navegador (abortam na hora).
        """
        with self._prog_lock:
            alvos = ([s for s, p in self.progress.items() if p.get("running")]
                     if sid is None else [sid])
        with self._cancel_lock:
            self._cancelados.update(alvos)
        for s in alvos:
            try:
                self.confirm_broker.resolve(s, False)
            except Exception:
                pass
        try:
            from yvakor.extensao_bridge import PONTE
            PONTE.cancelar_pendentes()
        except Exception:
            pass
        return alvos

    def _process_impl(self, user_message: str, session_id: str | None = None,
                      should_stop=None, extra_context: str | None = None,
                      on_event=None, private: bool = False,
                      history_override: list[dict] | None = None) -> str:
        """Processa uma mensagem.

        session_id: sessão onde ler/gravar o histórico. None = conversa ativa.
                    Tarefas cowork passam a própria sessão (isolada).
        should_stop: callable → True interrompe entre passos (cancelamento).
        extra_context: texto extra injetado no system prompt (ex.: workspace
                    e orçamento de passos de uma tarefa cowork).
        """
        # Comandos especiais só fazem sentido na conversa interativa.
        if session_id is None and not private:
            special = self.handle_special(user_message)
            if special is not None:
                return special

        sid = session_id or getattr(self.episodic, "active_id", "default")
        inicio = time.time()
        self._tl.msg_atual = user_message
        from yvakor.extensao_bridge import PONTE as _ponte
        _ponte.permitir_outro = bool(_re.search(
            r"\b(edge|firefox|outro navegador|outra janela|playwright)\b",
            user_message or "", _re.I))
        passos = {"n": 0}
        self.ultimos_artefatos = []

        # Chamada pelo nome: responde na hora; com pedido junto, remove o nome.
        from yvakor.nome import separar as _separar_nome
        _chamou, _resto = _separar_nome(user_message)
        if _chamou:
            if not _resto:
                resposta = "Estou aqui. Pode falar."
                self.episodic.log("conversa", user_message, resposta,
                                  session_id=sid)
                return resposta
            user_message = _resto

        # Intenções diretas de texto (hora, data, status…), sem IA.
        from yvakor.voz.diretos import detectar as _dd, executar as _de
        _int = _dd(user_message)
        if _int:
            _resp = _de(self, _int, getattr(self, "ultima_resposta", ""))
            self.ultima_resposta = _resp
            self.episodic.log("conversa", user_message, _resp, session_id=sid)
            return _resp

        # Navegação direta: abrir site/diagnosticar navegador, sem IA.
        try:
            from yvakor.voz.navegacao import detectar as _dn, executar as _en
            _int_nav = _dn(user_message)
            if _int_nav and _int_nav.get("acao") == "abrir_e_continuar":
                # "abre o gmail e verifica…": abre agora e o agente cuida do resto
                _abriu = _en(self, {"acao": "abrir", "url": _int_nav["url"],
                                    "motor": _int_nav.get("motor", "")})
                if str(_abriu).startswith("Não consegui"):
                    self.episodic.log("conversa", user_message, _abriu,
                                      session_id=sid)
                    return _abriu
                self._prog_step(sid, f"🌐 abri {_int_nav['url']}")
                user_message = (f"{_int_nav['resto']}\n\n(Contexto: eu JÁ abri "
                                f"{_int_nav['url']} no Chrome; a página atual é essa. Use "
                                "navegador_ver ou navegador_extrair para ler e, se preciso, "
                                "navegador_clicar/navegador_digitar. NÃO abra de novo.)")
                self._tl.msg_atual = user_message
            elif _int_nav:
                _resp = _en(self, _int_nav)
                self.ultima_resposta = _resp
                self.episodic.log("conversa", user_message, _resp,
                                  session_id=sid)
                return _resp
        except Exception:
            pass

        # Comando de rede por texto: executa direto (sem IA), como na voz.
        try:
            from yvakor.voz.rede import detectar as _dr, executar as _er
            if _dr(user_message):
                _r = _er(self, user_message)
                _resp = _r.get("fala") or "Comando de rede executado."
                self.episodic.log("conversa", user_message, _resp,
                                  session_id=sid)
                try:
                    self.telemetria.registrar(
                        "rede", (time.time() - inicio) * 1000,
                        detalhe=_r.get("acao", ""))
                except Exception:
                    pass
                return _resp
        except Exception:
            pass

        # Aprendiz de entorno por texto (mapear/ficha), direto.
        try:
            from yvakor.voz.ambiente import detectar as _da, executar as _ea
            if _da(user_message):
                _ra = _ea(self, user_message)
                _resp = _ra.get("fala") or "Ambiente atualizado."
                self.episodic.log("conversa", user_message, _resp,
                                  session_id=sid)
                return _resp
        except Exception:
            pass

        # Desenvolvimento completo: gera, salva e abre o projeto.
        try:
            from yvakor.voz.desenvolvimento import detectar as _dd, executar as _ed
            if _dd(user_message):
                _rd = _ed(self, user_message)
                _resp = _rd.get("fala") or "Projeto gerado."
                self.episodic.log("conversa", user_message, _resp,
                                  session_id=sid)
                return _resp
        except Exception:
            pass

        # ---- Cérebro primeiro: conhecimento antes de gastar IA ----
        decisao = None
        try:
            from yvakor.conversa import eh_continuacao
            continuacao = eh_continuacao(user_message)
        except Exception:
            continuacao = False
        tem_anexos = bool(extra_context and (
            "ANEXOS ENVIADOS" in extra_context
            or "PÁGINA ATUAL DO CHROME" in extra_context))
        quer_memoria = bool(_re.search(
            r"\b(lembra|lembrar|mem[oó]ria|recorda|anterior|conversa|sess[aã]o|"
            r"nota|skill|receita|projeto|falamos|sabe sobre|o que você sabe)\b",
            user_message or "", _re.I))
        if (not continuacao and not private and not tem_anexos and quer_memoria
                and self.cerebro is not None
                and self.settings.get("cerebro", {}).get("resposta_direta", True)):
            try:
                decisao = self.cerebro.decidir(user_message)
            except Exception:
                decisao = None

        if decisao and decisao.get("modo") == "cerebro":
            resposta = decisao["resposta"]
            self._prog_start(sid)
            self._prog_step(sid, "🧠 respondido pelo cérebro (sem IA)")
            self._prog_done(sid)
            self.episodic.log("conversa", user_message, resposta, session_id=sid)
            try:
                self.cerebro.registrar_origem("cerebro")
                self._sincronizar_cerebro_async()
            except Exception:
                pass
            try:
                self.telemetria.registrar(
                    "cerebro", (time.time() - inicio) * 1000,
                    detalhe="resposta direta do vault/memória")
            except Exception:
                pass
            return resposta

        if decisao and decisao.get("modo") == "receita":
            receita = decisao["receita"]
            simular = bool(self.settings.get("cerebro", {}).get(
                "receitas_simular", False))
            r = self.cerebro.executar_receita(receita, user_message, simular)
            if r.get("ok"):
                if r.get("simulado"):
                    resposta = (f"🧪 Simulação da receita **{receita.nome}** "
                                f"(nada foi executado):\n```json\n"
                                f"{json.dumps(r.get('plano'), ensure_ascii=False, indent=2)[:1500]}\n```")
                else:
                    ultimo = (r.get("resultados") or [{}])[-1]
                    resposta = (f"✅ Receita **{receita.nome}** executada em "
                                f"{r.get('passos')} passo(s).\n\n"
                                f"```json\n{json.dumps(ultimo, ensure_ascii=False)[:1200]}\n```")
            else:
                detalhe = r.get("erro") or "; ".join(r.get("erros") or [])
                resposta = f"⚠️ Receita **{receita.nome}** não executou: {detalhe}"
            self._prog_start(sid)
            self._prog_step(sid, f"⚙️ receita: {receita.nome}")
            self._prog_done(sid)
            self.episodic.log("conversa", user_message, resposta, session_id=sid)
            try:
                self.cerebro.registrar_origem("receita")
                self._sincronizar_cerebro_async()
            except Exception:
                pass
            try:
                self.telemetria.registrar(
                    "receita", (time.time() - inicio) * 1000,
                    ferramentas=len(receita.passos),
                    detalhe=receita.nome)
            except Exception:
                pass
            return resposta

        contexto_cerebro = decisao.get("contexto") if decisao else None
        forcar = "ollama" if (decisao and decisao.get("modo") == "local") else None

        # Local PRIMEIRO: mensagens simples (sem verbo de ação, curtas, sem
        # palavra-chave de tarefa profunda) são respondidas pelo modelo local.
        # Tarefas profundas (código, análise, pesquisa) e qualquer coisa que
        # exija ferramentas vão para o loop do agente no DeepSeek. Se o local
        # falhar/vier vazio, o bloco abaixo zera 'forcar' e cai no agente.
        _tipo_simples = self.router.classify(user_message)
        # Pergunta sobre a página/arquivo em foco (extra_context) precisa do
        # conteúdo completo → vai para o agente (DeepSeek), não para o 3B local,
        # que aqui responderia sem ver a página.
        # No modo "deepseek" o usuário pediu a nuvem primeiro: sem atalho local.
        # Pedido de AÇÃO no navegador (pesquisar, clicar, preencher…) precisa do
        # loop com ferramentas e de um modelo forte: nunca pega o atalho do 3B,
        # que só conversa. (No modo "local" o usuário escolheu o local de qualquer
        # forma — o roteador não chama a nuvem.)
        _acao_navegador = bool(AgentLoop._INTENCAO_NAVEGADOR.search(user_message))
        if (forcar is None and not extra_context
                and self.router.modo != "deepseek"
                and not (_acao_navegador and self.router.modo == "auto")
                and _tipo_simples in (
                    "resposta_simples", "resumo_curto", "classificacao")):
            forcar = "ollama"

        # Caminho local rápido: prompt curto, sem ferramentas. O 3B em CPU não
        # aguenta o prompt completo do agente (travava 4-6 minutos).
        if forcar == "ollama":
            try:
                self._prog_start(sid)
                resposta_local = self.router.complete_messages(
                    "resposta_simples",
                    self._mensagens_local(sid, user_message, contexto_cerebro),
                    forcar="ollama").strip()
                # Só aceita a resposta local se passar na verificação de
                # qualidade; senão cai no agente (DeepSeek) logo abaixo.
                if resposta_local and self._resposta_local_ok(
                        resposta_local, user_message):
                    self._prog_done(sid)
                    self.episodic.log("conversa", user_message, resposta_local,
                                      session_id=sid)
                    if self.cerebro is not None:
                        try:
                            self.cerebro.registrar_origem("local")
                        except Exception:
                            pass
                    try:
                        self.telemetria.registrar(
                            "local", (time.time() - inicio) * 1000,
                            provedor="ollama", ferramentas=0)
                    except Exception:
                        pass
                    self._sincronizar_cerebro_async()
                    return resposta_local
                self._prog_done(sid)
                forcar = None
            except Exception:
                self._prog_done(sid)
                forcar = None

        # Nuvem fora (ex.: DeepSeek HTTP 402 sem saldo)? Um probe barato decide
        # ANTES do 1º passo do agente — senão ele gastaria um prompt pesado
        # (~110s no 3B) numa tentativa que já se sabe que vai falhar.
        modo_local = False
        if forcar != "ollama":
            try:
                modo_local = not self.router.verificar_externos()
            except Exception:
                modo_local = False
        if modo_local:
            system = self._system_compacto(user_message, extra_context,
                                           contexto_cerebro)
            forcar = "ollama"
        else:
            system = self.build_system_prompt(
                user_message,
                self._juntar_contexto(extra_context, contexto_cerebro))
        task_type = self.router.classify(user_message)
        self._prog_start(sid)
        if modo_local:
            self._prog_step(sid, "🧠 DeepSeek indisponível — usando o modelo local "
                                 "(mais lento)")

        # Loop de agente: a IA decide e executa ferramentas (Claude Code-like).
        # A continuidade vem do histórico REAL da conversa (turnos user/assistant),
        # não mais de um resumo truncado no system prompt.
        def _trace(tipo, dado):
            if on_event is not None:
                try:
                    on_event(tipo, dado)
                except Exception:
                    pass
            if tipo == "ferramenta":
                passos["n"] += 1
                label = self._rotulo_passo(dado)
                self._prog_step(sid, label)
                self.episodic.log("ferramenta", dado.get("nome", ""),
                                  str(dado.get("args", ""))[:500],
                                  session_id=sid)
                # Feedback ao vivo no terminal (CLI)
                try:
                    print(f"\n  {label}", flush=True)
                except Exception:
                    pass
            elif tipo == "plano" and isinstance(dado, dict):
                self._prog_step(sid, self._rotulo_plano(dado))
            elif tipo == "aprovacao_plano":
                self._prog_step(sid, "📋 esperando você aprovar o plano")
            elif tipo == "observacao" and isinstance(dado, dict):
                res = dado.get("resultado", {})
                if isinstance(res, dict) and not res.get("ok", True):
                    try:
                        print(f"    ⚠ {res.get('error', res.get('erro', 'falha'))[:120]}",
                              flush=True)
                    except Exception:
                        pass

        history = (list(history_override) if history_override is not None
                   else self.episodic.history_messages(
                       self.settings["memory"]["episodic_context_last_n"],
                       session_id=sid))
        history = self._sanear_falhas_antigas(history)
        history.append({"role": "user", "content": user_message})
        if modo_local:
            history = history[-5:]   # prompt menor = passo bem mais rápido no 3B

        # Ações protegidas pedem confirmação via interface (popup no navegador),
        # roteadas pelo broker para ESTA sessão (conversa ou tarefa cowork).
        from yvakor.tools.guard import set_thread_confirmer, clear_thread_confirmer
        def _confirmar(action, detail):
            # Deixa claro no painel de processo POR QUE a conversa parou.
            self._prog_step(
                sid, f"⏳ Aguardando sua confirmação: {action} "
                     f"(negada em {int(self.confirm_broker.timeout)}s sem resposta)")
            return self.confirm_broker.request(sid, action, detail)
        set_thread_confirmer(_confirmar)
        # Mesmo canal para perguntas do agente (perguntar_usuario) e para a
        # aprovação do plano (modo plano): ver yvakor/interacao.py.
        from yvakor import interacao
        def _perguntar(tipo, titulo, detalhe, opcoes):
            try:
                from yvakor.notificacoes import emitir
                emitir("YVAKOR está esperando sua resposta: " + str(titulo)[:120],
                       "tarefa", 2)
            except Exception:
                pass
            return self.confirm_broker.perguntar(sid, tipo, titulo, detalhe, opcoes)
        interacao.definir(_perguntar)
        try:
            answer = self.agent.run(system, history=history, on_event=_trace,
                                    should_stop=should_stop,
                                    forcar_provider=forcar,
                                    compacto=modo_local)
            # Lista local desta resposta (agent.artefatos é thread-local, lido
            # na MESMA thread) — garante que os entregáveis anexados são os
            # desta execução, não os de outra tarefa concorrente.
            artefatos = list(getattr(self.agent, "artefatos", []))
            self.ultimos_artefatos = artefatos  # compat UI/voz (melhor esforço)
            answer = self._completar_entregaveis(answer, artefatos)
            answer = self._podar_resposta(answer, user_message, task_type,
                                          artefatos)
        finally:
            clear_thread_confirmer()
            interacao.limpar()
            self._prog_done(sid)

        self.episodic.log("conversa", user_message, answer, session_id=sid)
        # Título automático só na conversa do usuário (sessões de tarefa têm
        # nome próprio e não devem ser renomeadas).
        # (app e extensão podem estar em conversas diferentes: vale o sid da mensagem)
        if session_id is None or sid == self.episodic.active_id or self._eh_chat(sid):
            self.episodic.maybe_autotitle(user_message, session_id=sid)

        # Aprendizado automático: avalia a resposta e SÓ absorve fatos/destila
        # skills se a nota for boa (a nota 1-5 agora gateia o aprendizado, em
        # vez de ser apenas gravada em avaliacoes.jsonl).
        if self.settings["agent"]["reflection_enabled"] and not private:
            threading.Thread(target=self._aprender_fundo,
                             args=(user_message, answer, task_type),
                             daemon=True, name="yvakor-aprender").start()
        elif (self.settings["agent"].get("avaliar_auto") and not private
              and (not self.router.sem_externos()
                   or self.settings["agent"].get("aprender_local", False))):
            # Reflexão desligada: ainda avaliamos (telemetria de qualidade).
            threading.Thread(target=self._avaliar_fundo,
                             args=(user_message, answer),
                             daemon=True, name="yvakor-avaliar").start()

        if self.cerebro is not None:
            try:
                self.cerebro.registrar_origem("local" if forcar else "api")
            except Exception:
                pass
        try:
            self.telemetria.registrar(
                "local" if forcar else "api",
                (time.time() - inicio) * 1000,
                provedor="ollama" if forcar else "deepseek",
                ferramentas=passos["n"])
        except Exception:
            pass
        # Obsidian quase em tempo real: sincroniza no máximo a cada 2 min.
        self._sincronizar_cerebro_async()
        return answer

    def _eh_chat(self, sid: str | None) -> bool:
        """Conversa do usuário (não sessão de tarefa cowork, que tem nome próprio)."""
        try:
            row = self.episodic.conn.execute(
                "SELECT COALESCE(kind,'chat') FROM sessions WHERE id=?", (sid,)).fetchone()
            return bool(row) and row[0] == "chat"
        except Exception:
            return False

    _FALHA_EXTENSAO = _re.compile(
        r"extens[aã]o[^\n]{0,80}(n[aã]o (est[aá] )?respond|sem responder|"
        r"n[aã]o respondeu|continua sem|n[aã]o conect|desconect)|"
        r"n[aã]o tenho (nenhuma )?ferramenta de navegador", _re.I)
    NOTA_FALHA_ANTIGA = ("(Resposta antiga omitida: naquele momento o navegador "
                         "falhou. Isso já foi resolvido — a extensão está "
                         "conectada agora; use as ferramentas de navegador.)")

    def _sanear_falhas_antigas(self, history: list[dict]) -> list[dict]:
        """Com a extensão conectada, respostas antigas do tipo "a extensão não
        está respondendo" viram uma nota curta. Antes o modelo lia essas
        respostas no histórico e as repetia sem chamar nenhuma ferramenta."""
        try:
            from yvakor.extensao_bridge import PONTE as _p
            if not _p.disponivel():
                return history
        except Exception:
            return history
        saida = []
        for item in history:
            texto = item.get("content")
            if (item.get("role") == "assistant" and isinstance(texto, str)
                    and self._FALHA_EXTENSAO.search(texto)):
                item = {**item, "content": self.NOTA_FALHA_ANTIGA}
            saida.append(item)
        return saida

    # ------------------------------------------------------------------ #
    # Caminho local (modelo pequeno): prompt e controle de qualidade
    # ------------------------------------------------------------------ #
    def _mensagens_local(self, sid: str, pergunta: str,
                         contexto: str | None) -> list[dict]:
        """Prompt do modelo local: identidade enxuta, data e os últimos turnos.
        Antes só ia a pergunta solta — sem histórico, "e agora?", "isso" e
        qualquer continuação de conversa eram respondidos sem contexto."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        sistema = (
            "Você é o YVAKOR, assistente pessoal do usuário. Responda em "
            "português do Brasil, de forma direta, correta e natural, sem "
            "cumprimentos desnecessários nem repetir a pergunta. Se não souber "
            "ou não tiver como saber, diga isso claramente em vez de inventar. "
            f"Agora são {agora}. Não use JSON, ferramentas nem comandos.")
        if contexto:
            sistema += ("\n\nContexto conhecido (use só se responder à "
                        "pergunta):\n" + contexto[:1500])
        msgs: list[dict] = [{"role": "system", "content": sistema}]
        try:
            historico = self.episodic.history_messages(6, session_id=sid)
        except Exception:
            historico = []
        for m in (historico or [])[-6:]:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                msgs.append({"role": m["role"],
                             "content": str(m["content"])[:600]})
        msgs.append({"role": "user", "content": pergunta})
        return msgs

    # ------------------------------------------------------------------ #
    # Permissões da extensão (site novo / ação sensível)
    # ------------------------------------------------------------------ #
    def _confirmar_extensao(self, pol, pc: dict) -> dict | None:
        """Pergunta ao usuário (popup do painel/janela). None = permitido;
        senão devolve o resultado de erro. Sem confirmador (fora de uma
        conversa) NEGA: na dúvida, não age."""
        from yvakor.tools.guard import _thread_confirmer
        host = pc.get("host", "")
        site = pc.get("tipo") == "site"
        if site:
            acao = f"Permitir que o YVAKOR aja em {host}"
            detalhe = ("Ele poderá clicar, digitar e navegar neste site. A "
                       "permissão fica salva e pode ser revogada no painel."
                       + (" Atenção: site de banco/pagamento." if pc.get("host_sensivel") else ""))
        else:
            acao = pc.get("descricao") or "Ação sensível"
            detalhe = f"Em {host}. Motivo: {pc.get('motivo') or 'ação sensível'}."
        fn = _thread_confirmer()
        try:
            ok = bool(fn(acao, detalhe)) if fn else False
        except Exception:
            ok = False
        if ok:
            if site and host:
                pol.permitir(host)
            return None
        if site and host:
            pol.bloquear(host, so_nesta_sessao=True)   # "negar" vale até reiniciar
        return {"ok": False, "negado": True,
                "erro": f"O usuário não permitiu: {acao}."}

    def _permitir_navegacao(self, pol, url: str) -> dict | None:
        """Navegar para um site novo pede permissão (buscadores são livres)."""
        h = host_de(url)
        if h and pol.bloqueado(h):
            return {"ok": False, "negado": True,
                    "erro": f"O usuário bloqueou o YVAKOR em {h}."}
        alvo = pol.precisa_perguntar_navegacao(url)
        if alvo is None:
            return None
        return self._confirmar_extensao(
            pol, {"tipo": "site", "host": alvo, "host_sensivel": pol.sensivel(alvo)})

    def _system_compacto(self, pergunta: str, extra_context: str | None,
                         contexto_cerebro: str | None) -> str:
        """System prompt enxuto do agente LOCAL (~0,5k em vez de ~9k caracteres)."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        partes = [
            "Você é o YVAKOR, assistente pessoal do usuário, rodando no PC dele "
            "(Windows). Responda em português do Brasil, direto. Aja em vez de "
            "perguntar; só afirme que fez algo se uma ferramenta confirmou; se "
            f"não souber, diga. Agora são {agora}."]
        try:
            from yvakor.ajustes import bloco_perfil
            if bloco_perfil():
                partes.append(bloco_perfil()[:700])
        except Exception:
            pass
        if contexto_cerebro:
            partes.append("Contexto conhecido:\n" + contexto_cerebro[:600])
        if extra_context:
            partes.append(extra_context[:1500])
        return "\n\n".join(partes)

    _RECUSA_LOCAL = _re.compile(
        r"(como (um )?(modelo|assistente|ia)\b.{0,40}(linguagem|ia\b)|"
        r"n[ãa]o tenho acesso|n[ãa]o consigo acessar|n[ãa]o posso acessar|"
        r"as an ai|i('m| am) sorry|sou apenas um modelo)", _re.I)

    @classmethod
    def _resposta_local_ok(cls, resposta: str, pergunta: str) -> bool:
        """Rede de segurança do modelo pequeno: rejeita resposta vazia, JSON de
        ferramenta vazado, laço repetitivo, resposta curta demais para uma
        pergunta elaborada e recusas genéricas. Reprovada → vai ao agente."""
        r = (resposta or "").strip()
        if len(r) < 2:
            return False
        if r.startswith("{") and ('"acao"' in r or '"ferramenta"' in r):
            return False
        linhas = [x.strip() for x in r.splitlines() if x.strip()]
        if len(linhas) >= 4 and len(set(linhas)) <= max(1, len(linhas) // 3):
            return False
        if len(_re.findall(r"\w+", pergunta or "")) >= 6 and len(r) < 12:
            return False
        if cls._RECUSA_LOCAL.search(r):
            return False
        return True

    def _podar_resposta(self, texto: str, pergunta: str, task_type: str,
                        artefatos: list[dict]) -> str:
        """Remove preâmbulo/ofertas e limita resposta simples."""
        import re
        t = (texto or "").strip()
        if not t:
            return t
        t = re.sub(r"^(?:claro|certamente|com certeza|perfeito|ótimo|otimo)"
                   r"[!,.]?\s*", "", t, flags=re.I)
        t = re.sub(r"^(?:vou|vamos|aqui está|aqui esta|segue)\b[^\n.!?]*[.!?]\s*",
                   "", t, flags=re.I)
        t = re.sub(r"\n+(?:se quiser|caso (?:queira|precise)|posso (?:também|"
                   r"tambem|ajudar)|quer que eu|fico à disposição|fico a "
                   r"disposicao)[\s\S]*$", "", t, flags=re.I).rstrip()
        # Pedido explicativo ou resposta já estruturada (lista/parágrafos) NÃO
        # pode ser cortada em 3 frases: antes "como funciona X?" e listas
        # legítimas eram mutiladas pela poda de conversa simples.
        explicativo = bool(re.search(
            r"\b(por ?que|como (funciona|faz|fazer|eu|se)|explic|diferen[cç]a|"
            r"exemplo|passo a passo|list[ae]|tabela|compar|detalh|resum|"
            r"vantagens|desvantagens|o que [ée])", (pergunta or "").lower()))
        estruturada = (bool(re.search(r"(^|\n)\s*(?:[-*•]|\d+[.)])\s+", t))
                       or t.count("\n\n") >= 2)
        complexo = (bool(artefatos) or len(pergunta or "") > 180
                    or explicativo or estruturada
                    or task_type in ("analise_complexa", "codigo", "código",
                                     "arquitetura", "pesquisa_sintese",
                                     "redacao", "redação"))
        if not complexo and "```" not in t:
            frases = re.split(r"(?<=[.!?])\s+", t)
            if len(frases) > 3:
                t = " ".join(frases[:3]).strip()
            if len(t) > 620:
                corte = t[:620]
                ponto = max(corte.rfind(". "), corte.rfind("! "),
                            corte.rfind("? "))
                t = (corte[:ponto + 1] if ponto > 300 else corte).strip()
        return t

    def _completar_entregaveis(self, texto: str, artefatos: list[dict]) -> str:
        """Garante que a resposta cite todo arquivo/imagem produzido."""
        if not artefatos:
            return texto
        faltando = []
        for a in artefatos:
            url = str(a.get("url") or "")
            titulo = str(a.get("titulo") or a.get("nome") or "")
            if url and url in (texto or ""):
                continue
            if titulo and titulo in (texto or ""):
                continue
            faltando.append(a)
        if not faltando:
            return texto
        linhas = []
        for a in faltando[:8]:
            titulo = a.get("titulo") or a.get("nome") or a.get("tipo") or "arquivo"
            linhas.append(f"- [{titulo}]({a.get('url')})")
        return ((texto or "").rstrip() +
                "\n\n**Entregáveis gerados:**\n" + "\n".join(linhas))

    def _avaliar_fundo(self, pergunta: str, resposta: str) -> int | None:
        """Avalia a resposta (1-5), grava em avaliacoes.jsonl e devolve a nota
        (ou None se a avaliação falhar), para o aprendizado poder usá-la."""
        try:
            from yvakor.colaboracao import avaliar_resposta
            r = avaliar_resposta(self.router, pergunta, resposta)
            if not r.get("ok"):
                return None
            r.update({"ts": datetime.now().isoformat(timespec="seconds"),
                      "pergunta": (pergunta or "")[:600],
                      "resposta": (resposta or "")[:1200]})
            arq = ROOT / "data" / "avaliacoes.jsonl"
            arq.parent.mkdir(parents=True, exist_ok=True)
            with self._avaliacao_lock:
                with arq.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            try:
                return int(r.get("nota"))
            except (TypeError, ValueError):
                return None
        except Exception:
            return None

    # Nota mínima (1-5) para a resposta "ensinar" a memória. Respostas ruins
    # não contaminam fatos/skills (antes a nota era write-only em jsonl).
    NOTA_MIN_APRENDER = 4

    def _aprender_fundo(self, pergunta: str, resposta: str,
                        task_type: str) -> None:
        """Avalia e SÓ absorve/destila se a resposta foi boa. Antes absorção e
        avaliação eram threads independentes: a nota não influenciava nada."""
        # Sem provedor externo só sobra o 3B local (CPU): avaliar/extrair fatos
        # em segundo plano competiria com o chat e a qualidade seria ruim.
        try:
            if (self.router.sem_externos()
                    and not self.settings["agent"].get("aprender_local", False)):
                return
        except Exception:
            pass
        nota = None
        if self.settings["agent"].get("avaliar_auto"):
            nota = self._avaliar_fundo(pergunta, resposta)
            if nota is not None and nota < self.NOTA_MIN_APRENDER:
                return  # resposta fraca: não vira fato nem skill
        if not self._abs_lock.acquire(blocking=False):
            return
        try:
            self.absorber.after_response(pergunta, resposta, task_type)
        except Exception:
            pass
        finally:
            self._abs_lock.release()

    @staticmethod
    def _juntar_contexto(*partes) -> str | None:
        blocos = [p for p in partes if p]
        return "\n\n".join(blocos) if blocos else None

    def _sincronizar_cerebro_async(self) -> None:
        if self.cerebro is None:
            return
        agora = time.time()
        if agora - getattr(self, "_ultimo_sync_vault", 0.0) < 120:
            return
        self._ultimo_sync_vault = agora
        threading.Thread(target=self.cerebro.sincronizar, daemon=True,
                         name="yvakor-vault-sync").start()

    # ------------------------------------------------------------------ #
    # Encerramento
    # ------------------------------------------------------------------ #
    def shutdown(self) -> None:
        """Fecha navegador, mídia e tarefas em curso (usado ao desligar)."""
        try:
            self.mcp.parar()
        except Exception:
            pass
        try:
            self.agenda.parar()
        except Exception:
            pass
        try:
            self.cowork.shutdown()
        except Exception:
            pass
        try:
            if self.navegadores is not None:
                self.navegadores.shutdown()
            elif self.browser is not None:
                self.browser.shutdown()
        except Exception:
            pass
        try:
            if self.monitor_rede is not None:
                self.monitor_rede.parar()
            if self.rede is not None:
                self.rede.shutdown()
        except Exception:
            pass
        # Fecha conexões SQLite com checkpoint/optimize (dados consistentes).
        for obj in (self.cerebro, self.skills, self.semantic, self.episodic):
            try:
                if obj is not None:
                    obj.fechar()
            except Exception:
                pass
        try:
            self.telemetria.fechar()
        except Exception:
            pass

    def avisar(self, texto: str) -> None:
        """Fala um aviso curto (usado por tarefas de segundo plano)."""
        try:
            if self.voz is not None and self.settings.get("voz", {}).get(
                    "avisar_cowork", False):
                self.voz.falar(texto)
        except Exception:
            pass
