"""YVAKOR — descoberta dos projetos existentes no computador."""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from yvakor import seguro
from yvakor.config import ROOT

INDICE = ROOT / "data" / "projetos_index.json"
IGNORAR = {
    "node_modules", ".git", "venv", ".venv", "__pycache__", ".cache",
    "dist", "build", "target", "vendor", "site-packages", "AppData",
    "Windows", "Program Files", "Program Files (x86)", "$Recycle.Bin",
    "System Volume Information", ".next", "coverage", "tmp", "temp",
}
MARCADORES = {
    ".git": "git",
    "package.json": "node",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "composer.json": "php",
    "pom.xml": "java",
    "build.gradle": "java",
    "pubspec.yaml": "flutter",
    "Gemfile": "ruby",
    "*.sln": "dotnet",
    "*.csproj": "dotnet",
}


class GerenciadorProjetos:
    def __init__(self):
        self.itens: list[dict] = []
        self.atualizado_em = ""
        self._carregar()

    def _carregar(self):
        data = seguro.ler_json(INDICE, {})
        if not isinstance(data, dict):
            data = {}
        self.itens = data.get("projetos", [])
        self.atualizado_em = data.get("atualizado_em", "")

    def _salvar(self):
        seguro.gravar_json(INDICE, {"atualizado_em": self.atualizado_em,
                                    "projetos": self.itens}, indent=1)

    def precisa_escanear(self) -> bool:
        if not self.itens:
            return True
        try:
            quando = datetime.fromisoformat(self.atualizado_em)
            return (datetime.now() - quando).total_seconds() > 86400
        except Exception:
            return True

    def escanear(self, roots: list[str] | None = None, profundidade: int = 4,
                 limite_s: float = 35.0) -> dict:
        inicio = time.time()
        if roots is None:
            roots = []
            for p in ("E:/", "D:/", str(Path.home()), "C:/dev", "C:/projetos"):
                if Path(p).is_dir():
                    roots.append(p)
            roots.append(str(ROOT))
        achados: dict[str, dict] = {}
        for raiz in roots:
            if time.time() - inicio > limite_s:
                break
            base = Path(raiz)
            if not base.is_dir():
                continue
            base_prof = len(base.parts)
            for dirpath, dirnames, filenames in os.walk(base, topdown=True):
                if time.time() - inicio > limite_s:
                    break
                atual = Path(dirpath)
                if len(atual.parts) - base_prof > profundidade:
                    dirnames[:] = []
                    continue
                dirnames[:] = [d for d in dirnames if d not in IGNORAR
                               and not d.startswith(".")]
                baixo = str(atual).lower()
                if "\\data\\projetos" in baixo or "\\venv\\" in baixo:
                    dirnames[:] = []
                    continue
                tipos = []
                for marca, tipo in MARCADORES.items():
                    if marca.startswith("*"):
                        if any(atual.glob(marca)):
                            tipos.append(tipo)
                    elif (atual / marca).exists():
                        tipos.append(tipo)
                if not tipos:
                    continue
                # não conta subprojeto dentro de um projeto já achado
                if any(str(atual).lower().startswith(p + os.sep)
                       for p in achados):
                    dirnames[:] = []
                    continue
                try:
                    mtime = atual.stat().st_mtime
                except OSError:
                    mtime = 0
                achados[str(atual).lower()] = {
                    "nome": atual.name or str(atual),
                    "caminho": str(atual),
                    "tipos": sorted(set(tipos)),
                    "modificado": datetime.fromtimestamp(mtime).isoformat(
                        timespec="seconds") if mtime else "",
                }
                dirnames[:] = []
        self.itens = sorted(achados.values(), key=lambda x: x["nome"].lower())
        self.atualizado_em = datetime.now().isoformat(timespec="seconds")
        self._salvar()
        return {"ok": True, "total": len(self.itens),
                "atualizado_em": self.atualizado_em,
                "segundos": round(time.time() - inicio, 1)}

    def listar(self, filtro: str = "") -> list[dict]:
        if not filtro:
            return self.itens
        f = filtro.lower()
        return [p for p in self.itens
                if f in p["nome"].lower() or f in p["caminho"].lower()]

    def detalhe(self, termo: str) -> dict | None:
        f = (termo or "").lower()
        for p in self.itens:
            if p["nome"].lower() == f or p["caminho"].lower() == f:
                return p
        achados = self.listar(termo)
        return achados[0] if achados else None

    def abrir(self, termo: str) -> dict:
        p = self.detalhe(termo)
        if not p:
            return {"ok": False, "erro": f"projeto não encontrado: {termo}"}
        try:
            os.startfile(p["caminho"])  # type: ignore[attr-defined]
            return {"ok": True, "caminho": p["caminho"], "nome": p["nome"]}
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}


def registrar_ferramentas(tools, gerente: GerenciadorProjetos):
    def listar(filtro: str = "") -> dict:
        if not gerente.itens and not gerente.precisa_escanear():
            gerente.escanear()
        return {"ok": True, "total": len(gerente.itens),
                "projetos": gerente.listar(filtro)[:200]}

    def escanear() -> dict:
        return gerente.escanear()

    def detalhe(termo: str) -> dict:
        p = gerente.detalhe(termo)
        return {"ok": bool(p), "projeto": p} if p else {"ok": False,
                                                        "erro": "não encontrado"}

    def abrir(termo: str) -> dict:
        return gerente.abrir(termo)

    tools.register(
        "projetos_listar", listar,
        "Lista os projetos reconhecidos no computador.",
        {"filtro": {"type": "string", "description": "parte do nome/caminho"}})
    tools.register(
        "projetos_escanear", escanear,
        "Escaneia o computador e reconhece projetos.", {})
    tools.register(
        "projetos_detalhe", detalhe,
        "Detalha um projeto pelo nome ou caminho.",
        {"termo": {"type": "string"}})
    tools.register(
        "projetos_abrir", abrir,
        "Abre a pasta do projeto no Explorer.",
        {"termo": {"type": "string"}})
