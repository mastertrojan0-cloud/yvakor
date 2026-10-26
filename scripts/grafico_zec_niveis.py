# -*- coding: utf-8 -*-
"""Gera grafico de ZEC com niveis de trading marcados (entrada, stop, alvos)."""
import os
import time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = r"E:\YVAKOR\yvakor\data\graficos"
os.makedirs(OUT_DIR, exist_ok=True)

# Niveis (USD)
preco_atual = 1163.07
niveis = [
    ("Suporte 30d", 1127, "#1f77b4"),
    ("Preco atual", 1163.07, "#000000"),
    ("Gatilho entrada", 1250, "#2ca02c"),
    ("Alvo 1", 1400, "#9467bd"),
    ("Alvo 2", 1560, "#ff7f0e"),
    ("Topo 30d / Alvo 3", 1653, "#d62728"),
]

fig, ax = plt.subplots(figsize=(11, 6.5))

# Faixa de fundo entre suporte e topo
ax.axhspan(1127, 1653, color="#f0f0f0", zorder=0)

for nome, valor, cor in niveis:
    ls = "--" if nome != "Preco atual" else "-"
    lw = 2.5 if nome == "Preco atual" else 1.8
    ax.axhline(valor, color=cor, linestyle=ls, linewidth=lw, zorder=2)
    ax.text(1.01, valor, f"{nome}: US$ {valor:,.0f}",
            transform=ax.get_yaxis_transform(), va="center", ha="left",
            fontsize=9, color=cor, fontweight="bold")

# Zona de entrada (gatilho ate +20)
ax.axhspan(1250, 1270, color="#2ca02c", alpha=0.15, zorder=1)

ax.set_ylim(1080, 1700)
ax.set_xlim(0, 1)
ax.set_xticks([])
ax.set_ylabel("Preco (USD)")
ax.set_title("Zcash (ZEC) - Niveis de Trading", fontsize=14, fontweight="bold")
ax.grid(axis="y", alpha=0.3)

plt.tight_layout()
nome = f"zec-niveis-marcados-{int(time.time())}.png"
caminho = os.path.join(OUT_DIR, nome)
plt.savefig(caminho, dpi=130, bbox_inches="tight")
plt.close()
print(caminho)
