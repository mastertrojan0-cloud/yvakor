"""Grafico ao vivo de qualquer ativo (Binance WebSocket + matplotlib).
Uso:
    python scripts/grafico_ao_vivo.py BNBUSDT
    python scripts/grafico_ao_vivo.py BTCUSDT --interval 1m --candles 120
    python scripts/grafico_ao_vivo.py BNBUSDT --setup "suporte=700,entrada=760,alvo1=800,alvo2=850,stop=715"
"""
import argparse
import json
import threading
import time
from collections import deque

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import requests
import websocket

BINANCE_REST = "https://api.binance.com/api/v3/klines"
BINANCE_WS = "wss://stream.binance.com:9443/ws"

CORES_SETUP = {
    "suporte": "#2196f3",
    "entrada": "#4caf50",
    "alvo1": "#9c27b0",
    "alvo2": "#ff9800",
    "alvo3": "#f44336",
    "stop": "#b71c1c",
    "resistencia": "#00bcd4",
    "pivot": "#ffeb3b",
}


def parse_setup(texto):
    niveis = []
    if not texto:
        return niveis
    for parte in texto.split(","):
        parte = parte.strip()
        if not parte or "=" not in parte:
            continue
        nome, valor = parte.split("=", 1)
        nome = nome.strip().lower()
        try:
            valor = float(valor.strip())
        except ValueError:
            continue
        cor = CORES_SETUP.get(nome, "#9e9e9e")
        niveis.append({"nome": nome, "valor": valor, "cor": cor})
    return niveis


def baixar_historico(symbol, interval, limit):
    r = requests.get(BINANCE_REST, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
    r.raise_for_status()
    dados = r.json()
    return [
        {
            "t": int(k[0]),
            "o": float(k[1]),
            "h": float(k[2]),
            "l": float(k[3]),
            "c": float(k[4]),
            "v": float(k[5]),
        }
        for k in dados
    ]


class StreamAoVivo:
    def __init__(self, symbol, interval, candles):
        self.symbol = symbol.upper()
        self.interval = interval
        self.max_candles = candles
        self.candles = deque(maxlen=candles)
        self.lock = threading.Lock()
        self.ultimo_preco = None
        self.conectado = False

    def carregar(self):
        hist = baixar_historico(self.symbol, self.interval, self.max_candles)
        with self.lock:
            self.candles.clear()
            for c in hist:
                self.candles.append(c)
            if hist:
                self.ultimo_preco = hist[-1]["c"]

    def iniciar_ws(self):
        url = f"{BINANCE_WS}/{self.symbol.lower()}@kline_{self.interval}"

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                k = msg.get("k")
                if not k:
                    return
                candle = {
                    "t": int(k["t"]),
                    "o": float(k["o"]),
                    "h": float(k["h"]),
                    "l": float(k["l"]),
                    "c": float(k["c"]),
                    "v": float(k["v"]),
                }
                with self.lock:
                    self.ultimo_preco = candle["c"]
                    if self.candles and self.candles[-1]["t"] == candle["t"]:
                        self.candles[-1] = candle
                    else:
                        self.candles.append(candle)
            except Exception:
                pass

        def on_open(ws):
            self.conectado = True

        def on_close(ws, *a):
            self.conectado = False

        def on_error(ws, err):
            self.conectado = False

        self.ws = websocket.WebSocketApp(
            url,
            on_message=on_message,
            on_open=on_open,
            on_close=on_close,
            on_error=on_error,
        )
        t = threading.Thread(target=self.ws.run_forever, daemon=True)
        t.start()

    def snapshot(self):
        with self.lock:
            return list(self.candles), self.ultimo_preco


def desenhar(symbol, interval, stream, setups):
    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(13, 7), sharex=True,
        gridspec_kw={"height_ratios": [4, 1]},
    )
    fig.patch.set_facecolor("#0e1117")
    for a in (ax, axv):
        a.set_facecolor("#0e1117")
        a.tick_params(colors="#cccccc")
        for spine in a.spines.values():
            spine.set_color("#333333")
    ax.grid(True, color="#222222", linestyle="--", linewidth=0.5)
    axv.grid(True, color="#222222", linestyle="--", linewidth=0.5)

    def update(_frame):
        candles, preco = stream.snapshot()
        if not candles:
            return
        ax.clear()
        axv.clear()
        ax.set_facecolor("#0e1117")
        axv.set_facecolor("#0e1117")
        ax.grid(True, color="#222222", linestyle="--", linewidth=0.5)
        axv.grid(True, color="#222222", linestyle="--", linewidth=0.5)

        for i, c in enumerate(candles):
            cor = "#26a69a" if c["c"] >= c["o"] else "#ef5350"
            ax.plot([i, i], [c["l"], c["h"]], color=cor, linewidth=1)
            ax.add_patch(plt.Rectangle(
                (i - 0.35, min(c["o"], c["c"])),
                0.7,
                max(abs(c["c"] - c["o"]), 1e-9),
                color=cor,
            ))
            axv.bar(i, c["v"], color=cor, width=0.7)

        for s in setups:
            ax.axhline(s["valor"], color=s["cor"], linestyle="--", linewidth=1.4)
            ax.text(
                len(candles) - 0.5, s["valor"],
                f"  {s['nome'].upper()} {s['valor']:,.2f}",
                color=s["cor"], va="center", fontsize=9, fontweight="bold",
            )

        if preco:
            ax.axhline(preco, color="#ffffff", linestyle=":", linewidth=1)
            ax.text(
                len(candles) - 0.5, preco, f"  {preco:,.2f}",
                color="#ffffff", va="center", fontsize=10, fontweight="bold",
            )

        ax.set_title(
            f"{symbol}  {interval}  —  AO VIVO  ({'conectado' if stream.conectado else 'reconectando...'})",
            color="#ffffff", fontsize=12, loc="left",
        )
        ax.set_ylabel("Preco", color="#cccccc")
        axv.set_ylabel("Volume", color="#cccccc")
        ax.set_xlim(-1, len(candles))
        fig.tight_layout()

    ani = animation.FuncAnimation(fig, update, interval=1000, cache_frame_data=False)
    plt.show()
    return ani


def main():
    p = argparse.ArgumentParser()
    p.add_argument("symbol")
    p.add_argument("--interval", default="1m")
    p.add_argument("--candles", type=int, default=120)
    p.add_argument("--setup", default="", help="niveis: suporte=700,entrada=760,alvo1=800,stop=715")
    args = p.parse_args()

    setups = parse_setup(args.setup)
    stream = StreamAoVivo(args.symbol, args.interval, args.candles)
    print(f"Carregando historico {args.symbol} {args.interval}...")
    stream.carregar()
    print("Conectando WebSocket...")
    stream.iniciar_ws()
    time.sleep(1)
    if setups:
        print("Niveis marcados: " + ", ".join(f"{s['nome']}={s['valor']}" for s in setups))
    print("Abrindo janela ao vivo. Feche a janela para encerrar.")
    desenhar(args.symbol.upper(), args.interval, stream, setups)


if __name__ == "__main__":
    main()
