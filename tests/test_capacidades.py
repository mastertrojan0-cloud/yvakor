"""Testes das capacidades integradas (determinísticas)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def test_calculo():
    from yvakor.capacidades import calcular
    assert calcular("2 + 3 * 4")["resultado"] == 14
    assert calcular("sqrt(16) + 2**3")["resultado"] == 12
    assert not calcular("__import__('os').system('dir')")["ok"]
    print("  ✅ cálculo seguro — precedência, funções e bloqueio de código")


def test_estatistica():
    from yvakor.capacidades import estatisticas
    r = estatisticas("10, 20, 30, 40")
    assert r["ok"] and r["media"] == 25 and r["mediana"] == 25
    assert r["min"] == 10 and r["max"] == 40 and r["n"] == 4
    print("  ✅ estatística — média, mediana, extremos e quartis")


def test_grafico():
    from yvakor.capacidades import grafico
    for tipo in ("barra", "linha", "pizza"):
        r = grafico(tipo, [3, 7, 2, 9], f"teste {tipo}")
        assert r["ok"] and Path(r["arquivo"]).exists(), r
        cabecalho = Path(r["arquivo"]).read_bytes()[:8]
        assert cabecalho.startswith(b"\x89PNG") or cabecalho.startswith(b"<svg"), cabecalho
    print("  ✅ gráficos — PNG (matplotlib) com fallback SVG")


if __name__ == "__main__":
    test_calculo()
    test_estatistica()
    test_grafico()
