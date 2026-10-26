"""
YVAKOR — Chromecast / Google TV / Nest (pychromecast)

Permite tocar mídia, pausar, volume e ver o que está rodando. Arquivos locais
são servidos por um HTTP temporário na própria LAN para o aparelho conseguir
baixar (o Chromecast não enxerga o disco do PC).
"""
from __future__ import annotations

import mimetypes
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _ip_lan() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class _ServidorArquivos(ThreadingHTTPServer):
    """HTTP na LAN que só serve arquivos explicitamente registrados por token.

    Antes servíamos a PASTA inteira do arquivo (com listagem), expondo tudo ao
    redor na rede local. Agora cada arquivo castado ganha um token aleatório;
    qualquer outro caminho devolve 404 e não há listagem de diretório.
    """

    def __init__(self, addr, handler):
        super().__init__(addr, handler)
        self.arquivos: dict[str, Path] = {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self._servir(enviar_corpo=False)

    def do_GET(self):
        self._servir(enviar_corpo=True)

    def _servir(self, enviar_corpo: bool) -> None:
        token = self.path.lstrip("/").split("/", 1)[0].split("?", 1)[0]
        alvo = self.server.arquivos.get(token)
        if not alvo or not alvo.is_file():
            self.send_error(404)
            return
        tamanho = alvo.stat().st_size
        inicio, fim, parcial = 0, tamanho - 1, False
        faixa = self.headers.get("Range", "")
        if faixa.startswith("bytes="):
            try:
                a, b = faixa[6:].split("-", 1)
                inicio = int(a) if a else 0
                fim = int(b) if b else tamanho - 1
            except ValueError:
                inicio, fim = 0, tamanho - 1
            fim = min(fim, tamanho - 1)
            parcial = True
        ctype = mimetypes.guess_type(str(alvo))[0] or "application/octet-stream"
        self.send_response(206 if parcial else 200)
        if parcial:
            self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tamanho}")
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - inicio + 1))
        self.end_headers()
        if not enviar_corpo:
            return
        with open(alvo, "rb") as f:
            f.seek(inicio)
            restante = fim - inicio + 1
            while restante > 0:
                bloco = f.read(min(65536, restante))
                if not bloco:
                    break
                try:
                    self.wfile.write(bloco)
                except (BrokenPipeError, ConnectionResetError):
                    return
                restante -= len(bloco)


