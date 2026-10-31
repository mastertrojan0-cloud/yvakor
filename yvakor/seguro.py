"""YVAKOR — gravação segura de arquivos (anticrash).

Um JSON gravado direto (`write_text`) fica pela metade se o processo morrer, a
energia cair ou o disco encher no meio da escrita — e o carregamento seguinte
"se recuperava" com os valores padrão, apagando preferências, permissões e
agenda. Aqui toda gravação é:

  1. escrita num arquivo temporário na MESMA pasta,
  2. `flush` + `fsync`,
  3. troca atômica (`os.replace`) — o arquivo é sempre o antigo ou o novo,
  4. com cópia `.bak` do último conteúdo válido, usada na leitura se o principal
     estiver ilegível.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
import logging

_log = logging.getLogger(__name__)

_TRAVAS: dict[str, threading.Lock] = {}
_TRAVAS_LOCK = threading.Lock()


def _trava(path: Path) -> threading.Lock:
    chave = str(path)
    with _TRAVAS_LOCK:
        return _TRAVAS.setdefault(chave, threading.Lock())


def _substituir(origem: Path, destino: Path) -> None:
    """os.replace com repetição: no Windows falha se um leitor (antivírus,
    indexador) está com o destino aberto por alguns milissegundos."""
    ultimo: Exception | None = None
    for i in range(8):
        try:
            os.replace(origem, destino)
            return
        except PermissionError as exc:
            ultimo = exc
            time.sleep(0.03 * (i + 1))
    raise ultimo  # type: ignore[misc]


def gravar_texto(path: Path | str, texto: str, *, backup: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _trava(path):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(texto)
                f.flush()
                os.fsync(f.fileno())
            if backup and path.exists():
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                    _substituir_copia(path, path.with_name(path.name + ".bak"))
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)          # o atual já está ruim: não sobrescreve o .bak bom
            _substituir(tmp, path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


def _substituir_copia(origem: Path, destino: Path) -> None:
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_bytes(origem.read_bytes())
    _substituir(tmp, destino)


def gravar_json(path: Path | str, obj: Any, *, indent: int | None = 2) -> None:
    """Grava `obj` como JSON de forma atômica, mantendo `<arquivo>.bak`."""
    gravar_texto(path, json.dumps(obj, ensure_ascii=False, indent=indent),
                 backup=True)


def ler_json(path: Path | str, padrao: Any = None) -> Any:
    """Lê o JSON; se o arquivo sumiu/está corrompido usa o `.bak` (e o restaura)."""
    path = Path(path)
    for candidato, eh_backup in ((path, False),
                                 (path.with_name(path.name + ".bak"), True)):
        try:
            dados = json.loads(candidato.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            continue
        except Exception:
            continue
        if eh_backup:
            try:
                gravar_texto(path, json.dumps(dados, ensure_ascii=False, indent=2))
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        return dados
    return padrao


def rotacionar(path: Path | str, max_bytes: int, manter: int = 3) -> bool:
    """Se `path` passou de `max_bytes`: arquivo → arquivo.1 → .2 …; descarta o excedente."""
    path = Path(path)
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return False
    except OSError:
        return False
    with _trava(path):
        try:
            for n in range(manter, 0, -1):
                atual = path.with_name(f"{path.name}.{n}")
                if n == manter and atual.exists():
                    atual.unlink()
                anterior = path if n == 1 else path.with_name(f"{path.name}.{n - 1}")
                if anterior.exists():
                    _substituir(anterior, atual)
            return True
        except OSError:
            return False
