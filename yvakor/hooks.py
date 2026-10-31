"""
YVAKOR — Hooks: comandos seus que rodam em eventos do agente (como no Claude Code)

Configuração em config/hooks.json (mesmo formato do Claude Code) e em
hooks/hooks.json de plugins LIGADOS:

  {"hooks": {
     "PreToolUse":  [{"matcher": "executar_shell|arquivos_.*",
                      "hooks": [{"type": "command", "command": "python checar.py",
                                 "timeout": 30}]}],
     "PostToolUse": [...],          # depois da ferramenta (vê a resposta)
     "UserPromptSubmit": [...],     # quando chega mensagem sua
     "Stop": [...]}}                # quando a resposta fica pronta

O comando recebe no stdin um JSON (session_id, hook_event_name, tool_name,
tool_input, tool_response, prompt, cwd) e responde por código de saída:
  0  → segue; stdout em JSON pode trazer {"decision": "block", "reason": …},
       {"hookSpecificOutput": {"permissionDecision": "deny", …}} ou
       {"additionalContext": "…"}; em UserPromptSubmit, texto puro no stdout
       vira contexto extra para o agente;
  2  → BLOQUEIA (PreToolUse: a ferramenta não roda; UserPromptSubmit: a
       mensagem não segue); o stderr é o motivo, devolvido ao agente;
  outro → erro do hook: registrado no log, não bloqueia.

`matcher` é uma expressão regular sobre o nome da ferramenta ("" ou "*" =
todas). Hooks de plugin rodam com YVAKOR_PLUGIN_ROOT/CLAUDE_PLUGIN_ROOT
apontando para a pasta do plugin.
"""
from __future__ import annotations

import json
import locale
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from yvakor import proc as _ywproc
from yvakor.config import ROOT

_log = logging.getLogger(__name__)

CONFIG = ROOT / "config" / "hooks.json"
EVENTOS = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop")
TIMEOUT_PADRAO = 60


@dataclass
class Resultado:
    bloquear: bool = False
    motivo: str = ""
    contexto: list[str] = field(default_factory=list)


def _decodificar(dados: bytes | None) -> str:
    """UTF-8; se não for, a codificação do console do Windows (cp1252/cp850)."""
    if not dados:
        return ""
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode(locale.getpreferredencoding(False) or "latin-1", errors="replace")


def _regras(dados: dict, raiz: str = "") -> dict[str, list[tuple[str, dict, str]]]:
    saida: dict[str, list] = {e: [] for e in EVENTOS}
    for evento, grupos in ((dados or {}).get("hooks") or {}).items():
        if evento not in saida or not isinstance(grupos, list):
            continue
        for g in grupos:
            if not isinstance(g, dict):
                continue
            for h in g.get("hooks") or []:
                if isinstance(h, dict) and h.get("type", "command") == "command" \
                        and str(h.get("command") or "").strip():
                    saida[evento].append((str(g.get("matcher") or ""), h, raiz))
    return saida


