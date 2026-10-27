"""YVAKOR — análise de mercado (cripto e ações): dados reais, indicadores, sentimento e gráficos.

Tudo determinístico e sem IA: funciona mesmo com o modelo local fraco, e o resultado
completo (texto + tabela + gráficos) é mostrado no chat.

Fontes (APIs públicas, sem chave): Binance → Coinbase → CoinGecko (cripto), Yahoo (ações),
StockTwits (sentimento da comunidade) e Alternative.me (Índice Medo & Ganância).
Cada fonte que falhar é registrada em `avisos`; as outras seguem.

Não é recomendação de investimento: os "cenários" são níveis de referência por ATR.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PASTA_GRAFICOS = ROOT / "data" / "graficos"
UA = "Mozilla/5.0 (YVAKOR analise-mercado)"

CRIPTOS = {
    "btc": "BTC", "bitcoin": "BTC", "eth": "ETH", "ethereum": "ETH", "eter": "ETH",
    "sol": "SOL", "solana": "SOL", "bnb": "BNB", "xrp": "XRP", "ripple": "XRP",
    "ada": "ADA", "cardano": "ADA", "doge": "DOGE", "dogecoin": "DOGE", "ltc": "LTC",
    "litecoin": "LTC", "avax": "AVAX", "link": "LINK", "dot": "DOT", "matic": "POL",
    "pol": "POL", "zec": "ZEC", "zcash": "ZEC", "trx": "TRX", "ton": "TON", "shib": "SHIB",
    "pepe": "PEPE", "sui": "SUI", "near": "NEAR", "atom": "ATOM", "uni": "UNI",
}
INTERVALOS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h",
              "4h": "4h", "1d": "1d", "1w": "1w"}
_SEG = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
        "4h": 14400, "1d": 86400, "1w": 604800}
_COINBASE_GRAN = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
_YAHOO = {"1m": ("1m", "5d"), "5m": ("5m", "1mo"), "15m": ("15m", "1mo"), "30m": ("30m", "1mo"),
          "1h": ("60m", "6mo"), "2h": ("60m", "6mo"), "4h": ("60m", "6mo"),
          "1d": ("1d", "1y"), "1w": ("1wk", "5y")}


# --------------------------------------------------------------------------- #
# util
# --------------------------------------------------------------------------- #
def _get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(3_000_000)


def _json(url: str, timeout: float = 15):
    return json.loads(_get(url, timeout).decode("utf-8", "replace"))


def _fmt(v: float, casas: int | None = None) -> str:
    """Número no padrão pt-BR: 81.189,43 (casas conforme a grandeza)."""
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    a = abs(v)
    n = casas if casas is not None else (0 if a >= 1000 else 2 if a >= 1 else 4 if a >= 0.01 else 6)
    s = f"{v:,.{n}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _pct(v: float) -> str:
    return "—" if v is None or np.isnan(v) else f"{v:+.2f}%".replace(".", ",")


def resolver_ativo(texto: str) -> tuple[str, str]:
    """('BTC','cripto') | ('TSLA','acao'). Aceita 'btc', 'bitcoin', '$TSLA', 'ação AAPL'."""
    t = str(texto or "").strip()
    baixo = re.sub(r"[^a-z0-9$ ]", " ", t.lower())
    for palavra in baixo.split():
        if palavra in CRIPTOS:
            return CRIPTOS[palavra], "cripto"
    m = re.search(r"\$([A-Za-z]{1,6})\b", t)
    if m:
        s = m.group(1).upper()
        return (CRIPTOS.get(s.lower(), s), "cripto" if s.lower() in CRIPTOS else "acao")
    m = re.search(r"\b([A-Z]{2,5})\b", t)
    if m:
        s = m.group(1)
        return (CRIPTOS.get(s.lower(), s), "cripto" if s.lower() in CRIPTOS else "acao")
    s = re.sub(r"[^A-Za-z]", "", t).upper() or "BTC"
    return s, ("cripto" if s.lower() in CRIPTOS else "acao")


# --------------------------------------------------------------------------- #
# dados
# --------------------------------------------------------------------------- #
def _arrays(linhas: list[list[float]], fonte: str) -> dict:
    a = np.array(linhas, dtype=float)
    return {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4],
            "v": a[:, 5], "fonte": fonte}


def candles(simbolo: str, tipo: str, intervalo: str = "1d", limite: int = 220,
            avisos: list | None = None) -> dict:
    avisos = avisos if avisos is not None else []
    intervalo = INTERVALOS.get(intervalo, "1d")
    if tipo == "cripto":
        par = f"{simbolo}USDT"
        for nome, base in (("Binance", "https://api.binance.com"), ("Binance US", "https://api.binance.us")):
            try:
                d = _json(f"{base}/api/v3/klines?symbol={par}&interval={intervalo}&limit={limite}")
                if d:
                    return _arrays([[k[0] / 1000, k[1], k[2], k[3], k[4], k[5]] for k in d],
                                   f"{nome} ({par})")
            except Exception as exc:
                avisos.append(f"{nome}: {str(exc)[:60]}")
        gran = _COINBASE_GRAN.get(intervalo)
        if gran:
            try:
                d = _json(f"https://api.exchange.coinbase.com/products/{simbolo}-USD/candles?granularity={gran}")
                d = sorted(d, key=lambda k: k[0])[-limite:]
                return _arrays([[k[0], k[3], k[2], k[1], k[4], k[5]] for k in d], f"Coinbase ({simbolo}-USD)")
            except Exception as exc:
                avisos.append(f"Coinbase: {str(exc)[:60]}")
        raise RuntimeError("nenhuma fonte de preço respondeu para " + simbolo)
    # ações: Yahoo Finance
    iv, rng = _YAHOO.get(intervalo, ("1d", "1y"))
    d = _json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(simbolo)}?interval={iv}&range={rng}")
    res = (d.get("chart", {}).get("result") or [None])[0]
    if not res:
        raise RuntimeError(f"Yahoo não encontrou {simbolo}")
    q = res["indicators"]["quote"][0]
    linhas = []
    for i, t in enumerate(res["timestamp"]):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        linhas.append([t, q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0])
    return _arrays(linhas[-limite:], f"Yahoo Finance ({simbolo})")


def sentimento_stocktwits(simbolo: str, tipo: str) -> dict:
    sym = f"{simbolo}.X" if tipo == "cripto" else simbolo
    d = _json(f"https://api.stocktwits.com/api/2/streams/symbol/{quote(sym)}.json?limit=30", timeout=15)
    msgs = d.get("messages") or []
    alt = bai = neu = 0
    destaques = []
    for m in msgs:
        s = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        if s == "Bullish":
            alt += 1
        elif s == "Bearish":
            bai += 1
        else:
            neu += 1
        texto = re.sub(r"\s+", " ", re.sub(r"https?://\S+", "", m.get("body") or "")).strip()
        if len(texto) > 25:
            destaques.append({"autor": (m.get("user") or {}).get("username", "?"),
                              "sentimento": s or "—", "curtidas": ((m.get("likes") or {}).get("total") or 0),
                              "texto": texto[:170]})
    destaques.sort(key=lambda x: x["curtidas"], reverse=True)
    com = alt + bai
    return {"simbolo": sym, "mensagens": len(msgs), "altistas": alt, "baixistas": bai, "neutras": neu,
            "saldo": ((alt - bai) / com) if com else 0.0,
            "watchlist": ((d.get("symbol") or {}).get("watchlist_count")),
            "destaques": destaques[:3]}


def medo_ganancia(n: int = 30) -> dict:
    d = _json(f"https://api.alternative.me/fng/?limit={n}")["data"]
    return {"valor": int(d[0]["value"]), "classe": d[0]["value_classification"],
            "historico": [int(x["value"]) for x in reversed(d)]}


# --------------------------------------------------------------------------- #
# indicadores
# --------------------------------------------------------------------------- #
def sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    k = 2 / (n + 1)
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    g, p = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    mg, mp = g[:n].mean(), p[:n].mean()
    out[n] = 100 - 100 / (1 + (mg / mp if mp else np.inf))
    for i in range(n, len(d)):
        mg = (mg * (n - 1) + g[i]) / n
        mp = (mp * (n - 1) + p[i]) / n
        out[i + 1] = 100 - 100 / (1 + (mg / mp if mp else np.inf))
    return out


def atr(h, l, c, n: int = 14) -> np.ndarray:
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    if len(tr) >= n:
        a = tr[:n].mean()
        out[n] = a
        for i in range(n, len(tr)):
            a = (a * (n - 1) + tr[i]) / n
            out[i + 1] = a
    return out


def macd(c: np.ndarray):
    linha = ema(c, 12) - ema(c, 26)
    sinal = np.full(len(c), np.nan)
    ok = ~np.isnan(linha)
    if ok.sum() >= 9:
        idx = np.where(ok)[0]
        sinal[idx[0]:] = ema(linha[idx[0]:], 9)
    return linha, sinal, linha - sinal


def niveis(h: np.ndarray, l: np.ndarray, preco: float, janela: int = 5, tol: float = 0.012):
    """Suportes/resistências: pivôs de topo/fundo agrupados (±1,2%)."""
    piv = []
    for i in range(janela, len(h) - janela):
        if h[i] == h[i - janela:i + janela + 1].max():
            piv.append(h[i])
        if l[i] == l[i - janela:i + janela + 1].min():
            piv.append(l[i])
    grupos: list[list[float]] = []
    for p in sorted(piv):
        if grupos and abs(p - np.mean(grupos[-1])) / np.mean(grupos[-1]) < tol:
            grupos[-1].append(p)
        else:
            grupos.append([p])
    cand = [(float(np.mean(g)), len(g)) for g in grupos]
    sup = sorted([c for c in cand if c[0] < preco], key=lambda c: -c[0])[:3]
    res = sorted([c for c in cand if c[0] > preco], key=lambda c: c[0])[:3]
    return sup, res


def indicadores(d: dict) -> dict:
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    preco = float(c[-1])
    s20, s50, s200 = sma(c, 20), sma(c, 50), sma(c, 200)
    r = rsi(c)
    ml, ms, mh = macd(c)
    a = atr(h, l, c)
    dp = sma(c, 20)
    desv = np.array([c[max(0, i - 19):i + 1].std() if i >= 19 else np.nan for i in range(len(c))])
    bb_sup, bb_inf = dp + 2 * desv, dp - 2 * desv
    seg = max(1.0, float(np.median(np.diff(d["t"])))) if len(d["t"]) > 1 else 86400.0
    por_dia = 86400 / seg

    def var(n):
        k = int(round(n * por_dia))
        return (preco / c[-1 - k] - 1) * 100 if len(c) > k else np.nan
    ret = np.diff(np.log(c))
    vol_anual = float(ret[-60:].std() * np.sqrt(365 * por_dia) * 100) if len(ret) > 10 else np.nan
    sup, res = niveis(h, l, preco)
    pontos, motivos = 0, []

    def add(p, txt):
        nonlocal pontos
        pontos += p
        motivos.append(txt)
    for nome, m in (("SMA20", s20), ("SMA50", s50), ("SMA200", s200)):
        if not np.isnan(m[-1]):
            add(10 if preco > m[-1] else -10, f"preço {'acima' if preco > m[-1] else 'abaixo'} da {nome}")
    if not (np.isnan(s20[-1]) or np.isnan(s50[-1])):
        add(10 if s20[-1] > s50[-1] else -10, f"SMA20 {'>' if s20[-1] > s50[-1] else '<'} SMA50")
    if not np.isnan(mh[-1]):
        add(12 if mh[-1] > 0 else -12, f"MACD {'positivo' if mh[-1] > 0 else 'negativo'}")
    if not np.isnan(r[-1]):
        if r[-1] > 70:
            add(-6, "RSI em sobrecompra")
        elif r[-1] < 30:
            add(6, "RSI em sobrevenda")
        else:
            add(8 if r[-1] > 55 else -8 if r[-1] < 45 else 0, f"RSI {r[-1]:.0f}")
    m7 = var(7)
    if not np.isnan(m7):
        add(8 if m7 > 3 else -8 if m7 < -3 else 0, f"variação 7d {_pct(m7)}")
    score = max(-100, min(100, int(round(pontos * 100 / 70))))
    rotulo = ("Altista" if score >= 40 else "Levemente altista" if score >= 15 else
              "Neutro / lateral" if score > -15 else "Levemente baixista" if score > -40 else "Baixista")
    return {"preco": preco, "var_24h": var(1), "var_7d": var(7), "var_30d": var(30), "var_90d": var(90),
            "sma20": s20, "sma50": s50, "sma200": s200, "rsi": r, "macd": ml, "macd_sinal": ms, "macd_hist": mh,
            "atr": a, "bb_sup": bb_sup, "bb_inf": bb_inf, "vol_anual": vol_anual,
            "vol_rel": float(v[-1] / v[-21:-1].mean()) if len(v) > 21 and v[-21:-1].mean() else np.nan,
            "max": float(h.max()), "min": float(l.min()), "suportes": sup, "resistencias": res,
            "score": score, "veredito": rotulo, "motivos": motivos}


# --------------------------------------------------------------------------- #
# gráficos
# --------------------------------------------------------------------------- #
def _grafico_preco(d: dict, ind: dict, nome: str, intervalo: str, destino: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import date2num
    n = min(len(d["c"]), 130)
    sl = slice(-n, None)
    t = np.array([date2num(datetime.fromtimestamp(x)) for x in d["t"][sl]])
    o, h, l, c, v = (d[k][sl] for k in ("o", "h", "l", "c", "v"))
    larg = (t[1] - t[0]) * 0.65 if n > 1 else 0.5
    fundo, tinta, alt, bai, acento = "#faf9f5", "#1f1e1d", "#3d8b5a", "#c0463b", "#c96442"
    fig, eixos = plt.subplots(4, 1, figsize=(12, 9.2), sharex=True,
                              gridspec_kw={"height_ratios": [5, 1.3, 1.5, 1.5], "hspace": 0.06}, facecolor=fundo)
    ax, axv, axr, axm = eixos
    for a in eixos:
        a.set_facecolor(fundo)
        a.grid(alpha=.25, lw=.6)
        a.tick_params(colors=tinta, labelsize=8)
        for s in a.spines.values():
            s.set_alpha(.3)
    cores = np.where(c >= o, alt, bai)
    ax.vlines(t, l, h, colors=cores, lw=1)
    ax.bar(t, np.abs(c - o), bottom=np.minimum(o, c), width=larg, color=cores, edgecolor=cores)
    for nome_m, serie, cor in (("SMA20", ind["sma20"], "#d4a017"), ("SMA50", ind["sma50"], "#2f6db5"),
                               ("SMA200", ind["sma200"], "#7b4fa0")):
        s = serie[sl]
        if not np.all(np.isnan(s)):
            ax.plot(t, s, lw=1.3, color=cor, label=nome_m)
    ax.fill_between(t, ind["bb_inf"][sl], ind["bb_sup"][sl], color="#888", alpha=.10, label="Bollinger (20,2)")
    for p, forca in ind["suportes"]:
        ax.axhline(p, color=alt, ls="--", lw=.9, alpha=.8)
        ax.text(t[0], p, f" S {_fmt(p)}", color=alt, fontsize=8, va="bottom")
    for p, forca in ind["resistencias"]:
        ax.axhline(p, color=bai, ls="--", lw=.9, alpha=.8)
        ax.text(t[0], p, f" R {_fmt(p)}", color=bai, fontsize=8, va="bottom")
    ax.axhline(ind["preco"], color=acento, lw=1.1)
    ax.text(t[-1], ind["preco"], f" {_fmt(ind['preco'])}", color="white", fontsize=9, va="center",
            bbox=dict(boxstyle="round,pad=.25", fc=acento, ec="none"))
    ax.set_title(f"{nome} · {intervalo} · {ind['veredito']} (score {ind['score']:+d})  —  fonte: {d['fonte']}",
                 color=tinta, fontsize=11, loc="left")
    ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=4)
    axv.bar(t, v, width=larg, color=cores, alpha=.7)
    axv.set_ylabel("Vol", color=tinta, fontsize=8)
    axr.plot(t, ind["rsi"][sl], color="#2f6db5", lw=1.2)
    axr.axhline(70, color=bai, ls=":", lw=.8)
    axr.axhline(30, color=alt, ls=":", lw=.8)
    axr.set_ylim(0, 100)
    axr.set_ylabel("RSI", color=tinta, fontsize=8)
    mh = ind["macd_hist"][sl]
    axm.bar(t, np.nan_to_num(mh), width=larg, color=np.where(np.nan_to_num(mh) >= 0, alt, bai), alpha=.7)
    axm.plot(t, ind["macd"][sl], color="#2f6db5", lw=1)
    axm.plot(t, ind["macd_sinal"][sl], color="#d4a017", lw=1)
    axm.set_ylabel("MACD", color=tinta, fontsize=8)
    axm.xaxis_date()
    fig.autofmt_xdate(rotation=0, ha="center")
    fig.savefig(destino, dpi=105, facecolor=fundo, bbox_inches="tight")
    plt.close(fig)
    return destino


def _grafico_sentimento(st: dict | None, fg: dict | None, nome: str, destino: Path) -> Path | None:
    if not st and not fg:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fundo, tinta = "#faf9f5", "#1f1e1d"
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 3.8), facecolor=fundo,
                                 gridspec_kw={"width_ratios": [1, 1.4]})
    for a in (a1, a2):
        a.set_facecolor(fundo)
        a.tick_params(colors=tinta, labelsize=9)
        for s in a.spines.values():
            s.set_alpha(.3)
    if st and st["mensagens"]:
        vals = [st["altistas"], st["baixistas"], st["neutras"]]
        a1.barh(["Altistas", "Baixistas", "Sem rótulo"], vals, color=["#3d8b5a", "#c0463b", "#9a988f"])
        for i, x in enumerate(vals):
            a1.text(x, i, f" {x}", va="center", fontsize=10, color=tinta)
        a1.invert_yaxis()
        a1.set_title(f"StockTwits · {st['simbolo']} · últimas {st['mensagens']} mensagens", fontsize=10, color=tinta, loc="left")
    else:
        a1.axis("off")
        a1.text(.5, .5, "StockTwits indisponível", ha="center", color=tinta)
    if fg:
        h = fg["historico"]
        a2.plot(range(len(h)), h, color="#c96442", lw=2)
        a2.fill_between(range(len(h)), h, 0, color="#c96442", alpha=.12)
        for y, cor in ((25, "#c0463b"), (50, "#9a988f"), (75, "#3d8b5a")):
            a2.axhline(y, color=cor, ls=":", lw=.8)
        a2.set_ylim(0, 100)
        a2.set_title(f"Medo & Ganância (30 dias) · hoje {fg['valor']} — {fg['classe']}", fontsize=10, color=tinta, loc="left")
        a2.set_xticks([])
    else:
        a2.axis("off")
    fig.savefig(destino, dpi=105, facecolor=fundo, bbox_inches="tight")
    plt.close(fig)
    return destino


# --------------------------------------------------------------------------- #
# relatório
# --------------------------------------------------------------------------- #
def _leitura_rsi(v):
    return "—" if np.isnan(v) else ("sobrecomprado" if v > 70 else "sobrevendido" if v < 30 else
                                    "força compradora" if v > 55 else "força vendedora" if v < 45 else "neutro")


def _tabela(linhas: list[tuple]) -> str:
    out = ["| Indicador | Valor | Leitura |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in linhas]
    return "\n".join(out)


def analisar(ativo: str = "BTC", intervalo: str = "1d", sentimento: bool = True) -> dict:
    simbolo, tipo = resolver_ativo(ativo)
    intervalo = intervalo if intervalo in INTERVALOS else "1d"
    avisos: list[str] = []
    try:
        d = candles(simbolo, tipo, intervalo, avisos=avisos)
    except Exception as exc:
        return {"ok": False, "erro": f"não consegui os preços de {simbolo}: {exc}", "avisos": avisos}
    if len(d["c"]) < 30:
        return {"ok": False, "erro": f"poucos candles para {simbolo} ({len(d['c'])})", "avisos": avisos}
    ind = indicadores(d)
    preco, a14 = ind["preco"], float(ind["atr"][-1]) if not np.isnan(ind["atr"][-1]) else preco * 0.03
    quando = datetime.now()
    st = fg = None
    if sentimento:
        try:
            st = sentimento_stocktwits(simbolo, tipo)
        except Exception as exc:
            avisos.append(f"StockTwits: {str(exc)[:70]}")
        if tipo == "cripto":
            try:
                fg = medo_ganancia()
            except Exception as exc:
                avisos.append(f"Medo&Ganância: {str(exc)[:70]}")
    carimbo = quando.strftime("%Y%m%d_%H%M%S")
    PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    arquivos = []
    try:
        p = _grafico_preco(d, ind, simbolo, intervalo, PASTA_GRAFICOS / f"mercado_{simbolo}_{carimbo}_preco.png")
        arquivos.append({"arquivo": str(p), "titulo": f"{simbolo} {intervalo} — preço, médias, Bollinger, RSI e MACD"})
    except Exception as exc:
        avisos.append(f"gráfico de preço: {exc}")
    try:
        p = _grafico_sentimento(st, fg, simbolo, PASTA_GRAFICOS / f"mercado_{simbolo}_{carimbo}_sentimento.png")
        if p:
            arquivos.append({"arquivo": str(p), "titulo": f"{simbolo} — sentimento (StockTwits e Medo & Ganância)"})
    except Exception as exc:
        avisos.append(f"gráfico de sentimento: {exc}")

    s20, s50, s200 = ind["sma20"][-1], ind["sma50"][-1], ind["sma200"][-1]
    macd_h = ind["macd_hist"][-1]
    linhas = [("Preço", f"US$ {_fmt(preco)}", f"24h {_pct(ind['var_24h'])} · 7d {_pct(ind['var_7d'])} · 30d {_pct(ind['var_30d'])}"),
              ("SMA 20", _fmt(s20), "preço acima" if preco > s20 else "preço abaixo"),
              ("SMA 50", _fmt(s50), "preço acima" if preco > s50 else "preço abaixo"),
              ("SMA 200", _fmt(s200), "—" if np.isnan(s200) else ("preço acima" if preco > s200 else "preço abaixo")),
              ("RSI 14", f"{ind['rsi'][-1]:.1f}".replace(".", ","), _leitura_rsi(ind["rsi"][-1])),
              ("MACD (hist.)", _fmt(macd_h, 2), "momento positivo" if macd_h > 0 else "momento negativo"),
              ("ATR 14", _fmt(a14), f"{a14 / preco * 100:.1f}% do preço".replace(".", ",")),
              ("Volatilidade anual.", f"{ind['vol_anual']:.0f}%", "alta" if ind["vol_anual"] > 70 else "moderada"),
              ("Volume vs média 20", f"{ind['vol_rel']:.2f}x".replace(".", ","), "acima do normal" if ind["vol_rel"] > 1.3 else "normal")]
    sup = [p for p, _ in ind["suportes"]]
    res = [p for p, _ in ind["resistencias"]]
    # alvo = próximo nível além do gatilho (ou 2 ATR além dele, se não houver outro)
    alvo_a = res[1] if len(res) > 1 else (res[0] if res else preco) + 2 * a14
    alvo_b = sup[1] if len(sup) > 1 else (sup[0] if sup else preco) - 2 * a14
    md = [f"## Análise de {simbolo} — {intervalo} · {quando:%d/%m/%Y %H:%M}",
          f"**Veredito técnico: {ind['veredito']}** (score {ind['score']:+d}/100) — " + "; ".join(ind["motivos"][:5]) + ".",
          "", _tabela(linhas), "",
          f"**Suportes:** {', '.join('US$ ' + _fmt(x) for x in sup) or '—'}  ·  "
          f"**Resistências:** {', '.join('US$ ' + _fmt(x) for x in res) or '—'}",
          f"**Faixa do período:** mín. US$ {_fmt(ind['min'])} · máx. US$ {_fmt(ind['max'])}", "",
          "**Cenários de referência (por ATR — não é recomendação de investimento):**",
          f"- Altista: rompimento acima de US$ {_fmt(res[0] if res else preco + a14)} abre espaço até ~US$ {_fmt(alvo_a)}; "
          f"invalidação perto de US$ {_fmt(preco - 1.5 * a14)}.",
          f"- Baixista: perda de US$ {_fmt(sup[0] if sup else preco - a14)} leva a ~US$ {_fmt(alvo_b)}; "
          f"invalidação acima de US$ {_fmt(preco + 1.5 * a14)}."]
    if st or fg:
        md += ["", "## Sentimento"]
    if st and st["mensagens"]:
        com = st["altistas"] + st["baixistas"]
        leit = ("otimista" if st["saldo"] > .25 else "pessimista" if st["saldo"] < -.25 else "dividido")
        md.append(f"**StockTwits ({st['simbolo']}):** {st['mensagens']} mensagens recentes — "
                  f"{st['altistas']} altistas, {st['baixistas']} baixistas, {st['neutras']} sem rótulo "
                  f"→ comunidade **{leit}**" + (f" (saldo {st['saldo']:+.0%})" if com else "") +
                  (f" · {st['watchlist']:,} seguidores".replace(",", ".") if st.get("watchlist") else "") + ".")
        for x in st["destaques"]:
            md.append(f"- @{x['autor']} ({x['sentimento']}, {x['curtidas']} curtidas): “{x['texto']}”")
    elif sentimento:
        md.append("**StockTwits:** sem dados agora.")
    if fg:
        md.append(f"**Índice Medo & Ganância:** {fg['valor']} — {fg['classe']} "
                  f"(30 dias: mín. {min(fg['historico'])}, máx. {max(fg['historico'])}).")
    md.append(f"\n_Fonte dos preços: {d['fonte']}._" + (f" _Avisos: {'; '.join(avisos)}._" if avisos else ""))
    return {"ok": True, "ativo": simbolo, "tipo": tipo, "intervalo": intervalo, "preco": preco,
            "veredito": ind["veredito"], "score": ind["score"], "resumo": "\n".join(md),
            "arquivos": arquivos, "avisos": avisos, "fonte": d["fonte"],
            "sentimento": {k: st[k] for k in ("mensagens", "altistas", "baixistas", "neutras", "saldo")} if st else None,
            "medo_ganancia": fg["valor"] if fg else None}


# --------------------------------------------------------------------------- #
# ferramenta do agente
# --------------------------------------------------------------------------- #
def registrar_ferramentas(tools) -> None:
    def mercado_analisar(ativo: str = "BTC", intervalo: str = "1d", sentimento: bool = True) -> dict:
        return analisar(ativo, intervalo, bool(sentimento))
    tools.register(
        "mercado_analisar", mercado_analisar,
        "Análise técnica COMPLETA de cripto (BTC, ETH, SOL…) ou ação (ex.: TSLA): preço real, médias, RSI, "
        "MACD, Bollinger, suportes/resistências, cenários, sentimento do StockTwits e Medo&Ganância, com "
        "2 gráficos. Devolve `resumo` pronto em Markdown: ENTREGUE-O ao usuário na íntegra (os gráficos "
        "aparecem sozinhos no chat). intervalo = 15m|1h|4h|1d|1w.",
        {"ativo": "str", "intervalo": "str?", "sentimento": "bool?"})
