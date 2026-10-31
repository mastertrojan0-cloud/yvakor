"""
YVAKOR — Escopo de rede (autorização)

O agente só alcança o que estiver DENTRO do escopo autorizado:

  • as sub-redes diretamente conectadas a esta máquina (padrão), ou
  • o que o usuário listar em `rede.allowed_subnets` / `rede.allowed_hosts`.

Qualquer outro destino (internet, rede de terceiros) é negado, a menos que o
usuário ligue explicitamente `rede.allow_public: true`. Isso evita que uma
tarefa mal formulada vire varredura da internet ou de redes alheias.
"""
from __future__ import annotations

import ipaddress
import json
import socket
from yvakor import proc as _ywproc
import time
import logging

_log = logging.getLogger(__name__)

LOOPBACK = ipaddress.ip_network("127.0.0.0/8")

# Interfaces que não representam a rede física da casa/escritório
_VIRTUAIS = ("vethernet", "hyper-v", "vmware", "virtualbox", "loopback",
             "docker", "wsl", "bluetooth", "tap", "tun", "zerotier",
             "hamachi", "radmin", "wireguard")


def _ps_json(comando: str, timeout: int = 8):
    """Roda PowerShell e devolve JSON (usado só no Windows)."""
    try:
        p = _ywproc.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace")
        if p.returncode == 0 and p.stdout.strip():
            return json.loads(p.stdout)
    except Exception:
        _log.debug("exceção ignorada", exc_info=True)
    return None


