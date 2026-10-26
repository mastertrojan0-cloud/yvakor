"""YVAKOR — CLI principal. Uso: python -m yvakor.main"""
import sys

# Console Windows usa cp1252 por padrão e quebra com emojis/acentos.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from yvakor.orchestrator import Orchestrator

BANNER = """
╔═══════════════════════════════════════════════════════╗
║     YVAKOR — Agente Pessoal Evolutivo  v0.4           ║
║     [perfil] [skill] [memoria] [cowork] [nova]        ║
║     [cowork-status] [cowork-cancelar] [conversas]     ║
║     [retomar] [apagar-conversa] | 'sair'              ║
║     Navegador real: peça "abra o site X" no chat      ║
╚═══════════════════════════════════════════════════════╝
"""


def main():
    print(BANNER)
    agent = Orchestrator()
    while True:
        try:
            msg = input("\nvocê > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        if msg.lower() in ("sair", "exit", "quit"):
            break
        try:
            print(f"\n  pensando...", flush=True, end="")
            response = agent.process(msg)
            print(f"\r{' ' * 30}\r", end="")  # limpa "pensando..."
            print(f"\nyvakor > {response}")
        except Exception as e:
            print(f"\n[erro] {e}")
    print("\nAté logo. Memórias salvas.")


if __name__ == "__main__":
    main()
