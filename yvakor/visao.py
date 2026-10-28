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


TELAS_GIRO = 20      # data/telas/tela_00..19.png, reescritas em rodízio
_tela_n = 0


def capturar_tela(largura_max: int = 1920) -> Path:
    """Print do(s) monitor(es) do Windows num PNG em data/telas."""
    global _tela_n
    from PIL import ImageGrab
    from yvakor.config import ROOT
    img = ImageGrab.grab(all_screens=True)
    if img.width > largura_max:
        img = img.resize((largura_max, int(img.height * largura_max / img.width)))
    pasta = ROOT / "data" / "telas"
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"tela_{_tela_n % TELAS_GIRO:02d}.png"
    _tela_n += 1
    img.save(arq)
    return arq


def ver_tela(pergunta: str = "", visual: bool = False) -> dict:
    """Como o screenshot do computer use: o agente "olha" o monitor. Antes ele
    tentava scrot/import pelo shell (comandos de Linux) e pedia print."""
    try:
        arq = capturar_tela()
    except Exception as exc:
        return {"ok": False, "erro": f"não consegui capturar a tela: {exc}"}
    r = {"ok": True, "arquivo": str(arq)}
    try:
        from yvakor.documentos import ocr_imagem
        ocr = ocr_imagem(arq)
        r["texto"] = (ocr.get("texto") or "")[:6000] if ocr.get("ok") else ""
        if not ocr.get("ok"):
            r["aviso_ocr"] = ocr.get("erro", "")[:200]
    except Exception as exc:
        r["texto"], r["aviso_ocr"] = "", str(exc)[:200]
    if visual or (pergunta and len(r["texto"]) < 40):
        d = descrever(arq, pergunta or "Descreva o que aparece nesta tela.")
        if d.get("ok"):
            r["descricao_visual"] = d.get("texto", "")[:2000]
    r["dica"] = ("texto = o que está escrito na tela (OCR). Para detalhes visuais "
                 "use visual=true; se for uma página do Chrome, navegador_ver "
                 "devolve o conteúdo com refs para agir.")
    return r


def registrar_ferramentas(tools):
    def ver(caminho: str, pergunta: str = "Descreva a imagem") -> dict:
        return analisar(caminho, pergunta)

    tools.register("visao_analisar", ver,
                   "Analisa imagem/tela com visão local: descreve cena, layout, "
                   "texto e dados; usa OCR como complemento.",
                   {"caminho": "str", "pergunta": "str?"})
    tools.register("tela_ver", ver_tela,
                   "Captura a tela do Windows (todos os monitores) e lê o texto "
                   "dela (OCR). Use quando o usuário pergunta o que está na tela "
                   "ou quer que você veja um programa fora do navegador. "
                   "visual=true descreve também a imagem (mais lento).",
                   {"pergunta": "str?", "visual": "bool?"})