class ServidorMidia:
    """Servidor HTTP de arquivos para o Chromecast baixar mídia local.

    Só serve os arquivos explicitamente passados em url(), cada um sob um
    token aleatório não adivinhável — nunca a pasta inteira.
    """

    def __init__(self, diretorio: Path | None = None):
        # 'diretorio' é mantido só por compatibilidade; não é mais exposto.
        self._httpd: _ServidorArquivos | None = None
        self._thread = None

    def iniciar(self) -> str:
        if self._httpd is not None:
            return self._base()
        self._httpd = _ServidorArquivos(("0.0.0.0", 0), _Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="yvakor-midia")
        self._thread.start()
        return self._base()

    def _base(self) -> str:
        porta = self._httpd.server_address[1] if self._httpd else 0
        return f"http://{_ip_lan()}:{porta}"

    def url(self, caminho: Path) -> str:
        self.iniciar()
        alvo = Path(caminho).expanduser().resolve()
        token = secrets.token_urlsafe(16)
        self._httpd.arquivos[token] = alvo
        nome = urllib.parse.quote(alvo.name)
        return f"{self._base()}/{token}/{nome}"

    def parar(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
        self._httpd = None


class Chromecasts:
    def __init__(self, escopo=None):
        self.escopo = escopo
        self._cache: dict[str, dict] = {}
        self._servidor: ServidorMidia | None = None

    # ------------------------------------------------------------------ #
    # Descoberta
    # ------------------------------------------------------------------ #
    @staticmethod
    def _info(cast) -> dict:
        nome = ""
        host = ""
        porta = 8009
        uuid = ""
        try:
            info = cast.cast_info          # pychromecast >= 13
            nome = info.friendly_name
            host = info.host
            porta = info.port
            uuid = str(info.uuid)
        except Exception:
            nome = getattr(cast, "name", "") or getattr(cast.device, "friendly_name", "")
            host = getattr(cast, "host", "")
            porta = getattr(cast, "port", 8009)
            uuid = str(getattr(cast, "uuid", ""))
        modelo = ""
        try:
            modelo = cast.device.model_name or ""
        except Exception:
            pass
        return {"nome": nome, "ip": host, "porta": porta,
                "uuid": uuid, "modelo": modelo}

    def descobrir(self, timeout: float = 6.0) -> list[dict]:
        try:
            import pychromecast
        except ImportError:
            return []
        try:
            res = pychromecast.get_chromecasts(timeout=timeout)
            casts, browser = (res if isinstance(res, tuple) else (res, None))
        except Exception:
            return []
        saida = []
        for cast in casts:
            info = self._info(cast)
            if self.escopo and info["ip"] and not self.escopo.permitido(info["ip"]):
                continue
            saida.append(info)
            self._cache[info["nome"].lower()] = {"cast": cast, "ts": time.time(),
                                                 **info}
        if browser is not None:
            try:
                browser.stop_discovery()
            except Exception:
                pass
        return saida

    def _cliente(self, alvo: str):
        chave = (alvo or "").lower()
        item = self._cache.get(chave)
        if item and (time.time() - item["ts"]) < 120:
            cast = item["cast"]
            try:
                cast.wait(timeout=6)
                return cast
            except Exception:
                self._cache.pop(chave, None)
        achados = self.descobrir(8)
        for c in achados:
            if chave in (c["nome"].lower(), c["ip"], c["uuid"].lower()):
                cast = self._cache[c["nome"].lower()]["cast"]
                cast.wait(timeout=6)
                return cast
        # último recurso: tenta achar por prefixo
        for c in achados:
            if chave and (chave in c["nome"].lower() or chave in c["ip"]):
                cast = self._cache[c["nome"].lower()]["cast"]
                cast.wait(timeout=6)
                return cast
        raise RuntimeError(
            f"Chromecast '{alvo}' não encontrado. Disponíveis: "
            + (", ".join(f"{c['nome']} ({c['ip']})" for c in achados) or "nenhum"))

    # ------------------------------------------------------------------ #
    # Ações
    # ------------------------------------------------------------------ #
    def status(self, alvo: str) -> dict:
        cast = self._cliente(alvo)
        info = self._info(cast)
        dados = {"ok": True, **info, "volume": None, "tocando": None,
                 "titulo": None}
        try:
            dados["volume"] = round(float(cast.status.volume_level) * 100)
            dados["mudo"] = bool(cast.status.volume_muted)
        except Exception:
            pass
        try:
            mc = cast.media_controller
            dados["tocando"] = mc.status.player_state
            dados["titulo"] = mc.status.title or mc.status.media_artist or None
        except Exception:
            pass
        return dados

    def tocar(self, alvo: str, midia: str,
              tipo: str = "", titulo: str = "") -> dict:
        cast = self._cliente(alvo)
        midia = (midia or "").strip()
        if not midia:
            raise ValueError("informe a URL ou o caminho do arquivo")
        if midia.startswith(("http://", "https://")):
            url = midia
        else:
            caminho = Path(midia).expanduser()
            if not caminho.is_file():
                raise ValueError(f"arquivo não encontrado: {midia}")
            if self._servidor is None:
                self._servidor = ServidorMidia(caminho.parent)
                self._servidor.iniciar()
            url = self._servidor.url(caminho)
        if not tipo:
            ext = url.lower().rsplit(".", 1)[-1].split("?")[0]
            tipo = {"mp4": "video/mp4", "webm": "video/webm",
                    "mp3": "audio/mpeg", "m4a": "audio/mp4",
                    "wav": "audio/wav", "jpg": "image/jpeg",
                    "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "video/mp4")
        mc = cast.media_controller
        mc.play_media(url, tipo, title=titulo or None)
        mc.block_until_active(timeout=15)
        return {"ok": True, "tocando": url, "tipo": tipo,
                "estado": mc.status.player_state}

    def pausar(self, alvo: str) -> dict:
        self._cliente(alvo).media_controller.pause()
        return {"ok": True, "acao": "pausado"}

    def continuar(self, alvo: str) -> dict:
        self._cliente(alvo).media_controller.play()
        return {"ok": True, "acao": "tocando"}

    def parar(self, alvo: str) -> dict:
        self._cliente(alvo).media_controller.stop()
        return {"ok": True, "acao": "parado"}

    def volume(self, alvo: str, nivel: int | None = None,
               delta: int | None = None) -> dict:
        cast = self._cliente(alvo)
        atual = float(cast.status.volume_level or 0)
        if nivel is not None:
            novo = max(0.0, min(1.0, float(nivel) / 100.0))
        else:
            novo = max(0.0, min(1.0, atual + float(delta or 0) / 100.0))
        cast.set_volume(novo)
        return {"ok": True, "volume": round(novo * 100)}

    def mudo(self, alvo: str, ativo: bool = True) -> dict:
        cast = self._cliente(alvo)
        cast.set_volume_muted(bool(ativo))
        return {"ok": True, "mudo": bool(ativo)}

    def shutdown(self) -> None:
        """Encerra o servidor HTTP de mídia local, se estiver ativo."""
        if self._servidor is not None:
            self._servidor.parar()
            self._servidor = None
