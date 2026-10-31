"""
YVAKOR — Plugins: pacotes de skills + comandos + servidores MCP

No modelo dos plugins do Claude (e compatível com o layout deles):

  plugins/<nome>/
    .yvakor-plugin/plugin.json   (ou .claude-plugin/plugin.json, ou plugin.json)
        {"name": "...", "description": "...", "version": "..."}
    skills/<skill>/SKILL.md      → skills "<plugin>:<skill>" (só leitura)
    commands/<comando>.md        → comando "/<comando>" no chat; o texto é o
                                   prompt, com $ARGUMENTS = o resto da mensagem
    agents/<agente>.md           → subagente "<plugin>:<agente>" (yvakor/agentes.py)
    hooks/hooks.json             → hooks somados ao config/hooks.json (yvakor/hooks.py)
    .mcp.json                    → {"mcpServers": {...}} somados ao config/mcp.json
                                   (${CLAUDE_PLUGIN_ROOT}/${YVAKOR_PLUGIN_ROOT}
                                   viram a pasta do plugin)

Plugin novo começa DESLIGADO: ele pode trazer servidores MCP (programas que
rodam no PC) e instruções que entram no prompt. Leia o conteúdo e ligue com
"/plugins ligar <nome>". Estado em data/plugins_estado.json.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from yvakor import injecao, seguro
from yvakor.config import ROOT

_log = logging.getLogger(__name__)

PASTA = ROOT / "plugins"
ESTADO = ROOT / "data" / "plugins_estado.json"
MANIFESTOS = (".yvakor-plugin/plugin.json", ".claude-plugin/plugin.json", "plugin.json")
_RAIZ_VARS = ("${CLAUDE_PLUGIN_ROOT}", "${YVAKOR_PLUGIN_ROOT}")


@dataclass
class Plugin:
    nome: str
    pasta: Path
    descricao: str = ""
    versao: str = ""
    skills: dict[str, Path] = field(default_factory=dict)
    comandos: dict[str, Path] = field(default_factory=dict)
    mcp: dict[str, dict] = field(default_factory=dict)
    agentes: dict[str, Path] = field(default_factory=dict)
    hooks: dict = field(default_factory=dict)
    bloqueados: list[str] = field(default_factory=list)


def _nome(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (texto or "").lower()).strip("-")


def _trocar_raiz(valor, raiz: str):
    if isinstance(valor, str):
        for v in _RAIZ_VARS:
            valor = valor.replace(v, raiz)
        return valor
    if isinstance(valor, list):
        return [_trocar_raiz(v, raiz) for v in valor]
    if isinstance(valor, dict):
        return {k: _trocar_raiz(v, raiz) for k, v in valor.items()}
    return valor


def ler_plugin(pasta: Path) -> Plugin | None:
    manifesto = next((pasta / m for m in MANIFESTOS if (pasta / m).is_file()), None)
    if manifesto is None:
        return None
    try:
        meta = json.loads(manifesto.read_text(encoding="utf-8"))
    except ValueError:
        _log.warning("plugin com manifesto inválido: %s", manifesto)
        return None
    p = Plugin(nome=_nome(meta.get("name") or pasta.name) or _nome(pasta.name),
               pasta=pasta, descricao=str(meta.get("description") or "")[:500],
               versao=str(meta.get("version") or ""))
    for arq in sorted(pasta.glob("skills/*/SKILL.md")):
        texto = arq.read_text(encoding="utf-8", errors="replace")
        motivos = injecao.varrer(texto)
        if motivos:      # skill de terceiro suspeita não entra no prompt
            _log.warning("skill de plugin bloqueada (%s): %s", ", ".join(motivos), arq)
            p.bloqueados.append(f"skill {arq.parent.name}: {', '.join(motivos)}")
            continue
        p.skills[f"{p.nome}:{arq.parent.name}"] = arq
    for arq in sorted(pasta.glob("commands/*.md")):
        texto = arq.read_text(encoding="utf-8", errors="replace")
        motivos = injecao.varrer(texto)
        if motivos:
            p.bloqueados.append(f"comando {arq.stem}: {', '.join(motivos)}")
            continue
        p.comandos[_nome(arq.stem)] = arq
    for arq in sorted(pasta.glob("agents/*.md")):
        p.agentes[f"{p.nome}:{arq.stem}"] = arq     # varredura em agentes.ler_definicao
    ganchos = pasta / "hooks" / "hooks.json"
    if ganchos.is_file():
        try:
            p.hooks = json.loads(ganchos.read_text(encoding="utf-8"))
        except ValueError:
            p.bloqueados.append("hooks/hooks.json inválido")
    mcp = pasta / ".mcp.json"
    if mcp.is_file():
        try:
            dados = json.loads(mcp.read_text(encoding="utf-8"))
            servidores = dados.get("mcpServers") or dados.get("servers") or {}
            p.mcp = {f"{p.nome}-{n}": {**_trocar_raiz(c, str(pasta)), "enabled": True}
                     for n, c in servidores.items() if isinstance(c, dict)}
        except ValueError:
            p.bloqueados.append(".mcp.json inválido")
    return p


class GerenciadorPlugins:
    def __init__(self, pasta: Path | None = None, estado: Path | None = None):
        self.pasta = Path(pasta or PASTA)
        self.estado = Path(estado or ESTADO)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    def descobrir(self) -> list[Plugin]:
        if not self.pasta.is_dir():
            return []
        achados = [ler_plugin(d) for d in sorted(self.pasta.iterdir()) if d.is_dir()]
        return [p for p in achados if p is not None]

    def _ligados(self) -> set[str]:
        return set((seguro.ler_json(self.estado, {}) or {}).get("ligados") or [])

    def ativos(self) -> list[Plugin]:
        ligados = self._ligados()
        return [p for p in self.descobrir() if p.nome in ligados]

    def definir(self, nome: str, ligado: bool) -> dict:
        nome = _nome(nome)
        if not any(p.nome == nome for p in self.descobrir()):
            return {"ok": False, "error": f"plugin {nome!r} não existe em {self.pasta}"}
        with self._lock:
            ligados = self._ligados()
            (ligados.add if ligado else ligados.discard)(nome)
            seguro.gravar_json(self.estado, {"ligados": sorted(ligados)})
        aviso = " Servidores MCP do plugin sobem no próximo início do YVAKOR." \
            if ligado and any(p.mcp for p in self.descobrir() if p.nome == nome) else ""
        return {"ok": True, "result": f"plugin {nome} {'ligado' if ligado else 'desligado'}."
                + aviso}

    # ------------------------------------------------------------------ #
    def skills_extras(self) -> dict[str, Path]:
        extras: dict[str, Path] = {}
        for p in self.ativos():
            extras.update(p.skills)
        return extras

    def comandos(self) -> dict[str, Path]:
        """'/plugin:cmd' sempre; '/cmd' quando só um plugin ativo o define."""
        cmds: dict[str, Path] = {}
        contagem: dict[str, int] = {}
        for p in self.ativos():
            for c, arq in p.comandos.items():
                cmds[f"{p.nome}:{c}"] = arq
                contagem[c] = contagem.get(c, 0) + 1
                cmds.setdefault(c, arq)
        for c, n in contagem.items():
            if n > 1:
                cmds.pop(c, None)
        return cmds

    def agentes_extras(self) -> dict[str, Path]:
        extras: dict[str, Path] = {}
        for p in self.ativos():
            extras.update(p.agentes)
        return extras

    def hooks_extras(self) -> list[tuple[dict, Path]]:
        return [(p.hooks, p.pasta) for p in self.ativos() if p.hooks]

    def servidores_mcp(self) -> dict[str, dict]:
        servidores: dict[str, dict] = {}
        for p in self.ativos():
            servidores.update(p.mcp)
        return servidores

    def listar(self) -> dict:
        ligados = self._ligados()
        return {"ok": True, "pasta": str(self.pasta), "plugins": [{
            "nome": p.nome, "descricao": p.descricao, "versao": p.versao,
            "ligado": p.nome in ligados, "skills": sorted(p.skills),
            "comandos": sorted(p.comandos), "mcp": sorted(p.mcp),
            "agentes": sorted(p.agentes), "hooks": sorted((p.hooks.get("hooks") or {})),
            "bloqueados": p.bloqueados} for p in self.descobrir()]}


def expandir_comando(arq: Path, argumentos: str) -> str:
    """Texto do comando com $ARGUMENTS trocado (ou os argumentos no fim)."""
    texto = arq.read_text(encoding="utf-8", errors="replace")
    if texto.startswith("---"):      # front-matter (description etc.) não vai ao modelo
        fim = texto.find("\n---", 3)
        if fim != -1:
            texto = texto[fim + 4:]
    texto = texto.strip()
    if "$ARGUMENTS" in texto:
        return texto.replace("$ARGUMENTS", argumentos)
    return f"{texto}\n\n{argumentos}".strip()
