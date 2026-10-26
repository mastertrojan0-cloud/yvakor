"""YVAKOR — supervisor anticrash com watchdog de saúde.

- reinicia o servidor se ele cair;
- reinicia também se ele ficar vivo mas **sem responder** ao /api/health;
- backoff progressivo, limite de reinícios por janela e log estruturado.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "data" / "logs"


def _registrar(evento: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "supervisor.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    try:
        from yvakor.notificacoes import emitir
        emitir(evento.get("mensagem", "Servidor reiniciado"), "sistema", 2,
               falar=False)
    except Exception:
        pass


def _saudavel(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _matar(proc: subprocess.Popen) -> None:
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _log_rotativo() -> object:
    LOGS.mkdir(parents=True, exist_ok=True)
    arq = LOGS / "servidor.log"
    try:
        if arq.exists() and arq.stat().st_size > 10 * 1024 * 1024:
            arq.replace(LOGS / "servidor.old.log")
    except OSError:
        pass
    return arq.open("a", encoding="utf-8", buffering=1)


def main() -> int:
    import msvcrt
    from yvakor.config import ROOT
    try:
        _trava = open(ROOT / "data" / "supervisor.lock", "a+")
        _trava.seek(0)
        msvcrt.locking(_trava.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("  [supervisor] já existe outro supervisor ativo; saindo.")
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--comando", default="")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max-restarts", type=int, default=10)
    ap.add_argument("--janela", type=float, default=600)
    ap.add_argument("--health-url", default="http://127.0.0.1:7777/api/ping")
    ap.add_argument("--probe-interval", type=float, default=20)
    ap.add_argument("--probe-falhas", type=int, default=3)
    ap.add_argument("--grace", type=float, default=30)
    args = ap.parse_args()
    cmd = ([c.strip('"') for c in shlex.split(args.comando, posix=False)]
           if args.comando else [sys.executable, "-m", "yvakor.server"])
    print(f"  [supervisor] comando: {' '.join(cmd)}")
    reinicios: list[float] = []
    while True:
        saida = _log_rotativo()
        t0 = time.time()
        proc = None
        try:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP") else 0
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=saida,
                                    stderr=subprocess.STDOUT,
                                    creationflags=flags)
            falhas, ultimo_probe, motivo = 0, 0.0, ""
            while proc.poll() is None:
                time.sleep(1)
                if args.once or not args.health_url:
                    continue
                agora = time.time()
                if agora - t0 < args.grace:
                    continue
                if agora - ultimo_probe < args.probe_interval:
                    continue
                ultimo_probe = agora
                if _saudavel(args.health_url):
                    falhas = 0
                else:
                    falhas += 1
                    print(f"  [supervisor] health falhou ({falhas}/{args.probe_falhas})")
                    if falhas >= args.probe_falhas:
                        motivo = "sem resposta ao /api/health"
                        _matar(proc)
                        break
            codigo = proc.wait()
        except KeyboardInterrupt:
            if proc is not None:
                _matar(proc)
            print("\n  [supervisor] encerrado.")
            return 0
        except Exception as exc:
            codigo, motivo = -1, f"falha ao iniciar: {exc}"
            print(f"  [supervisor] {motivo}")
        finally:
            try:
                saida.close()
            except Exception:
                pass
        duracao = round(time.time() - t0, 1)
        if codigo == 0 and args.once:
            return 0
        agora = time.time()
        reinicios = [t for t in reinicios if agora - t < args.janela]
        reinicios.append(agora)
        evento = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "codigo": codigo,
                  "duracao_s": duracao, "motivo": motivo,
                  "restarts_janela": len(reinicios),
                  "mensagem": (f"Servidor encerrou (código {codigo}) após "
                               f"{duracao}s" + (f" — {motivo}" if motivo else "")
                               + "; reiniciando.")}
        _registrar(evento)
        print(f"  [supervisor] {evento['mensagem']}")
        if args.once or len(reinicios) > args.max_restarts:
            print("  [supervisor] limite de reinícios atingido; parando.")
            return codigo if codigo else 1
        espera = 2 if duracao > 60 else min(60, 2 ** len(reinicios))
        time.sleep(espera)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
