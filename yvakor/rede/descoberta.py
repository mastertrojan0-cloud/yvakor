"""
YVAKOR — Descoberta de dispositivos na rede local

Camadas usadas (todas dentro do escopo autorizado):
  1. TCP probe   — acha hosts vivos e portas abertas (rápido, sem admin)
  2. ARP         — MAC dos vizinhos (identifica fabricante pelo OUI)
  3. SSDP/UPnP   — TVs, roteadores, media servers, câmeras com UPnP
  4. mDNS        — Chromecast/Google TV, AirPlay, impressoras, Shelly/ESPHome

O resultado é classificado (câmera, tv, telefone, iot, roteador…) e gravado no
registro persistente, para o agente lembrar dos aparelhos entre execuções.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import subprocess
from yvakor import proc as _ywproc
import subprocess
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from yvakor.rede.escopo import EscopoRede
from yvakor.rede.registro import RegistroRede

OUI = {
    "00:1a:11": "Google", "54:60:09": "Google", "f4:f5:d8": "Google",
    "3c:5a:b4": "Google", "da:a1:19": "Google", "1c:f2:9a": "Google",
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi",
    "00:1b:a9": "Brother", "00:80:77": "Brother", "3c:2a:f4": "Brother",
    "00:17:88": "Philips Hue", "ec:b5:fa": "Philips Hue",
    "00:1d:c9": "GainSpan/TP-Link", "50:c7:bf": "TP-Link", "a4:2b:b0": "TP-Link",
    "f4:f2:6d": "TP-Link", "60:38:e0": "Belkin/Wemo", "94:10:3e": "Belkin/Wemo",
    "b0:be:76": "TP-Link", "00:0e:58": "Sonos", "5c:aa:fd": "Sonos",
    "48:a6:b8": "Sonos", "00:04:20": "Slim Devices", "00:1f:3a": "Roku",
    "cc:6d:a0": "Roku", "b0:a7:37": "Roku", "dc:3a:5e": "Roku",
    "00:1e:c2": "Apple", "f0:18:98": "Apple", "ac:bc:32": "Apple",
    "3c:22:fb": "Apple", "a4:83:e7": "Apple", "dc:a9:04": "Apple",
    "8c:85:90": "Apple", "9c:20:7b": "Apple", "70:3e:ac": "Apple",
    "00:12:fb": "Samsung", "8c:77:12": "Samsung", "78:1f:db": "Samsung",
    "d0:03:df": "Samsung", "e4:7c:f9": "Samsung", "c8:ba:94": "Samsung",
    "00:1e:75": "LG", "a8:23:fe": "LG", "c4:36:6c": "LG", "2c:54:cf": "LG",
    "00:1a:79": "Xiaomi", "64:b4:73": "Xiaomi", "78:11:dc": "Xiaomi",
    "50:8f:4c": "Xiaomi", "9c:99:a0": "Xiaomi",
    "00:04:4b": "NVIDIA", "48:b0:2d": "NVIDIA", "b8:ae:ed": "NVIDIA",
    "24:0a:c4": "Espressif (ESP32)", "30:ae:a4": "Espressif (ESP32)",
    "84:f3:eb": "Espressif (ESP32)", "a4:cf:12": "Espressif (ESP32)",
    "dc:4f:22": "Espressif (ESP32)", "ec:fa:bc": "Espressif (ESP32)",
    "54:48:e6": "Tuya/Smart Life", "68:57:2d": "Tuya/Smart Life",
    "d8:1f:12": "Tuya/Smart Life", "18:69:d8": "Tuya/Smart Life",
    "00:11:32": "Synology", "00:1a:8c": "Synology",
    "c0:56:27": "Hikvision", "44:19:b6": "Hikvision", "bc:ad:28": "Hikvision",
    "3c:ef:8c": "Dahua", "e0:50:8b": "Dahua", "90:02:a9": "Dahua",
    "00:12:12": "Intelbras", "0c:47:3d": "Intelbras", "f4:6d:3f": "Intelbras",
    "58:8e:81": "Intel", "a4:bb:6d": "Intel", "f8:63:3f": "Intel",
    "00:1b:21": "Intel", "3c:97:0e": "Intel", "8c:16:45": "Intel",
    "00:50:56": "VMware", "00:0c:29": "VMware", "00:15:5d": "Microsoft (Hyper-V)",
    "e4:5f:01:xx": "Raspberry Pi", "b4:2e:99": "Giga-Byte",
}

# Serviços mDNS que valem a pena observar
SERVICOS_MDNS = [
    "_googlecast._tcp.local.",     # Chromecast / Google TV / Nest
    "_airplay._tcp.local.",        # Apple TV / TVs com AirPlay
    "_raop._tcp.local.",           # AirPlay audio
    "_onvif._tcp.local.",          # câmeras IP ONVIF
    "_rtsp._tcp.local.",           # câmeras/streams
    "_ipp._tcp.local.",            # impressoras
    "_printer._tcp.local.",
    "_hap._tcp.local.",            # HomeKit
    "_shelly._tcp.local.",         # Shelly
    "_esphomelib._tcp.local.",     # ESPHome
    "_http._tcp.local.",           # genérico
    "_smb._tcp.local.",            # computadores
    "_ssh._tcp.local.",
    "_androidtvremote2._tcp.local.",  # Android TV
    "_spotify-connect._tcp.local.",
]

_MAC_RE = re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")


# ----------------------------------------------------------------------- #
# Utilitários
# ----------------------------------------------------------------------- #
def _mac_valido(mac: str) -> bool:
    if not mac:
        return False
    m = mac.lower().replace("-", ":")
    if m in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"):
        return False
    return bool(_MAC_RE.fullmatch(m))


_OUI_EXTRA = {
    "8c:5c:53": "Intelbras", "44:19:b6": "Hikvision", "3c:ef:8c": "Dahua",
    "f4:f5:d8": "Google", "44:65:0d": "Amazon", "8c:77:12": "Samsung",
    "58:fd:b1": "LG", "30:f9:ed": "Sony", "50:c7:bf": "TP-Link",
    "64:cc:2e": "Xiaomi", "b0:a7:37": "Roku", "dc:3a:5e": "Roku",
    "00:15:5d": "Microsoft (Hyper-V)", "24:0a:c4": "Espressif",
}


def fabricante_por_mac(mac: str) -> str:
    if not mac:
        return ""
    prefixo = mac.lower().replace("-", ":")[:8]
    return OUI.get(prefixo, "") or _OUI_EXTRA.get(prefixo, "")


def _netbios(ip: str) -> str:
    try:
        out = _ywproc.run(["nbtstat", "-A", ip], capture_output=True,
                             text=True, timeout=2).stdout
        for linha in out.splitlines():
            if "<00>" in linha and "UNIQUE" in linha.upper():
                nome = linha.split("<00>")[0].strip()
                if nome and nome not in ("..", "--"):
                    return nome
    except Exception:
        pass
    return ""


def _mac_aleatorio(mac: str) -> bool:
    """MAC localmente administrado (privacidade): típico de celular/tablet."""
    try:
        primeiro = int(mac.replace("-", ":")[:2], 16)
        return bool(primeiro & 0x02) and primeiro not in (0x00, 0x02)
    except Exception:
        return False


def _dns_reverso(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def _virtual(nome: str) -> bool:
    baixo = (nome or "").lower()
    return any(k in baixo for k in ("docker", "wsl", "tailscale",
                                    "host.internal", "localhost",
                                    "vmware", "hyper-v", "virtualbox"))


def arp_tabela() -> dict[str, str]:
    """IP -> MAC, lido da tabela ARP do sistema (só hosts unicast reais)."""
    tabela: dict[str, str] = {}
    try:
        p = _ywproc.run(["arp", "-a"], capture_output=True, text=True,
                           timeout=8, encoding="utf-8", errors="replace")
        for linha in p.stdout.splitlines():
            m = _MAC_RE.search(linha)
            if not m:
                continue
            mac = m.group(0).replace("-", ":").lower()
            if not _mac_valido(mac):
                continue
            # MACs multicast (01:00:5e…, 33:33…, 01:80:c2…) não são aparelhos
            if mac.startswith(("01:00:5e", "33:33", "01:80:c2", "ff:ff")):
                continue
            ip = linha.strip().split()[0]
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if addr.is_multicast or addr.is_unspecified or addr.is_reserved:
                continue
            tabela[ip] = mac
    except Exception:
        pass
    return tabela


async def _testar_portas(ip: str, portas: list[int], timeout: float,
                         sem: asyncio.Semaphore) -> list[int]:
    abertas: list[int] = []

    async def uma(porta: int):
        async with sem:
            try:
                fut = asyncio.open_connection(ip, porta)
                leitor, escritor = await asyncio.wait_for(fut, timeout=timeout)
                escritor.close()
                try:
                    await escritor.wait_closed()
                except Exception:
                    pass
                abertas.append(porta)
            except Exception:
                return

    await asyncio.gather(*(uma(p) for p in portas))
    return sorted(abertas)


def varrer_hosts(alvos: list[str], portas: list[int], timeout: float = 0.6,
                 concorrencia: int = 64) -> dict[str, list[int]]:
    """Hosts vivos e suas portas abertas (assíncrono, com teto)."""
    if not alvos:
        return {}

    async def principal():
        sem = asyncio.Semaphore(max(1, concorrencia))
        tarefas = {ip: asyncio.create_task(_testar_portas(ip, portas, timeout, sem))
                   for ip in alvos}
        saida = {}
        for ip, t in tarefas.items():
            try:
                abertas = await t
                if abertas:
                    saida[ip] = abertas
            except Exception:
                continue
        return saida

    try:
        return asyncio.run(principal())
    except RuntimeError:
        # já existe loop (ex.: chamado de dentro de um async): roda em thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(principal())).result()
    except Exception:
        return {}


# ----------------------------------------------------------------------- #
# SSDP / UPnP
# ----------------------------------------------------------------------- #
def ssdp(segundos: float = 3.0) -> list[dict]:
    """Descobre dispositivos UPnP via M-SEARCH."""
    achados: dict[str, dict] = {}
    msg = ("M-SEARCH * HTTP/1.1\r\n"
           "HOST: 239.255.255.250:1900\r\n"
           'MAN: "ssdp:discover"\r\n'
           "MX: 2\r\n"
           "ST: ssdp:all\r\n\r\n").encode()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.settimeout(0.5)
    try:
        s.sendto(msg, ("239.255.255.250", 1900))
    except OSError:
        pass

    fim = time.time() + float(segundos)
    while time.time() < fim:
        try:
            dados, (ip, _) = s.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        texto = dados.decode("utf-8", errors="replace")
        cab = {}
        for linha in texto.split("\r\n")[1:]:
            if ":" in linha:
                k, v = linha.split(":", 1)
                cab[k.strip().lower()] = v.strip()
        item = achados.setdefault(ip, {
            "ip": ip, "servicos": [], "nome": "", "fabricante": "",
            "modelo": "", "server": cab.get("server", ""),
            "location": cab.get("location", ""),
        })
        st = cab.get("st", "") or cab.get("nt", "")
        if st and st not in item["servicos"]:
            item["servicos"].append(st)
        loc = cab.get("location", "")
        if loc and not item.get("modelo"):
            info = _ler_upnp(loc)
            if info:
                item["nome"] = info.get("friendlyName") or item["nome"]
                item["fabricante"] = info.get("manufacturer") or item["fabricante"]
                item["modelo"] = info.get("modelName") or item["modelo"]
                tipo = info.get("deviceType", "")
                if tipo:
                    item["servicos"].append(tipo)
    s.close()

    for item in achados.values():
        item["servicos"] = sorted(set(item["servicos"]))
    return list(achados.values())


def _ler_upnp(url: str) -> dict:
    """Lê o XML de descrição do dispositivo UPnP (campos principais)."""
    if not url.lower().startswith("http"):
        return {}
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "YVAKOR/2.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            xml = r.read(65536)
        raiz = ET.fromstring(xml)
        ns = {"u": "urn:schemas-upnp-org:device-1-0"}
        dev = raiz.find(".//u:device", ns) or raiz.find(".//device")
        if dev is None:
            return {}
        def txt(tag):
            el = dev.find(f"u:{tag}", ns) or dev.find(tag)
            return (el.text or "").strip() if el is not None else ""
        return {
            "friendlyName": txt("friendlyName"),
            "manufacturer": txt("manufacturer"),
            "modelName": txt("modelName"),
            "deviceType": txt("deviceType"),
        }
    except Exception:
        return {}


# ----------------------------------------------------------------------- #
# mDNS (Chromecast, AirPlay, ONVIF, impressoras, Shelly…)
# ----------------------------------------------------------------------- #
def mdns(segundos: float = 4.0) -> list[dict]:
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return []

    achados: dict[str, dict] = {}

    class Listener(ServiceListener):
        def add_service(self, zc, tipo, nome):
            self._guardar(zc, tipo, nome)

        def update_service(self, zc, tipo, nome):
            self._guardar(zc, tipo, nome)

        def remove_service(self, zc, tipo, nome):
            pass

        def _guardar(self, zc, tipo, nome):
            try:
                info = zc.get_service_info(tipo, nome, timeout=1500)
            except Exception:
                return
            if not info:
                return
            try:
                enderecos = info.parsed_addresses()
            except Exception:
                enderecos = []
            props = {}
            for k, v in (info.properties or {}).items():
                try:
                    chave = k.decode() if isinstance(k, bytes) else str(k)
                    valor = v.decode() if isinstance(v, bytes) else str(v)
                    props[chave] = valor
                except Exception:
                    continue
            for ip in enderecos:
                if ":" in ip:
                    continue
                item = achados.setdefault(ip, {
                    "ip": ip, "servicos": [], "nome": "", "fabricante": "",
                    "modelo": "", "props": {},
                })
                servico = tipo.rstrip(".")
                if servico not in item["servicos"]:
                    item["servicos"].append(servico)
                rotulo = (props.get("fn") or props.get("md")
                          or nome.split(".")[0].replace("._", " ").replace("_", " "))
                if rotulo and not item["nome"]:
                    item["nome"] = str(rotulo)[:80]
                if props.get("md") and not item["modelo"]:
                    item["modelo"] = str(props["md"])[:80]
                item["props"].update(props)

    zc = None
    try:
        zc = Zeroconf()
        for tipo in SERVICOS_MDNS:
            try:
                ServiceBrowser(zc, tipo, Listener())
            except Exception:
                continue
        time.sleep(max(0.5, float(segundos)))
    except Exception:
        return []
    finally:
        if zc is not None:
            try:
                zc.close()
            except Exception:
                pass
    return list(achados.values())


# ----------------------------------------------------------------------- #
# Classificação
# ----------------------------------------------------------------------- #
def classificar(dev: dict, gateway: str | None = None) -> str:
    servicos = " ".join(dev.get("servicos") or []).lower()
    portas = set(dev.get("portas") or [])
    nome = " ".join(str(dev.get(k) or "") for k in
                    ("nome", "modelo", "fabricante")).lower()

    if any(k in servicos for k in ("onvif", "rtsp")) or 554 in portas \
            or 37777 in portas:
        return "camera"
    if any(k in servicos for k in ("googlecast", "airplay", "raop",
                                   "mediarenderer", "androidtvremote")) \
            or portas & {8001, 8009, 3000, 3001, 7000}:
        return "tv"
    if "ipp" in servicos or "printer" in servicos or 9100 in portas or 631 in portas:
        return "impressora"
    if any(k in servicos for k in ("shelly", "esphomelib", "tasmota")) \
            or portas & {1883, 8883}:
        return "iot"
    if gateway and dev.get("ip") == gateway:
        return "roteador"
    if 62078 in portas or "apple-mobdev" in servicos:
        return "telefone"
    if portas & {445, 3389, 22, 5900} or "smb" in servicos or "ssh" in servicos:
        return "computador"
    if 8008 in portas or 8009 in portas:
        return "tv"
    if any(k in nome for k in ("camera", "câmera", "ipcam", "dvr", "nvr", "hikvision",
                               "dahua", "intelbras", "ezviz", "reolink", "tapo")):
        return "camera"
    if any(k in nome for k in ("tv", "chromecast", "roku", "fire", "bravia",
                               "smart tv", "androidtv", "apple tv")):
        return "tv"
    return "desconhecido"


ROTULOS = {
    "camera": "📷 câmera", "tv": "📺 TV", "telefone": "📱 telefone",
    "roteador": "🌐 roteador", "impressora": "🖨 impressora",
    "iot": "💡 IoT", "computador": "💻 computador",
    "desconhecido": "❔ desconhecido",
}


# ----------------------------------------------------------------------- #
# Orquestração
# ----------------------------------------------------------------------- #
class Descobridor:
    def __init__(self, settings: dict, escopo: EscopoRede,
                 registro: RegistroRede):
        self.cfg = (settings or {}).get("rede", {}) or {}
        self.escopo = escopo
        self.registro = registro

    def _fundir(self, base: dict[str, dict], extra: list[dict]) -> None:
        for e in extra:
            ip = e.get("ip")
            if not ip or not self.escopo.permitido(ip):
                continue
            atual = base.setdefault(ip, {
                "ip": ip, "mac": "", "nome": "", "fabricante": "",
                "modelo": "", "servicos": [], "portas": [],
            })
            for campo in ("nome", "fabricante", "modelo"):
                if e.get(campo) and not atual.get(campo):
                    atual[campo] = e[campo]
            atual["servicos"] = sorted(set(atual.get("servicos", [])
                                           + (e.get("servicos") or [])))

    def escanear(self, profundo: bool = True) -> list[dict]:
        """Varre a rede autorizada e devolve os dispositivos classificados.

        Duas fases: (1) sondagem rápida em poucas portas para achar hosts
        vivos; (2) leitura da ARP (pega até aparelho sem porta aberta) e
        varredura completa de portas apenas nesses hosts. Sem isso, varrer
        254 IPs × 18 portas levaria ~45 s.
        """
        self.escopo.atualizar(forcar=True)
        alvos = self.escopo.alvos()
        portas = self.escopo.portas
        inicio = time.time()

        # SSDP e mDNS são passivos (esperam resposta): rodam em paralelo com a
        # varredura de portas para não somar 7 s ao tempo total.
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=2)
        fut_ssdp = fut_mdns = None
        if profundo:
            fut_ssdp = pool.submit(ssdp, float(self.cfg.get("ssdp_segundos", 3)))
            fut_mdns = pool.submit(mdns, float(self.cfg.get("mdns_segundos", 4)))

        sondagem = [p for p in (80, 443, 554, 8001, 8009, 8080, 62078, 9100,
                                1883, 445, 22) if p in portas] or portas[:6]
        timeout = float(self.cfg.get("probe_timeout_ms", 350)) / 1000
        vivos = varrer_hosts(alvos, sondagem, timeout=timeout,
                             concorrencia=int(self.cfg.get("concurrency", 256)))

        tabela_arp = arp_tabela()
        base: dict[str, dict] = {}
        for ip in set(vivos) | {ip for ip in tabela_arp
                                if self.escopo.permitido(ip)}:
            base[ip] = {"ip": ip, "mac": tabela_arp.get(ip, ""), "nome": "",
                        "fabricante": "", "modelo": "",
                        "servicos": [], "portas": vivos.get(ip, [])}

        # Portas completas só nos hosts que já se mostraram vivos
        if base:
            detalhe = varrer_hosts(list(base), portas,
                                   timeout=float(self.cfg.get("scan_timeout_ms", 650)) / 1000,
                                   concorrencia=min(64, len(base) * 4))
            for ip, abertas in detalhe.items():
                base[ip]["portas"] = sorted(set(base[ip]["portas"]) | set(abertas))

        if profundo:
            if fut_ssdp is not None:
                self._fundir(base, fut_ssdp.result())
            if fut_mdns is not None:
                self._fundir(base, fut_mdns.result())
        pool.shutdown(wait=False)

        dispositivos = []
        for ip, dev in base.items():
            if not dev.get("mac"):
                dev["mac"] = tabela_arp.get(ip, "")
            dns = ""  # DNS reverso custa ~5 s por IP e raramente resolve na LAN
            if _virtual(dns):
                self.registro.remover(ip)
                continue
            if dns and not dev.get("nome"):
                dev["nome"] = dns
            dev["fabricante"] = dev.get("fabricante") or fabricante_por_mac(dev["mac"])
            dev["tipo"] = classificar(dev, self.escopo.gateway)
            if dev["tipo"] == "desconhecido" and _mac_aleatorio(dev.get("mac", "")):
                dev["tipo"] = "telefone"
                if not dev.get("nome"):
                    dev["nome"] = "celular (MAC privado)"
            if dev["tipo"] == "desconhecido" and not dev.get("nome"):
                nb = _netbios(ip)
                if nb:
                    dev["nome"] = nb
            if not dev.get("nome"):
                dev["nome"] = (dev.get("modelo") or dev.get("fabricante")
                               or dev["tipo"])
            dev["visivel"] = True
            salvo = self.registro.upsert(dev)
            salvo["portas"] = salvo.get("portas") or dev["portas"]
            dispositivos.append(salvo)

        dispositivos.sort(key=lambda d: (d.get("tipo") != "roteador", d["ip"]))
        self.registro.marcar_offline([d.get("ip") for d in dispositivos])
        # remove registros antigos que não apareceram e nunca foram nomeados
        vistos = {d.get("ip") for d in dispositivos}
        try:
            for antigo in self.registro.listar():
                if (antigo.get("ip") not in vistos
                        and not antigo.get("portas")
                        and (antigo.get("nome") or "").lower()
                        in ("", "desconhecido")):
                    self.registro.remover(antigo["ip"])
        except Exception:
            pass
        self.ultimo = {
            "total": len(dispositivos),
            "duracao_s": round(time.time() - inicio, 1),
            "alvos": len(alvos),
        }
        return dispositivos
