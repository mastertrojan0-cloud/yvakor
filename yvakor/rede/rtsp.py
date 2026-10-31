"""
YVAKOR — Cliente RTSP nativo (sem dependência do EYE DELTA)

Por que existe: câmeras Yoosee recusam o OPTIONS que o ffmpeg envia, então
`ffmpeg -i rtsp://...` falha com 405 mesmo com a senha certa. Aqui falamos
RTSP na mão (DESCRIBE → SETUP → PLAY), recebemos RTP/UDP, remontamos os NALs
H.264 e entregamos ao ffmpeg só o fluxo elementar — que ele decodifica bem.

A janela é do YVAKOR: o servidor expõe MJPEG em /api/rede/camera/<ip>/ao-vivo.mjpg
e o navegador abre /camera/<ip>.
"""
from __future__ import annotations

import base64
import hashlib
import re
import shutil
import socket
import subprocess
from yvakor import proc as _ywproc
import threading
from pathlib import Path
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent


class RTSPErro(RuntimeError):
    pass


def _resposta(sock: socket.socket) -> tuple[int, dict, bytes]:
    dados = b""
    while b"\r\n\r\n" not in dados:
        bloco = sock.recv(8192)
        if not bloco:
            raise RTSPErro("conexão encerrada pela câmera")
        dados += bloco
    cabecalho, corpo = dados.split(b"\r\n\r\n", 1)
    linhas = cabecalho.decode("utf-8", "replace").split("\r\n")
    try:
        status = int(linhas[0].split()[1])
    except (IndexError, ValueError):
        raise RTSPErro(f"resposta inválida: {linhas[0][:80]}")
    headers = {}
    for linha in linhas[1:]:
        if ":" in linha:
            k, v = linha.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    tamanho = int(headers.get("content-length", "0") or 0)
    while len(corpo) < tamanho:
        bloco = sock.recv(tamanho - len(corpo))
        if not bloco:
            # Peer fechou a conexão no meio do corpo: sem este guarda o laço
            # girava para sempre (recv() devolvendo b"" a 100% de CPU).
            raise RTSPErro("conexão encerrada antes do corpo completo")
        corpo += bloco
    return status, headers, corpo


def _digest(desafio: str, metodo: str, uri: str, usuario: str, senha: str) -> str:
    campos = dict(re.findall(r'(\w+)="?([^",]+)"?', desafio))
    realm, nonce = campos.get("realm", ""), campos.get("nonce", "")
    qop = campos.get("qop", "")
    opaque = campos.get("opaque", "")

    def md5(t: str) -> str:
        return hashlib.md5(t.encode()).hexdigest()

    ha1, ha2 = md5(f"{usuario}:{realm}:{senha}"), md5(f"{metodo}:{uri}")
    nc, cnonce = "00000001", base64.b16encode(__import__("os").urandom(6)).decode()
    if qop:
        resposta = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        resposta = md5(f"{ha1}:{nonce}:{ha2}")
    partes = [f'username="{usuario}"', f'realm="{realm}"', f'nonce="{nonce}"',
              f'uri="{uri}"', f'response="{resposta}"']
    if qop:
        partes += [f"qop={qop}", f"nc={nc}", f'cnonce="{cnonce}"']
    if opaque:
        partes.append(f'opaque="{opaque}"')
    return "Digest " + ", ".join(partes)


