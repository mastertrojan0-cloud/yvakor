"""
YVAKOR — Assistente de voz (modo mãos livres)

Ciclo: ouvir → transcrever → processar (o mesmo cérebro do chat) → falar.

  python -m yvakor.voz              # conversa contínua
  python -m yvakor.voz --uma        # uma pergunta e sai
  python -m yvakor.voz --sem-ativacao  # não exige a palavra-chave

A palavra de ativação é comparada de forma tolerante, porque o reconhecedor
costuma grafar "YVAKOR" de formas criativas ("eva coruja", "ivacor"...).
"""
from __future__ import annotations

import re
import sys
import time

from yvakor.voz.stt_multi import STTMulti
from yvakor.voz.tts import TTS
import logging

_log = logging.getLogger(__name__)

ALIASES_PADRAO = ["yvakor", "yvacor", "evacor", "eva coruja",
                  "iva cor", "ivacor", "yva kor", "eva cor", "yvakour"]


def _normalizar(txt: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (txt or "").lower()).strip()


def contem_ativacao(texto: str, palavra: str, aliases: list[str] | None = None) -> bool:
    if not palavra:
        return True
    primeiros = " ".join(_normalizar(texto).split()[:6])
    candidatos = {_normalizar(palavra)}
    candidatos.update(_normalizar(a) for a in (aliases or ALIASES_PADRAO))
    for c in candidatos:
        if c and (primeiros == c or primeiros.startswith(c + " ")
                  or f" {c} " in f" {primeiros} "):
            return True
    return False


def limpar_para_fala(texto: str, limite: int = 700) -> str:
    """Tira markdown/código para a fala não virar sopa de símbolos."""
    t = re.sub(r"```.*?```", " (bloco de código omitido) ", texto or "",
               flags=re.DOTALL)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^[#>\-\*\+]+\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\*\*|__|~~", "", t)
    t = re.sub(r"\s+\n", "\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    if len(t) <= limite:
        return t
    corte = t[:limite]
    ponto = max(corte.rfind("."), corte.rfind("!"), corte.rfind("?"))
    return (corte[:ponto + 1] if ponto > limite * 0.5 else corte).strip()


class AssistenteVoz:
    def __init__(self, orchestrator, settings: dict):
        self.orch = orchestrator
        self.settings = settings
        cfg = (settings or {}).get("voz", {}) or {}
        self.cfg = cfg
        self.palavra = str(cfg.get("palavra_ativacao") or "")
        self.aliases = cfg.get("aliases_ativacao") or ALIASES_PADRAO
        self.stt = STTMulti(settings)
        self.tts = TTS(settings)
        self.ultima_fala = ""
        self.ultima_resposta = ""
        from yvakor.voz.sessao import SessaoVoz
        self.sessao = SessaoVoz(orchestrator, self, settings)
        self.sessao.aquecer()

    # ------------------------------------------------------------------ #
    def ouvir(self, segundos: float | None = None) -> dict:
        return self.stt.ouvir(segundos)

    def falar(self, texto: str, tocar: bool = True) -> dict:
        return self.tts.falar(limpar_para_fala(texto), tocar=tocar)

    # ------------------------------------------------------------------ #
    def processar(self, texto: str, idioma: str | None = None) -> dict:
        """Manda o texto para o cérebro e fala a resposta (escopo de sessão)."""
        return self.sessao.processar(texto, idioma=idioma, falar=True,
                                     exigir_ativacao=False)

    # ------------------------------------------------------------------ #
    def conversar(self, exigir_ativacao: bool = True,
                  max_turnos: int | None = None) -> None:
        status = self.stt.status()
        print("\n  YVAKOR — modo voz")
        print(f"  microfone: {'sim' if status['microfone'] else 'NÃO detectado'}"
              f" | modelo: {status['modelo']}"
              f"{'' if status['modelo_baixado'] else ' (será baixado)'}")
        if not status["microfone"]:
            print("  Sem microfone nesta máquina: use voz_transcrever(arquivo) "
                  "ou o microfone da interface web.\n")
            return
        if exigir_ativacao and self.palavra:
            print(f"  Diga \"{self.palavra}\" para acordar. Ctrl+C para sair.\n")
        else:
            print("  Fale normalmente. Ctrl+C para sair.\n")

        turnos = 0
        while True:
            try:
                print("  · ouvindo…", end="", flush=True)
                r = self.ouvir()
                print("\r" + " " * 20 + "\r", end="")
                texto = (r.get("texto") or "").strip()
                if not texto:
                    continue
                if not exigir_ativacao or contem_ativacao(
                        texto, self.palavra, self.aliases):
                    print(f"  você > {texto}")
                    res = self.processar(texto)
                    print(f"  yvakor > {res.get('resposta', res.get('erro'))}\n")
                    turnos += 1
                    if max_turnos and turnos >= max_turnos:
                        return
                else:
                    print(f"  (ignorado — sem a palavra de ativação: {texto[:60]})")
            except KeyboardInterrupt:
                print("\n  até logo.")
                return
            except Exception as exc:
                print(f"\n  [erro] {exc}")
                time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
    from yvakor.orchestrator import Orchestrator
    from yvakor.config import load_settings

    settings = load_settings()
    orch = Orchestrator()
    voz = AssistenteVoz(orch, settings)
    uma = "--uma" in argv
    try:
        if uma:
            r = voz.ouvir()
            texto = (r.get("texto") or "").strip()
            if not texto:
                print(json_dumps(r))
                return 2
            print(json_dumps(voz.processar(texto)))
            return 0
        voz.conversar(exigir_ativacao="--sem-ativacao" not in argv,
                      max_turnos=1 if uma else None)
        return 0
    finally:
        try:
            orch.shutdown()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
