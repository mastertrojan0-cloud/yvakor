"""YVAKOR — guardião de rede e vírus (NÃO invasivo).

Observa, compara com o "normal" desta máquina e avisa. Nunca mata processo,
bloqueia rede, apaga arquivo nem lê conteúdo (pacotes, documentos, teclas).
A única ação é pedir ao Windows Defender uma verificação — quando o usuário
pede (guardiao_escanear, com confirmação).

Verificações (cada uma no seu intervalo, numa thread de baixa prioridade):
  defender      proteção ligada, assinaturas em dia, ameaças detectadas
  inicializacao programa novo nas chaves Run/RunOnce e pastas Inicializar
  portas        porta nova em escuta no PC (e qual programa abriu)
  conexoes      conexão para portas típicas de malware (4444, IRC, Tor…)
  processos     programa rodando de Temp/Downloads/Public sem assinatura
  gateway       MAC do roteador mudou (sinal de ARP spoofing)
  hosts         arquivo hosts alterado (sequestro de sites)

Primeira rodada = linha de base (o estado atual vira o normal, sem alerta).
Estado em data/guardiao.json; eventos em data/guardiao_eventos.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from yvakor import proc
from yvakor.config import ROOT

_log = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None

PORTAS_MALWARE = {4444: "Metasploit/shell reverso", 1337: "backdoor comum",
                  31337: "Back Orifice", 6667: "IRC (botnet)", 6697: "IRC (botnet)",
                  9001: "Tor", 9050: "Tor", 9150: "Tor", 5555: "ADB remoto",
                  23: "Telnet"}
PORTAS_RISCO = {3389: "Área de Trabalho Remota (RDP)", 5900: "VNC", 23: "Telnet",
                21: "FTP", 445: "Compartilhamento de arquivos (SMB)",
                7070: "AnyDesk", 5938: "TeamViewer", 22: "SSH"}
PASTAS_SUSPEITAS = re.compile(
    r"\\(appdata\\local\\temp|temp|downloads|users\\public|\$recycle\.bin)\\", re.I)
INTERVALOS = {"defender": 1800, "inicializacao": 300, "portas": 300,
              "conexoes": 120, "processos": 120, "gateway": 300, "hosts": 600}


def _ps_json(comando: str, timeout: float = 60):
    r = proc.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                  "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + comando],
                 capture_output=True, timeout=timeout)
    saida = r.stdout.decode("utf-8", "replace").strip()
    return json.loads(saida) if saida else None


class Guardiao:
    def __init__(self, settings: dict, rede=None, raiz: Path | None = None):
        self.cfg = (settings or {}).get("guardiao", {}) or {}
        self.raiz = Path(raiz or ROOT)
        self.rede = rede
        self.arq_estado = self.raiz / "data" / "guardiao.json"
        self.arq_eventos = self.raiz / "data" / "guardiao_eventos.jsonl"
        self.notificar = bool(self.cfg.get("notificar", True))
        self.intervalos = {**INTERVALOS, **(self.cfg.get("intervalos") or {})}
        self.estado = self._ler_estado()
        self._proxima = {k: 0.0 for k in self.intervalos}
        self._pids_vistos: set[int] = set()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Estado (linha de base + alertas já dados)
    # ------------------------------------------------------------------ #
    def _ler_estado(self) -> dict:
        try:
            return json.loads(self.arq_estado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"base": {}, "alertados": {}, "confiaveis": []}

    def _gravar_estado(self) -> None:
        try:
            self.arq_estado.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.arq_estado.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.arq_estado)
        except OSError:
            _log.debug("exceção ignorada", exc_info=True)

    def _novos(self, verificacao: str, atuais: dict[str, str]) -> dict[str, str]:
        """Compara com a linha de base; na 1ª vez só registra (sem alerta)."""
        base = self.estado.setdefault("base", {})
        if verificacao not in base:
            base[verificacao] = atuais
            return {}
        conhecidos = base[verificacao]
        novos = {k: v for k, v in atuais.items()
                 if k not in conhecidos and k not in self.estado.get("confiaveis", [])}
        return novos

    # ------------------------------------------------------------------ #
    # Alertas
    # ------------------------------------------------------------------ #
    def _alerta(self, nivel: str, chave: str, titulo: str, detalhe: str = "",
                sugestao: str = "") -> dict | None:
        with self._lock:
            if chave in self.estado.setdefault("alertados", {}):
                return None
            ev = {"ts": datetime.now().isoformat(timespec="seconds"), "nivel": nivel,
                  "chave": chave, "titulo": titulo, "detalhe": detalhe[:400],
                  "sugestao": sugestao}
            self.estado["alertados"][chave] = ev["ts"]
        try:
            self.arq_eventos.parent.mkdir(parents=True, exist_ok=True)
            with self.arq_eventos.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except OSError:
            _log.debug("exceção ignorada", exc_info=True)
        if self.notificar and nivel in ("alto", "medio"):
            try:
                from yvakor.notificacoes import emitir
                emitir(f"🛡 {titulo}", "seguranca", 2 if nivel == "alto" else 1,
                       falar=nivel == "alto", detalhe=detalhe[:200])
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        return ev

    # ------------------------------------------------------------------ #
    # Verificações
    # ------------------------------------------------------------------ #
    def defender(self) -> list[dict]:
        if sys.platform != "win32":
            return []
        out = []
        st = _ps_json("Get-MpComputerStatus | Select-Object AntivirusEnabled, "
                      "RealTimeProtectionEnabled, AntivirusSignatureAge, QuickScanAge, "
                      "IsTamperProtected | ConvertTo-Json -Compress", 45) or {}
        self.estado["defender"] = {**st, "verificado": datetime.now().isoformat(
            timespec="seconds")}
        if st and not st.get("AntivirusEnabled"):
            out.append(self._alerta("alto", "defender:desligado", "Windows Defender desligado",
                                    sugestao="Ative em Segurança do Windows."))
        if st and not st.get("RealTimeProtectionEnabled"):
            out.append(self._alerta("alto", "defender:tempo_real",
                                    "Proteção em tempo real desligada",
                                    sugestao="Religue em Segurança do Windows → Vírus e ameaças."))
        idade = st.get("AntivirusSignatureAge") or 0
        if 3 < idade < 10000:
            out.append(self._alerta("medio", f"defender:assinaturas:{idade // 7}",
                                    f"Assinaturas do antivírus com {idade} dias",
                                    sugestao="Rode o Windows Update."))
        ameacas = _ps_json("Get-MpThreatDetection | Select-Object ThreatID, "
                           "@{n='Quando';e={$_.InitialDetectionTime.ToString('s')}}, "
                           "ActionSuccess, @{n='Recursos';e={$_.Resources -join '; '}} | "
                           "ConvertTo-Json -Compress", 45) or []
        for a in (ameacas if isinstance(ameacas, list) else [ameacas]):
            out.append(self._alerta(
                "alto", f"ameaca:{a.get('ThreatID')}:{a.get('Quando')}",
                "O Defender detectou uma ameaça",
                f"{a.get('Recursos', '')[:200]} — tratada: {a.get('ActionSuccess')}",
                "Veja em Segurança do Windows → Histórico de proteção."))
        return [x for x in out if x]

    def inicializacao(self) -> list[dict]:
        if sys.platform != "win32":
            return []
        import winreg
        atuais: dict[str, str] = {}
        for raiz, nome in ((winreg.HKEY_CURRENT_USER, "HKCU"),
                           (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
            for sub in ("Run", "RunOnce"):
                try:
                    k = winreg.OpenKey(raiz, rf"Software\Microsoft\Windows\CurrentVersion\{sub}")
                except OSError:
                    continue
                i = 0
                while True:
                    try:
                        n, v, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    atuais[f"{nome}\\{sub}\\{n}"] = str(v)[:300]
                    i += 1
        for pasta in (Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup",
                      Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\StartUp"):
            try:
                for f in pasta.iterdir():
                    if f.name.lower() != "desktop.ini":
                        atuais[f"Inicializar\\{f.name}"] = str(f)
            except OSError:
                pass
        out = []
        for chave, cmd in self._novos("inicializacao", atuais).items():
            nivel = "alto" if PASTAS_SUSPEITAS.search(cmd) else "medio"
            out.append(self._alerta(
                nivel, f"inicio:{chave}", f"Novo programa iniciando com o Windows: "
                f"{chave.split(chr(92))[-1]}", cmd,
                "Se não foi você que instalou, desative em Gerenciador de Tarefas → "
                "Inicializar (ou peça guardiao_confiar se for conhecido)."))
        return [x for x in out if x]

    def portas(self) -> list[dict]:
        if psutil is None:
            return []
        atuais: dict[str, str] = {}
        for c in psutil.net_connections("inet"):
            if c.status == psutil.CONN_LISTEN and c.laddr:
                try:
                    nome = psutil.Process(c.pid).name() if c.pid else "?"
                except psutil.Error:
                    nome = "?"
                atuais[f"{c.laddr.port}:{nome.lower()}"] = nome
        self.estado["portas_abertas"] = sorted(atuais)
        # programas que já abriam porta: trocar de porta (Tailscale, Ollama
        # sorteiam a cada boot) não é novidade — só porta de risco é
        ja_escutavam = {k.split(":", 1)[1] for k in
                        (self.estado.get("base") or {}).get("portas", {})}
        out = []
        for chave, nome in self._novos("portas", atuais).items():
            porta = int(chave.split(":")[0])
            risco = PORTAS_RISCO.get(porta) or PORTAS_MALWARE.get(porta)
            if nome.lower() in ja_escutavam and not risco:
                continue
            out.append(self._alerta(
                "alto" if porta in PORTAS_MALWARE else "medio",
                f"porta:{chave}", f"Porta nova aberta no PC: {porta} ({nome})",
                risco or "", "Se não reconhece o programa, verifique-o ou rode "
                             "guardiao_escanear."))
        return [x for x in out if x]

    def conexoes(self) -> list[dict]:
        if psutil is None:
            return []
        out = []
        for c in psutil.net_connections("inet"):
            if c.status != psutil.CONN_ESTABLISHED or not c.raddr:
                continue
            motivo = PORTAS_MALWARE.get(c.raddr.port)
            if not motivo:
                continue
            try:
                nome = psutil.Process(c.pid).name() if c.pid else "?"
            except psutil.Error:
                nome = "?"
            out.append(self._alerta(
                "alto", f"conexao:{nome}:{c.raddr.port}",
                f"{nome} conectado a uma porta típica de {motivo}",
                f"destino {c.raddr.ip}:{c.raddr.port}",
                "Se não reconhece, rode guardiao_escanear (verificação do Defender)."))
        return [x for x in out if x]

    def processos(self) -> list[dict]:
        if psutil is None:
            return []
        suspeitos = []
        primeira = not self._pids_vistos     # 1ª rodada = linha de base
        for p in psutil.process_iter(["pid", "name", "exe"]):
            if p.info["pid"] in self._pids_vistos:
                continue
            self._pids_vistos.add(p.info["pid"])
            if primeira:
                continue
            exe = p.info.get("exe") or ""
            if exe and PASTAS_SUSPEITAS.search(exe):
                suspeitos.append(exe)
        out = []
        for exe in sorted(set(suspeitos))[:10]:
            assinatura = self._assinatura(exe)
            if assinatura == "Valid":
                continue
            out.append(self._alerta(
                "alto" if assinatura in ("NotSigned", "HashMismatch") else "medio",
                f"processo:{exe.lower()}", f"Programa sem assinatura rodando de "
                f"pasta temporária: {Path(exe).name}", f"{exe} (assinatura: {assinatura})",
                "Se não foi você que abriu, rode guardiao_escanear."))
        return [x for x in out if x]

    def _assinatura(self, exe: str) -> str:
        cache = self.estado.setdefault("assinaturas", {})
        if exe in cache:
            return cache[exe]
        try:
            caminho = exe.replace("'", "''")
            r = _ps_json(f"(Get-AuthenticodeSignature -LiteralPath '{caminho}')"
                         ".Status.ToString() | ConvertTo-Json", 20)
            status = str(r or "Unknown")
        except Exception:
            status = "Unknown"
        cache[exe] = status
        return status

    def gateway(self) -> list[dict]:
        if sys.platform != "win32":
            return []
        dados = _ps_json("$gw = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
                         "Sort-Object RouteMetric | Select-Object -First 1).NextHop; "
                         "$n = Get-NetNeighbor -IPAddress $gw -ErrorAction SilentlyContinue | "
                         "Select-Object -First 1; @{ip=$gw; mac=$n.LinkLayerAddress} | "
                         "ConvertTo-Json -Compress", 20) or {}
        ip, mac = dados.get("ip"), (dados.get("mac") or "").lower()
        if not ip or not mac or mac in ("00-00-00-00-00-00", "ff-ff-ff-ff-ff-ff"):
            return []
        anterior = self.estado.setdefault("base", {}).setdefault("gateway", {})
        if ip not in anterior:
            anterior[ip] = mac
            return []
        if anterior[ip] != mac:
            ev = self._alerta(
                "alto", f"gateway:{ip}:{mac}", "O roteador mudou de identidade (MAC)",
                f"{ip}: era {anterior[ip]}, agora {mac}",
                "Pode ser troca de roteador — ou alguém se passando por ele (ARP "
                "spoofing). Se não trocou o roteador, desconfie da rede.")
            return [ev] if ev else []
        return []

    def hosts(self) -> list[dict]:
        arq = Path(os.environ.get("WINDIR", r"C:\Windows")) / r"System32\drivers\etc\hosts"
        try:
            texto = arq.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        linhas = sorted({l.strip() for l in texto.splitlines()
                         if l.strip() and not l.strip().startswith("#")})
        h = hashlib.sha256("\n".join(linhas).encode()).hexdigest()[:16]
        base = self.estado.setdefault("base", {})
        if "hosts" not in base:
            base["hosts"] = {"hash": h, "linhas": linhas}
            return []
        if base["hosts"]["hash"] == h:
            return []
        novas = [l for l in linhas if l not in base["hosts"]["linhas"]]
        ev = self._alerta("alto", f"hosts:{h}", "O arquivo hosts foi alterado",
                          "; ".join(novas)[:300] or "linhas removidas",
                          "Linhas novas no hosts podem desviar sites (banco, e-mail) "
                          "para servidores falsos. Confira se foi você.")
        return [ev] if ev else []

    # ------------------------------------------------------------------ #
    # Ciclo
    # ------------------------------------------------------------------ #
    def verificar(self, quais: list[str] | None = None, forcar: bool = True) -> list[dict]:
        alertas, agora = [], time.time()
        for nome in quais or list(self.intervalos):
            if not forcar and agora < self._proxima.get(nome, 0):
                continue
            self._proxima[nome] = agora + self.intervalos[nome]
            try:
                alertas += getattr(self, nome)()
            except Exception:
                _log.debug("verificação %s falhou", nome, exc_info=True)
        self.estado["ultima_verificacao"] = datetime.now().isoformat(timespec="seconds")
        self._gravar_estado()
        return alertas

    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="yvakor-guardiao")
        self._thread.start()

    def _loop(self) -> None:
        try:
            from yvakor.entorno.motor import _baixar_prioridade_thread
            _baixar_prioridade_thread()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        if self._parar.wait(20):             # deixa o boot terminar primeiro
            return
        while not self._parar.is_set():
            self.verificar(forcar=False)
            if self._parar.wait(30):
                break

    def parar(self) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._gravar_estado()

    # ------------------------------------------------------------------ #
    # Relatório e ações pedidas pelo usuário
    # ------------------------------------------------------------------ #
    def eventos(self, horas: float = 168) -> list[dict]:
        if not self.arq_eventos.exists():
            return []
        desde = datetime.fromtimestamp(time.time() - horas * 3600).isoformat()
        out = []
        for linha in self.arq_eventos.read_text(encoding="utf-8").splitlines()[-500:]:
            try:
                ev = json.loads(linha)
            except ValueError:
                continue
            if ev.get("ts", "") >= desde:
                out.append(ev)
        return out[::-1]

    def postura(self) -> dict:
        """Pontos de atenção permanentes (não são alertas: é o retrato atual)."""
        d = self.estado.get("defender") or {}
        abertas = {int(p.split(":")[0]): p.split(":", 1)[1]
                   for p in self.estado.get("portas_abertas", [])}
        riscos = [f"porta {p} aberta — {PORTAS_RISCO[p]} ({abertas[p]})"
                  for p in sorted(abertas) if p in PORTAS_RISCO]
        return {
            "antivirus": ("ativo" if d.get("AntivirusEnabled") else "DESLIGADO") if d else "não verificado",
            "tempo_real": d.get("RealTimeProtectionEnabled"),
            "assinaturas_dias": d.get("AntivirusSignatureAge"),
            "ultima_verificacao_rapida_dias": d.get("QuickScanAge"),
            "pontos_de_atencao": riscos,
            "programas_na_inicializacao": len((self.estado.get("base") or {}).get("inicializacao", {})),
        }

    def escanear(self, tipo: str = "rapida") -> dict:
        """Pede ao Windows Defender uma verificação (roda em segundo plano)."""
        if sys.platform != "win32":
            return {"ok": False, "erro": "só no Windows"}
        exe = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"
        modo = "2" if str(tipo).lower().startswith("comp") else "1"
        if not exe.exists():
            return {"ok": False, "erro": "MpCmdRun.exe não encontrado"}
        proc.popen([str(exe), "-Scan", "-ScanType", modo])

        def _depois():
            time.sleep(60 if modo == "1" else 600)
            for _ in range(120):
                st = _ps_json("(Get-MpComputerStatus).QuickScanAge", 30) if modo == "1" else None
                if modo == "2" or st == 0:
                    break
                time.sleep(30)
            novos = self.defender()
            try:
                from yvakor.notificacoes import emitir
                emitir("🛡 Verificação do Defender concluída" + (
                    f": {len(novos)} ameaça(s) — veja o relatório" if novos else
                    ": nenhuma ameaça nova"), "seguranca", 2 if novos else 1)
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        threading.Thread(target=_depois, daemon=True, name="yvakor-defender-scan").start()
        return {"ok": True, "iniciada": "completa" if modo == "2" else "rápida",
                "obs": "o Windows Defender está verificando em segundo plano; aviso "
                       "quando terminar (rápida: 2–10 min; completa: até horas)"}

    def confiar(self, chave: str) -> dict:
        """Marca um item avisado como conhecido (não avisa mais)."""
        conf = self.estado.setdefault("confiaveis", [])
        ref = chave.split(":", 1)[1] if ":" in chave else chave
        if ref not in conf:
            conf.append(ref)
        self._gravar_estado()
        return {"ok": True, "confiavel": ref}


def register_guardiao_tools(registry, g: Guardiao) -> list[str]:
    def guardiao_status() -> dict:
        return {"ok": True, **g.postura(), "alertas_7_dias": g.eventos(168)[:15],
                "ultima_verificacao": g.estado.get("ultima_verificacao")}

    def guardiao_verificar() -> dict:
        novos = g.verificar(forcar=True)
        return {"ok": True, "alertas_novos": novos, **g.postura()}

    def guardiao_eventos(horas: float = 168) -> dict:
        return {"ok": True, "eventos": g.eventos(float(horas))}

    registry.register("guardiao_status", guardiao_status,
                      "Segurança do PC e da rede (só leitura): antivírus, proteção em "
                      "tempo real, portas de risco abertas e alertas recentes do guardião.",
                      {})
    registry.register("guardiao_verificar", guardiao_verificar,
                      "Roda agora todas as verificações do guardião (Defender, "
                      "inicialização, portas, conexões suspeitas, processos em Temp, "
                      "roteador/ARP, arquivo hosts).", {})
    registry.register("guardiao_escanear", lambda tipo="rapida": g.escanear(tipo),
                      "Pede ao Windows Defender uma verificação de vírus (tipo: rapida | "
                      "completa), em segundo plano; avisa ao terminar.", {"tipo": "str?"})
    registry.register("guardiao_eventos", guardiao_eventos,
                      "Alertas do guardião nas últimas N horas.", {"horas": "float?"})
    registry.register("guardiao_confiar", lambda chave: g.confiar(chave),
                      "Marca um item avisado pelo guardião como conhecido/confiável "
                      "(use a 'chave' do alerta).", {"chave": "str"})
    return ["guardiao_status", "guardiao_verificar", "guardiao_escanear",
            "guardiao_eventos", "guardiao_confiar"]
