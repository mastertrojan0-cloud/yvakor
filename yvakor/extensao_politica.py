"""YVAKOR — política de permissões da extensão do navegador.

Inspirada no Claude no Chrome:
  * por SITE: o agente só age num domínio depois de o usuário permitir (uma
    vez; fica salvo e dá para revogar). No modo "autonomo" isso é dispensado.
  * ações SENSÍVEIS (comprar, pagar, enviar, apagar, senha, cartão…) pedem
    confirmação sempre, nos dois modos.
  * sites de BANCO/PAGAMENTO pedem permissão sempre, mesmo no modo autônomo.

Fonte da verdade no núcleo (data/permissoes_sites.json). A decisão fina — qual
elemento, qual host exato no momento da ação — é da extensão, que recebe esta
política em cada comando; este módulo só guarda, valida e responde.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.parse import urlparse

from yvakor import seguro
from yvakor.config import ROOT

ARQUIVO = ROOT / "data" / "permissoes_sites.json"
PREFS = ROOT / "data" / "preferencias.json"

MODOS = {
    "perguntar": {
        "rotulo": "Pedir permissão por site",
        "descricao": "Pergunta na primeira vez em cada site. Ações sensíveis "
                     "(comprar, enviar, apagar…) sempre pedem confirmação."},
    "autonomo": {
        "rotulo": "Agir sem pedir permissão",
        "descricao": "Não pergunta por site. Ações sensíveis e sites de banco/"
                     "pagamento ainda pedem confirmação."},
}
MODO_PADRAO = "perguntar"

# Bancos, carteiras, cripto e governo: sempre pedem permissão.
HOST_SENSIVEL = re.compile(
    r"(bank|banco|bradesco|itau|santander|caixa\.gov|nubank|inter\.co|c6bank|"
    r"sicredi|sicoob|bancodobrasil|paypal|mercadopago|pagseguro|pagbank|picpay|"
    r"stripe|wise\.com|binance|coinbase|mercadobitcoin|gov\.br|receita\.fazenda)",
    re.I)

# Buscadores: navegar até eles nunca exige permissão (é o ponto de partida).
BUSCADORES_LIVRES = {"google.com", "duckduckgo.com", "bing.com", "youtube.com"}


def host_de(url_ou_host: str) -> str:
    """Normaliza URL ou host: minúsculas, sem 'www.', sem porta."""
    s = str(url_ou_host or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        s = "//" + s
    try:
        h = urlparse(s).hostname or ""
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _combina(host: str, regra: str) -> bool:
    """Regra 'exemplo.com' vale para exemplo.com e para qualquer subdomínio."""
    return bool(host) and bool(regra) and (host == regra or host.endswith("." + regra))


class PoliticaSites:
    def __init__(self, arquivo: Path | None = None, prefs: Path | None = None):
        self.arquivo = Path(arquivo or ARQUIVO)
        self.prefs = Path(prefs or PREFS)
        self._lock = threading.Lock()
        self._bloqueados_sessao: set[str] = set()   # "negar" vale até reiniciar
        self._dados = self._ler()

    # ------------------------------------------------------------------ #
    def _ler(self) -> dict:
        try:
            d = seguro.ler_json(self.arquivo, None)
            if not isinstance(d, dict):
                raise ValueError("sem dados")
            return {"permitidos": sorted({host_de(h) for h in d.get("permitidos", []) if host_de(h)}),
                    "bloqueados": sorted({host_de(h) for h in d.get("bloqueados", []) if host_de(h)})}
        except Exception:
            return {"permitidos": [], "bloqueados": []}

    def _gravar(self) -> None:
        seguro.gravar_json(self.arquivo, self._dados)

    def _pref(self, chave, padrao=None):
        d = seguro.ler_json(self.prefs, {})
        return d.get(chave, padrao) if isinstance(d, dict) else padrao

    def _gravar_pref(self, chave, valor) -> None:
        d = seguro.ler_json(self.prefs, {})
        if not isinstance(d, dict):
            d = {}
        d[chave] = valor
        seguro.gravar_json(self.prefs, d)

    # ------------------------------------------------------------------ #
    @property
    def modo(self) -> str:
        m = str(self._pref("extensao_modo", MODO_PADRAO)).lower()
        return m if m in MODOS else MODO_PADRAO

    def definir_modo(self, modo: str) -> None:
        modo = str(modo or "").lower()
        if modo not in MODOS:
            raise ValueError(f"modo inválido: {modo!r} (use: {', '.join(MODOS)})")
        with self._lock:
            self._gravar_pref("extensao_modo", modo)

    def permitido(self, host: str) -> bool:
        h = host_de(host)
        return any(_combina(h, r) for r in self._dados["permitidos"])

    def bloqueado(self, host: str) -> bool:
        h = host_de(host)
        return (any(_combina(h, r) for r in self._dados["bloqueados"])
                or any(_combina(h, r) for r in self._bloqueados_sessao))

    def sensivel(self, host: str) -> bool:
        return bool(HOST_SENSIVEL.search(host_de(host)))

    def permitir(self, host: str) -> str:
        h = host_de(host)
        if not h:
            raise ValueError("site inválido")
        with self._lock:
            if h not in self._dados["permitidos"]:
                self._dados["permitidos"] = sorted(self._dados["permitidos"] + [h])
            self._dados["bloqueados"] = [b for b in self._dados["bloqueados"] if b != h]
            self._bloqueados_sessao.discard(h)
            self._gravar()
        return h

    def bloquear(self, host: str, so_nesta_sessao: bool = False) -> str:
        h = host_de(host)
        if not h:
            raise ValueError("site inválido")
        with self._lock:
            if so_nesta_sessao:
                self._bloqueados_sessao.add(h)
            else:
                self._dados["permitidos"] = [p for p in self._dados["permitidos"] if p != h]
                if h not in self._dados["bloqueados"]:
                    self._dados["bloqueados"] = sorted(self._dados["bloqueados"] + [h])
                self._gravar()
        return h

    def remover(self, host: str) -> bool:
        h = host_de(host)
        with self._lock:
            antes = len(self._dados["permitidos"]) + len(self._dados["bloqueados"])
            self._dados["permitidos"] = [p for p in self._dados["permitidos"] if p != h]
            self._dados["bloqueados"] = [p for p in self._dados["bloqueados"] if p != h]
            self._bloqueados_sessao.discard(h)
            mudou = antes != len(self._dados["permitidos"]) + len(self._dados["bloqueados"])
            if mudou:
                self._gravar()
        return mudou

    # ------------------------------------------------------------------ #
    def para_extensao(self) -> dict:
        """O que a extensão precisa saber a cada comando de ação."""
        return {"modo": self.modo,
                "permitidos": list(self._dados["permitidos"]),
                "bloqueados": list(self._dados["bloqueados"] + sorted(self._bloqueados_sessao))}

    def info(self) -> dict:
        return {"modo": self.modo,
                "modos": [{"id": k, **v} for k, v in MODOS.items()],
                "permitidos": list(self._dados["permitidos"]),
                "bloqueados": list(self._dados["bloqueados"])}

    def precisa_perguntar_navegacao(self, url: str) -> str | None:
        """Navegar para `url` exige perguntar? Devolve o host a perguntar, ou None."""
        h = host_de(url)
        if not h or h in BUSCADORES_LIVRES or any(_combina(h, b) for b in BUSCADORES_LIVRES):
            return None
        if self.permitido(h):
            return None
        if self.modo == "perguntar" or self.sensivel(h):
            return h
        return None
