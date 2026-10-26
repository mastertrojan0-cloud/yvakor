"""YVAKOR — leitura de documentos e OCR local (Windows.Media.Ocr)."""
from __future__ import annotations

import hashlib
import subprocess
from yvakor import proc as _ywproc
import tempfile
from pathlib import Path

from yvakor.config import ROOT

TEMP = ROOT / "data" / "temp"
OCR_PS1 = TEMP / "yvakor_ocr.ps1"

_PS = r"""
param([string]$Imagem)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}
$path = (Resolve-Path $Imagem).Path
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw "OCR do Windows indisponível para o idioma atual" }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$result.Text
"""


def _garantir_ps() -> Path:
    TEMP.mkdir(parents=True, exist_ok=True)
    if not OCR_PS1.is_file():
        OCR_PS1.write_text(_PS, encoding="utf-8")
    return OCR_PS1


def ocr_imagem(caminho: str | Path) -> dict:
    p = Path(caminho).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "erro": f"imagem não encontrada: {p}"}
    try:
        proc = _ywproc.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(_garantir_ps()), str(p)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60)
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
    texto = (proc.stdout or "").strip()
    if not texto:
        return {"ok": False, "erro": (proc.stderr or "OCR sem texto").strip()[-400:]}
    return {"ok": True, "caminho": str(p), "texto": texto[:12000],
            "caracteres": len(texto)}


def _ocr_pdf(caminho: Path, max_paginas: int = 20) -> dict:
    try:
        import pymupdf
    except Exception:
        return {"ok": False, "erro": "PyMuPDF não instalado"}
    textos: list[str] = []
    try:
        doc = pymupdf.open(str(caminho))
        for i, pagina in enumerate(doc):
            if i >= max_paginas:
                break
            t = pagina.get_text("text").strip()
            if len(t) > 60:
                textos.append(t)
                continue
            try:
                pix = pagina.get_pixmap(dpi=200)
                temp = TEMP / f"pdf_{hashlib.md5(str(caminho).encode()).hexdigest()[:8]}_{i}.png"
                pix.save(str(temp))
                ocr = ocr_imagem(temp)
                if ocr.get("ok"):
                    textos.append(ocr["texto"])
                temp.unlink(missing_ok=True)
            except Exception:
                pass
        doc.close()
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
    texto = "\n\n".join(textos).strip()
    if not texto:
        return {"ok": False, "erro": "PDF sem texto legível"}
    return {"ok": True, "caminho": str(caminho), "texto": texto[:20000],
            "paginas": len(textos)}


def ler_documento(caminho: str | Path) -> dict:
    p = Path(caminho).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "erro": f"arquivo não encontrado: {p}"}
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _ocr_pdf(p)
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        return ocr_imagem(p)
    try:
        texto = p.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "caminho": str(p), "texto": texto[:20000]}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def extrair_texto(caminho: str | Path) -> str:
    r = ler_documento(caminho)
    return r.get("texto", "") if r.get("ok") else ""


def registrar_ferramentas(tools):
    def documento(caminho: str) -> dict:
        return ler_documento(caminho)

    def imagem(caminho: str) -> dict:
        return ocr_imagem(caminho)

    def pdf(caminho: str) -> dict:
        return _ocr_pdf(Path(caminho).expanduser().resolve())

    tools.register("documento_ler", documento,
                   "Lê PDF, imagem (OCR) ou texto e devolve o conteúdo.",
                   {"caminho": "str"})
    tools.register("imagem_ocr", imagem,
                   "Extrai texto de uma imagem usando OCR do Windows.",
                   {"caminho": "str"})
    tools.register("pdf_ler", pdf,
                   "Extrai texto de PDF (texto nativo ou OCR por página).",
                   {"caminho": "str"})
