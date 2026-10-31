"""Confirmation Guard — nenhuma ação perigosa sem confirmação explícita.
Padrão já validado no Gestor Master / Assistente Master."""
from __future__ import annotations
import re
import sys
import threading
import logging

_log = logging.getLogger(__name__)

# Confirmador por thread: no modo servidor (sem terminal), o orquestrador
# injeta aqui uma função (action, detail) -> bool que faz o handshake com a
# interface (popup no navegador). Cada requisição /api/chat roda em sua própria
# thread, então o thread-local isola uma conversa da outra.
_local = threading.local()

# Modo "Agir sem pedir" (extensao_modo = "autonomo" em data/preferencias.json):
# rodar código deixa de abrir popup — cada passo de gráfico/cálculo parava a
# tarefa esperando um clique que o usuário sempre dava. Continua pedindo o que
# apaga, desliga, mexe no registro/processos/usuários ou envia dados para fora.
# Organizar pastas só move (com desfazer): reversível, então também roda sem
# popup nesse modo. Limpar temporários e esvaziar a Lixeira apagam de vez:
# continuam pedindo (1 confirmação para a limpeza toda).
# Atualizar drivers: o UAC do Windows já é a confirmação humana.
LIBERADAS_AUTONOMO = {"executar_python", "executar_shell", "cap_executar_codigo",
                      "organizar_executar", "sistema_drivers_atualizar",
                      "guardiao_escanear"}
_DESTRUTIVO_SHELL = re.compile(
    r"\b(del|erase|rd|rmdir|rm|format|shutdown|restart-computer|stop-computer|"
    r"taskkill|stop-process|kill|remove-item|move-item|rename-item|diskpart|"
    r"bcdedit|takeown|icacls|cipher|schtasks|vssadmin|wmic|set-executionpolicy|"
    r"reg\s+(add|delete|import)|net\s+(user|localgroup|share)|sc\s+(delete|stop|config)|"
    r"invoke-webrequest|iwr|invoke-restmethod|irm|curl|wget|start-process|"
    r"pip\s+uninstall|webclient|uploadfile|uploadstring|bitsadmin|start-bitstransfer|"
    r"send-mailmessage|ftp|scp)\b"
    # gravar por redirecionamento (> arquivo), menos 2>NUL / >NUL / 2>&1
    r"|(?<![\d&])>{1,2}\s*(?!nul\b)(?!&)[\w\"'%$\\/.:]", re.I)
_DESTRUTIVO_PY = re.compile(
    r"os\.(remove|unlink|rmdir|removedirs|rename|replace|system|popen|kill|chmod)\b"
    r"|shutil\.(rmtree|move|chown)|\.unlink\(|\.rmdir\(|\bsubprocess\b|\bwinreg\b"
    r"|\bctypes\b|\bsmtplib\b|requests\.(post|put|delete|patch)|\bsocket\b"
    r"|__import__|\beval\(|\bexec\(", re.I)


def destrutivo(action: str, texto: str) -> bool:
    texto = texto or ""
    if action == "executar_shell":
        # "python -c ..." no shell também é código Python
        return bool(_DESTRUTIVO_SHELL.search(texto) or _DESTRUTIVO_PY.search(texto))
    return bool(_DESTRUTIVO_PY.search(texto))


def modo_autonomo() -> bool:
    try:
        from yvakor import seguro
        from yvakor.config import ROOT
        prefs = seguro.ler_json(ROOT / "data" / "preferencias.json", {})
        return isinstance(prefs, dict) and prefs.get("extensao_modo") == "autonomo"
    except Exception:
        return False


# Revisor (como o classificador do modo auto do Claude Code): no modo
# autônomo, código que passou no filtro de padrões ainda é lido por um modelo
# que decide "permitir" ou "perguntar" olhando o pedido do usuário. O
# orquestrador injeta revisor(acao, codigo) -> (permitir: bool, motivo: str);
# exceção ou None = revisor indisponível.
_revisor = None


def definir_revisor(fn) -> None:
    global _revisor
    _revisor = fn


# Conteúdo externo nesta tarefa (página, pesquisa, API). Se veio com cara de
# instrução para o agente ("ignore as instruções…", "execute…"), a tarefa fica
# SUSPEITA e nada roda sozinho até o fim dela — defesa contra prompt injection.
def marcar_externo(suspeito: bool = False) -> None:
    _local.externo = True
    if suspeito:
        _local.suspeito = True


def limpar_externo() -> None:
    _local.externo = False
    _local.suspeito = False


def estado_externo() -> tuple[bool, bool]:
    return bool(getattr(_local, "externo", False)), bool(getattr(_local, "suspeito", False))


