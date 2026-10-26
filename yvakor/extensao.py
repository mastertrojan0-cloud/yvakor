"""YVAKOR — sincroniza a extensão do Chrome com a versão do núcleo."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from yvakor.config import ROOT

VERSAO_FILE = ROOT / "config" / "version.json"
EXT = ROOT / "chrome-extension"


def versao_core() -> dict:
    try:
        return json.loads(VERSAO_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "0.0.0", "build": "dev"}


def sincronizar(ext: Path | None = None) -> dict:
    ext = Path(ext or EXT)
    manifest_path = ext / "manifest.json"
    if not manifest_path.is_file():
        return {"ok": False, "motivo": "extensão não encontrada"}
    info = versao_core()
    versao = str(info.get("version") or "0.0.0")
    build = str(info.get("build") or "dev")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "erro": f"manifest inválido: {exc}"}
    manifest["version"] = versao
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)
                             + "\n", encoding="utf-8")
    # fontes compartilhadas com o app nativo
    origem_fontes = ROOT / "interface" / "fonts"
    destino_fontes = ext / "fonts"
    destino_fontes.mkdir(parents=True, exist_ok=True)
    for fonte in origem_fontes.glob("*.ttf"):
        shutil.copy2(fonte, destino_fontes / fonte.name)
    payload = {
        "version": versao,
        "build": build,
        "canal": info.get("canal", "dev"),
        "sincronizado_em": datetime.now().isoformat(timespec="seconds"),
    }
    (ext / "build.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return {"ok": True, "version": versao, "build": build,
            "manifest": str(manifest_path), "build_json": str(ext / "build.json")}


if __name__ == "__main__":
    print(json.dumps(sincronizar(), ensure_ascii=False, indent=2))
