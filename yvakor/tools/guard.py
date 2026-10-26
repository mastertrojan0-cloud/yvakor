"""Confirmation Guard — nenhuma ação perigosa sem confirmação explícita.
Padrão já validado no Gestor Master / Assistente Master."""
from __future__ import annotations
import sys
import threading

# Confirmador por thread: no modo servidor (sem terminal), o orquestrador
# injeta aqui uma função (action, detail) -> bool que faz o handshake com a
# interface (popup no navegador). Cada requisição /api/chat roda em sua própria
# thread, então o thread-local isola uma conversa da outra.
_local = threading.local()


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

    def confirm(self, action: str, detail: str) -> bool:
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
                    pass
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
                    pass
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
