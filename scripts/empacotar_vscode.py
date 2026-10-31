"""Empacota vscode-extension/ como .vsix (sem precisar de Node/vsce).

Uso:  python scripts/empacotar_vscode.py [--instalar]
Gera dist/yvakor-vscode-<versão>.vsix; com --instalar roda
`code --install-extension <vsix> --force`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FONTE = RAIZ / "vscode-extension"


def empacotar() -> Path:
    pkg = json.loads((FONTE / "package.json").read_text(encoding="utf-8"))
    destino = RAIZ / "dist" / f"yvakor-vscode-{pkg['version']}.vsix"
    destino.parent.mkdir(parents=True, exist_ok=True)
    manifesto = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{pkg['name']}" Version="{pkg['version']}" Publisher="{pkg['publisher']}"/>
    <DisplayName>{pkg['displayName']}</DisplayName>
    <Description xml:space="preserve">{pkg['description']}</Description>
    <Categories>Other</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg['engines']['vscode']}"/>
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
  </Assets>
</PackageManifest>
"""
    tipos = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension=".json" ContentType="application/json"/>
  <Default Extension=".js" ContentType="application/javascript"/>
  <Default Extension=".svg" ContentType="image/svg+xml"/>
  <Default Extension=".md" ContentType="text/markdown"/>
  <Default Extension=".vsixmanifest" ContentType="text/xml"/>
</Types>
"""
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("extension.vsixmanifest", manifesto)
        z.writestr("[Content_Types].xml", tipos)
        for arq in sorted(FONTE.rglob("*")):
            if arq.is_file():
                z.write(arq, "extension/" + arq.relative_to(FONTE).as_posix())
    return destino


def main() -> int:
    vsix = empacotar()
    print("gerado:", vsix)
    if "--instalar" in sys.argv:
        code = shutil.which("code") or shutil.which("code.cmd")
        if not code:
            print("VS Code (comando 'code') não encontrado no PATH")
            return 1
        r = subprocess.run([code, "--install-extension", str(vsix), "--force"],
                           capture_output=True, text=True, errors="replace")
        print((r.stdout or "") + (r.stderr or ""))
        return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
