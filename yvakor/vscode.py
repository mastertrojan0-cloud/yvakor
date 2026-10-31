"""YVAKOR — ponte com o VS Code (a extensão em vscode-extension/).

O VS Code não é ferramenta solta: a extensão do YVAKOR
  - registra a pasta aberta como workspace;
  - manda o contexto do editor (arquivo, seleção, problemas, abas abertas);
  - tem o painel de chat que conversa com este mesmo núcleo;
  - executa comandos que o YVAKOR pede (abrir arquivo na linha, mostrar diff).

Contexto fica em memória (não vai para o disco) e expira em 15 min.
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path

from yvakor import proc

_log = logging.getLogger(__name__)

IDADE_MAX_S = 900          # contexto mais velho que isso não entra no prompt
CONECTADO_S = 40           # poll da extensão mais recente que isso = conectado

_lock = threading.Lock()
_contextos: dict[str, dict] = {}     # pasta (minúscula) → último contexto
_fila: list[dict] = []
_evento = threading.Event()
_ultimo_poll = 0.0


def registrar_contexto(dados: dict) -> dict:
    pasta = str(dados.get("workspace") or "").strip()
    with _lock:
        _contextos[pasta.lower()] = {**dados, "recebido": time.time()}
    return {"ok": True}


def contexto(pasta: str | Path | None = None) -> dict | None:
    """Contexto mais recente (do workspace dado, se houver)."""
    agora = time.time()
    with _lock:
        if pasta:
            c = _contextos.get(str(pasta).lower())
        else:
            c = max(_contextos.values(), key=lambda x: x["recebido"], default=None)
    if not c or agora - c["recebido"] > IDADE_MAX_S:
        return None
    return c


def conectado() -> bool:
    return time.time() - _ultimo_poll < CONECTADO_S


def enfileirar(cmd: dict) -> None:
    with _lock:
        _fila.append(cmd)
    _evento.set()


def pegar_comandos(espera: float = 25) -> list[dict]:
    """Long-poll da extensão: devolve os comandos pendentes (ou [] no timeout)."""
    global _ultimo_poll
    _ultimo_poll = time.time()
    if not _fila:
        _evento.wait(max(0.0, min(float(espera), 30)))
    with _lock:
        cmds = list(_fila)
        _fila.clear()
        _evento.clear()
    _ultimo_poll = time.time()
    return cmds


def abrir(arquivo: str, linha: int = 1) -> dict:
    """Abre o arquivo no VS Code na linha (pela extensão; sem ela, pelo `code`)."""
    p = Path(arquivo)
    if not p.is_absolute():
        try:
            from yvakor.workspaces import caminho_ativo
            base = caminho_ativo()
            if base:
                p = base / p
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
    if not p.exists():
        return {"ok": False, "erro": f"arquivo não existe: {p}"}
    linha = max(1, int(linha or 1))
    if conectado():
        enfileirar({"tipo": "abrir", "arquivo": str(p), "linha": linha})
        return {"ok": True, "via": "extensão", "arquivo": str(p), "linha": linha}
    code = shutil.which("code") or shutil.which("code.cmd")
    if not code:
        return {"ok": False, "erro": "VS Code não encontrado"}
    proc.popen([code, "-g", f"{p}:{linha}"])
    return {"ok": True, "via": "code -g", "arquivo": str(p), "linha": linha}


def mostrar_diff(arquivo: str) -> dict:
    if not conectado():
        return {"ok": False, "erro": "extensão do YVAKOR no VS Code não está conectada"}
    enfileirar({"tipo": "diff", "arquivo": arquivo})
    return {"ok": True}


def bloco_prompt(pasta: str | Path | None) -> str:
    c = contexto(pasta) if pasta else None
    if not c:
        return ""
    linhas = ["## VS CODE (o que o usuário está vendo agora — \"este arquivo\", "
              "\"esta função\" se referem a isto)",
              f"- Arquivo aberto: {c.get('arquivo') or '—'} ({c.get('linguagem') or '?'})"
              + (f", cursor na linha {c.get('linha')}" if c.get("linha") else "")]
    sel = (c.get("selecao") or "").strip()
    if sel:
        linhas.append(f"- Seleção (linhas {c.get('linha_inicio')}–{c.get('linha_fim')}):\n"
                      f"```\n{sel[:3000]}\n```")
    probs = c.get("problemas") or []
    if probs:
        linhas.append("- Problemas no editor: " + "; ".join(str(p)[:140] for p in probs[:8]))
    abertos = c.get("abertos") or []
    if abertos:
        linhas.append("- Abas abertas: " + ", ".join(Path(a).name for a in abertos[:12]))
    return "\n".join(linhas)


def register_vscode_tools(registry) -> list[str]:
    def vscode_contexto() -> dict:
        try:
            from yvakor.workspaces import caminho_ativo
            c = contexto(caminho_ativo()) or contexto()
        except Exception:
            c = contexto()
        if not c:
            return {"ok": False, "erro": "o VS Code não mandou contexto recente "
                                         "(extensão do YVAKOR aberta?)"}
        return {"ok": True, **{k: v for k, v in c.items() if k != "recebido"},
                "conectado": conectado()}

    registry.register("vscode_contexto", vscode_contexto,
                      "O que está aberto no VS Code agora: arquivo, seleção, cursor, "
                      "problemas (erros) e abas.", {})
    registry.register("vscode_abrir", lambda arquivo, linha=1: abrir(arquivo, linha),
                      "Abre um arquivo no VS Code na linha indicada (para mostrar ao "
                      "usuário o que você mudou ou encontrou).",
                      {"arquivo": "str", "linha": "int?"})
    registry.register("vscode_diff", lambda arquivo: mostrar_diff(arquivo),
                      "Mostra no VS Code o diff do arquivo contra o último commit.",
                      {"arquivo": "str"})
    return ["vscode_contexto", "vscode_abrir", "vscode_diff"]
