"""
YVAKOR — Gerenciador de navegadores (Edge + Chrome)

Um "motor" por navegador, cada um com perfil persistente próprio:

    edge   → data/browser_profiles/edge
    chrome → data/browser_profiles/chrome

Dois modos por motor:
  • launch — o Playwright abre o navegador real (Edge/Chrome) com perfil próprio
  • cdp    — anexa a um navegador JÁ ABERTO com --remote-debugging-port
             (útil para usar uma janela que o usuário abriu e deixou logada)

Sessões são criadas sob demanda: só abre o navegador quem realmente usa.
"""
from __future__ import annotations

import threading

from yvakor.browser.session import BrowserSession
import logging

_log = logging.getLogger(__name__)

MOTORES_PADRAO = {
    "edge": {"channel": "msedge", "profile_dir": "data/browser_profiles/edge",
             "mode": "launch", "cdp_url": "http://127.0.0.1:9223"},
    "chrome": {"channel": "chrome", "profile_dir": "data/browser_profiles/chrome",
               "mode": "launch", "cdp_url": "http://127.0.0.1:9222"},
}


class Navegadores:
    def __init__(self, settings: dict):
        cfg = (settings or {}).get("browser", {}) or {}
        self.cfg = cfg
        self.padrao = str(cfg.get("motor_padrao") or "edge").lower()
        configurados = cfg.get("engines") or MOTORES_PADRAO
        self.engines: dict[str, dict] = {}
        for nome, dados in configurados.items():
            base = dict(MOTORES_PADRAO.get(nome, {}))
            base.update(dados or {})
            base.setdefault("channel", "msedge" if nome == "edge" else nome)
            base.setdefault("profile_dir", f"data/browser_profiles/{nome}")
            base.setdefault("mode", "launch")
            self.engines[nome] = base
        if self.padrao not in self.engines:
            self.padrao = next(iter(self.engines))
        self._sessoes: dict[str, BrowserSession] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    def nomes(self) -> list[str]:
        return list(self.engines)

    def motor(self, nome: str | None = None) -> str:
        alvo = str(nome or "").strip().lower()
        if alvo in self.engines:
            return alvo
        return self.padrao

    def sessao(self, nome: str | None = None) -> BrowserSession:
        alvo = self.motor(nome)
        with self._lock:
            sess = self._sessoes.get(alvo)
            if sess is None:
                cfg = self.engines[alvo]
                sess = BrowserSession(
                    {"browser": {**self.cfg, **cfg, "headless": self.cfg.get(
                        "headless", True)}},
                    engine=cfg.get("channel", alvo),
                    mode=cfg.get("mode", "launch"),
                    profile_dir=cfg.get("profile_dir"),
                    cdp_url=cfg.get("cdp_url"),
                    rotulo=alvo,
                )
                self._sessoes[alvo] = sess
            return sess

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        motores = {}
        for nome, cfg in self.engines.items():
            sess = self._sessoes.get(nome)
            if sess is not None:
                st = sess.status()
                try:
                    st["grupos"] = sess.grupos().get("grupos", {})
                except Exception:
                    st["grupos"] = {}
            else:
                st = {"aberto": False, "url": "", "titulo": "",
                      "engine": cfg.get("channel", nome),
                      "visivel": not self.cfg.get("headless", True),
                      "perfil": cfg.get("profile_dir", ""),
                      "ultimo_erro": "", "ultima_acao": ""}
            st.update({"motor": nome, "modo": cfg.get("mode", "launch"),
                       "cdp_url": cfg.get("cdp_url", ""),
                       "criado": sess is not None})
            motores[nome] = st
        return {"padrao": self.padrao, "motores": motores,
                "disponivel": True}

    def resumo(self) -> str:
        linhas = []
        for nome, st in self.status()["motores"].items():
            estado = "aberto" if st.get("aberto") else "fechado"
            extra = f" · {st.get('url')}" if st.get("url") else ""
            linhas.append(f"{nome}: {estado}{extra}")
        return " | ".join(linhas)

    # ------------------------------------------------------------------ #
    def conectar_cdp(self, nome: str, url: str | None = None) -> dict:
        """Anexa o motor a um navegador já aberto com remote debugging."""
        alvo = self.motor(nome)
        sess = self.sessao(alvo)
        return sess.conectar_cdp(url or self.engines[alvo].get("cdp_url", ""))

    def fechar(self, nome: str | None = None) -> dict:
        if nome:
            sess = self._sessoes.get(self.motor(nome))
            return sess.close() if sess else {"ok": True, "fechado": True}
        for sess in list(self._sessoes.values()):
            try:
                sess.close()
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        return {"ok": True, "fechado": True}

    def shutdown(self) -> None:
        for sess in list(self._sessoes.values()):
            try:
                sess.shutdown()
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
