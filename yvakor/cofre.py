"""
YVAKOR — Cofre de segredos (tokens OAuth etc.) com DPAPI do Windows

proteger("texto") → "dpapi:<base64>": cifrado com a chave do SEU usuário do
Windows (CryptProtectData). Outro usuário da máquina, ou o arquivo copiado
para outro PC, não consegue abrir. No Windows, se a DPAPI falhar, levanta
erro (nunca grava aberto). Fora do Windows guarda como "plano:<texto>" — o
mesmo que os conectores já fazem hoje.
"""
from __future__ import annotations

import base64
import ctypes
import logging
import os

_log = logging.getLogger(__name__)
_ENTROPIA = b"YVAKOR-cofre-v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(dados: bytes) -> tuple[_Blob, ctypes.Array]:
    """Devolve o blob E o buffer: quem chama segura o buffer vivo até a DPAPI
    terminar (só o ponteiro no blob não impede o coletor de liberá-lo)."""
    buf = ctypes.create_string_buffer(dados, len(dados))
    return _Blob(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi(dados: bytes, cifrar: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    (entrada, _buf_e), (entropia, _buf_x) = _blob(dados), _blob(_ENTROPIA)
    saida = _Blob()
    if cifrar:
        ok = crypt32.CryptProtectData(ctypes.byref(entrada), "YVAKOR", ctypes.byref(entropia),
                                      None, None, 0, ctypes.byref(saida))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia),
                                        None, None, 0, ctypes.byref(saida))
    if not ok:
        raise OSError("DPAPI falhou")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


def proteger(texto: str) -> str:
    if not texto:
        return ""
    if os.name == "nt":
        # No Windows a cifra é obrigatória: se a DPAPI falhar, o login falha
        # com erro claro em vez de gravar o token aberto em silêncio.
        try:
            return "dpapi:" + base64.b64encode(_dpapi(texto.encode("utf-8"), True)).decode()
        except Exception as exc:
            _log.error("DPAPI falhou; segredo NÃO foi gravado", exc_info=True)
            raise RuntimeError(f"não consegui cifrar o segredo com a DPAPI: {exc}") from exc
    return "plano:" + texto


def revelar(guardado: str) -> str:
    if not guardado:
        return ""
    if guardado.startswith("dpapi:"):
        try:
            return _dpapi(base64.b64decode(guardado[6:]), False).decode("utf-8")
        except Exception:
            _log.warning("não consegui abrir um segredo do cofre (outro usuário/PC?)")
            return ""
    return guardado[6:] if guardado.startswith("plano:") else guardado