class CameraRTSP:
    def __init__(self, host: str, caminho: str = "/onvif1", usuario: str = "",
                 senha: str = "", porta: int = 554):
        self.host = host
        self.porta = int(porta)
        self.caminho = caminho if caminho.startswith("/") else "/" + caminho
        self.usuario, self.senha = usuario, senha
        self.url = f"rtsp://{host}:{self.porta}{self.caminho}"
        self._sock: socket.socket | None = None
        self._rtp: socket.socket | None = None
        self._ffmpeg: subprocess.Popen | None = None
        self._rodando = False
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self.ultimo_jpeg: bytes | None = None
        self.quadros = 0
        self.cseq = 0
        self.sessao = ""
        self.auth = ""
        self.diagnostico: list[str] = []

    # ------------------------------------------------------------------ #
    def _pedido(self, metodo: str, url: str, extras: dict | None = None,
                corpo: str = "", auth: str = "") -> tuple[int, dict, bytes]:
        self.cseq += 1
        linhas = [f"{metodo} {url} RTSP/1.0", f"CSeq: {self.cseq}",
                  "User-Agent: YVAKOR/1.0"]
        if self.sessao:
            linhas.append(f"Session: {self.sessao}")
        if auth:
            linhas.append(f"Authorization: {auth}")
        elif self.auth:
            linhas.append(f"Authorization: {self.auth}")
        for k, v in (extras or {}).items():
            linhas.append(f"{k}: {v}")
        if corpo:
            linhas.append(f"Content-Length: {len(corpo.encode())}")
        bruto = ("\r\n".join(linhas) + "\r\n\r\n" + corpo).encode()
        assert self._sock is not None
        self._sock.sendall(bruto)
        return _resposta(self._sock)

    def _autorizacao(self, desafio: str, metodo: str, url: str) -> str:
        if desafio.lower().startswith("basic"):
            token = base64.b64encode(
                f"{self.usuario}:{self.senha}".encode()).decode()
            return f"Basic {token}"
        if desafio.lower().startswith("digest"):
            return _digest(desafio, metodo, url, self.usuario, self.senha)
        return ""

    # ------------------------------------------------------------------ #
    def _handshake(self) -> dict:
        self._sock = socket.create_connection((self.host, self.porta), timeout=8)
        self._sock.settimeout(8)
        auth = ""
        if self.usuario:
            token = base64.b64encode(
                f"{self.usuario}:{self.senha}".encode()).decode()
            auth = f"Basic {token}"
        status, headers, corpo = self._pedido(
            "DESCRIBE", self.url, {"Accept": "application/sdp"}, auth=auth)
        self.diagnostico.append(f"DESCRIBE {status}")
        if status == 401:
            desafio = headers.get("www-authenticate", "")
            auth = self._autorizacao(desafio, "DESCRIBE", self.url)
            status, headers, corpo = self._pedido(
                "DESCRIBE", self.url,
                {"Accept": "application/sdp"}, auth=auth)
            self.diagnostico.append(f"DESCRIBE(autenticado) {status}")
        if status != 200:
            raise RTSPErro(f"DESCRIBE recusado ({status})")
        self.auth = auth
        sdp = corpo.decode("utf-8", "replace")
        return self._parse_sdp(sdp)

    @staticmethod
    def _parse_sdp(sdp: str) -> dict:
        video = {"control": "", "sps": b"", "pps": b"", "codec": "", "pt": "96"}
        em_video = False
        for linha in sdp.splitlines():
            linha = linha.strip()
            if linha.startswith("m=video"):
                em_video = True
                partes = linha.split()
                if len(partes) > 3:
                    video["pt"] = partes[3]
                continue
            if linha.startswith("m=") and em_video:
                break
            if not em_video:
                continue
            if linha.startswith("a=control:"):
                video["control"] = linha.split(":", 1)[1].strip()
            elif linha.startswith("a=rtpmap:"):
                video["codec"] = linha.split(" ", 1)[-1].strip()
            elif linha.startswith("a=fmtp:"):
                m = re.search(r"sprop-parameter-sets=([^;\s]+)", linha)
                if m:
                    for i, b64 in enumerate(m.group(1).split(",")):
                        try:
                            dado = base64.b64decode(b64 + "==")
                        except Exception:
                            continue
                        if dado[:1] and (dado[0] & 0x1F) == 7:
                            video["sps"] = dado
                        elif dado[:1] and (dado[0] & 0x1F) == 8:
                            video["pps"] = dado
        return video

    # ------------------------------------------------------------------ #
    def iniciar(self) -> dict:
        info = self._handshake()
        if not info.get("control"):
            info["control"] = "trackID=1"
        base = self.url if self.url.endswith("/") else self.url + "/"
        alvo = (info["control"] if info["control"].startswith("rtsp://")
                else base + info["control"].lstrip("/"))
        self._rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rtp.bind(("0.0.0.0", 0))
        porta = self._rtp.getsockname()[1]
        if porta % 2:
            self._rtp.close()
            self._rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._rtp.bind(("0.0.0.0", porta + 1))
            porta += 1
        self._rtp.settimeout(1.0)
        status, headers, _ = self._pedido(
            "SETUP", alvo,
            {"Transport": f"RTP/AVP;unicast;client_port={porta}-{porta + 1}"})
        self.diagnostico.append(f"SETUP {status}")
        if status != 200:
            raise RTSPErro(f"SETUP recusado ({status})")
        self.sessao = headers.get("session", "").split(";")[0].strip()
        status, _, _ = self._pedido("PLAY", self.url,
                                    {"Range": "npt=0.000-"})
        self.diagnostico.append(f"PLAY {status}")
        if status != 200:
            raise RTSPErro(f"PLAY recusado ({status})")

        if not shutil.which("ffmpeg"):
            raise RTSPErro("ffmpeg não encontrado no PATH — instale o ffmpeg "
                           "(winget/choco) para ver o vídeo da câmera")
        comando = ["ffmpeg", "-hide_banner", "-loglevel", "error",
                   "-fflags", "nobuffer", "-flags", "low_delay",
                   "-f", "h264", "-i", "-", "-f", "image2pipe",
                   "-vcodec", "mjpeg", "-q:v", "5", "-"]
        self._ffmpeg = _ywproc.popen(
            comando, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        if info.get("sps") and info.get("pps"):
            self._ffmpeg.stdin.write(b"\x00\x00\x00\x01" + info["sps"]
                                     + b"\x00\x00\x00\x01" + info["pps"])
            self._ffmpeg.stdin.flush()
        self._rodando = True
        t1 = threading.Thread(target=self._receber_rtp, daemon=True,
                              name="yvakor-rtp")
        t2 = threading.Thread(target=self._ler_jpegs, daemon=True,
                              name="yvakor-mjpeg")
        t1.start(); t2.start()
        self._threads = [t1, t2]
        return {"ok": True, "url": re.sub(r"//[^@/]+@", "//***@", self.url),
                "codec": info.get("codec", ""), "sessao": self.sessao,
                "porta_rtp": porta, "diagnostico": self.diagnostico}

    # ------------------------------------------------------------------ #
    def _receber_rtp(self) -> None:
        buffer_fu = b""
        while self._rodando and self._rtp is not None:
            try:
                pacote, _ = self._rtp.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(pacote) < 12:
                continue
            cc = pacote[0] & 0x0F
            cabecalho = 12 + cc * 4
            if pacote[0] & 0x10:  # extensão
                if len(pacote) < cabecalho + 4:
                    continue
                ext = int.from_bytes(pacote[cabecalho + 2:cabecalho + 4], "big")
                cabecalho += 4 + ext * 4
            carga = pacote[cabecalho:]
            if not carga:
                continue
            tipo = carga[0] & 0x1F
            try:
                if tipo == 28 and len(carga) > 2:      # FU-A
                    inicio, fim = bool(carga[1] & 0x80), bool(carga[1] & 0x40)
                    nal_tipo = carga[1] & 0x1F
                    if inicio:
                        buffer_fu = bytes([(carga[0] & 0xE0) | nal_tipo]) + carga[2:]
                    elif buffer_fu:
                        buffer_fu += carga[2:]
                    if fim and buffer_fu:
                        self._enviar_nal(buffer_fu)
                        buffer_fu = b""
                elif tipo == 24 and len(carga) > 2:    # STAP-A
                    pos = 1
                    while pos + 2 <= len(carga):
                        tamanho = int.from_bytes(carga[pos:pos + 2], "big")
                        pos += 2
                        if tamanho and pos + tamanho <= len(carga):
                            self._enviar_nal(carga[pos:pos + tamanho])
                        pos += tamanho
                elif tipo in (1, 5):                    # NAL único
                    self._enviar_nal(carga)
            except Exception:
                continue

    def _enviar_nal(self, nal: bytes) -> None:
        if not nal or self._ffmpeg is None or self._ffmpeg.stdin is None:
            return
        try:
            self._ffmpeg.stdin.write(b"\x00\x00\x00\x01" + nal)
            self._ffmpeg.stdin.flush()
        except Exception:
            self._rodando = False

    def _ler_jpegs(self) -> None:
        buffer = b""
        assert self._ffmpeg and self._ffmpeg.stdout
        while self._rodando:
            bloco = self._ffmpeg.stdout.read(8192)
            if not bloco:
                break
            buffer += bloco
            while True:
                inicio = buffer.find(b"\xff\xd8")
                fim = buffer.find(b"\xff\xd9", inicio + 2) if inicio >= 0 else -1
                if inicio >= 0 and fim > inicio:
                    with self._lock:
                        self.ultimo_jpeg = buffer[inicio:fim + 2]
                        self.quadros += 1
                    buffer = buffer[fim + 2:]
                else:
                    break
            if len(buffer) > 4_000_000:
                buffer = buffer[-1_000_000:]

    # ------------------------------------------------------------------ #
    def quadro(self) -> bytes | None:
        with self._lock:
            return self.ultimo_jpeg

    def status(self) -> dict:
        with self._lock:
            return {"ativo": self._rodando, "quadros": self.quadros,
                    "tem_imagem": self.ultimo_jpeg is not None,
                    "diagnostico": list(self.diagnostico)}

    def parar(self) -> None:
        self._rodando = False
        try:
            if self._sock is not None:
                self._pedido("TEARDOWN", self.url)
                self._sock.close()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        self._sock = None
        try:
            if self._rtp is not None:
                self._rtp.close()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        self._rtp = None
        try:
            if self._ffmpeg is not None:
                self._ffmpeg.terminate()
                self._ffmpeg.wait(timeout=3)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        self._ffmpeg = None
