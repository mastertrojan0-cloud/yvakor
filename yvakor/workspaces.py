"""YVAKOR — workspaces: pastas de projeto em que o YVAKOR trabalha.

Criar (com modelo pronto), adicionar uma pasta existente, ativar, ver detalhe
(árvore, git, README) e abrir na pasta/VS Code. Com um workspace ATIVO:
  - o prompt do agente leva o resumo do projeto (bloco_prompt);
  - executar_shell roda dentro dele e caminhos relativos apontam para ele.

Estado em data/workspaces.json. Remover da lista nunca apaga a pasta.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from yvakor import proc
from yvakor.config import ROOT

_log = logging.getLogger(__name__)

ARQ = ROOT / "data" / "workspaces.json"
IGNORAR = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
           ".next", ".cache", "target", ".idea", ".vscode", "coverage"}
STACKS = (("pyproject.toml", "Python"), ("requirements.txt", "Python"),
          ("package.json", "Node"), ("Cargo.toml", "Rust"), ("go.mod", "Go"),
          ("pom.xml", "Java"), ("composer.json", "PHP"), ("index.html", "Web"),
          ("pubspec.yaml", "Flutter"))

MODELOS: dict[str, dict[str, str]] = {
    "vazio": {},
    "python": {
        "main.py": 'def main() -> None:\n    print("Olá do {nome}!")\n\n\n'
                   'if __name__ == "__main__":\n    main()\n',
        "requirements.txt": "",
        "tests/test_main.py": "from main import main\n\n\ndef test_main(capsys):\n"
                              "    main()\n    assert \"{nome}\" in capsys.readouterr().out\n",
    },
    "node": {
        "package.json": '{{\n  "name": "{slug}",\n  "version": "0.1.0",\n'
                        '  "main": "index.js",\n  "scripts": {{ "start": "node index.js" }}\n}}\n',
        "index.js": 'console.log("Olá do {nome}!");\n',
    },
    "web": {
        "index.html": '<!doctype html>\n<html lang="pt-BR">\n<head>\n  <meta charset="utf-8">\n'
                      '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                      '  <title>{nome}</title>\n  <link rel="stylesheet" href="style.css">\n'
                      '</head>\n<body>\n  <main><h1>{nome}</h1></main>\n'
                      '  <script src="app.js"></script>\n</body>\n</html>\n',
        "style.css": "body {{ font-family: system-ui, sans-serif; margin: 2rem; }}\n",
        "app.js": 'console.log("{nome} pronto");\n',
    },
}
GITIGNORE = ("__pycache__/\n*.pyc\nvenv/\n.venv/\nnode_modules/\ndist/\nbuild/\n"
             ".env\n.DS_Store\nThumbs.db\n")

_lock = threading.RLock()


def _slug(texto: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (texto or "").strip().lower()).strip("-")
    return s or "workspace"


def pasta_base(settings: dict | None = None) -> Path:
    cfg = ((settings or {}).get("workspaces") or {}).get("pasta_base") or ""
    if cfg:
        return Path(os.path.expandvars(cfg))
    return Path("E:/Workspaces") if Path("E:/").exists() else Path.home() / "Workspaces"


def _ler() -> dict:
    try:
        dados = json.loads(ARQ.read_text(encoding="utf-8"))
        if isinstance(dados, dict):
            dados.setdefault("itens", [])
            return dados
    except (OSError, ValueError):
        pass
    return {"ativo": None, "itens": []}


def _gravar(dados: dict) -> None:
    ARQ.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQ.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ARQ)


def _git(caminho: Path, *args: str, timeout: float = 4) -> str:
    if not (caminho / ".git").exists() or not shutil.which("git"):
        return ""
    try:
        r = proc.run(["git", "-C", str(caminho), *args], capture_output=True,
                     text=True, encoding="utf-8", timeout=timeout)
        # só o fim: no porcelain o espaço inicial é parte do estado (" M arq")
        return (r.stdout or "").rstrip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _stack(caminho: Path) -> str:
    achadas = []
    for arq, nome in STACKS:
        if (caminho / arq).exists() and nome not in achadas:
            achadas.append(nome)
    return " + ".join(achadas) or "—"


def _info(item: dict, ativo: str | None) -> dict:
    p = Path(item["caminho"])
    existe = p.is_dir()
    status = _git(p, "status", "--porcelain", "-b") if existe else ""
    linhas = status.splitlines()
    branch = linhas[0][3:].split("...")[0] if linhas and linhas[0].startswith("##") else ""
    return {**item, "existe": existe, "ativo": item["id"] == ativo,
            "stack": _stack(p) if existe else "—", "branch": branch,
            "alteracoes": max(0, len(linhas) - 1) if branch else 0,
            "git": bool(branch)}


# ---------------------------------------------------------------------- #
# API
# ---------------------------------------------------------------------- #
def listar(com_info: bool = True) -> dict:
    dados = _ler()
    itens = sorted(dados["itens"], key=lambda i: i.get("ultimo_uso") or "", reverse=True)
    if com_info:
        itens = [_info(i, dados.get("ativo")) for i in itens]
    return {"ok": True, "ativo": dados.get("ativo"), "itens": itens,
            "sugestoes": sugestoes(dados)}


def sugestoes(dados: dict | None = None, limite: int = 12) -> list[dict]:
    """Projetos já descobertos no PC que ainda não viraram workspace."""
    dados = dados or _ler()
    conhecidos = {str(Path(i["caminho"])).lower() for i in dados["itens"]}
    try:
        from yvakor.projetos import INDICE
        idx = json.loads(INDICE.read_text(encoding="utf-8"))
        itens = (idx.get("projetos") or idx.get("itens")) if isinstance(idx, dict) else idx
    except (OSError, ValueError, ImportError):
        return []
    out = []
    for p in itens or []:
        caminho = str(p.get("caminho") or p.get("path") or "")
        if caminho and caminho.lower() not in conhecidos and Path(caminho).is_dir():
            out.append({"nome": p.get("nome") or Path(caminho).name, "caminho": caminho})
        if len(out) >= limite:
            break
    return out


def _achar(dados: dict, alvo: str) -> dict | None:
    alvo = (alvo or "").strip()
    for i in dados["itens"]:
        if alvo and (i["id"] == alvo or i["nome"].lower() == alvo.lower()
                     or str(Path(i["caminho"])).lower() == str(Path(alvo)).lower()):
            return i
    return None


def adicionar(caminho: str, nome: str = "", descricao: str = "", ativar: bool = True) -> dict:
    p = Path(os.path.expandvars(os.path.expanduser(caminho or ""))).resolve()
    if not p.is_dir():
        return {"ok": False, "erro": f"pasta não existe: {p}"}
    with _lock:
        dados = _ler()
        item = _achar(dados, str(p))
        if item is None:
            item = {"id": uuid.uuid4().hex[:8], "nome": nome or p.name, "caminho": str(p),
                    "descricao": descricao, "criado": datetime.now().isoformat(timespec="seconds"),
                    "ultimo_uso": ""}
            dados["itens"].append(item)
        if ativar:
            dados["ativo"] = item["id"]
            item["ultimo_uso"] = datetime.now().isoformat(timespec="seconds")
        _gravar(dados)
    return {"ok": True, "workspace": _info(item, dados.get("ativo"))}


def criar(nome: str, modelo: str = "vazio", descricao: str = "", caminho: str = "",
          settings: dict | None = None) -> dict:
    nome = (nome or "").strip()
    if not nome:
        return {"ok": False, "erro": "dê um nome ao workspace"}
    modelo = (modelo or "vazio").lower()
    if modelo not in MODELOS:
        return {"ok": False, "erro": f"modelo: {', '.join(MODELOS)}"}
    destino = Path(caminho) if caminho else pasta_base(settings) / _slug(nome)
    if destino.exists() and any(destino.iterdir()):
        return {"ok": False, "erro": f"a pasta já existe e não está vazia: {destino} "
                                     "(use workspace_adicionar para usá-la)"}
    destino.mkdir(parents=True, exist_ok=True)
    vars_ = {"nome": nome, "slug": _slug(nome)}
    readme = f"# {nome}\n\n{descricao or 'Workspace criado pelo YVAKOR.'}\n"
    arquivos = {"README.md": readme, ".gitignore": GITIGNORE, **MODELOS[modelo]}
    for rel, conteudo in arquivos.items():
        alvo = destino / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(conteudo.format(**vars_) if rel not in ("README.md", ".gitignore")
                        else conteudo, encoding="utf-8")
    if shutil.which("git"):
        try:
            proc.run(["git", "init", "-q", str(destino)], capture_output=True, timeout=15)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
    r = adicionar(str(destino), nome=nome, descricao=descricao, ativar=True)
    r["criados"] = sorted(arquivos)
    return r


def ativar(alvo: str | None) -> dict:
    with _lock:
        dados = _ler()
        if not alvo:
            dados["ativo"] = None
            _gravar(dados)
            return {"ok": True, "ativo": None}
        item = _achar(dados, alvo)
        if item is None:
            return {"ok": False, "erro": f"workspace '{alvo}' não encontrado"}
        dados["ativo"] = item["id"]
        item["ultimo_uso"] = datetime.now().isoformat(timespec="seconds")
        _gravar(dados)
    return {"ok": True, "ativo": item["id"], "workspace": _info(item, item["id"])}


def remover(alvo: str) -> dict:
    """Tira da lista (a pasta continua no disco)."""
    with _lock:
        dados = _ler()
        item = _achar(dados, alvo)
        if item is None:
            return {"ok": False, "erro": "não encontrado"}
        dados["itens"].remove(item)
        if dados.get("ativo") == item["id"]:
            dados["ativo"] = None
        _gravar(dados)
    return {"ok": True, "removido": item["nome"], "obs": "a pasta não foi apagada"}


# Como no Claude Code, cada conversa trabalha no SEU workspace: o orquestrador
# fixa, na thread que processa a mensagem, o workspace da conversa. Sem isso,
# duas conversas (app + VS Code) brigariam pelo "ativo" global.
_tl = threading.local()


class usar:
    """with usar(wid): ...  — wid None = segue o ativo global; "" = nenhum."""

    def __init__(self, wid: str | None):
        self.wid = wid

    def __enter__(self):
        self._antes = getattr(_tl, "wid", None)
        _tl.wid = self.wid
        return self

    def __exit__(self, *exc):
        _tl.wid = self._antes
        return False


def ativo() -> dict | None:
    dados = _ler()
    fixado = getattr(_tl, "wid", None)
    alvo = dados.get("ativo") if fixado is None else fixado
    item = _achar(dados, alvo or "")
    return item if item and Path(item["caminho"]).is_dir() else None


def caminho_ativo() -> Path | None:
    a = ativo()
    return Path(a["caminho"]) if a else None


def _arvore(raiz: Path, limite: int = 160) -> list[str]:
    linhas: list[str] = []

    def andar(p: Path, prefixo: str, nivel: int):
        try:
            filhos = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError:
            return
        for f in filhos:
            if len(linhas) >= limite:
                return
            if f.name in IGNORAR or (f.name.startswith(".") and f.name != ".gitignore"):
                continue
            linhas.append(f"{prefixo}{f.name}{'/' if f.is_dir() else ''}")
            if f.is_dir() and nivel < 2:
                andar(f, prefixo + "  ", nivel + 1)
    andar(raiz, "", 0)
    return linhas


def detalhe(alvo: str = "") -> dict:
    dados = _ler()
    item = _achar(dados, alvo or dados.get("ativo") or "")
    if item is None:
        return {"ok": False, "erro": "nenhum workspace ativo ou encontrado"}
    p = Path(item["caminho"])
    if not p.is_dir():
        return {"ok": False, "erro": f"a pasta não existe mais: {p}"}
    readme = next((f for f in ("README.md", "readme.md", "README.txt") if (p / f).exists()), "")
    texto_readme = ""
    if readme:
        try:
            texto_readme = (p / readme).read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            pass
    return {"ok": True, **_info(item, dados.get("ativo")), "arvore": _arvore(p),
            "git_status": _git(p, "status", "--short").splitlines()[:30],
            "git_log": _git(p, "log", "--oneline", "-n", "6").splitlines(),
            "readme": texto_readme}


def abrir(alvo: str, onde: str = "pasta") -> dict:
    dados = _ler()
    item = _achar(dados, alvo or dados.get("ativo") or "")
    if item is None:
        return {"ok": False, "erro": "não encontrado"}
    caminho = item["caminho"]
    if onde == "vscode":
        code = shutil.which("code") or shutil.which("code.cmd")
        if not code:
            return {"ok": False, "erro": "VS Code não encontrado no PATH"}
        proc.popen([code, caminho])
    else:
        os.startfile(caminho)  # noqa: S606 — abre no Explorer
    return {"ok": True, "aberto": caminho, "onde": onde}


def bloco_prompt() -> str:
    a = ativo()
    if not a:
        return ""
    info = _info(a, a["id"])
    p = Path(a["caminho"])
    principais = [n for n in _arvore(p, limite=25) if not n.startswith("  ")][:15]
    git = (f"branch {info['branch']}, {info['alteracoes']} arquivo(s) alterado(s)"
           if info["git"] else "sem git")
    bloco = (f"## WORKSPACE ATIVO: {a['nome']}\n"
             f"- Pasta: {p} · stack: {info['stack']} · {git}\n"
             + (f"- Descrição: {a['descricao']}\n" if a.get("descricao") else "")
             + f"- Itens na raiz: {', '.join(principais) or '(vazia)'}\n"
             "- Trabalhe DENTRO desta pasta: executar_shell já roda nela e caminhos "
             "relativos apontam para ela. Antes de editar, leia o arquivo.")
    nome, texto = instrucoes(p)
    if texto:
        bloco += f"\n### Instruções do projeto ({nome}) — siga sempre\n{texto}"
    return bloco


ARQUIVOS_INSTRUCOES = ("YVAKOR.md", "CLAUDE.md", "AGENTS.md")


def instrucoes(pasta: Path, limite: int = 3000) -> tuple[str, str]:
    """Instruções permanentes do projeto (como o CLAUDE.md no Claude Code)."""
    for nome in ARQUIVOS_INSTRUCOES:
        arq = pasta / nome
        if arq.is_file():
            try:
                return nome, arq.read_text(encoding="utf-8", errors="replace").strip()[:limite]
            except OSError:
                return "", ""
    return "", ""


def mudancas(alvo: str = "") -> dict:
    """Arquivos alterados no git do workspace (para o painel de mudanças)."""
    dados = _ler()
    item = _achar(dados, alvo or dados.get("ativo") or "")
    if item is None:
        return {"ok": False, "erro": "workspace não encontrado"}
    p = Path(item["caminho"])
    saida = _git(p, "status", "--porcelain", "-uall")
    arquivos = []
    for linha in saida.splitlines():
        estado, caminho = linha[:2], linha[3:].strip().strip('"')
        if " -> " in caminho:
            caminho = caminho.split(" -> ", 1)[1]
        rotulo = {"??": "novo", " M": "alterado", "M ": "alterado", "MM": "alterado",
                  " D": "apagado", "D ": "apagado", "A ": "novo", "R ": "renomeado"}
        arquivos.append({"arquivo": caminho, "estado": rotulo.get(estado, estado.strip())})
    return {"ok": True, "workspace": item["nome"], "git": (p / ".git").exists(),
            "arquivos": arquivos[:300]}


def diff(alvo: str, arquivo: str) -> dict:
    """Diff de um arquivo contra o último commit (arquivo novo = todo adicionado)."""
    dados = _ler()
    item = _achar(dados, alvo or dados.get("ativo") or "")
    if item is None:
        return {"ok": False, "erro": "workspace não encontrado"}
    p = Path(item["caminho"])
    alvo_arq = (p / arquivo).resolve()
    if p.resolve() not in alvo_arq.parents and alvo_arq != p.resolve():
        return {"ok": False, "erro": "arquivo fora do workspace"}
    texto = _git(p, "diff", "HEAD", "--", arquivo, timeout=8) or _git(
        p, "diff", "--", arquivo, timeout=8)
    if not texto and alvo_arq.is_file():
        try:
            corpo = alvo_arq.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            corpo = ""
        texto = f"+++ {arquivo} (arquivo novo)\n" + "\n".join("+" + l for l in corpo.splitlines())
    return {"ok": True, "arquivo": arquivo, "diff": texto[:60000]}


def register_workspaces_tools(registry, settings: dict | None = None) -> list[str]:
    registry.register("workspace_listar", lambda: listar(),
                      "Lista os workspaces (pastas de projeto) e qual está ativo.", {})
    registry.register("workspace_atual", lambda: detalhe(""),
                      "Detalhe do workspace ativo: árvore, git, README.", {})
    registry.register("workspace_criar",
                      lambda nome, modelo="vazio", descricao="": criar(
                          nome, modelo, descricao, settings=settings),
                      "Cria e ativa um workspace novo (modelo: vazio | python | node | "
                      "web), com README, .gitignore e git.",
                      {"nome": "str", "modelo": "str?", "descricao": "str?"})
    registry.register("workspace_adicionar",
                      lambda caminho, nome="": adicionar(caminho, nome),
                      "Usa uma pasta existente como workspace (e ativa).",
                      {"caminho": "str", "nome": "str?"})
    registry.register("workspace_ativar", lambda alvo="": ativar(alvo or None),
                      "Ativa um workspace (nome, id ou caminho); vazio = desativa.",
                      {"alvo": "str?"})
    registry.register("workspace_detalhe", lambda alvo="": detalhe(alvo),
                      "Árvore, status do git, últimos commits e README de um workspace.",
                      {"alvo": "str?"})
    return ["workspace_listar", "workspace_atual", "workspace_criar",
            "workspace_adicionar", "workspace_ativar", "workspace_detalhe"]