def _decisao_autonoma(action: str, codigo: str) -> tuple[bool, str]:
    """(roda sem perguntar?, motivo para o popup quando não)."""
    if destrutivo(action, codigo):
        return False, "comando que apaga/altera o sistema ou envia dados"
    externo, suspeito = estado_externo()
    if suspeito:
        return False, "a página lida nesta tarefa tinha instruções para o agente"
    if _revisor is not None:
        try:
            r = _revisor(action, codigo)
        except Exception:
            r = None
        if r is not None:
            permitir, motivo = r
            return bool(permitir), str(motivo or "o revisor pediu confirmação")
        if externo:      # sem revisor e com conteúdo da web: na dúvida, pergunta
            return False, "revisor indisponível depois de ler conteúdo da web"
    return True, ""


def set_thread_confirmer(fn) -> None:
    _local.confirmer = fn


def clear_thread_confirmer() -> None:
    _local.confirmer = None


def _thread_confirmer():
    return getattr(_local, "confirmer", None)


def _safe_print(msg: str) -> None:
    """Imprime sem quebrar em consoles legados (cp1252 do Windows não tem
    emojis/✓). Se a codificação do console não suportar, cai para ASCII."""
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = (getattr(sys.stdout, "encoding", None) or "ascii")
        print(msg.encode(enc, "replace").decode(enc, "replace"))


class ConfirmationGuard:
    def __init__(self, guarded_actions: list[str], auto_approve: bool = False,
                 always_confirm: list[str] | None = None,
                 total: bool = False):
        self.guarded = set(guarded_actions)
        self.auto_approve = auto_approve
        # Privilégios totais: o agente age como o próprio usuário (sem popup).
        # Fica registrado em data/auditoria.jsonl para auditoria posterior.
        self.total = bool(total)
        # Ações que NUNCA são auto-aprovadas (envio externo / destrutivas),
        # mesmo com auto_approve ligado.
        self.always_confirm = set(always_confirm or
                                  ["send_email", "send_whatsapp", "delete_file"])

    def requires_confirmation(self, action: str) -> bool:
        # Uma ação é checada se está na lista de guardadas OU na de
        # always_confirm — assim, mesmo que o settings esqueça de listar uma
        # ação destrutiva em guarded_actions, ela continua protegida.
        return action in self.guarded or action in self.always_confirm

    def confirm(self, action: str, detail: str, completo: str | None = None) -> bool:
        """`completo` = argumentos inteiros (o `detail` vem cortado em 200
        caracteres para o popup e não serve para julgar o código todo)."""
        if action in LIBERADAS_AUTONOMO and modo_autonomo():
            livre, motivo = _decisao_autonoma(
                action, completo if completo is not None else detail)
            if livre:
                try:
                    from yvakor.arquivos import _auditar
                    _auditar("acao_autonoma", action, {"detalhe": detail[:200]})
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
                return True
            detail = f"[{motivo}] {detail}"     # o popup diz POR QUE perguntou
        # Ações externas/destrutivas (always_confirm) SEMPRE exigem um humano,
        # mesmo com privilégios "total" ou auto_approve ligados. É a última
        # linha de defesa contra prompt-injection e contra requisições
        # disparadas por páginas web: nenhum "total" aprova sozinho apagar
        # arquivo, rodar shell, enviar mensagem ou controlar um dispositivo.
        critica = action in self.always_confirm

        if not critica:
            if self.total:
                try:
                    from yvakor.arquivos import _auditar
                    _auditar("acao_sem_confirmacao", action,
                             {"detalhe": detail[:200]})
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
                _safe_print(f"  • executado (privilégios totais): {action}")
                return True
            # Modo automático: aprova ações de trabalho sem travar.
            if self.auto_approve:
                _safe_print(f"  ✓ auto-aprovado: {action} · {detail[:120]}")
                return True

        # A partir daqui exige confirmação humana real — total/auto NÃO valem.
        # Se houver um confirmador de thread (modo servidor), faz o handshake
        # com a interface: bloqueia até o usuário aprovar/negar no navegador.
        fn = _thread_confirmer()
        if fn is not None:
            ok = bool(fn(action, detail))
            if critica:
                try:
                    from yvakor.arquivos import _auditar
                    _auditar("confirmacao_critica", action,
                             {"ok": ok, "detalhe": detail[:200]})
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            return ok

        # Fora de um terminal interativo (ex.: servidor web), NUNCA bloqueia
        # esperando input — nega por segurança e deixa o rastro no log.
        if not (sys.stdin and sys.stdin.isatty()):
            _safe_print(f"\n⚠️  AÇÃO PROTEGIDA negada (sem terminal p/ confirmar): "
                        f"{action} · {detail}")
            return False
        _safe_print(f"\n⚠️  AÇÃO PROTEGIDA: {action}\n    {detail}")
        answer = input("    Confirmar? (sim/não) > ").strip().lower()
        return answer in ("sim", "s", "yes", "y")
