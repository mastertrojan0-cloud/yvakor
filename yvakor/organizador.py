"""YVAKOR — organizador de pastas em lote (analisar → planejar → executar → desfazer).

Antes, organizar pastas esbarrava num limite: cada arquivo era um
`arquivos_mover`, que sempre pede confirmação — 500 arquivos, 500 popups —
então o agente parava e devolvia perguntas em vez de organizar.

Aqui a tarefa inteira vira um plano:
  organizar_analisar   só leitura: tipos, tamanhos, duplicados, lixo (livre);
  organizar_plano      monta os movimentos e guarda em data/organizador/;
  organizar_executar   executa o plano todo de uma vez (1 confirmação, ou
                       nenhuma no modo "Agir sem pedir");
  organizar_desfazer   devolve cada arquivo ao lugar de origem;
  limpar_temporarios   apaga o %TEMP% antigo (1 confirmação), com progresso;
  esvaziar_lixeira     esvazia a Lixeira do Windows (sempre confirma).

Organizar nunca apaga: duplicados vão para `_Duplicados`, nada sai da pasta
do usuário sem caminho de volta. Pastas de sistema, ocultas, atalhos e downloads em
andamento ficam intocados.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from yvakor.config import ROOT
import logging

_log = logging.getLogger(__name__)

DIR_PLANOS = ROOT / "data" / "organizador"

CATEGORIAS = {
    "Documentos": "pdf doc docx odt rtf txt md xls xlsx xlsm csv ods ppt pptx odp epub",
    "Imagens": "jpg jpeg png gif bmp webp heic heif svg tif tiff raw cr2 nef ico psd",
    "Videos": "mp4 mkv avi mov wmv webm flv m4v 3gp mpg mpeg",
    "Musicas": "mp3 wav flac aac ogg m4a wma opus mid",
    "Instaladores": "exe msi msix msixbundle appx apk dmg iso img",
    "Compactados": "zip rar 7z tar gz tgz bz2 xz",
    "Codigo": "py js ts html htm css json xml sql java c cpp h cs php sh ps1 bat "
              "ipynb yaml yml toml",
    "Fontes": "ttf otf woff woff2",
    "Torrents": "torrent",
}
EXT_CAT = {e: c for c, exts in CATEGORIAS.items() for e in exts.split()}
# Pastas que já são de um tipo só: organizar por ano faz mais sentido.
POR_DATA = {"pictures", "imagens", "fotos", "videos", "vídeos", "music", "musicas",
            "músicas"}
IGNORAR_EXT = {"lnk", "url", "ini", "crdownload", "part", "partial", "tmp",
               "download", "opdownload"}
PASTAS_ORGANIZADOR = {"_duplicados", *(c.lower() for c in CATEGORIAS), "outros"}
RECENTE_S = 600          # mexido há menos de 10 min: pode estar em uso/baixando


# ---------------------------------------------------------------------- #
# Segurança: o que pode ser organizado
# ---------------------------------------------------------------------- #
def _proibida(p: Path) -> str:
    """Motivo para recusar a pasta, ou '' se pode organizar."""
    s = str(p.resolve()).lower().rstrip("\\/")
    home = str(Path.home()).lower().rstrip("\\/")
    if len(p.resolve().parts) <= 1:
        # Downloads/Documentos podem estar redirecionados para a raiz de outro
        # disco (ex.: F:\). Aí vale organizar os arquivos soltos — mas nunca a
        # raiz do disco do sistema nem uma raiz qualquer.
        sistema = os.environ.get("SystemDrive", "C:").lower()
        usuario = {str(x.resolve()).lower().rstrip("\\/")
                   for x in pastas_usuario().values()}
        if s in usuario and not s.startswith(sistema):
            return ""
        return "raiz de disco"
    if s == home:
        return "raiz do perfil (organize Downloads, Documentos, Área de Trabalho…)"
    windir = os.environ.get("WINDIR", r"C:\Windows").lower()
    sistemas = [windir, r"c:\program files", r"c:\program files (x86)",
                r"c:\programdata", os.path.join(home, "appdata").lower(),
                str(ROOT).lower()]
    for base in sistemas:
        if s == base or s.startswith(base + os.sep):
            return "pasta de sistema/programa"
    if any(part.startswith(".") for part in p.resolve().parts[1:]):
        return "pasta oculta/configuração"
    return ""


def _ignorar(f: Path, agora: float) -> bool:
    nome = f.name.lower()
    if nome.startswith((".", "~$")) or nome in ("desktop.ini", "thumbs.db"):
        return True
    if f.suffix.lower().lstrip(".") in IGNORAR_EXT:
        return True
    try:
        st = f.stat()
    except OSError:
        return True
    if agora - st.st_mtime < RECENTE_S:
        return True
    if sys.platform == "win32":
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & (0x2 | 0x4):          # oculto | sistema
            return True
    return False


def pastas_usuario() -> dict[str, Path]:
    """Pastas de conteúdo do usuário (segue o redirecionamento p/ OneDrive)."""
    nomes = {"Desktop": "Desktop", "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
             "Documentos": "Personal", "Imagens": "My Pictures",
             "Musicas": "My Music", "Videos": "My Video"}
    out = {}
    try:
        import winreg
        chave = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                               r"\User Shell Folders")
        for rot, valor in nomes.items():
            try:
                bruto, _ = winreg.QueryValueEx(chave, valor)
                p = Path(os.path.expandvars(bruto))
                if p.is_dir():
                    out[rot] = p
            except OSError:
                pass
    except (ImportError, OSError):
        pass
    for rot, sub in (("Desktop", "Desktop"), ("Downloads", "Downloads"),
                     ("Documentos", "Documents"), ("Imagens", "Pictures"),
                     ("Musicas", "Music"), ("Videos", "Videos")):
        p = Path.home() / sub
        if rot not in out and p.is_dir():
            out[rot] = p
    return out


def _resolver(pastas: str) -> list[Path]:
    alvo = (pastas or "").strip()
    usuario = pastas_usuario()
    if alvo.lower() in ("", "usuario", "usuário", "todas", "pessoais"):
        unicas: dict[str, Path] = {}
        for p in usuario.values():          # Downloads e Documentos podem ser a mesma
            unicas.setdefault(str(p.resolve()).lower(), p)
        return list(unicas.values())
    out = []
    for parte in alvo.replace(";", ",").split(","):
        parte = parte.strip().strip('"')
        if not parte:
            continue
        chave = next((k for k in usuario if k.lower() == parte.lower()), None)
        out.append(usuario[chave] if chave else Path(os.path.expandvars(parte)).expanduser())
    return out


# ---------------------------------------------------------------------- #
# Análise
# ---------------------------------------------------------------------- #
def _hash(f: Path, limite: int = 0) -> str:
    h = hashlib.sha256()
    with f.open("rb") as fh:
        lido = 0
        while bloco := fh.read(1 << 20):
            h.update(bloco)
            lido += len(bloco)
            if limite and lido >= limite:
                break
    return h.hexdigest()


def _duplicados(arquivos: list[Path]) -> list[list[Path]]:
    """Grupos de conteúdo idêntico: tamanho → hash parcial → hash completo."""
    por_tam: dict[int, list[Path]] = {}
    for f in arquivos:
        try:
            t = f.stat().st_size
        except OSError:
            continue
        if t > 0:
            por_tam.setdefault(t, []).append(f)
    grupos = []
    for lista in por_tam.values():
        if len(lista) < 2:
            continue
        parcial: dict[str, list[Path]] = {}
        for f in lista:
            try:
                parcial.setdefault(_hash(f, 1 << 16), []).append(f)
            except OSError:
                pass
        for cand in parcial.values():
            if len(cand) < 2:
                continue
            total: dict[str, list[Path]] = {}
            for f in cand:
                try:
                    total.setdefault(_hash(f), []).append(f)
                except OSError:
                    pass
            grupos += [sorted(g, key=lambda x: x.stat().st_mtime)
                       for g in total.values() if len(g) > 1]
    return grupos


def _mb(n: float) -> float:
    return round(n / 1024 ** 2, 1)


def _soltos(pasta: Path, recursivo: bool, agora: float) -> list[Path]:
    if recursivo:
        it = (f for f in pasta.rglob("*") if f.is_file())
    else:
        it = (f for f in pasta.iterdir() if f.is_file())
    return [f for f in it if not _ignorar(f, agora)]


def analisar(pastas: str = "", recursivo: bool = False) -> dict:
    agora = time.time()
    relatorio = []
    for pasta in _resolver(pastas):
        if not pasta.is_dir():
            relatorio.append({"pasta": str(pasta), "erro": "não existe"})
            continue
        motivo = _proibida(pasta)
        if motivo:
            relatorio.append({"pasta": str(pasta), "erro": f"não organizo: {motivo}"})
            continue
        arquivos = _soltos(pasta, recursivo, agora)
        cats: dict[str, dict] = {}
        for f in arquivos:
            c = EXT_CAT.get(f.suffix.lower().lstrip("."), "Outros")
            d = cats.setdefault(c, {"arquivos": 0, "mb": 0.0})
            d["arquivos"] += 1
            d["mb"] += f.stat().st_size
        for d in cats.values():
            d["mb"] = _mb(d["mb"])
        dups = _duplicados(arquivos)
        grandes = sorted(arquivos, key=lambda f: -f.stat().st_size)[:5]
        antigos = [f for f in arquivos if EXT_CAT.get(f.suffix.lower().lstrip(".")) ==
                   "Instaladores" and agora - f.stat().st_mtime > 90 * 86400]
        relatorio.append({
            "pasta": str(pasta), "arquivos_soltos": len(arquivos),
            "por_tipo": dict(sorted(cats.items(), key=lambda x: -x[1]["mb"])),
            "duplicados": {"grupos": len(dups),
                           "copias": sum(len(g) - 1 for g in dups),
                           "mb_recuperaveis": _mb(sum(g[0].stat().st_size * (len(g) - 1)
                                                      for g in dups)),
                           "exemplos": [[str(x.name) for x in g] for g in dups[:5]]},
            "maiores": [{"nome": f.name, "mb": _mb(f.stat().st_size)} for f in grandes],
            "instaladores_antigos": {"arquivos": len(antigos),
                                     "mb": _mb(sum(f.stat().st_size for f in antigos))},
        })
    temp = Path(os.environ.get("TEMP", "")) if os.environ.get("TEMP") else None
    return {"ok": True, "pastas": relatorio,
            "temporarios_mb_minimo": _mb(_tam_temp(temp)) if temp else 0,
            "proximo_passo": "organizar_plano(pastas) e depois organizar_executar(plano)"}


# ---------------------------------------------------------------------- #
# Plano e execução
# ---------------------------------------------------------------------- #
def _modo_da_pasta(pasta: Path, modo: str) -> str:
    if modo in ("tipo", "data", "tipo_data"):
        return modo
    return "data" if pasta.name.lower() in POR_DATA else "tipo"


def _destino(pasta: Path, f: Path, modo: str) -> Path:
    cat = EXT_CAT.get(f.suffix.lower().lstrip("."), "Outros")
    ano = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y")
    if modo == "data":
        return pasta / ano / f.name
    if modo == "tipo_data":
        return pasta / cat / ano / f.name
    return pasta / cat / f.name


def plano(pastas: str = "", modo: str = "auto", duplicados: bool = True) -> dict:
    """Monta (sem mexer em nada) os movimentos para organizar as pastas."""
    agora = time.time()
    movs, recusadas = [], []
    for pasta in _resolver(pastas):
        motivo = "não existe" if not pasta.is_dir() else _proibida(pasta)
        if motivo:
            recusadas.append({"pasta": str(pasta), "motivo": motivo})
            continue
        m = _modo_da_pasta(pasta, modo)
        arquivos = _soltos(pasta, False, agora)
        extras: set[Path] = set()
        if duplicados:
            for g in _duplicados(arquivos):
                for f in g[1:]:                      # fica o mais antigo
                    extras.add(f)
                    movs.append({"de": str(f), "para": str(pasta / "_Duplicados" / f.name),
                                 "motivo": f"duplicado de {g[0].name}",
                                 "tam": f.stat().st_size})
        for f in arquivos:
            if f in extras:
                continue
            d = _destino(pasta, f, m)
            if d.parent != f.parent:
                movs.append({"de": str(f), "para": str(d),
                             "motivo": d.parent.relative_to(pasta).as_posix(),
                             "tam": f.stat().st_size})
    pid = uuid.uuid4().hex[:8]
    DIR_PLANOS.mkdir(parents=True, exist_ok=True)
    dados = {"id": pid, "criado": datetime.now().isoformat(timespec="seconds"),
             "movimentos": movs, "executado": False}
    (DIR_PLANOS / f"plano_{pid}.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    resumo: dict[str, int] = {}
    for mv in movs:
        origem = Path(mv["de"]).parent
        chave = f"{origem.name or str(origem)} → {mv['motivo'].split(' de ')[0]}"
        resumo[chave] = resumo.get(chave, 0) + 1
    return {"ok": True, "plano": pid, "movimentos": len(movs),
            "mb": _mb(sum(m["tam"] for m in movs)), "resumo": resumo,
            "recusadas": recusadas,
            "aviso": "Só move (nada é apagado); organizar_desfazer(plano) desfaz tudo."}


def _livre(destino: Path) -> Path:
    if not destino.exists():
        return destino
    i = 2
    while True:
        cand = destino.with_name(f"{destino.stem} ({i}){destino.suffix}")
        if not cand.exists():
            return cand
        i += 1


def _ler_plano(pid: str) -> tuple[Path, dict] | tuple[None, None]:
    arq = DIR_PLANOS / f"plano_{(pid or '').strip()}.json"
    if not arq.exists():
        return None, None
    return arq, json.loads(arq.read_text(encoding="utf-8"))


def executar(plano_id: str) -> dict:
    arq, dados = _ler_plano(plano_id)
    if dados is None:
        return {"ok": False, "erro": f"plano '{plano_id}' não encontrado"}
    if dados.get("executado"):
        return {"ok": False, "erro": "plano já executado (use organizar_desfazer)"}
    feitos, falhas = [], []
    total, aviso = len(dados["movimentos"]), time.time()
    _progresso(f"📂 organizando: {total} arquivos")
    for i, mv in enumerate(dados["movimentos"], 1):
        if time.time() - aviso >= 2:
            aviso = time.time()
            _progresso(f"📂 {i}/{total} arquivos ({round(100 * i / max(total, 1))}%)")
        de, para = Path(mv["de"]), Path(mv["para"])
        try:
            if not de.exists() or de.stat().st_size != mv["tam"]:
                falhas.append({"arquivo": de.name, "erro": "mudou desde o plano"})
                continue
            para.parent.mkdir(parents=True, exist_ok=True)
            final = _livre(para)
            shutil.move(str(de), str(final))
            feitos.append({"de": str(de), "para": str(final)})
        except OSError as exc:
            falhas.append({"arquivo": de.name, "erro": str(exc)[:120]})
    dados.update(executado=True, feitos=feitos, falhas=falhas,
                 executado_em=datetime.now().isoformat(timespec="seconds"))
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        from yvakor.arquivos import _auditar
        _auditar("organizar", plano_id, {"movidos": len(feitos), "falhas": len(falhas)})
    except Exception:
        _log.debug("exceção ignorada", exc_info=True)
    return {"ok": True, "plano": plano_id, "movidos": len(feitos),
            "falhas": falhas[:10], "desfazer": f"organizar_desfazer('{plano_id}')"}


def desfazer(plano_id: str) -> dict:
    arq, dados = _ler_plano(plano_id)
    if dados is None or not dados.get("executado"):
        return {"ok": False, "erro": "plano não encontrado ou ainda não executado"}
    voltaram, falhas, pastas = 0, [], set()
    for mv in reversed(dados.get("feitos", [])):
        de, para = Path(mv["de"]), Path(mv["para"])
        try:
            if para.exists() and not de.exists():
                de.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(para), str(de))
                voltaram += 1
                pastas.add(para.parent)
            else:
                falhas.append(para.name)
        except OSError as exc:
            falhas.append(f"{para.name}: {str(exc)[:80]}")
    for p in sorted(pastas, key=lambda x: -len(x.parts)):     # remove pastas vazias criadas
        for q in (p, p.parent):
            try:
                if q.name.lower() in PASTAS_ORGANIZADOR or q.name.isdigit():
                    q.rmdir()
            except OSError:
                pass
    dados.update(executado=False, desfeito_em=datetime.now().isoformat(timespec="seconds"))
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "voltaram": voltaram, "falhas": falhas[:10]}


# ---------------------------------------------------------------------- #
# Progresso visível no painel (o orquestrador injeta por thread)
# ---------------------------------------------------------------------- #
_local = threading.local()


def definir_progresso(fn) -> None:
    """fn(texto) mostra um passo no painel de progresso da conversa."""
    _local.progresso = fn


def _progresso(texto: str) -> None:
    fn = getattr(_local, "progresso", None)
    if fn is not None:
        try:
            fn(texto)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)


# ---------------------------------------------------------------------- #
# Temporários e Lixeira
# ---------------------------------------------------------------------- #
def _tam_temp(temp: Path | None, limite_s: float = 4.0) -> int:
    """Tamanho do TEMP com teto de tempo (pastas de GB levavam 30 s)."""
    total = 0
    if not temp or not temp.is_dir():
        return 0
    fim = time.time() + limite_s
    for f in temp.rglob("*"):
        if time.time() > fim:
            break
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _apagar_item(item: Path) -> tuple[int, int]:
    """Apaga arquivo ou pasta (o que estiver em uso fica). (apagados, bytes)."""
    if item.is_file() or item.is_symlink():
        t = item.stat().st_size
        item.unlink()
        return 1, t
    n = b = 0
    for f in sorted(item.rglob("*"), key=lambda x: -len(x.parts)):
        try:
            if f.is_dir() and not f.is_symlink():
                f.rmdir()
            else:
                t = f.stat().st_size
                f.unlink()
                n, b = n + 1, b + t
        except OSError:
            pass
    try:
        item.rmdir()
    except OSError:
        pass
    return n, b


def limpar_temporarios(dias: int = 2, limite_s: float = 90) -> dict:
    """Apaga o que está no %TEMP% há mais de N dias (como a Limpeza de Disco
    do Windows). Antes mandava tudo para a Lixeira: com GBs levava 225 s,
    estourava o limite da tarefa e não mostrava progresso (conversa 71)."""
    temp = Path(os.environ.get("TEMP", ""))
    if not temp.is_dir():
        return {"ok": False, "erro": "pasta TEMP não encontrada"}
    corte = time.time() - max(int(dias), 1) * 86400
    try:
        itens = [f for f in temp.iterdir() if f.stat().st_mtime < corte]
    except OSError as exc:
        return {"ok": False, "erro": str(exc)[:120]}
    fim = time.time() + float(limite_s)
    apagados = bytes_ = feitos = 0
    aviso = time.time()
    _progresso(f"🧹 limpando temporários: {len(itens)} itens com mais de {dias} dia(s)")
    for i, item in enumerate(itens, 1):
        if time.time() > fim:
            break
        try:
            n, b = _apagar_item(item)
            apagados, bytes_ = apagados + n, bytes_ + b
        except OSError:
            pass                                   # em uso: fica
        feitos = i
        if time.time() - aviso >= 2:
            aviso = time.time()
            _progresso(f"🧹 {i}/{len(itens)} itens · {_mb(bytes_)} MB liberados "
                       f"({round(100 * i / max(len(itens), 1))}%)")
    restantes = len(itens) - feitos
    _progresso(f"🧹 temporários: {_mb(bytes_)} MB liberados"
               + (f" — faltam {restantes} itens" if restantes else ""))
    return {"ok": True, "arquivos_apagados": apagados, "mb_liberados": _mb(bytes_),
            "itens_analisados": feitos, "itens_restantes": restantes,
            "obs": ("Chame de novo para continuar." if restantes else
                    "Itens em uso pelo sistema ficaram onde estão.")}


def esvaziar_lixeira() -> dict:
    """Esvazia a Lixeira do Windows (permanente)."""
    if sys.platform != "win32":
        return {"ok": False, "erro": "só no Windows"}
    import ctypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_int64),
                    ("i64NumItems", ctypes.c_int64)]

    info = SHQUERYRBINFO(cbSize=ctypes.sizeof(SHQUERYRBINFO))
    ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if info.i64NumItems == 0:
        return {"ok": True, "itens": 0, "mb_liberados": 0, "obs": "a Lixeira já estava vazia"}
    _progresso(f"🗑 esvaziando a Lixeira: {info.i64NumItems} itens")
    SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 1, 2, 4
    r = ctypes.windll.shell32.SHEmptyRecycleBinW(
        None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
    return {"ok": r == 0, "itens": int(info.i64NumItems),
            "mb_liberados": _mb(info.i64Size), **({} if r == 0 else {"erro": f"código {r}"})}


def register_organizador_tools(registry) -> list[str]:
    def organizar_analisar(pastas: str = "", recursivo: bool = False) -> dict:
        return analisar(pastas, str(recursivo).lower() in ("true", "1", "sim"))

    def organizar_plano(pastas: str = "", modo: str = "auto",
                        duplicados: bool = True) -> dict:
        return plano(pastas, modo, str(duplicados).lower() not in ("false", "0", "nao", "não"))

    registry.register(
        "organizar_analisar", organizar_analisar,
        "Analisa pastas (só leitura): arquivos por tipo, tamanhos, duplicados, "
        "instaladores antigos e temporários. pastas: vazio = pastas do usuário "
        "(Desktop, Downloads, Documentos, Imagens, Músicas, Vídeos), ou nomes/"
        "caminhos separados por vírgula.", {"pastas": "str?", "recursivo": "bool?"})
    registry.register(
        "organizar_plano", organizar_plano,
        "Monta o plano para ORGANIZAR pastas sem mexer em nada: arquivos soltos "
        "vão para subpastas por tipo (Documentos, Imagens, Instaladores…) ou por "
        "ano (modo: auto | tipo | data | tipo_data); duplicados vão para "
        "_Duplicados. Devolve o id do plano.",
        {"pastas": "str?", "modo": "str?", "duplicados": "bool?"})
    registry.register(
        "organizar_executar", executar,
        "Executa de uma vez um plano de organizar_plano (só move, nada é "
        "apagado; dá para desfazer).", {"plano_id": "str"})
    registry.register(
        "organizar_desfazer", desfazer,
        "Desfaz um plano executado: cada arquivo volta ao lugar original.",
        {"plano_id": "str"})
    registry.register(
        "limpar_temporarios", lambda dias=2: limpar_temporarios(int(dias)),
        "Apaga os arquivos temporários (%TEMP%) com mais de N dias, mostrando "
        "o progresso; para em ~90 s e diz quantos faltam (chame de novo).",
        {"dias": "int?"})
    registry.register(
        "esvaziar_lixeira", esvaziar_lixeira,
        "Esvazia a Lixeira do Windows (o \"lixo\"); permanente.", {})
    return ["organizar_analisar", "organizar_plano", "organizar_executar",
            "organizar_desfazer", "limpar_temporarios", "esvaziar_lixeira"]
