"""Hook de exemplo (PreToolUse): barra comandos destrutivos antes de rodarem.

Recebe no stdin o JSON do evento; sair com código 2 bloqueia e o stderr vira o
motivo devolvido ao agente. Ligue copiando config/hooks.exemplo.json para
config/hooks.json.
"""
import json
import re
import sys

PERIGOSOS = (
    r"\brm\s+-rf?\b", r"\bdel\s+/[sq]\b", r"\bformat\s+[a-z]:", r"\bRemove-Item\b.*-Recurse",
    r"\bshutdown\b", r"\bdiskpart\b", r"\breg\s+delete\b", r"\bgit\s+push\s+.*--force\b",
)

dados = json.load(sys.stdin)
entrada = dados.get("tool_input") or {}
texto = " ".join(str(v) for v in entrada.values())
for padrao in PERIGOSOS:
    if re.search(padrao, texto, re.I):
        sys.stderr.write(f"comando destrutivo barrado pelo hook ({padrao}). "
                         "Peça confirmação ao usuário ou use outra forma.")
        sys.exit(2)
sys.exit(0)
