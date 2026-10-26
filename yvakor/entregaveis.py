"""YVAKOR — entregáveis: relatórios, planilhas, fotos e pacotes."""
from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from yvakor.config import ROOT

PASTA = ROOT / "data" / "artefatos"
FOTOS = PASTA / "fotos"


def _slug(texto: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (texto or "entrega").lower()).strip("-")
    return (base[:60] or "entrega") + "-" + str(int(datetime.now().timestamp()))


def _md_para_texto(md: str) -> str:
    t = str(md or "")
    t = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", t).replace("```", "")
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t, flags=re.S)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", t)
    t = re.sub(r"`([^`\n]+)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", t)
    t = re.sub(r"(?m)^\s*[-*]\s+", "• ", t)
    return t.strip()


def _pdf(titulo: str, texto: str, destino: Path) -> None:
    import pymupdf
    doc = pymupdf.open()
    margem = 56
    largura, altura = 595, 842
    restante = texto
    while restante:
        pagina = doc.new_page(width=largura, height=altura)
        pagina.insert_text((margem, 58), titulo, fontsize=15,
                           fontname="hebo", color=(0.12, 0.11, 0.09))
        pagina.draw_line((margem, 68), (largura - margem, 68),
                         color=(0.75, 0.62, 0.35), width=1)
        ret = pymupdf.Rect(margem, 82, largura - margem, altura - margem)
        sobra = pagina.insert_textbox(ret, restante, fontsize=9.5,
                                      fontname="helv", lineheight=1.35)
        if sobra >= 0 or len(restante) < 20:
            break
        # insert_textbox devolve espaço não usado; calcula corte aproximado
        corte = max(500, int(len(restante) * (1 - max(0, sobra) /
                                               max(1, ret.height * 1.35))))
        if corte >= len(restante):
            break
        restante = restante[corte:]
    doc.save(str(destino))
    doc.close()


def _html(titulo: str, markdown: str, destino: Path) -> None:
    corpo = _md_para_texto(markdown)
    linhas = "\n".join(f"<p>{ln}</p>" if ln.strip() else "<br>"
                       for ln in corpo.splitlines())
    destino.write_text(f"""<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><title>{titulo}</title>
<style>
@font-face{{font-family:'Inter';src:url('/fonts/Inter.ttf')}}
@font-face{{font-family:'Lora';src:url('/fonts/Lora.ttf')}}
body{{margin:0;background:#f7f3ea;color:#1e1c19;font-family:Inter,sans-serif;
line-height:1.55}}
main{{max-width:760px;margin:48px auto;padding:38px 44px;background:#fffdf8;
border:1px solid #e6dfd2;border-radius:14px}}
h1{{font-family:Lora,serif;font-size:30px;font-weight:600;margin:0 0 6px}}
.meta{{color:#716b61;font-size:11px;margin-bottom:24px}}
p{{font-size:13px;margin:7px 0}}
</style></head><body><main><h1>{titulo}</h1>
<div class="meta">YVAKOR · {datetime.now():%d/%m/%Y %H:%M}</div>
{linhas}</main></body></html>""", encoding="utf-8")


def relatorio(titulo: str, conteudo: str, formato: str = "pdf") -> dict:
    PASTA.mkdir(parents=True, exist_ok=True)
    formato = (formato or "pdf").lower()
    slug = _slug(titulo)
    try:
        if formato == "pdf":
            destino = PASTA / f"{slug}.pdf"
            try:
                _pdf(titulo, _md_para_texto(conteudo).replace("•", "-"), destino)
                tipo = "pdf"
            except Exception:
                destino = PASTA / f"{slug}.html"
                _html(titulo, conteudo, destino)
                tipo = "relatorio"
        elif formato == "html":
            destino = PASTA / f"{slug}.html"
            _html(titulo, conteudo, destino)
            tipo = "relatorio"
        elif formato == "docx":
            from docx import Document
            destino = PASTA / f"{slug}.docx"
            doc = Document()
            doc.add_heading(titulo, level=1)
            for linha in _md_para_texto(conteudo).splitlines():
                doc.add_paragraph(linha)
            doc.save(str(destino))
            tipo = "documento"
        else:
            destino = PASTA / f"{slug}.md"
            destino.write_text(f"# {titulo}\n\n{conteudo}\n", encoding="utf-8")
            tipo = "texto"
        return {"ok": True, "arquivo": str(destino), "titulo": titulo,
                "tipo": tipo, "formato": destino.suffix.lstrip(".")}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def _linhas(dados) -> list[list[str]]:
    if isinstance(dados, list):
        if dados and isinstance(dados[0], (list, tuple)):
            return [[str(c) for c in linha] for linha in dados]
        return [[str(x)] for x in dados]
    texto = str(dados or "").strip()
    if not texto:
        return []
    try:
        j = json.loads(texto)
        if isinstance(j, list):
            return _linhas(j)
    except Exception:
        pass
    return [linha for linha in csv.reader(io.StringIO(texto))]


def planilha(titulo: str, dados, formato: str = "xlsx") -> dict:
    PASTA.mkdir(parents=True, exist_ok=True)
    linhas = _linhas(dados)
    if not linhas:
        return {"ok": False, "erro": "sem dados para a planilha"}
    slug = _slug(titulo)
    try:
        if formato.lower() == "csv":
            destino = PASTA / f"{slug}.csv"
            with destino.open("w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerows(linhas)
            tipo = "planilha"
        else:
            try:
                from openpyxl import Workbook
                from openpyxl.styles import Font, PatternFill
                destino = PASTA / f"{slug}.xlsx"
                wb = Workbook()
                ws = wb.active
                ws.title = (titulo or "Dados")[:28]
                for linha in linhas:
                    ws.append(linha)
                for c in ws[1]:
                    c.font = Font(bold=True, color="FFFFFF")
                    c.fill = PatternFill("solid", fgColor="B9822E")
                for col in ws.columns:
                    ws.column_dimensions[col[0].column_letter].width = min(
                        48, max(12, max(len(str(c.value or "")) for c in col) + 2))
                wb.save(str(destino))
                tipo = "planilha"
            except Exception:
                destino = PASTA / f"{slug}.csv"
                with destino.open("w", encoding="utf-8", newline="") as f:
                    csv.writer(f).writerows(linhas)
                tipo = "planilha"
        return {"ok": True, "arquivo": str(destino), "titulo": titulo,
                "tipo": tipo, "linhas": len(linhas)}
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def _baixar(url: str, destino: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "YVAKOR/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        dados = r.read(12_000_000)
    if len(dados) < 2000:
        return False
    destino.write_bytes(dados)
    return True


def buscar_foto(termo: str, quantidade: int = 1) -> dict:
    """Busca foto real em acervos abertos e, se não achar, gera uma imagem."""
    FOTOS.mkdir(parents=True, exist_ok=True)
    termo = (termo or "").strip()
    if not termo:
        return {"ok": False, "erro": "termo vazio"}
    q = urllib.parse.quote_plus(termo)
    fotos = []

    # Pexels (opcional, se houver chave) — licença Pexels
    chave_pexels = os.getenv("PEXELS_API_KEY") or ""
    if chave_pexels:
        try:
            req = urllib.request.Request(
                f"https://api.pexels.com/v1/search?query={q}"
                f"&per_page={max(1, min(5, quantidade))}",
                headers={"Authorization": chave_pexels,
                         "User-Agent": "YVAKOR/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                dados = json.loads(r.read().decode("utf-8", errors="replace"))
            for item in (dados.get("photos") or [])[:quantidade]:
                f = FOTOS / f"foto-{_slug(termo)}-pexels-{len(fotos)+1}.jpg"
                if not _baixar((item.get("src") or {}).get("large2x") or "", f):
                    continue
                fotos.append({
                    "ok": True, "arquivo": str(f),
                    "titulo": item.get("alt") or termo,
                    "fonte": "Pexels",
                    "autor": item.get("photographer") or "Pexels",
                    "licenca": "Licença Pexels",
                    "url_origem": item.get("url") or "",
                    "tipo": "foto"})
        except Exception:
            pass

    # Openverse — todas as licenças, com atribuição
    if not fotos:
        try:
            req = urllib.request.Request(
                f"https://api.openverse.org/v1/images/?q={q}"
                f"&page_size={max(1, min(5, quantidade))}",
                headers={"User-Agent": "YVAKOR/1.0"})
            with urllib.request.urlopen(req, timeout=18) as r:
                dados = json.loads(r.read().decode("utf-8", errors="replace"))
            for item in (dados.get("results") or [])[:quantidade]:
                img_url = item.get("url") or ""
                if not img_url.lower().split("?")[0].endswith(
                        (".jpg", ".jpeg", ".png", ".webp")):
                    continue
                f = FOTOS / f"foto-{_slug(termo)}-{len(fotos)+1}.jpg"
                if not _baixar(img_url, f):
                    continue
                autor = re.sub(r"<[^>]+>", "", str(item.get("creator") or ""))
                fotos.append({
                    "ok": True, "arquivo": str(f),
                    "titulo": item.get("title") or termo,
                    "fonte": item.get("source") or "Openverse",
                    "autor": html.unescape(autor) or "desconhecido",
                    "licenca": item.get("license") or "ver fonte",
                    "url_origem": item.get("foreign_landing_url") or img_url,
                    "tipo": "foto"})
        except Exception:
            pass

    # Wikimedia Commons — todas as licenças, com atribuição
    if not fotos:
        try:
            api = ("https://commons.wikimedia.org/w/api.php?action=query"
                   "&generator=search&gsrnamespace=6&gsrlimit="
                   f"{max(1, min(5, quantidade))}&gsrsearch=" + q +
                   "&prop=imageinfo&iiprop=url|extmetadata&format=json")
            req = urllib.request.Request(api, headers={"User-Agent": "YVAKOR/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                dados = json.loads(r.read().decode("utf-8", errors="replace"))
            for pagina in (dados.get("query", {}).get("pages") or {}).values():
                info = (pagina.get("imageinfo") or [{}])[0]
                img = info.get("url") or ""
                if (not img or img.lower().split("?")[0].endswith(".pdf")
                        or img.lower().split("?")[0].endswith(".svg")):
                    continue
                meta = info.get("extmetadata") or {}
                f = FOTOS / f"foto-{_slug(termo)}-{len(fotos)+1}.jpg"
                if not _baixar(img, f):
                    continue
                autor = html.unescape(re.sub(
                    r"<[^>]+>", "", str((meta.get("Artist") or {}).get("value") or "")))
                licenca = html.unescape(re.sub(
                    r"<[^>]+>", "",
                    str((meta.get("LicenseShortName") or {}).get("value") or "")))
                fotos.append({
                    "ok": True, "arquivo": str(f),
                    "titulo": pagina.get("title") or termo,
                    "fonte": "Wikimedia Commons",
                    "autor": autor.strip() or "desconhecido",
                    "licenca": licenca.strip() or "ver fonte",
                    "url_origem": info.get("descriptionurl") or img,
                    "tipo": "foto"})
        except Exception:
            pass

    # Fallback criativo: gera a imagem quando não existe foto adequada.
    if not fotos:
        try:
            from yvakor.capacidades import gerar_imagem
            r = gerar_imagem(f"fotografia realista de {termo}, alta qualidade, "
                             f"iluminação natural, composição editorial")
            if r.get("ok") and r.get("arquivo"):
                fotos.append({
                    "ok": True, "arquivo": r["arquivo"],
                    "titulo": f"Imagem gerada: {termo}",
                    "fonte": "IA (Pollinations)",
                    "autor": "YVAKOR",
                    "licenca": "imagem gerada",
                    "url_origem": "",
                    "tipo": "imagem"})
        except Exception:
            pass

    if not fotos:
        return {"ok": False, "erro": "nenhuma foto encontrada"}
    return {"ok": True, "fotos": fotos, "termo": termo}


def registrar_ferramentas(tools):
    def rel(titulo: str, conteudo: str, formato: str = "pdf") -> dict:
        return relatorio(titulo, conteudo, formato)

    def plan(titulo: str, dados: str, formato: str = "xlsx") -> dict:
        return planilha(titulo, dados, formato)

    def foto(termo: str, quantidade: int = 1) -> dict:
        return buscar_foto(termo, quantidade)

    tools.register("entregar_relatorio", rel,
                   "Gera relatório PDF/HTML/DOCX/MD e entrega o arquivo.",
                   {"titulo": "str", "conteudo": "str", "formato": "str?"})
    tools.register("gerar_planilha", plan,
                   "Gera planilha XLSX/CSV a partir de linhas CSV/JSON.",
                   {"titulo": "str", "dados": "str", "formato": "str?"})
    tools.register("buscar_foto", foto,
                   "Busca foto real com licença aberta e entrega o arquivo.",
                   {"termo": "str", "quantidade": "int?"})
