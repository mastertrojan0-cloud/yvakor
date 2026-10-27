"""
YVAKOR — Auto-manutenção / Auto-atualização

Duas frentes, rodando automaticamente em segundo plano (intervalo configurável
em settings.yaml → maintenance):

  1. CONHECIMENTO: consolida a memória semântica (remove duplicatas/ruído) e
     promove skills usadas com sucesso N vezes de 'nova' → 'estavel'.
  2. CÓDIGO: verifica (via git) se há versão nova do próprio software. Só faz
     'git pull' se auto_update_code=true E for um repositório git com remoto.
     NUNCA baixa/executa código de fontes não-git.

Endpoints/curinga: o servidor inicia o agendador; [manutencao] roda na hora.
"""
from __future__ import annotations
import re
import threading
import subprocess
from yvakor import proc as _ywproc
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent


class Maintenance:
    def __init__(self, orchestrator):
        self.o = orchestrator
        self.cfg = orchestrator.settings.get("maintenance", {})
        self.last = {"quando": None, "conhecimento": None, "codigo": None}
        self._timer: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ #
    # 1. Conhecimento
    # ------------------------------------------------------------------ #
    def consolidate_knowledge(self) -> dict:
        res = {"skills_estabilizadas": [], "memoria": {}}
        # 1a. promove skills estáveis
        limiar = self.o.settings["skills"].get("stable_threshold", 3)
        for f in self.o.skills.all_skills():
            try:
                txt = f.read_text(encoding="utf-8")
            except Exception:
                continue
            if "status: nova" not in txt:
                continue
            usos = self.o.episodic.skill_success_count(f.stem)
            if usos >= limiar:
                novo = txt.replace("status: nova", "status: estavel", 1)
                f.write_text(novo, encoding="utf-8")
                res["skills_estabilizadas"].append(f.stem)
        # 1b. consolida memória semântica (dedup/limpeza) — usa a IA principal
        if self.cfg.get("consolidate_memory", True):
            try:
                # consolidate_memory() SUBSTITUI todos os fatos pelo que o modelo
                # devolver. Com a nuvem fora só sobra o 3B local, que pode
                # devolver uma lista empobrecida e apagar memória de verdade:
                # adia para quando houver o modelo principal.
                if self.o.router.sem_externos():
                    res["memoria"] = {"adiado": "provedor externo indisponível"}
                else:
                    res["memoria"] = self.o.absorber.consolidate_memory()
            except Exception as e:
                res["memoria"] = {"erro": str(e)}
        self.last["conhecimento"] = res
        return res

    # ------------------------------------------------------------------ #
    # 2. Código (via git, opcional e seguro)
    # ------------------------------------------------------------------ #
    def _git(self, *args, timeout=60) -> tuple[int, str]:
        try:
            p = _ywproc.run(["git", *args], cwd=str(ROOT),
                               capture_output=True, text=True, timeout=timeout)
            return p.returncode, (p.stdout + p.stderr).strip()
        except FileNotFoundError:
            return 127, "git não está instalado"
        except subprocess.TimeoutExpired:
            return 124, "timeout no git"

    def check_code_update(self) -> dict:
        if not (ROOT / ".git").exists():
            res = {"ok": False, "estado": "sem_git",
                   "motivo": "Não é um repositório git. Para habilitar a auto-"
                             "atualização: git init, git remote add origin <url>, "
                             "git push -u origin main."}
            self.last["codigo"] = res
            return res

        remote = self.cfg.get("git_remote", "origin")
        branch = self.cfg.get("git_branch", "main")
        rc, _ = self._git("fetch", remote, branch)
        if rc != 0:
            res = {"ok": False, "estado": "erro_fetch", "motivo": _}
            self.last["codigo"] = res
            return res

        _, local = self._git("rev-parse", "HEAD")
        _, remoto = self._git("rev-parse", f"{remote}/{branch}")
        if local == remoto:
            res = {"ok": True, "estado": "atualizado", "motivo": "já na última versão"}
            self.last["codigo"] = res
            return res

        # há versão nova
        if not self.cfg.get("auto_update_code", False):
            res = {"ok": True, "estado": "disponivel",
                   "motivo": "Nova versão disponível. Ative auto_update_code:true "
                             "ou rode 'git pull' manualmente.",
                   "local": local[:8], "remoto": remoto[:8]}
            self.last["codigo"] = res
            return res

        rc, out = self._git("pull", "--ff-only", remote, branch, timeout=120)
        res = {"ok": rc == 0,
               "estado": "atualizado_agora" if rc == 0 else "falha_pull",
               "motivo": ("Código atualizado. Reinicie o YVAKOR para aplicar."
                          if rc == 0 else out)}
        self.last["codigo"] = res
        return res

    # ------------------------------------------------------------------ #
    # Ciclo completo + agendador
    # ------------------------------------------------------------------ #
    def run_cycle(self) -> dict:
        self.last["quando"] = datetime.now().isoformat(timespec="seconds")
        conhecimento = self.consolidate_knowledge()
        banco = self.maintain_databases()
        codigo = self.check_code_update()
        try:
            self.o.episodic.log("manutencao", "ciclo automático",
                                f"skills_estaveis={len(conhecimento['skills_estabilizadas'])}; "
                                f"podados={banco.get('podados', {}).get('removidos', 0)}; "
                                f"codigo={codigo.get('estado')}")
        except Exception:
            pass
        return {"quando": self.last["quando"], "conhecimento": conhecimento,
                "banco": banco, "codigo": codigo}

    # ------------------------------------------------------------------ #
    # 1b. Banco de dados (poda + índices + VACUUM incremental + cérebro)
    # ------------------------------------------------------------------ #
    def maintain_databases(self) -> dict:
        res: dict = {}
        try:
            res["podados"] = self.o.episodic.podar(
                dias=int(self.cfg.get("reter_operacionais_dias", 30)),
                max_operacionais=int(self.cfg.get("max_operacionais", 20000)))
        except Exception as e:
            res["podados"] = {"erro": str(e)}
        for nome, obj, metodo in (
            ("episodico", self.o.episodic, "otimizar"),
            ("semantico", self.o.semantic, "otimizar"),
            ("skills", self.o.skills, "otimizar"),
        ):
            try:
                res[nome] = getattr(obj, metodo)()
            except Exception as e:
                res[nome] = {"erro": str(e)}
        if getattr(self.o, "cerebro", None) is not None:
            try:
                res["cerebro"] = self.o.cerebro.sincronizar()["status"]
            except Exception as e:
                res["cerebro"] = {"erro": str(e)}
        try:                      # WAL, backup, logs e capturas (yvakor/banco.py)
            from yvakor import banco
            res["guardiao"] = banco.ciclo_periodico()
        except Exception as e:
            res["guardiao"] = {"erro": str(e)}
        res["tamanhos_mb"] = {
            "episodico": res.get("episodico", {}).get("mb", 0),
            "semantico": res.get("semantico", {}).get("mb", 0),
            "cerebro": res.get("cerebro", {}).get("mb", 0),
        }
        self.last["banco"] = res
        return res

    def start_background(self):
        if not self.cfg.get("enabled", False) or self._timer:
            return
        horas = max(1, int(self.cfg.get("interval_hours", 12)))

        def _loop():
            # primeira passada após 1 min (deixa o servidor subir tranquilo)
            if self._stop.wait(60):
                return
            while not self._stop.is_set():
                try:
                    self.run_cycle()
                except Exception:
                    pass
                self._stop.wait(horas * 3600)

        self._timer = threading.Thread(target=_loop, daemon=True,
                                       name="yvakor-maintenance")
        self._timer.start()

    def stop(self):
        self._stop.set()
