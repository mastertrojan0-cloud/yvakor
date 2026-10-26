"""
YVAKOR — Acesso total ao sistema de arquivos

O agente roda com os MESMOS privilégios do usuário: lê, cria, edita, move,
copia, compacta e apaga em qualquer pasta (inclusive fora do projeto).

Decisões de engenharia:
  • caminhos relativos partem do diretório atual; variáveis (%USERPROFILE%) e
    ~ são expandidas; nada é confinado a sandbox.
  • `apagar` move para data/lixeira/ por padrão (recuperável); `permanente=True`
    remove de verdade.
  • toda ação destrutiva/escrita é registrada em data/auditoria.jsonl, para
    você conseguir reconstruir o que o agente fez.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIXEIRA = ROOT / "data" / "lixeira"
AUDITORIA = ROOT / "data" / "auditoria.jsonl"
SNAPSHOTS = ROOT / "data" / "snapshots"
MANIFESTO = SNAPSHOTS / "manifesto.jsonl"
LIMITE_LEITURA = 200_000
LIMITE_SNAPSHOT = 20 * 1024 * 1024   # não copia arquivos gigantes


def _p(caminho: str) -> Path:
    c = str(caminho or "").strip().strip('"').strip("'")
    c = os.path.expandvars(os.path.expanduser(c))
    if not c:
        raise ValueError("caminho vazio")
    p = Path(c)
    return p if p.is_absolute() else (Path.cwd() / p)


def _auditar(acao: str, caminho: str, extra: dict | None = None) -> None:
    try:
        AUDITORIA.parent.mkdir(parents=True, exist_ok=True)
        with AUDITORIA.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "acao": acao, "caminho": str(caminho), **(extra or {}),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _snapshot(p: Path, acao: str) -> str:
    """Cópia de segurança antes de alterar um arquivo. Devolve o id."""
    try:
        if not p.is_file() or p.stat().st_size > LIMITE_SNAPSHOT:
            return ""
        sid = f"{time.strftime('%Y%m%d_%H%M%S')}_{os.urandom(2).hex()}"
        destino = SNAPSHOTS / sid
        destino.mkdir(parents=True, exist_ok=True)
        backup = destino / p.name
        shutil.copy2(p, backup)
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        with MANIFESTO.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": sid, "original": str(p),
                                "backup": str(backup), "acao": acao,
                                "ts": datetime.now().isoformat(timespec="seconds")},
                               ensure_ascii=False) + "\n")
        return sid
    except Exception:
        return ""


def snapshots(limite: int = 20) -> dict:
    if not MANIFESTO.exists():
        return {"ok": True, "total": 0, "itens": []}
    linhas = MANIFESTO.read_text(encoding="utf-8").splitlines()[-max(1, int(limite)):]
    itens = []
    for linha in reversed(linhas):
        try:
            itens.append(json.loads(linha))
        except Exception:
            continue
    return {"ok": True, "total": len(itens), "itens": itens}


def desfazer(snapshot_id: str = "") -> dict:
    """Restaura o snapshot mais recente (ou o id informado)."""
    if not MANIFESTO.exists():
        return {"ok": False, "erro": "nenhum snapshot disponível"}
    registros = []
    for linha in MANIFESTO.read_text(encoding="utf-8").splitlines():
        try:
            registros.append(json.loads(linha))
        except Exception:
            continue
    alvo = None
    if snapshot_id:
        alvo = next((r for r in registros if r.get("id") == snapshot_id), None)
    elif registros:
        alvo = registros[-1]
    if not alvo:
        return {"ok": False, "erro": "snapshot não encontrado"}
    backup, original = Path(alvo["backup"]), Path(alvo["original"])
    if not backup.exists():
        return {"ok": False, "erro": "cópia de segurança ausente"}
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, original)
    _auditar("desfazer", original, {"snapshot": alvo["id"]})
    return {"ok": True, "restaurado": str(original), "snapshot": alvo["id"]}


def _info(p: Path) -> dict:
    st = p.stat()
    return {
        "caminho": str(p), "nome": p.name, "pasta": p.is_dir(),
        "bytes": st.st_size if p.is_file() else None,
        "modificado": datetime.fromtimestamp(st.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"),
        "extensao": p.suffix.lower(),
    }


# ----------------------------------------------------------------------- #
# Leitura
# ----------------------------------------------------------------------- #
def listar(caminho: str = ".", recursivo: bool = False,
           limite: int = 500) -> dict:
    p = _p(caminho)
    if not p.exists():
        return {"ok": False, "erro": f"não existe: {p}"}
    itens: list[dict] = []
    try:
        gerador = p.rglob("*") if recursivo else p.iterdir()
        for filho in gerador:
            if len(itens) >= max(1, min(int(limite), 5000)):
                break
            try:
                st = filho.stat()
                itens.append({
                    "caminho": str(filho),
                    "nome": filho.name,
                    "pasta": filho.is_dir(),
                    "bytes": st.st_size if filho.is_file() else None,
                })
            except OSError:
                continue
    except OSError as exc:
        return {"ok": False, "erro": str(exc)}
    itens.sort(key=lambda x: (not x["pasta"], x["nome"].lower()))
    return {"ok": True, "caminho": str(p), "total": len(itens),
            "itens": itens}


def ler(caminho: str, inicio: int = 0, limite: int = LIMITE_LEITURA) -> dict:
    p = _p(caminho)
    if not p.is_file():
        return {"ok": False, "erro": "arquivo não encontrado"}
    dados = p.read_bytes()
    total = len(dados)
    parte = dados[max(0, int(inicio)):max(0, int(inicio)) + max(1, int(limite))]
    try:
        texto = parte.decode("utf-8")
        binario = False
    except UnicodeDecodeError:
        texto = base64.b64encode(parte).decode()
        binario = True
    return {"ok": True, "caminho": str(p), "bytes_total": total,
            "lido": len(parte), "binario": binario,
            "conteudo": texto, "truncado": total > int(inicio) + len(parte)}


def info(caminho: str) -> dict:
    p = _p(caminho)
    if not p.exists():
        return {"ok": False, "erro": "não encontrado"}
    return {"ok": True, **_info(p)}


def buscar(padrao: str, raiz: str = ".", limite: int = 200) -> dict:
    base = _p(raiz)
    if not base.exists():
        return {"ok": False, "erro": f"raiz não existe: {base}"}
    achados = []
    try:
        for f in base.rglob(padrao):
            if len(achados) >= max(1, min(int(limite), 2000)):
                break
            try:
                achados.append(str(f))
            except OSError:
                continue
    except OSError as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, "raiz": str(base), "padrao": padrao,
            "total": len(achados), "achados": achados}


# ----------------------------------------------------------------------- #
# Escrita
# ----------------------------------------------------------------------- #
def escrever(caminho: str, conteudo: str, modo: str = "sobrescrever",
             encoding: str = "utf-8") -> dict:
    p = _p(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    modo = (modo or "sobrescrever").lower()
    if p.exists() and modo not in ("anexar", "append", "a"):
        _snapshot(p, "escrever")
    if modo in ("anexar", "append", "a"):
        with open(p, "a", encoding=encoding or "utf-8") as f:
            f.write(str(conteudo))
    else:
        if isinstance(conteudo, str) and conteudo.startswith("base64:"):
            p.write_bytes(base64.b64decode(conteudo[7:]))
        else:
            p.write_text(str(conteudo), encoding=encoding or "utf-8")
    _auditar("escrever", p, {"modo": modo, "bytes": p.stat().st_size})
    return {"ok": True, "caminho": str(p), "bytes": p.stat().st_size}


def editar(caminho: str, busca: str, troca: str, regex: bool = False,
           todas: bool = False) -> dict:
    p = _p(caminho)
    if not p.is_file():
        return {"ok": False, "erro": "arquivo não encontrado"}
    _snapshot(p, "editar")
    texto = p.read_text(encoding="utf-8", errors="replace")
    if regex:
        padrao = re.compile(str(busca), re.MULTILINE)
        novo, n = padrao.subn(str(troca), texto, count=0 if todas else 1)
    else:
        n = texto.count(str(busca))
        if n == 0:
            return {"ok": False, "erro": "trecho não encontrado"}
        novo = texto.replace(str(busca), str(troca), -1 if todas else 1)
        n = n if todas else 1
    p.write_text(novo, encoding="utf-8")
    _auditar("editar", p, {"ocorrencias": n, "regex": bool(regex)})
    return {"ok": True, "caminho": str(p), "ocorrencias": n,
            "bytes": p.stat().st_size}


def criar_pasta(caminho: str) -> dict:
    p = _p(caminho)
    p.mkdir(parents=True, exist_ok=True)
    _auditar("criar_pasta", p)
    return {"ok": True, "caminho": str(p)}


def copiar(origem: str, destino: str, sobrescrever: bool = True) -> dict:
    o, d = _p(origem), _p(destino)
    if not o.exists():
        return {"ok": False, "erro": f"origem não existe: {o}"}
    if d.exists() and not sobrescrever:
        return {"ok": False, "erro": f"destino já existe: {d}"}
    d.parent.mkdir(parents=True, exist_ok=True)
    if d.exists() and d.is_file():
        _snapshot(d, "copiar")
    if o.is_dir():
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(o, d)
    else:
        shutil.copy2(o, d)
    _auditar("copiar", d, {"origem": str(o)})
    return {"ok": True, "origem": str(o), "destino": str(d)}


def mover(origem: str, destino: str, sobrescrever: bool = True) -> dict:
    o, d = _p(origem), _p(destino)
    if not o.exists():
        return {"ok": False, "erro": f"origem não existe: {o}"}
    if d.exists() and not sobrescrever:
        return {"ok": False, "erro": f"destino já existe: {d}"}
    d.parent.mkdir(parents=True, exist_ok=True)
    if d.exists():
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
        else:
            d.unlink()
    if o.is_file():
        _snapshot(o, "mover")
    shutil.move(str(o), str(d))
    _auditar("mover", d, {"origem": str(o)})
    return {"ok": True, "origem": str(o), "destino": str(d)}


def apagar(caminho: str, permanente: bool = False, recursivo: bool = True) -> dict:
    p = _p(caminho)
    if not p.exists():
        return {"ok": False, "erro": f"não existe: {p}"}
    if p.is_dir() and any(p.iterdir()) and not recursivo:
        return {"ok": False, "erro": "pasta não vazia (use recursivo=True)"}
    if p.is_file():
        _snapshot(p, "apagar")
    if permanente:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        _auditar("apagar_permanente", p)
        return {"ok": True, "caminho": str(p), "permanente": True}
    # lixeira recuperável dentro do projeto
    LIXEIRA.mkdir(parents=True, exist_ok=True)
    alvo = LIXEIRA / f"{time.strftime('%Y%m%d_%H%M%S')}_{p.name}"
    shutil.move(str(p), str(alvo))
    _auditar("apagar_lixeira", p, {"lixeira": str(alvo)})
    return {"ok": True, "caminho": str(p), "lixeira": str(alvo),
            "permanente": False}


def zipar(origem: str, destino: str = "") -> dict:
    o = _p(origem)
    if not o.exists():
        return {"ok": False, "erro": f"origem não existe: {o}"}
    d = _p(destino) if destino else o.with_suffix(o.suffix + ".zip")
    d.parent.mkdir(parents=True, exist_ok=True)
    base = shutil.make_archive(str(d.with_suffix("")), "zip",
                               root_dir=str(o.parent), base_dir=o.name)
    _auditar("zipar", base, {"origem": str(o)})
    return {"ok": True, "arquivo": base, "bytes": Path(base).stat().st_size}


def extrair(arquivo: str, destino: str = "") -> dict:
    a = _p(arquivo)
    if not a.is_file():
        return {"ok": False, "erro": "arquivo não encontrado"}
    d = _p(destino) if destino else a.with_suffix("")
    d.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(str(a), str(d))
    # zip-slip: garante que nada saiu do destino
    for f in d.rglob("*"):
        if d.resolve() not in f.resolve().parents and f.resolve() != d.resolve():
            return {"ok": False, "erro": "arquivo suspeito fora do destino"}
    _auditar("extrair", d, {"arquivo": str(a)})
    return {"ok": True, "destino": str(d)}


# ----------------------------------------------------------------------- #
# Registro
# ----------------------------------------------------------------------- #
def register_arquivos_tools(registry) -> list[str]:
    reg = registry.register
    reg("arquivos_listar", listar,
        "Lista qualquer pasta do sistema (arquivos e subpastas), inclusive "
        "ocultos; recursivo=True varre a árvore.",
        {"caminho": "str?", "recursivo": "bool?", "limite": "int?"})
    reg("arquivos_ler", ler,
        "Lê qualquer arquivo (texto; binário em base64). Aceita inicio/limite "
        "para arquivos grandes.", {"caminho": "str", "inicio": "int?",
                                   "limite": "int?"})
    reg("arquivos_info", info,
        "Metadados de arquivo/pasta (tamanho, data, extensão).",
        {"caminho": "str"})
    reg("arquivos_buscar", buscar,
        "Busca por padrão glob (ex.: *.pdf) dentro de uma raiz.",
        {"padrao": "str", "raiz": "str?", "limite": "int?"})
    reg("arquivos_escrever", escrever,
        "Cria/sobrescreve arquivo em QUALQUER pasta; modo=anexar para adicionar. "
        "Cria pastas intermediárias. Use caminho absoluto.",
        {"caminho": "str", "conteudo": "str", "modo": "str?",
         "encoding": "str?"})
    reg("arquivos_editar", editar,
        "Substitui trecho em arquivo (literal ou regex); todas=True troca todas.",
        {"caminho": "str", "busca": "str", "troca": "str", "regex": "bool?",
         "todas": "bool?"})
    reg("arquivos_criar_pasta", criar_pasta,
        "Cria pasta (com pais) em qualquer lugar.", {"caminho": "str"})
    reg("arquivos_copiar", copiar,
        "Copia arquivo/pasta para outro caminho.", {"origem": "str",
                                                   "destino": "str",
                                                   "sobrescrever": "bool?"})
    reg("arquivos_mover", mover,
        "Move/renomeia arquivo ou pasta.", {"origem": "str", "destino": "str",
                                            "sobrescrever": "bool?"})
    reg("arquivos_apagar", apagar,
        "Apaga arquivo/pasta. Por padrão vai para data/lixeira (recuperável); "
        "permanente=True remove de vez.",
        {"caminho": "str", "permanente": "bool?", "recursivo": "bool?"})
    reg("arquivos_zipar", zipar,
        "Compacta arquivo/pasta em .zip.", {"origem": "str", "destino": "str?"})
    reg("arquivos_extrair", extrair,
        "Extrai .zip em uma pasta.", {"arquivo": "str", "destino": "str?"})
    reg("arquivos_snapshots", snapshots,
        "Lista cópias de segurança feitas antes de escrever/editar/apagar.",
        {"limite": "int?"})
    reg("arquivos_desfazer", desfazer,
        "Restaura o arquivo a partir do snapshot mais recente (ou id).",
        {"snapshot_id": "str?"})
    return [n for n in registry.tools if n.startswith("arquivos_")]
