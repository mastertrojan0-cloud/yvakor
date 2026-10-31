"""Hook de exemplo (Stop): anota cada pedido respondido em data/logs/hooks_stop.log."""
import json
import sys
import time
from pathlib import Path

dados = json.load(sys.stdin)
log = Path(dados.get("cwd") or ".") / "data" / "logs" / "hooks_stop.log"
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as f:
    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {str(dados.get('prompt', ''))[:200]}\n")
