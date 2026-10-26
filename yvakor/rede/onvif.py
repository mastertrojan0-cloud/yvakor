"""
YVAKOR — ONVIF mínimo (câmeras IP)

Implementação direta em SOAP/HTTP (stdlib), sem SDK:
  • WS-Discovery          — acha câmeras na rede (multicast 239.255.255.250:3702)
  • GetDeviceInformation  — fabricante/modelo/firmware
  • GetProfiles           — perfis de vídeo (token obrigatório nos demais)
  • GetSnapshotUri        — URL do JPEG (usada para tirar foto)
  • GetStreamUri          — URL RTSP (usada para gravar clipe)
  • PTZ ContinuousMove/Stop — mover/parar (requer usuário com permissão)

Autenticação: WS-Security UsernameToken com PasswordDigest (SHA1), que é o que
praticamente todo fabricante aceita (Hikvision, Dahua, Intelbras, Axis…).

Nada de força bruta: sem credencial salva, a câmera é consultada só para
metadados públicos e o agente pede usuário/senha ao dono.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

NS_S = "http://www.w3.org/2003/05/soap-envelope"
NS_TDS = "http://www.onvif.org/ver10/device/wsdl"
NS_TRT = "http://www.onvif.org/ver10/media/wsdl"
NS_TPTZ = "http://www.onvif.org/ver20/ptz/wsdl"
NS_TT = "http://www.onvif.org/ver10/schema"
NS_WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
NS_WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
NS_WSSE = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
           "wssecurity-secext-1.0.xsd")
NS_WSU = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
          "wssecurity-utility-1.0.xsd")
NS_PW = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
         "username-token-profile-1.0#PasswordDigest")
NS_B64 = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-"
          "soap-message-security-1.0#Base64Binary")


class OnvifErro(RuntimeError):
    pass


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wsse(usuario: str, senha: str) -> str:
    nonce = os.urandom(16)
    criado = _iso()
    digest = base64.b64encode(
        hashlib.sha1(nonce + criado.encode() + senha.encode()).digest()).decode()
    nonce_b64 = base64.b64encode(nonce).decode()
    return (
        '<s:Header><Security s:mustUnderstand="1" '
        f'xmlns="{NS_WSSE}">'
        f'<UsernameToken><Username>{_xml_esc(usuario)}</Username>'
        f'<Password Type="{NS_PW}">{digest}</Password>'
        f'<Nonce EncodingType="{NS_B64}">{nonce_b64}</Nonce>'
        f'<Created xmlns="{NS_WSU}">{criado}</Created>'
        "</UsernameToken></Security></s:Header>")


def _xml_esc(txt: str) -> str:
    return (str(txt).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def envelope(corpo: str, usuario: str = "", senha: str = "") -> bytes:
    header = _wsse(usuario, senha) if usuario else "<s:Header/>"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<s:Envelope xmlns:s="{NS_S}" xmlns:tds="{NS_TDS}" '
        f'xmlns:trt="{NS_TRT}" xmlns:tptz="{NS_TPTZ}" xmlns:tt="{NS_TT}">'
        f"{header}<s:Body>{corpo}</s:Body></s:Envelope>").encode("utf-8")


def _tag(el) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _filhos(el, nome: str):
    return [c for c in el.iter() if _tag(c) == nome]


def _txt(el, nome: str, padrao: str = "") -> str:
    achados = _filhos(el, nome)
    if achados and achados[0].text:
        return achados[0].text.strip()
    return padrao


# ----------------------------------------------------------------------- #
# HTTP (POST SOAP / GET com Digest ou Basic)
# ----------------------------------------------------------------------- #
def _http(url: str, corpo: bytes | None = None, usuario: str = "",
          senha: str = "", timeout: float = 8.0) -> tuple[int, bytes, dict]:
    headers = {"User-Agent": "YVAKOR/2.0 (ONVIF)"}
    if corpo is not None:
        headers["Content-Type"] = "application/soap+xml; charset=utf-8"
    if usuario:
        headers["Authorization"] = "Basic " + base64.b64encode(
            f"{usuario}:{senha}".encode()).decode()
    req = urllib.request.Request(url, data=corpo, headers=headers,
                                 method="POST" if corpo is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        desafio = e.headers.get("WWW-Authenticate", "") or ""
        if e.code == 401 and usuario and desafio.lower().startswith("digest"):
            try:
                auth = _digest(desafio, "POST" if corpo is not None else "GET",
                               url, usuario, senha)
                req.add_header("Authorization", auth)
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, r.read(), dict(r.headers)
            except urllib.error.HTTPError as e2:
                return e2.code, e2.read(), dict(e2.headers or {})
        return e.code, e.read(), dict(e.headers or {})


def _digest(desafio: str, metodo: str, url: str, usuario: str,
            senha: str) -> str:
    """Monta o header Authorization Digest (RFC 7616, MD5)."""
    campos = dict(re.findall(r'(\w+)="?([^",]+)"?', desafio))
    realm = campos.get("realm", "")
    nonce = campos.get("nonce", "")
    qop = campos.get("qop", "")
    opaque = campos.get("opaque", "")
    algoritmo = campos.get("algorithm", "MD5")
    uri = urlparse(url).path or "/"
    if urlparse(url).query:
        uri += "?" + urlparse(url).query

    def md5(txt: str) -> str:
        return hashlib.md5(txt.encode()).hexdigest()

    ha1 = md5(f"{usuario}:{realm}:{senha}")
    ha2 = md5(f"{metodo}:{uri}")
    nc = "00000001"
    cnonce = base64.b16encode(os.urandom(8)).decode()
    if qop:
        resposta = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        resposta = md5(f"{ha1}:{nonce}:{ha2}")
    partes = [f'username="{usuario}"', f'realm="{realm}"',
              f'nonce="{nonce}"', f'uri="{uri}"', f'response="{resposta}"',
              f"algorithm={algoritmo}"]
    if qop:
        partes += [f"qop={qop}", f"nc={nc}", f'cnonce="{cnonce}"']
    if opaque:
        partes.append(f'opaque="{opaque}"')
    return "Digest " + ", ".join(partes)


# ----------------------------------------------------------------------- #
# WS-Discovery
# ----------------------------------------------------------------------- #
def descobrir(segundos: float = 3.0) -> list[dict]:
    """Procura câmeras ONVIF na rede (multicast WS-Discovery)."""
    probe = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<e:Envelope xmlns:e="{NS_S}" xmlns:w="{NS_WSA}" xmlns:d="{NS_WSD}" '
        'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        "<e:Header><w:MessageID>uuid:" + str(os.urandom(16).hex()) + "</w:MessageID>"
        f"<w:To e:mustUnderstand=\"true\">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
        '<w:Action e:mustUnderstand="true">'
        "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>"
        "</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter"
        "</d:Types></d:Probe></e:Body></e:Envelope>").encode()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.settimeout(0.5)
    try:
        s.sendto(probe, ("239.255.255.250", 3702))
    except OSError:
        pass

    achados: dict[str, dict] = {}
    fim = time.time() + float(segundos)
    while time.time() < fim:
        try:
            dados, (ip, _) = s.recvfrom(8192)
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            raiz = ET.fromstring(dados)
        except ET.ParseError:
            continue
        xaddrs = " ".join(t.text or "" for t in raiz.iter()
                          if _tag(t) == "XAddrs").strip()
        urls = [u for u in xaddrs.split() if u.lower().startswith("http")]
        if not urls:
            continue
        item = achados.setdefault(ip, {"ip": ip, "xaddr": urls[0],
                                       "xaddrs": urls, "tipos": []})
        for t in raiz.iter():
            if _tag(t) == "Types" and t.text:
                item["tipos"].append(t.text.strip())
        if len(urls) > len(item["xaddrs"]):
            item["xaddrs"] = urls
    s.close()
    return list(achados.values())


# ----------------------------------------------------------------------- #
# Cliente de uma câmera
# ----------------------------------------------------------------------- #
class OnvifCamera:
    def __init__(self, ip: str, usuario: str = "", senha: str = "",
                 porta: int = 80, xaddr: str | None = None,
                 timeout: float = 8.0):
        self.ip = ip
        self.usuario = usuario
        self.senha = senha
        self.timeout = timeout
        self.xaddr = xaddr or f"http://{ip}:{porta}/onvif/device_service"
        self._perfis: list[dict] | None = None
        self._ptz_xaddr: str | None = None

    # -- infra -------------------------------------------------------- #
    def _chamar(self, url: str, corpo: str) -> ET.Element:
        status, dados, _ = _http(url, envelope(corpo, self.usuario, self.senha),
                                 self.usuario, self.senha, self.timeout)
        if status == 401:
            raise OnvifErro("credenciais recusadas pela câmera (401)")
        try:
            raiz = ET.fromstring(dados)
        except ET.ParseError:
            raise OnvifErro(f"resposta inválida da câmera (HTTP {status})")
        falhas = [e for e in raiz.iter() if _tag(e) == "Fault"]
        if falhas:
            motivo = _txt(falhas[0], "Text") or _txt(falhas[0], "Reason") or "fault"
            raise OnvifErro(f"câmera recusou: {motivo[:200]}")
        return raiz

    def _media(self, corpo: str) -> ET.Element:
        return self._chamar(self._media_xaddr(), corpo)

    def _media_xaddr(self) -> str:
        if self._perfis is None:
            self.info()
        return getattr(self, "_media_url", self.xaddr.replace(
            "device_service", "media_service"))

    # -- operações ---------------------------------------------------- #
    def info(self) -> dict:
        corpo = (f'<tds:GetDeviceInformation xmlns:tds="{NS_TDS}"/>')
        raiz = self._chamar(self.xaddr, corpo)
        dados = {
            "fabricante": _txt(raiz, "Manufacturer"),
            "modelo": _txt(raiz, "Model"),
            "firmware": _txt(raiz, "FirmwareVersion"),
            "serial": _txt(raiz, "SerialNumber"),
            "hardware": _txt(raiz, "HardwareId"),
        }
        # Endereço do serviço de mídia (varia por fabricante)
        self._media_url = self.xaddr
        try:
            caps = self._chamar(self.xaddr, f'<tds:GetCapabilities xmlns:tds="{NS_TDS}">'
                                            "<tds:Category>All</tds:Category>"
                                            "</tds:GetCapabilities>")
            for el in caps.iter():
                if _tag(el) == "Media" and el.attrib.get("XAddr"):
                    self._media_url = el.attrib["XAddr"]
                if _tag(el) == "PTZ" and el.attrib.get("XAddr"):
                    self._ptz_xaddr = el.attrib["XAddr"]
        except OnvifErro:
            pass
        self._perfis = []
        return dados

    def perfis(self) -> list[dict]:
        if self._perfis:
            return self._perfis
        raiz = self._media(f'<trt:GetProfiles xmlns:trt="{NS_TRT}"/>')
        saida = []
        for p in raiz.iter():
            if _tag(p) != "Profiles":
                continue
            token = p.attrib.get("token", "")
            nome = _txt(p, "Name")
            resolucao = ""
            for w in p.iter():
                if _tag(w) in ("Width", "Height") and w.text:
                    resolucao += f"{w.text}"
                    if _tag(w) == "Width":
                        resolucao += "x"
            saida.append({"token": token, "nome": nome,
                          "resolucao": resolucao.rstrip("x")})
        self._perfis = saida
        return saida

    def _token(self, perfil: str | None = None) -> str:
        perfis = self.perfis()
        if not perfis:
            raise OnvifErro("câmera não informou perfis de vídeo")
        if perfil:
            for p in perfis:
                if perfil in (p["token"], p["nome"]):
                    return p["token"]
            raise OnvifErro(f"perfil '{perfil}' não existe")
        return perfis[0]["token"]

    def snapshot_url(self, perfil: str | None = None) -> str:
        token = self._token(perfil)
        raiz = self._media(
            f'<trt:GetSnapshotUri xmlns:trt="{NS_TRT}">'
            f"<trt:ProfileToken>{_xml_esc(token)}</trt:ProfileToken>"
            "</trt:GetSnapshotUri>")
        url = _txt(raiz, "Uri")
        if not url:
            raise OnvifErro("câmera não devolveu URL de snapshot")
        return url

    def stream_url(self, perfil: str | None = None) -> str:
        token = self._token(perfil)
        raiz = self._media(
            f'<trt:GetStreamUri xmlns:trt="{NS_TRT}">'
            '<trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream>'
            "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>"
            "</trt:StreamSetup>"
            f"<trt:ProfileToken>{_xml_esc(token)}</trt:ProfileToken>"
            "</trt:GetStreamUri>")
        url = _txt(raiz, "Uri")
        if not url:
            raise OnvifErro("câmera não devolveu URL RTSP")
        return url

    def ptz(self, x: float = 0.0, y: float = 0.0, zoom: float = 0.0,
            segundos: float = 0.4) -> dict:
        if not self._ptz_xaddr:
            self.info()
        if not self._ptz_xaddr:
            raise OnvifErro("esta câmera não expôs serviço PTZ")
        token = self._token()
        corpo = (
            f'<tptz:ContinuousMove xmlns:tptz="{NS_TPTZ}">'
            f"<tptz:ProfileToken>{_xml_esc(token)}</tptz:ProfileToken>"
            "<tptz:Velocity>"
            f"<tt:PanTilt x='{float(x):.3f}' y='{float(y):.3f}'/>"
            f"<tt:Zoom x='{float(zoom):.3f}'/>"
            "</tptz:Velocity></tptz:ContinuousMove>")
        self._chamar(self._ptz_xaddr, corpo)
        time.sleep(max(0.1, float(segundos)))
        self.parar()
        return {"ok": True, "x": x, "y": y, "zoom": zoom, "segundos": segundos}

    def parar(self) -> dict:
        if not self._ptz_xaddr:
            self.info()
        token = self._token()
        corpo = (f'<tptz:Stop xmlns:tptz="{NS_TPTZ}">'
                 f"<tptz:ProfileToken>{_xml_esc(token)}</tptz:ProfileToken>"
                 "<tptz:PanTilt>true</tptz:PanTilt>"
                 "<tptz:Zoom>true</tptz:Zoom></tptz:Stop>")
        self._chamar(self._ptz_xaddr, corpo)
        return {"ok": True, "parado": True}


def credenciais_da_url(url: str) -> tuple[str, str, str]:
    """Extrai usuário/senha embutidos na URL (http://user:pass@ip/...)."""
    p = urlparse(url)
    if p.username:
        limpa = p._replace(netloc=p.netloc.split("@", 1)[-1]).geturl()
        return p.username, p.password or "", limpa
    return "", "", url


def baixar_snapshot(url: str, usuario: str = "", senha: str = "",
                    timeout: float = 10.0) -> bytes:
    """Baixa o JPEG do snapshot (usa credenciais da URL ou as informadas)."""
    u_user, u_pass, url_limpa = credenciais_da_url(url)
    usuario = usuario or u_user
    senha = senha or u_pass
    status, dados, headers = _http(url_limpa, None, usuario, senha, timeout)
    if status >= 400:
        raise OnvifErro(f"snapshot recusado (HTTP {status})")
    tipo = (headers.get("Content-Type") or "").lower()
    if "image" not in tipo and not dados.startswith(b"\xff\xd8"):
        raise OnvifErro(f"resposta não é imagem ({tipo or 'sem tipo'})")
    return dados
