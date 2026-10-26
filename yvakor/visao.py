"""YVAKOR — visão local: descreve imagens/telas com Ollama e OCR."""
from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434"


def _settings() -> dict:
    try:
        from yvakor.config import load_settings
        return (load_settings() or {}).get("visao", {}) or {}
    except Exception:
        return {}


def modelo() -> str:
    import os
    return os.getenv("VISION_MODEL") or _settings().get("modelo") or "moondream"


def disponivel(m: str | None = None) -> bool:
    try:
        req = urllib.request.Request(OLLAMA + "/api/tags",
                                     headers={"User-Agent": "YVAKOR/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            tags = json.loads(r.read().decode())
        alvo = (m or modelo()).split(":")[0]
        return any(alvo in (x.get("name") or "") for x in tags.get("models", []))
    except Exception:
        return False


def descrever(caminho: str | Path, pergunta: str = "",
              m: str | None = None, timeout: int | None = None) -> dict:
    p = Path(caminho).expanduser().resolve()
    if not p.is_file():
        return {"ok": False, "erro": "imagem não encontrada"}
    cfg = _settings()
    if not cfg.get("ativa", True):
        return {"ok": False, "erro": "visão desativada"}
    m = m or modelo()
    if not disponivel(m):
        return {"ok": False, "erro": f"modelo de visão '{m}' não instalado"}
    try:
        from PIL import Image
        import tempfile
        with Image.open(p) as img:
            img = img.convert("RGB")
            lado = max(img.size)
            if lado > 384:
                escala = 384 / lado
                img = img.resize((max(1, int(img.width * escala)),
                                  max(1, int(img.height * escala))))
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                img.save(tmp.name, format="JPEG", quality=82)
                caminho_tmp = Path(tmp.name)
        try:
            b64 = base64.b64encode(caminho_tmp.read_bytes()).decode()
        finally:
            try:
                caminho_tmp.unlink()
            except OSError:
                pass
        prompt = (
            "Describe this screenshot objectively in English. Mention the "
            "layout, visible text, buttons, charts and important details.")
        payload = {"model": m, "prompt": prompt, "images": [b64],
                   "stream": False,
                   "options": {"temperature": 0.2, "num_predict": 90}}
        req = urllib.request.Request(
            OLLAMA + "/api/generate", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "User-Agent": "YVAKOR/1.0"})
        with urllib.request.urlopen(req, timeout=timeout or
                                    int(cfg.get("timeout_s", 120))) as r:
            dados = json.loads(r.read().decode("utf-8", errors="replace"))
        texto = (dados.get("response") or "").strip()
        if not texto:
            return {"ok": False, "erro": "modelo não retornou descrição"}
        return {"ok": True, "texto": texto, "motor": f"ollama-{m}",
                "modelo": m, "arquivo": str(p)}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def analisar(caminho: str | Path, pergunta: str = "") -> dict:
    """Visão + OCR; sempre devolve o máximo que conseguir."""
    visao = descrever(caminho, pergunta)
    ocr = ""
    try:
        from yvakor.documentos import extrair_texto
        ocr = extrair_texto(caminho)
    except Exception:
        pass
    if not visao.get("ok") and not ocr:
        return {"ok": False, "erro": visao.get("erro", "sem análise")}
    partes = []
    if visao.get("ok") and len((visao.get("texto") or "").strip()) >= 10:
        partes.append("## ANÁLISE VISUAL\n" + visao["texto"])
    if ocr:
        partes.append("## TEXTO OCR\n" + ocr[:8000])
    if not partes:
        return {"ok": False, "erro": visao.get("erro", "sem análise")}
    return {"ok": True, "texto": "\n\n".join(partes),
            "motor": visao.get("motor", "ocr"),
            "visao": visao.get("texto", ""), "ocr": ocr[:8000]}


def registrar_ferramentas(tools):
    def ver(caminho: str, pergunta: str = "Descreva a imagem") -> dict:
        return analisar(caminho, pergunta)

    tools.register("visao_analisar", ver,
                   "Analisa imagem/tela com visão local: descreve cena, layout, "
                   "texto e dados; usa OCR como complemento.",
                   {"caminho": "str", "pergunta": "str?"})