class Hooks:
    def __init__(self, cfg_path: Path | None = None, extras=None):
        self.cfg_path = Path(cfg_path or CONFIG)
        # hooks de plugins ligados: callable → [(dados_json, pasta_do_plugin)]
        self.extras = extras
        self._cache: tuple[float, dict] = (-1.0, {})
        self._lock = threading.Lock()

    def _do_config(self) -> dict:
        try:
            mtime = self.cfg_path.stat().st_mtime
        except OSError:
            return {}
        with self._lock:
            if self._cache[0] != mtime:
                try:
                    dados = json.loads(self.cfg_path.read_text(encoding="utf-8"))
                except ValueError:
                    _log.warning("hooks.json inválido: %s", self.cfg_path)
                    dados = {}
                self._cache = (mtime, _regras(dados))
            return self._cache[1]

    def regras(self, evento: str) -> list[tuple[str, dict, str]]:
        lista = list(self._do_config().get(evento) or [])
        if self.extras is not None:
            try:
                for dados, raiz in self.extras():
                    lista += _regras(dados, str(raiz)).get(evento) or []
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        return lista

    @staticmethod
    def _casa(matcher: str, ferramenta: str) -> bool:
        if matcher in ("", "*") or not ferramenta:
            return True
        try:
            return re.fullmatch(matcher, ferramenta) is not None
        except re.error:
            return matcher == ferramenta

    def _rodar(self, hook: dict, raiz: str, payload: dict) -> tuple[int, str, str]:
        comando = str(hook["command"])
        env = os.environ.copy()
        env["YVAKOR_PROJECT_DIR"] = str(ROOT)
        if raiz:
            env["YVAKOR_PLUGIN_ROOT"] = env["CLAUDE_PLUGIN_ROOT"] = raiz
            comando = comando.replace("${CLAUDE_PLUGIN_ROOT}", raiz) \
                             .replace("${YVAKOR_PLUGIN_ROOT}", raiz)
        env.setdefault("PYTHONUTF8", "1")          # hooks em Python falam UTF-8
        try:
            r = _ywproc.run(comando, shell=True, cwd=raiz or str(ROOT), env=env,
                            input=json.dumps(payload, ensure_ascii=False,
                                             default=str).encode("utf-8"),
                            capture_output=True,
                            timeout=float(hook.get("timeout") or TIMEOUT_PADRAO))
        except subprocess.TimeoutExpired:
            _log.warning("hook passou do tempo: %s", comando)
            return -1, "", "timeout"
        except Exception as exc:
            _log.warning("hook falhou ao iniciar (%s): %s", exc, comando)
            return -1, "", str(exc)
        return r.returncode, _decodificar(r.stdout), _decodificar(r.stderr)

    def disparar(self, evento: str, ferramenta: str = "", **dados) -> Resultado:
        res = Resultado()
        regras = [(m, h, raiz) for m, h, raiz in self.regras(evento)
                  if self._casa(m, ferramenta)]
        if not regras:
            return res
        payload = {"hook_event_name": evento, "cwd": str(ROOT), **dados}
        if ferramenta:
            payload["tool_name"] = ferramenta
        for _, hook, raiz in regras:
            codigo, saida, erro = self._rodar(hook, raiz, payload)
            if codigo == 2:
                res.bloquear = True
                res.motivo = erro.strip()[:1000] or "bloqueado por hook"
            elif codigo == 0:
                self._ler_saida(evento, saida, res)
            else:
                _log.warning("hook %s saiu com %s: %s", hook["command"], codigo,
                             erro.strip()[:300])
            if res.bloquear:
                break
        return res

    @staticmethod
    def _ler_saida(evento: str, saida: str, res: Resultado) -> None:
        texto = saida.strip()
        if not texto:
            return
        try:
            j = json.loads(texto)
        except ValueError:
            if evento == "UserPromptSubmit":
                res.contexto.append(texto[:4000])
            return
        if not isinstance(j, dict):
            return
        especifico = j.get("hookSpecificOutput") or {}
        if j.get("decision") == "block" or j.get("continue") is False \
                or especifico.get("permissionDecision") == "deny":
            res.bloquear = True
            res.motivo = str(j.get("reason") or j.get("stopReason")
                             or especifico.get("permissionDecisionReason")
                             or "bloqueado por hook")[:1000]
        extra = j.get("additionalContext") or especifico.get("additionalContext")
        if extra:
            res.contexto.append(str(extra)[:4000])


_PADRAO = Hooks()


def padrao() -> Hooks:
    return _PADRAO


def configurar(cfg_path: Path | None = None, extras=None) -> Hooks:
    """O orquestrador chama no início para somar os hooks dos plugins."""
    global _PADRAO
    _PADRAO = Hooks(cfg_path, extras)
    return _PADRAO
