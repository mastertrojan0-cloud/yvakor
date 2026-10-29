"""YVAKOR — motor de aprendizado adaptativo do entorno.

Instalado numa casa, empresa ou qualquer local, aprende sozinho como aquele
ambiente costuma ser: horários de uso do computador, apps habituais, carga
da máquina, tráfego, aparelhos que entram e saem da rede e as ferramentas que
o usuário mais pede ao YVAKOR. Com o perfil aprendido, aponta o que foge do
normal (anomalias) e o que é novo (novidades).

Harmonia com o resto do sistema:
  - zero chamadas de LLM no ciclo de aprendizado (só aritmética incremental);
  - uma única thread de baixa prioridade; cada sensor tem seu intervalo;
  - orçamento: sensor que ficar caro tem o intervalo dobrado (até 8x) e
    volta ao normal quando barateia; com CPU alta, só os essenciais rodam;
  - o modelo recebe no máximo um bloco curto (~700 caracteres) e só quando
    a mensagem fala do ambiente/rotina; o resto é consultado por ferramenta.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from yvakor.entorno import sensores
from yvakor.entorno.perfil import Perfil

ROOT = Path(__file__).resolve().parent.parent.parent

ROTULOS = {
    "pc.cpu": "CPU (%)", "pc.ram": "memória (%)",
    "pc.disco_livre_gb": "disco livre (GB)", "pc.bateria": "bateria (%)",
    "pc.processos": "processos", "rede.download_kbs": "download (KB/s)",
    "rede.upload_kbs": "upload (KB/s)", "rede.conexoes": "conexões ativas",
    "rede.portas_escuta": "portas em escuta",
    "rede.dispositivos_online": "aparelhos online", "uso.ativo": "uso do PC",
    "uso.tarefas_falhas": "falhas por tarefa",
}
# Métricas que viram anomalia (as demais só alimentam o perfil).
VIGIADAS = {"pc.cpu", "pc.ram", "rede.upload_kbs", "rede.download_kbs",
            "rede.conexoes", "rede.portas_escuta", "rede.dispositivos_online",
            "pc.processos"}
GATILHOS = ("ambiente", "entorno", "rotina", "costum", "habito", "hábito",
            "normal", "anomal", "estranh", "padr", "rede", "dispositiv",
            "aparelho", "computador", " pc", "lento", "travando", "uso ",
            "tráfego", "trafego", "internet", "quem entrou", "novo", "aprendeu")


def _baixar_prioridade_thread() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetThreadPriority(k.GetCurrentThread(), -2)   # THREAD_PRIORITY_LOWEST
    except Exception:
        pass


class MotorEntorno:
    def __init__(self, settings: dict, rede=None, cerebro=None,
                 raiz: Path | None = None):
        self.cfg = (settings or {}).get("entorno", {}) or {}
        self.raiz = Path(raiz or ROOT)
        self.rede = rede
        self.cerebro = cerebro
        self.perfil = Perfil(self.raiz / "data" / "entorno.db")
        self.sensores = sensores.criar(self.cfg, rede, self.raiz)
        for s in self.sensores:
            if hasattr(s, "pos"):       # histórico continua de onde parou
                s.pos = int(self.perfil.meta(f"pos.{s.nome}") or 0)
        self.z_limite = float(self.cfg.get("z_anomalia", 3.5))
        self.cpu_max = float(self.cfg.get("cpu_max", 80))
        self.orcamento_ms = float(self.cfg.get("orcamento_ms", 150))
        self.aquecimento_h = float(self.cfg.get("aquecimento_horas", 24))
        self.notificar = bool(self.cfg.get("notificar", True))
        self._estado = {s.nome: {"proxima": 0.0, "fator": 1, "custo_ms": 0.0,
                                 "execucoes": 0, "pulos": 0, "erro": ""}
                        for s in self.sensores}
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.pausado = False
        self._ultimo_aviso: dict[str, float] = {}
        self._avisos_hora: list[float] = []
        self._insights: dict = {}
        self._insights_em = 0.0
        self._nota_em = 0.0
        inicio = self.perfil.meta("inicio")
        self.inicio = float(inicio) if inicio else float(
            self.perfil.meta("inicio", str(time.time())))

    # ------------------------------------------------------------------ #
    # Ciclo
    # ------------------------------------------------------------------ #
    def iniciar(self) -> dict:
        if self._thread and self._thread.is_alive():
            return self.status()
        self._parar.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="yvakor-entorno")
        self._thread.start()
        return self.status()

    def parar(self) -> None:
        self._parar.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        self.perfil.fechar()

    def _loop(self) -> None:
        _baixar_prioridade_thread()
        if self.perfil.meta("bootstrap") is None:
            try:
                self.importar_historico()
            except Exception:
                pass
        if sensores.psutil is not None:
            sensores.psutil.cpu_percent(interval=None)   # referência p/ leitura não bloqueante
        ultimo_flush = time.time()
        while not self._parar.wait(5):
            if self.pausado:
                continue
            try:
                self.ciclo()
            except Exception:
                pass
            agora = time.time()
            if agora - ultimo_flush >= 60:
                try:
                    self.perfil.flush()
                except Exception:
                    pass
                ultimo_flush = agora
            if agora - self._nota_em >= 1800:
                self._nota_em = agora
                try:
                    self.gravar_nota()
                except Exception:
                    pass

    def _cpu_alta(self) -> bool:
        if sensores.psutil is None:
            return False
        try:
            return sensores.psutil.cpu_percent(interval=None) > self.cpu_max
        except Exception:
            return False

    def ciclo(self, agora: float | None = None) -> int:
        """Roda os sensores vencidos; devolve quantos rodaram."""
        agora = agora or time.time()
        rodados = 0
        cpu_alta = None
        for s in self.sensores:
            st = self._estado[s.nome]
            if agora < st["proxima"]:
                continue
            if not s.essencial:
                if cpu_alta is None:
                    cpu_alta = self._cpu_alta()
                if cpu_alta:
                    st["pulos"] += 1
                    st["proxima"] = agora + s.intervalo
                    continue
            t0 = time.perf_counter()
            try:
                obs = s.ler()
                st["erro"] = ""
            except Exception as exc:
                obs = []
                st["erro"] = str(exc)[:120]
            custo = (time.perf_counter() - t0) * 1000
            st["custo_ms"] = round(custo if not st["execucoes"]
                                   else 0.7 * st["custo_ms"] + 0.3 * custo, 2)
            st["execucoes"] += 1
            if st["custo_ms"] > self.orcamento_ms:
                st["fator"] = min(st["fator"] * 2, 8)
            elif st["custo_ms"] < self.orcamento_ms / 4 and st["fator"] > 1:
                st["fator"] //= 2
            st["proxima"] = agora + s.intervalo * st["fator"]
            self.aprender(obs, s.nome)
            if hasattr(s, "pos"):
                self.perfil.meta(f"pos.{s.nome}", str(s.pos))
            rodados += 1
        return rodados

    # ------------------------------------------------------------------ #
    # Aprendizado
    # ------------------------------------------------------------------ #
    def aquecido(self) -> bool:
        return time.time() - self.inicio >= self.aquecimento_h * 3600

    def aprender(self, obs: list[tuple], origem: str = "") -> None:
        for o in obs:
            tipo = o[0]
            if tipo == "m":
                _, chave, valor = o
                z = self.perfil.observar(chave, float(valor))
                if (z is not None and chave in VIGIADAS and abs(z) >= self.z_limite
                        and self.aquecido()):
                    self._anomalia(chave, float(valor), z)
            elif tipo == "m@":          # histórico: só aprende, não alarma
                _, chave, valor, ts = o
                self.perfil.observar(chave, float(valor), ts)
            elif tipo in ("i", "i@"):
                _, cat, nome, peso, rotulo, *resto = o
                ts = resto[0] if resto else None
                ja_tinha_tipo = self.perfil.tem_itens(cat)
                novo = self.perfil.item(cat, nome, peso, ts, rotulo)
                if novo and tipo == "i" and ja_tinha_tipo and self.aquecido():
                    self._novidade(cat, nome, rotulo)

    def _anomalia(self, chave: str, valor: float, z: float) -> None:
        exp = self.perfil.esperado(chave)
        media = exp[0] if exp else 0.0
        direcao = "acima" if z > 0 else "abaixo"
        detalhe = (f"{ROTULOS.get(chave, chave)} {direcao} do normal para este "
                   f"horário: {valor:g} (costuma {media:.1f}; z={z:.1f})")
        self.perfil.evento("anomalia", chave, valor, media, detalhe)
        self._avisar(chave, detalhe, "sistema")

    def _novidade(self, cat: str, nome: str, rotulo: str) -> None:
        detalhe = f"{cat} novo: {rotulo or nome}"
        self.perfil.evento("novidade", f"{cat}:{nome}", 1, 0, detalhe)
        # aparelho novo na rede já é avisado pelo monitor de rede
        if cat in ("processo",):
            self._avisar(f"{cat}:{nome}", f"Processo nunca visto neste PC: {nome}",
                         "sistema")

    def _avisar(self, chave: str, texto: str, categoria: str) -> None:
        if not self.notificar:
            return
        agora = time.time()
        if agora - self._ultimo_aviso.get(chave, 0) < 6 * 3600:
            return
        self._avisos_hora = [t for t in self._avisos_hora if agora - t < 3600]
        if len(self._avisos_hora) >= int(self.cfg.get("max_avisos_hora", 3)):
            return
        self._ultimo_aviso[chave] = agora
        self._avisos_hora.append(agora)
        try:
            from yvakor.notificacoes import emitir
            emitir(texto, categoria, 1, falar=False, detalhe="entorno")
        except Exception:
            pass

    def importar_historico(self) -> dict:
        """Primeira subida: aprende com o que já está gravado (entradas e
        saídas de aparelhos e histórico de tarefas), sem esperar dias."""
        n_rede = 0
        arq = self.raiz / "data" / "rede_monitor.jsonl"
        if arq.exists():
            for linha in arq.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]:
                try:
                    ev = json.loads(linha)
                    ts = datetime.fromisoformat(ev["ts"]).timestamp()
                except (ValueError, KeyError, TypeError):
                    continue
                if ev.get("tipo") == "entrou" and ev.get("ip"):
                    dev = (self.rede.registro.obter(ev["ip"]) or {}) if self.rede else {}
                    chave = (dev.get("mac") or ev["ip"]).lower()
                    self.perfil.item("dispositivo", chave, 1.0, ts,
                                     ev.get("nome") or ev.get("tipo_dispositivo") or "")
                    n_rede += 1
        n_hist = 0
        for s in self.sensores:
            if isinstance(s, sensores.SensorHistoricoYvakor):
                obs = s.ler()
                self.aprender(obs, s.nome)
                self.perfil.meta(f"pos.{s.nome}", str(s.pos))
                n_hist = len(obs)
        self.perfil.meta("bootstrap", datetime.now().isoformat(timespec="seconds"))
        self.perfil.flush()
        return {"eventos_rede": n_rede, "historico": n_hist}

    # ------------------------------------------------------------------ #
    # O que foi aprendido
    # ------------------------------------------------------------------ #
    @staticmethod
    def _faixas_horas(horas: list[int]) -> str:
        if not horas:
            return ""
        partes, ini, ant = [], horas[0], horas[0]
        for h in horas[1:] + [None]:
            if h is not None and h == ant + 1:
                ant = h
                continue
            partes.append(f"{ini}h–{ant + 1}h" if ant != ini else f"{ini}h")
            if h is not None:
                ini = ant = h
        return ", ".join(partes)

    def insights(self, forcar: bool = False) -> dict:
        if not forcar and time.time() - self._insights_em < 600 and self._insights:
            return self._insights
        p = self.perfil
        out: dict = {}
        ativo = [c for c in p.curva("uso.ativo") if c["n"] >= 4]
        horas = [c["hora"] for c in ativo if c["media"] >= 0.5]
        if horas:
            out["ritmo"] = f"PC costuma estar em uso: {self._faixas_horas(horas)}"
        apps = p.itens("app", 5)
        if apps:
            out["apps"] = ", ".join(f"{a['nome'].removesuffix('.exe')} "
                                    f"(~{round(a['contagem'] / 3600, 1)} h)" for a in apps)
        devs = p.itens("dispositivo", 6)
        if devs:
            linhas = []
            for d in devs:
                hs = [h for h, n in enumerate(d["horas"]) if n >= max(2, max(d["horas"]) * 0.3)]
                faixa = self._faixas_horas(hs)
                linhas.append(f"{d['rotulo'] or d['nome']}"
                              + (f" ({faixa})" if faixa else ""))
            out["dispositivos"] = "; ".join(linhas)
        ferr = p.itens("ferramenta", 5)
        if ferr:
            out["ferramentas"] = ", ".join(f["nome"] for f in ferr)
        agora = []
        for chave in ("pc.cpu", "pc.ram", "rede.download_kbs", "rede.dispositivos_online"):
            exp = p.esperado(chave)
            if exp:
                agora.append(f"{ROTULOS[chave]} ~{exp[0]:.0f}")
        if agora:
            out["normal_agora"] = "Normal para este horário: " + ", ".join(agora)
        ev = p.eventos(24, limite=5)
        if ev:
            out["ultimas_24h"] = [f"{e['em']} {e['detalhe']}" for e in ev]
        out["aprendendo_ha"] = f"{(time.time() - self.inicio) / 86400:.1f} dia(s)"
        self._insights, self._insights_em = out, time.time()
        return out

    def bloco_prompt(self, mensagem: str, limite: int = 700) -> str:
        """Bloco curto p/ o system prompt; vazio se a mensagem não for sobre
        o ambiente (não gasta token à toa)."""
        msg = f" {(mensagem or '').lower()} "
        if not any(g in msg for g in GATILHOS):
            return ""
        ins = self.insights()
        linhas = [ins[k] for k in ("ritmo", "normal_agora") if ins.get(k)]
        if ins.get("apps"):
            linhas.append("Apps habituais: " + ins["apps"])
        if ins.get("dispositivos"):
            linhas.append("Aparelhos habituais: " + ins["dispositivos"])
        for e in (ins.get("ultimas_24h") or [])[:3]:
            linhas.append("Recente: " + e)
        if not linhas:
            return ""
        txt = ("## ENTORNO APRENDIDO (perfil local; detalhes em entorno_resumo)\n"
               + "\n".join(f"- {l}" for l in linhas))
        return txt[:limite]

    def resumo_texto(self) -> str:
        ins = self.insights(forcar=True)
        rot = {"ritmo": "Ritmo", "apps": "Apps mais usados",
               "dispositivos": "Aparelhos habituais (horário)",
               "ferramentas": "Ferramentas mais pedidas", "normal_agora": "Agora",
               "aprendendo_ha": "Aprendendo há"}
        linhas = [f"- **{rot[k]}:** {ins[k]}" for k in rot if ins.get(k)]
        if ins.get("ultimas_24h"):
            linhas.append("- **Últimas 24 h:**")
            linhas += [f"  - {e}" for e in ins["ultimas_24h"]]
        return "\n".join(linhas) or "Ainda aprendendo — poucos dados até agora."

    def gravar_nota(self) -> str | None:
        if self.cerebro is None:
            return None
        from yvakor.ambiente import _nota, _vault
        vault = _vault(self.cerebro, getattr(self.cerebro, "cfg", {}) or {})
        corpo = ("# Ambiente — Rotina aprendida\n\n" + self.resumo_texto()
                 + "\n\nGerada pelo motor de entorno (estatística local, sem IA). "
                 "Dados brutos não são guardados; só médias e contagens.")
        arq = _nota(vault, "Ambiente", "rotina", corpo,
                    ["ambiente", "rotina", "entorno"], "Ambiente — Rotina aprendida")
        return str(arq)

    def status(self) -> dict:
        return {
            "ativo": bool(self._thread and self._thread.is_alive()),
            "pausado": self.pausado,
            "aquecido": self.aquecido(),
            "metricas": len(self.perfil.chaves()),
            "sensores": {s.nome: {"intervalo_s": s.intervalo * self._estado[s.nome]["fator"],
                                  "custo_ms": self._estado[s.nome]["custo_ms"],
                                  "execucoes": self._estado[s.nome]["execucoes"],
                                  "pulos_cpu": self._estado[s.nome]["pulos"],
                                  "erro": self._estado[s.nome]["erro"]}
                         for s in self.sensores},
        }


def register_entorno_tools(registry, motor: MotorEntorno) -> list[str]:
    def entorno_resumo() -> dict:
        return {"ok": True, "resumo": motor.resumo_texto()}

    def entorno_perfil(metrica: str = "") -> dict:
        if not metrica:
            return {"ok": True, "metricas": {c: ROTULOS.get(c, c)
                                             for c in motor.perfil.chaves()}}
        return {"ok": True, "metrica": metrica, "por_hora": motor.perfil.curva(metrica)}

    def entorno_eventos(horas: float = 24, tipo: str = "") -> dict:
        return {"ok": True, "eventos": motor.perfil.eventos(float(horas), tipo)}

    def entorno_status() -> dict:
        return {"ok": True, **motor.status()}

    def entorno_pausar(pausar: bool = True) -> dict:
        motor.pausado = bool(pausar) if not isinstance(pausar, str) \
            else pausar.lower() not in ("false", "0", "nao", "não")
        return {"ok": True, "pausado": motor.pausado}

    registry.register("entorno_resumo", entorno_resumo,
                      "O que o YVAKOR aprendeu do ambiente: horários de uso, apps "
                      "habituais, aparelhos da rede e anomalias recentes.", {})
    registry.register("entorno_perfil", entorno_perfil,
                      "Valor normal de uma métrica por hora do dia (vazio = lista "
                      "as métricas: pc.cpu, rede.download_kbs, uso.ativo…).",
                      {"metrica": "str"})
    registry.register("entorno_eventos", entorno_eventos,
                      "Anomalias e novidades do ambiente nas últimas N horas "
                      "(tipo: anomalia | novidade | vazio).",
                      {"horas": "float", "tipo": "str"})
    registry.register("entorno_status", entorno_status,
                      "Estado do motor de entorno: sensores, custo e intervalos.", {})
    registry.register("entorno_pausar", entorno_pausar,
                      "Pausa (true) ou retoma (false) o aprendizado do ambiente.",
                      {"pausar": "bool"})
    return ["entorno_resumo", "entorno_perfil", "entorno_eventos",
            "entorno_status", "entorno_pausar"]