class EscopoRede:
    def __init__(self, settings: dict):
        cfg = (settings or {}).get("rede", {}) or {}
        self.cfg = cfg
        self.habilitado = bool(cfg.get("habilitado", True))
        self.allow_public = bool(cfg.get("allow_public", False))
        self.max_hosts = int(cfg.get("max_hosts", 254))
        self.timeout_ms = int(cfg.get("scan_timeout_ms", 650))
        self.concorrencia = int(cfg.get("concurrency", 64))
        self.portas = [int(p) for p in cfg.get("portas", [])] or [80, 443, 554]

        self.subredes: list[ipaddress.IPv4Network] = []
        self.hosts: set[str] = set()
        self.gateway: str | None = None
        self.interfaces: list[dict] = []
        self._carregado_em = 0.0
        self.atualizar(forcar=True)

    # ------------------------------------------------------------------ #
    # Detecção
    # ------------------------------------------------------------------ #
    def atualizar(self, forcar: bool = False) -> None:
        if not forcar and (time.time() - self._carregado_em) < 60:
            return
        self._carregado_em = time.time()
        self.hosts = set()
        for h in (self.cfg.get("allowed_hosts") or []):
            try:
                self.hosts.add(str(ipaddress.ip_address(str(h).split(":")[0])))
            except ValueError:
                try:
                    self.hosts.add(socket.gethostbyname(str(h)))
                except OSError:
                    pass

        configuradas = []
        for s in (self.cfg.get("allowed_subnets") or []):
            try:
                configuradas.append(ipaddress.ip_network(str(s), strict=False))
            except ValueError:
                continue
        self.subredes = configuradas or self._detectar_subredes()
        if self.gateway is None:
            self.gateway = self._detectar_gateway()

    def _detectar_subredes(self) -> list[ipaddress.IPv4Network]:
        pares: list[tuple[ipaddress.IPv4Network, str]] = []

        # 1) psutil (se estiver instalado) — melhor fonte (IP + máscara + nome)
        try:
            import psutil  # type: ignore
            for nome, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if a.family == socket.AF_INET and a.netmask:
                        try:
                            pares.append((ipaddress.ip_network(
                                f"{a.address}/{a.netmask}", strict=False), nome))
                        except ValueError:
                            pass
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

        # 2) Windows: Get-NetIPAddress com prefixo e nome da interface
        if not pares:
            dados = _ps_json(
                "Get-NetIPAddress -AddressFamily IPv4 | "
                "Where-Object {$_.IPAddress -notlike '127.*'} | "
                "Select-Object IPAddress,PrefixLength,InterfaceAlias | "
                "ConvertTo-Json -Compress")
            if isinstance(dados, dict):
                dados = [dados]
            for item in (dados or []):
                try:
                    pares.append((ipaddress.ip_network(
                        f"{item['IPAddress']}/{item['PrefixLength']}", strict=False),
                        str(item.get("InterfaceAlias") or "")))
                except Exception:
                    continue

        # 3) Fallback: IPs da máquina com /24
        if not pares:
            try:
                for info in socket.getaddrinfo(socket.gethostname(), None,
                                               socket.AF_INET):
                    ip = info[4][0]
                    if not ip.startswith("127."):
                        pares.append((ipaddress.ip_network(f"{ip}/24",
                                                           strict=False), ""))
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)

        # Descarta redes de adaptadores virtuais; se sobrar nada, usa tudo.
        fisicas = [(r, n) for r, n in pares
                   if not any(v in (n or "").lower() for v in _VIRTUAIS)]
        if fisicas:
            pares = fisicas

        gw = self._detectar_gateway()
        self.gateway = gw
        # A rede que contém o gateway é a principal; depois as mais específicas.
        pares.sort(key=lambda p: (not (gw and ipaddress.ip_address(gw) in p[0]),
                                  -p[0].prefixlen))
        self.interfaces = [{"rede": str(r), "interface": n} for r, n in pares]
        redes = [r for r, _ in pares]
        if not redes:
            redes.append(ipaddress.ip_network("127.0.0.1/32"))
        return redes

    def _detectar_gateway(self) -> str | None:
        dados = _ps_json(
            "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
            "Sort-Object RouteMetric | Select-Object -First 1 "
            "-ExpandProperty NextHop | ConvertTo-Json -Compress")
        if isinstance(dados, str) and dados.strip():
            return dados.strip()
        return None

    # ------------------------------------------------------------------ #
    # Autorização
    # ------------------------------------------------------------------ #
    def permitido(self, alvo: str) -> bool:
        """True se o alvo está dentro do escopo autorizado."""
        if not self.habilitado:
            return False
        try:
            ip = ipaddress.ip_address(str(alvo).strip().split(":")[0])
        except ValueError:
            try:
                ip = ipaddress.ip_address(socket.gethostbyname(str(alvo)))
            except OSError:
                return False

        if ip.is_loopback:
            return True
        if str(ip) in self.hosts:
            return True
        for rede in self.subredes:
            if ip in rede and not rede.is_loopback:
                return True
        if self.allow_public:
            return True
        return False

    def exigir(self, alvo: str) -> str:
        """Valida e devolve o IP; levanta PermissionError se fora do escopo."""
        try:
            ip = str(ipaddress.ip_address(str(alvo).strip()))
        except ValueError:
            try:
                ip = socket.gethostbyname(str(alvo))
            except OSError as exc:
                raise ValueError(f"alvo inválido: {alvo}") from exc
        if not self.permitido(ip):
            raise PermissionError(
                f"{ip} está fora do escopo autorizado. O YVAKOR só alcança a "
                "rede local desta máquina (ou o que estiver em "
                "rede.allowed_subnets / allowed_hosts)."
                + ("" if self.allow_public else
                   " Para liberar outro destino, ajuste config/settings.yaml."))
        return ip

    # ------------------------------------------------------------------ #
    # Alvos de varredura
    # ------------------------------------------------------------------ #
    def alvos(self, limite: int | None = None) -> list[str]:
        """IPs a varrer: hosts explícitos + hosts das sub-redes locais."""
        limite = min(int(limite or self.max_hosts), 4096)
        vistos: list[str] = []
        for h in sorted(self.hosts):
            if h not in vistos:
                vistos.append(h)
        for rede in self.subredes:
            if rede.is_loopback:
                continue
            # /31 e /32 não têm "rede utilizável" no sentido usual
            if rede.num_addresses <= 2:
                for ip in rede:
                    s = str(ip)
                    if s not in vistos:
                        vistos.append(s)
                continue
            for ip in rede.hosts():
                s = str(ip)
                if s not in vistos:
                    vistos.append(s)
                if len(vistos) >= limite:
                    return vistos[:limite]
        return vistos[:limite]

    def descrever(self) -> str:
        redes = ", ".join(str(r) for r in self.subredes) or "(nenhuma)"
        extra = ", ".join(sorted(self.hosts)) or "(nenhum)"
        return (f"escopo: {redes} | hosts extras: {extra} | "
                f"internet: {'liberada' if self.allow_public else 'bloqueada'} | "
                f"gateway: {self.gateway or '?'}")

    def resumo(self) -> dict:
        return {
            "habilitado": self.habilitado,
            "subredes": [str(r) for r in self.subredes],
            "hosts_extras": sorted(self.hosts),
            "gateway": self.gateway,
            "allow_public": self.allow_public,
            "max_hosts": self.max_hosts,
            "portas": self.portas,
            "descricao": self.descrever(),
        }
