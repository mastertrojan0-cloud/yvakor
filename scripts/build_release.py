"""Gera um pacote de distribuição limpo do YVAKOR (sem dados/segredos)."""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
EXCLUIR_DIRS = {".git", "venv", "data", "dist", "__pycache__", ".pytest_cache",
                "browser_profiles", "htmlcov", ".idea", ".vscode"}
EXCLUIR_EXT = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log", ".zip"}
EXCLUIR_NOMES = {".env", "runId.txt", "agenda.json", "avaliacoes.jsonl"}
INCLUIR_RAIZ = {"INICIAR.bat", "YVAKOR-APP.bat", "INSTALAR-CHROME-EXTENSAO.bat",
                "README.md", "LICENSE", "requirements.txt", "pyproject.toml",
                ".env.example", ".gitignore"}


def _incluir(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    if any(part in EXCLUIR_DIRS for part in rel.parts):
        return False
    if p.name in EXCLUIR_NOMES:
        return False
    if p.suffix.lower() in EXCLUIR_EXT:
        return False
    if p.name.startswith(".") and p.name not in (".env.example", ".gitignore"):
        return False
    if rel.parts[0] in ("config",) and p.name == "settings.yaml":
        return True
    return True


def main() -> int:
    versao = json.loads((ROOT / "config" / "version.json").read_text(
        encoding="utf-8"))
    ver = versao.get("version", "0.0.0")
    DIST.mkdir(exist_ok=True)
    destino = DIST / f"YVAKOR-{ver}.zip"
    manifesto = []
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob("*"):
            if not p.is_file() or not _incluir(p):
                continue
            rel = p.relative_to(ROOT)
            if len(rel.parts) == 1 and p.name not in INCLUIR_RAIZ:
                continue
            z.write(p, arcname=str(Path("YVAKOR") / rel))
            manifesto.append(str(rel))
    meta = {"produto": "YVAKOR", "versao": ver,
            "build": versao.get("build"),
            "gerado_em": datetime.now().isoformat(timespec="seconds"),
            "arquivos": len(manifesto)}
    (DIST / "RELEASE.json").write_text(json.dumps(meta, ensure_ascii=False,
                                                  indent=2), encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (DIST / "SHA256SUMS.txt").write_text(f"{sha}  {destino.name}\n",
                                         encoding="utf-8")
    print(json.dumps({"ok": True, "zip": str(destino), "sha256": sha,
                      "arquivos": len(manifesto)}, ensure_ascii=False,
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
