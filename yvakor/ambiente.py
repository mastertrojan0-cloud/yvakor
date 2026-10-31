"""YVAKOR — aprendiz de entorno: sistema e fichas de cada equipamento.

Grava notas determinísticas no vault (sobrescreve, não duplica):
  Ambiente/Sistema.md
  Equipamentos/<slug>.md
O cérebro indexa e passa a responder sobre o que cada aparelho faz.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import time
import urllib.request
from datetime import datetime
from pathlib import Path
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE_TESTES = ROOT / "data" / "ambiente_probes.json"


def _slug(texto: str) -> str:
    t = (texto or "").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "equipamento"


def _vault(cerebro, settings: dict) -> Path:
    d = getattr(cerebro, "dir", None)
    if d:
        return Path(d)
    return Path(settings.get("cerebro", {}).get("vault_dir", "data/vault"))


def _nota(vault: Path, pasta: str, nome: str, corpo: str, tags: list[str],
          titulo: str) -> Path:
    d = vault / pasta
    d.mkdir(parents=True, exist_ok=True)
    arq = d / f"{nome}.md"
    tags_txt = ", ".join(tags)
    arq.write_text(
        f"---\ntitulo: {titulo}\ntags: [{tags_txt}]\ntipo: {pasta.lower()}\n"
        f"atualizado: {datetime.now().isoformat(timespec='seconds')}\n---\n\n"
        f"{corpo.strip()}\n", encoding="utf-8")
    return arq


def _funcoes(dev: dict) -> list[str]:
    tipo = (dev.get("tipo") or "").lower()
    portas = set(dev.get("portas") or [])
    funcs = []
    if tipo == "camera":
        funcs.append("captura de imagem (snapshot)")
        funcs.append("vídeo ao vivo por RTSP")
        if portas & {80, 5000}:
            funcs.append("configuração via ONVIF")
        funcs.append("controle PTZ (se o modelo suportar)")
    elif tipo == "tv":
        funcs.append("espelhar tela / enviar mídia (Chromecast/DIAL)")
        funcs.append("ligar/desligar por rede (quando suportado)")
    elif tipo == "roteador":
        funcs.append("gateway da rede local")
        funcs.append("administração web")
    elif tipo == "telefone":
        funcs.append("pareamento/controle por ADB ou companion")
    elif tipo == "iot":
        funcs.append("controle por MQTT")
    elif tipo == "impressora":
        funcs.append("impressão via IPP/RAW")
    if 1883 in portas:
        funcs.append("MQTT")
    return funcs or ["função ainda não identificada"]


def _comandos(dev: dict) -> list[str]:
    tipo = (dev.get("tipo") or "").lower()
    if tipo == "camera":
        return ["rede_camera_janela(alvo)", "rede_camera_snapshot(alvo)",
                "rede_camera_ptz(alvo, x, y, zoom)"]
    if tipo == "tv":
        return ["rede_cast(alvo, ...)", "rede_tv(alvo, acao)"]
    if tipo == "roteador":
        return ["rede_escopo()", "rede_http_dispositivo(alvo)"]
    return ["rede_escanear()", "rede_dispositivos()"]


def _limitacoes(dev: dict) -> list[str]:
    tipo = (dev.get("tipo") or "").lower()
    portas = set(dev.get("portas") or [])
    lim = []
    if tipo == "camera" and 554 in portas:
        lim.append("RTSP pode recusar SETUP (ex.: firmware Yoosee 400); "
                   "ao vivo pode depender do app do fabricante.")
    if not portas:
        lim.append("nenhuma porta aberta: só presença/ARP; função não confirmada.")
    if not dev.get("fabricante"):
        lim.append("fabricante não identificado pelo MAC.")
    return lim or ["nenhuma limitação registrada."]


def _http_titulo(ip: str, portas: list[int]) -> str:
    for porta in [p for p in (80, 8080, 8000, 443) if p in portas]:
        try:
            url = f"http://{ip}:{porta}/"
            with urllib.request.urlopen(url, timeout=2) as r:
                html = r.read(20000).decode("utf-8", "replace")
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            if m:
                return f"HTTP {porta} — {m.group(1).strip()[:80]}"
        except Exception:
            continue
    return ""


def _probe(rede, dev: dict) -> list[str]:
    """Testes inofensivos: TCP, título HTTP e (câmera) snapshot."""
    ip = dev.get("ip")
    cache = {}
    try:
        if CACHE_TESTES.exists():
            cache = json.loads(CACHE_TESTES.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    anterior = cache.get(ip) or {}
    if anterior and time.time() - anterior.get("ts", 0) < 600:
        return anterior.get("testes") or []

    testes = []
    portas = dev.get("portas") or []
    if portas:
        try:
            s = socket.create_connection((ip, int(portas[0])), timeout=1.5)
            s.close()
            testes.append(f"TCP {portas[0]}: acessível")
        except Exception:
            testes.append(f"TCP {portas[0]}: sem resposta")
    titulo = _http_titulo(ip, portas)
    if titulo:
        testes.append(titulo)
    if (dev.get("tipo") or "") == "camera" and hasattr(rede, "cameras"):
        try:
            r = rede.cameras.snapshot(ip)
            testes.append("snapshot: " + (
                f"ok via {r.get('via')}" if r.get("ok")
                else f"falhou ({str(r.get('erro'))[:80]})"))
        except Exception as exc:
            testes.append(f"snapshot: erro ({str(exc)[:60]})")
    if not testes:
        testes.append("sem teste possível (sem portas abertas)")

    cache[ip] = {"ts": time.time(), "testes": testes}
    try:
        CACHE_TESTES.parent.mkdir(parents=True, exist_ok=True)
        CACHE_TESTES.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    except OSError:
        pass
    return testes


def _corpo_equipamento(dev: dict, testes: list[str] | None = None) -> str:
    nome = dev.get("nome") or dev.get("ip")
    linhas = [
        f"# {nome}", "",
        f"- **IP:** {dev.get('ip')}",
        f"- **Tipo:** {dev.get('tipo')}",
        f"- **Fabricante:** {dev.get('fabricante') or 'desconhecido'}",
        f"- **Modelo:** {dev.get('modelo') or '—'}",
        f"- **MAC:** {dev.get('mac') or '—'}",
        f"- **Portas:** {', '.join(str(p) for p in (dev.get('portas') or [])) or '—'}",
        f"- **Visto em:** {dev.get('atualizado_em') or dev.get('visto_em') or '—'}",
        "", "## Funções descobertas",
    ]
    linhas += [f"- {f}" for f in _funcoes(dev)]
    linhas += ["", "## Como operar"]
    linhas += [f"- `{c}`" for c in _comandos(dev)]
    linhas += ["", "## Limitações"]
    linhas += [f"- {l}" for l in _limitacoes(dev)]
    if testes:
        linhas += ["", "## Testes de capacidades"]
        linhas += [f"- {t}" for t in testes]
    linhas += ["", "## Observações",
               "Ficha gerada automaticamente pelo aprendiz de entorno. "
               "Credenciais ficam em data/rede.json, nunca nesta nota."]
    return "\n".join(linhas)


def _corpo_sistema(settings: dict, rede) -> str:
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "—"
    disco = shutil.disk_usage("E:\\") if os.path.exists("E:\\") else shutil.disk_usage("/")
    gateway = getattr(getattr(rede, "escopo", None), "gateway", "—")
    browser = settings.get("browser", {}) or {}
    linhas = [
        "# Ambiente — Sistema", "",
        f"- **Máquina:** {platform.node()}",
        f"- **SO:** {platform.system()} {platform.release()} ({platform.version()})",
        f"- **Python:** {platform.python_version()}",
        f"- **CPU:** {platform.processor() or '—'} ({os.cpu_count()} núcleos)",
        f"- **IP local:** {ip}",
        f"- **Gateway:** {gateway}",
        f"- **Disco E::** {round(disco.free / 1024**3, 1)} GB livres de "
        f"{round((disco.used + disco.free) / 1024**3, 1)} GB",
        f"- **Navegadores:** Edge/Chrome via Playwright "
        f"(modo {browser.get('modo', 'launch')})",
        "", "## Rotinas",
        "- monitor de rede contínuo (novos dispositivos viram ficha)",
        "- varredura de portas, SSDP e mDNS",
        "- cérebro Obsidian indexado em FTS5",
        "", f"Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M')}.",
    ]
    return "\n".join(linhas)


def aprender_equipamento(rede, cerebro, alvo: str,
                         sincronizar: bool = False) -> dict:
    dev = rede.registro.obter(alvo)
    if not dev:
        return {"ok": False, "erro": f"equipamento '{alvo}' não encontrado"}
    vault = _vault(cerebro, getattr(cerebro, "cfg", {}) or {})
    tipo = dev.get("tipo") or "dispositivo"
    testes = _probe(rede, dev)
    nome = _slug(dev.get("nome") or dev.get("ip"))
    arq = _nota(vault, "Equipamentos", f"{nome}-{dev.get('ip', '').replace('.', '-')}",
                _corpo_equipamento(dev, testes),
                ["equipamento", "ambiente", tipo], f"Equipamento {dev.get('nome') or dev.get('ip')}")
    if sincronizar:
        try:
            cerebro.sincronizar()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
    return {"ok": True, "ip": dev.get("ip"), "tipo": tipo, "nota": str(arq)}

def mapear(rede, cerebro) -> dict:
    settings = getattr(cerebro, "cfg", {}) or {}
    vault = _vault(cerebro, settings)
    sistema = _nota(vault, "Ambiente", "sistema", _corpo_sistema(settings, rede),
                    ["ambiente", "sistema"], "Ambiente — Sistema")
    notas = [str(sistema)]
    for dev in rede.registro.listar():
        r = aprender_equipamento(rede, cerebro, dev.get("ip"))
        if r.get("ok"):
            notas.append(r["nota"])
    try:
        cerebro.sincronizar()
    except Exception:
        _log.debug("exceção ignorada", exc_info=True)
    return {"ok": True, "notas": len(notas), "equipamentos": len(notas) - 1,
            "arquivos": notas, "vault": str(vault)}


def register_ambiente_tools(registry, rede, cerebro) -> list[str]:
    def ambiente_mapear() -> dict:
        return mapear(rede, cerebro)

    def ambiente_equipamento(alvo: str) -> dict:
        return aprender_equipamento(rede, cerebro, alvo)

    registry.register("ambiente_mapear", ambiente_mapear,
                      "Mapeia o sistema e grava/atualiza a ficha de cada "
                      "equipamento no vault.", {})
    registry.register("ambiente_equipamento", ambiente_equipamento,
                      "Aprende/atualiza a ficha de um equipamento (IP ou nome).",
                      {"alvo": "str"})
    return ["ambiente_mapear", "ambiente_equipamento"]
