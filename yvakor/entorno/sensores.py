"""YVAKOR — sensores do entorno.

Cada sensor é barato, roda no seu próprio intervalo e devolve observações:
  ("m", chave, valor)               → métrica numérica
  ("i", tipo, nome, peso, rotulo)   → item visto (app, processo, dispositivo…)

Privacidade: nada de conteúdo. Do app em foco só o nome do executável (nunca
o título da janela); da rede só volumes, contagens e presença de aparelhos
(nunca pacotes, sites ou endereços remotos); do teclado/mouse só o tempo
ocioso, nunca as teclas.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:          # o motor desliga os sensores que dependem dele
    psutil = None

_WIN = sys.platform == "win32"


def _ocioso_s() -> float | None:
    if not _WIN:
        return None
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    agora = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((agora - info.dwTime) & 0xFFFFFFFF) / 1000.0


def _app_em_foco() -> str:
    if not _WIN or psutil is None:
        return ""
    import ctypes
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        return psutil.Process(pid.value).name().lower()
    except (psutil.Error, ValueError):
        return ""


class Sensor:
    nome = "sensor"
    intervalo = 60
    essencial = False        # roda mesmo com CPU alta (custo desprezível)
    requer_psutil = True

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def ler(self) -> list[tuple]:
        raise NotImplementedError


class SensorSistema(Sensor):
    nome, intervalo = "sistema", 60

    def ler(self):
        obs = [("m", "pc.cpu", psutil.cpu_percent(interval=None)),
               ("m", "pc.ram", psutil.virtual_memory().percent)]
        raiz = os.environ.get("SystemDrive", "C:") + "\\" if _WIN else "/"
        try:
            obs.append(("m", "pc.disco_livre_gb",
                        round(psutil.disk_usage(raiz).free / 1024**3, 1)))
        except OSError:
            pass
        try:
            bat = psutil.sensors_battery()
            if bat is not None:
                obs.append(("m", "pc.bateria", bat.percent))
        except (AttributeError, NotImplementedError, OSError):
            pass
        return obs


class SensorTrafego(Sensor):
    nome, intervalo = "trafego", 60

    def __init__(self, cfg):
        super().__init__(cfg)
        self._ant = None

    def ler(self):
        c = psutil.net_io_counters()
        agora = time.time()
        ant, self._ant = self._ant, (agora, c.bytes_recv, c.bytes_sent)
        if ant is None:
            return []
        dt = max(agora - ant[0], 1.0)
        # KB/s; contador zerado (reboot do adaptador) não vira pico negativo
        rx = max(c.bytes_recv - ant[1], 0) / dt / 1024
        tx = max(c.bytes_sent - ant[2], 0) / dt / 1024
        return [("m", "rede.download_kbs", round(rx, 1)),
                ("m", "rede.upload_kbs", round(tx, 1))]


class SensorConexoes(Sensor):
    nome, intervalo = "conexoes", 300

    def ler(self):
        try:
            cons = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError):
            return []
        estab = [c for c in cons if c.status == psutil.CONN_ESTABLISHED]
        escutando = [c for c in cons if c.status == psutil.CONN_LISTEN]
        return [("m", "rede.conexoes", len(estab)),
                ("m", "rede.portas_escuta", len({c.laddr.port for c in escutando
                                                 if c.laddr}))]


class SensorAtividade(Sensor):
    nome, intervalo, essencial = "atividade", 30, True

    def ler(self):
        ocioso = _ocioso_s()
        if ocioso is None:
            return []
        limite = float(self.cfg.get("ocioso_s", 120))
        ativo = ocioso < limite
        obs = [("m", "uso.ativo", 1.0 if ativo else 0.0)]
        if ativo:
            app = _app_em_foco()
            ignorar = {a.lower() for a in self.cfg.get("ignorar_apps", [])}
            if app and app not in ignorar:
                obs.append(("i", "app", app, float(self.intervalo), ""))
        return obs


class SensorProcessos(Sensor):
    nome, intervalo = "processos", 900

    def ler(self):
        nomes = set()
        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower()
            if n:
                nomes.add(n)
        return [("m", "pc.processos", len(nomes))] + [
            ("i", "processo", n, 1.0, "") for n in sorted(nomes)]


class SensorDispositivos(Sensor):
    """Presença dos aparelhos da rede, lida do registro que o monitor de rede
    já mantém (não faz varredura própria)."""
    nome, intervalo, requer_psutil = "dispositivos", 180, False

    def __init__(self, cfg, rede=None):
        super().__init__(cfg)
        self.rede = rede

    def ler(self):
        if self.rede is None:
            return []
        devs = [d for d in self.rede.registro.listar() if d.get("online")]
        obs = [("m", "rede.dispositivos_online", len(devs))]
        for d in devs:
            chave = (d.get("mac") or d.get("ip") or "").lower()
            if chave:
                rotulo = d.get("nome") or d.get("tipo") or d.get("ip") or ""
                obs.append(("i", "dispositivo", chave, 1.0, rotulo))
        return obs


class SensorHistoricoYvakor(Sensor):
    """Lê de forma incremental o histórico de tarefas do próprio YVAKOR
    (data/rastros.jsonl): que ferramentas o usuário usa e em que horário."""
    nome, intervalo, requer_psutil = "historico", 300, False

    def __init__(self, cfg, arquivo: Path):
        super().__init__(cfg)
        self.arquivo = Path(arquivo)
        self.pos = 0

    def ler(self):
        if not self.arquivo.exists():
            return []
        tam = self.arquivo.stat().st_size
        if tam < self.pos:          # arquivo rotacionado
            self.pos = 0
        obs = []
        with self.arquivo.open("rb") as f:
            f.seek(self.pos)
            bloco = f.read(512 * 1024)
        # só consome até a última linha completa
        fim = bloco.rfind(b"\n") + 1
        self.pos += fim
        for linha in bloco[:fim].splitlines():
            try:
                r = json.loads(linha)
                ts = time.mktime(time.strptime(r["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, KeyError, TypeError):
                continue
            obs.append(("m@", "uso.tarefas_falhas", float(r.get("falhas") or 0), ts))
            for p in r.get("passos") or []:
                if p.get("nome"):
                    obs.append(("i@", "ferramenta", p["nome"], 1.0, "", ts))
        return obs


def criar(cfg: dict, rede, raiz: Path) -> list[Sensor]:
    ligados = cfg.get("sensores") or {}
    todos = [SensorSistema(cfg), SensorTrafego(cfg), SensorConexoes(cfg),
             SensorAtividade(cfg), SensorProcessos(cfg),
             SensorDispositivos(cfg, rede),
             SensorHistoricoYvakor(cfg, raiz / "data" / "rastros.jsonl")]
    out = []
    for s in todos:
        if not ligados.get(s.nome, True):
            continue
        if s.requer_psutil and psutil is None:
            continue
        s.intervalo = int((cfg.get("intervalos") or {}).get(s.nome, s.intervalo))
        out.append(s)
    return out
