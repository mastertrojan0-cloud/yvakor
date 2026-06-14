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
                 always_confirm: list[str] | None = None):
        self.guarded = set(guarded_actions)
        self.auto_approve = auto_approve
        # Ações que NUNCA são auto-aprovadas (envio externo / destrutivas),
        # mesmo com auto_approve ligado.
        self.always_confirm = set(always_confirm or
                                  ["send_email", "send_whatsapp", "delete_file"])

    def requires_confirmation(self, action: str) -> bool:
        return action in self.guarded

    def confirm(self, action: str, detail: str) -> bool:
        # Modo automático: aprova ações de trabalho sem travar (registra rastro).
        # Exceção: ações realmente externas/destrutivas seguem exigindo confirmação.
        if self.auto_approve and action not in self.always_confirm:
            _safe_print(f"  ✓ auto-aprovado: {action} · {detail[:120]}")
            return True

        # Se houver um confirmador de thread (modo servidor), faz o handshake
        # com a interface: bloqueia até o usuário aprovar/negar no navegador.
        fn = _thread_confirmer()
        if fn is not None:
            return bool(fn(action, detail))

        # Fora de um terminal interativo (ex.: servidor web), NUNCA bloqueia
        # esperando input — nega por segurança e deixa o rastro no log.
        if not (sys.stdin and sys.stdin.isatty()):
            _safe_print(f"\n⚠️  AÇÃO PROTEGIDA negada (sem terminal p/ confirmar): "
                        f"{action} · {detail}")
            return False
        _safe_print(f"\n⚠️  AÇÃO PROTEGIDA: {action}\n    {detail}")
        answer = input("    Confirmar? (sim/não) > ").strip().lower()
        return answer in ("sim", "s", "yes", "y")
