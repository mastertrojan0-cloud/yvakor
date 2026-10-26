#!/usr/bin/env python3
"""Analise tecnica de QUALQUER ativo: dados Binance + indicadores TradingView + grafico com niveis.

Uso:
    python analise_cripto.py ZECUSDT
    python analise_cripto.py BTCUSDT --interval 4h
    python analise_cripto.py ETHUSDT --interval 1h --limit 120
    python analise_cripto.py SOLUSDT --exchange KUCOIN
    python analise_cripto.py BNBUSDT --setup "suporte=700,entrada=760,alvo1=800,alvo2=850,stop=715"

Aceita qualquer par negociado na Binance (cripto). Para acoes/forex use --exchange
com um exchange suportado pelo TradingView (ex.: NASDAQ, FX_IDC).
"""
import argparse
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests


INTERVALOS_TV = {
    "1m": "INTERVAL_1_MINUTE",
    "5m": "INTERVAL_5_MINUTES",
    "15m": "INTERVAL_15_MINUTES",
    "30m": "INTERVAL_30_MINUTES",
    "1h": "INTERVAL_1_HOUR",
    "2h": "INTERVAL_2_HOURS",
    "4h": "INTERVAL_4_HOURS",
    "1d": "INTERVAL_1_DAY",
    "1W": "INTERVAL_1_WEEK",
    "1M": "INTERVAL_1_MONTH",
}

CORES = {
    "suporte": "blue",
    "entrada": "green",
    "alvo1": "purple",
    "alvo2": "orange",
    "alvo3": "red",
    "stop": "darkred",
}


def dados_binance(symbol="ZECUSDT", interval="1d", limit=60):
    interval = {"1W": "1w"}.get(interval, interval)
    url = "https://api.binance.com/api/v3/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
    r.raise_for_status()
    return r.json()


def indicadores_tv(symbol="ZECUSDT", exchange="BINANCE", interval="1d"):
    try:
        from tradingview_ta import TA_Handler, Interval
        attr = INTERVALOS_TV.get(interval, "INTERVAL_1_DAY")
        iv = getattr(Interval, attr)
        h = TA_Handler(symbol=symbol, screener="crypto", exchange=exchange, interval=iv)
        return h.get_analysis()
    except Exception as e:
        print("[aviso] TradingView indisponivel:", e, file=sys.stderr)
        return None


def parse_setup(txt):
    niveis = {}
    if not txt:
        return niveis
    for par in txt.split(","):
        if "=" in par:
            k, v = par.split("=", 1)
            try:
                niveis[k.strip().lower()] = float(v.strip())
            except ValueError:
                pass
    return niveis


def gerar_grafico(symbol, k, niveis, out):
    datas = [datetime.fromtimestamp(x[0] / 1000) for x in k]
    fech = [float(x[4]) for x in k]
    alt = [float(x[2]) for x in k]
    baix = [float(x[3]) for x in k]
    atual = fech[-1]

    fig, ax = plt.subplots(figsize=(14, 7))
    ax.fill_between(datas, baix, alt, color="gray", alpha=0.25, label="Max/Min")
    ax.plot(datas, fech, color="black", linewidth=1.5, label="Fechamento")
    ax.axhline(atual, color="black", linestyle=":", linewidth=1, label=f"Atual {atual:.2f}")

    for nome, val in niveis.items():
        cor = CORES.get(nome, "gray")
        ax.axhline(val, color=cor, linestyle="--", linewidth=1.2, label=f"{nome} {val:,.2f}")

    ax.set_title(f"{symbol} - Niveis de Trading")
    ax.set_ylabel("Preco")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main():
    p = argparse.ArgumentParser(description="Analise tecnica de qualquer ativo")
    p.add_argument("symbol", nargs="?", default="ZECUSDT", help="ex.: ZECUSDT, BTCUSDT, ETHUSDT")
    p.add_argument("--interval", default="1d", choices=list(INTERVALOS_TV.keys()))
    p.add_argument('--semana', action='store_true', help='atalho para timeframe semanal (1W)')
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--exchange", default="BINANCE")
    p.add_argument("--out", default=r"E:\YVAKOR\yvakor\data\graficos")
    p.add_argument("--setup", default=None, help='niveis manuais: "suporte=700,entrada=760,alvo1=800,stop=715"')
    args = p.parse_args()
    if args.semana:
        args.interval = '1W'

    k = dados_binance(args.symbol, args.interval, args.limit)
    tv = indicadores_tv(args.symbol, args.exchange, args.interval)

    fech = [float(x[4]) for x in k]
    alt = [float(x[2]) for x in k]
    baix = [float(x[3]) for x in k]
    atual = fech[-1]
    suporte = min(baix[-30:])
    topo = max(alt[-30:])

    niveis = {
        "suporte": round(suporte, 2),
        "entrada": round(atual * 1.08, 2),
        "alvo1": round(atual * 1.20, 2),
        "alvo2": round(atual * 1.34, 2),
        "alvo3": round(topo, 2),
        "stop": round(atual * 0.95, 2),
    }

    manuais = parse_setup(args.setup)
    if manuais:
        niveis = manuais

    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, f"{args.symbol.lower()}_niveis.png")
    gerar_grafico(args.symbol, k, niveis, out)

    print(f"Ativo: {args.symbol} | Intervalo: {args.interval}")
    print(f"Preco atual: {atual:,.2f}")
    if tv:
        print(f"Sinal TV: {tv.summary.get('RECOMMENDATION', '?')}")
    print("Niveis no grafico:")
    for nome, val in niveis.items():
        print(f"  {nome}: {val:,.2f}")
    print(f"Grafico: {out}")


if __name__ == "__main__":
    main()
