"""Testes das melhorias: memória, receitas, snapshots, telemetria, nativo."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_memoria_qualidade():
    from yvakor.memory.semantic import SemanticMemory
    sem = SemanticMemory(Path(tempfile.mkdtemp()) / "sem")
    assert sem.store("qual o ip da camera?") is False
    assert sem.store("diga apenas ok") is False
    assert sem.store("A camera da garagem fica no IP 192.168.15.7") is True
    assert sem.store("A camera da garagem fica no IP 192.168.15.7") is False
    sem.store("O servidor fica no IP 10.0.0.5 hoje")
    sem.store("O servidor fica no IP 10.0.0.9 hoje")
    assert not any("10.0.0.5" in f for f in sem.search("servidor ip")), sem.search("servidor ip")
    sem.store("Preferencia de baixa confianca", confianca=0.3)
    assert not any("baixa confianca" in f for f in sem.search("preferencia")), "revisar não deve aparecer"
    print("  ✅ memória — ruído, dedup, contradição e baixa confiança")


def test_receitas():
    from yvakor.cerebro.receitas import carregar_de_texto, ExecutorReceitas
    texto = """# Soma e dobra
## Receita
```yaml
aprovada: true
gatilhos: ["somar e dobrar"]
parametros:
  n: "([0-9]+)"
passos:
  - ferramenta: somar
    args: {a: "{{n}}", b: "2"}
  - ferramenta: dobrar
    args: {x: "{{passo1.result}}"}
```
"""
    r = carregar_de_texto("soma", texto)
    assert r and r.aprovada and len(r.passos) == 2, r

    class Reg:
        tools = {"somar": None, "dobrar": None}
        specs = {"somar": {"args": {"a": "int", "b": "int"}},
                 "dobrar": {"args": {"x": "int"}}}

        def run(self, nome, **kw):
            if nome == "somar":
                return {"ok": True, "result": int(kw["a"]) + int(kw["b"])}
            return {"ok": True, "result": int(kw["x"]) * 2}

    ex = ExecutorReceitas(Reg())
    assert not ex.validar(r), ex.validar(r)
    sim = ex.executar(r, "somar e dobrar 3", simular=True)
    assert sim["ok"] and sim["plano"][0]["args"]["a"] == "3", sim
    real = ex.executar(r, "somar e dobrar 3")
    assert real["ok"] and real["resultados"][-1]["result"] == 10, real
    # receita não aprovada nunca executa
    r.aprovada = False
    assert ex.validar(r) and not ex.executar(r, "somar e dobrar 3")["ok"]
    print("  ✅ receitas — parse, validação, simulação, execução e aprovação")


def test_snapshots():
    from yvakor import arquivos as a
    tmp = Path(tempfile.mkdtemp(prefix="yvk-snap-"))
    f = tmp / "nota.txt"
    a.escrever(str(f), "versao 1")
    a.escrever(str(f), "versao 2")
    assert f.read_text(encoding="utf-8") == "versao 2"
    lista = a.snapshots(5)
    assert lista["total"] >= 1, lista
    r = a.desfazer(lista["itens"][0]["id"])
    assert r["ok"], r
    assert f.read_text(encoding="utf-8") == "versao 1", f.read_text(encoding="utf-8")
    print("  ✅ snapshots — cópia antes de sobrescrever e restauração")


def test_telemetria():
    from yvakor.telemetria import Telemetria
    t = Telemetria(Path(tempfile.mkdtemp()) / "tel.db")
    t.registrar("cerebro", 12.5)
    t.registrar("api", 900, provedor="deepseek", ferramentas=2)
    r = t.resumo(7)
    assert r["total"] == 2 and r["por_origem"]["api"]["ferramentas"] == 2, r
    assert r["economia_pct"] == 50.0, r
    t.fechar()
    print("  ✅ telemetria — origem, latência, ferramentas e economia")


def test_nativo():
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    from yvakor.agent import AgentLoop

    reg = ToolRegistry(load_settings())
    reg.register("fake_somar", lambda a, b: {"ok": True, "result": int(a) + int(b)},
                 "Soma dois números.", {"a": "int", "b": "int"})
    reg.register("fake_opt", lambda x="": {"ok": True}, "Opcional.",
                 {"x": "str?"})
    esquemas = reg.schemas()
    nomes = [e["function"]["name"] for e in esquemas]
    assert "fake_somar" in nomes and "fake_opt" in nomes
    opt = next(e for e in esquemas if e["function"]["name"] == "fake_opt")
    assert opt["function"]["parameters"]["required"] == [], opt
    assert reg.coagir("fake_somar", {"a": "2", "b": "3", "ignorar": 1}) == {"a": 2, "b": 3}

    class Router:
        n = 0

        def complete_tools(self, task, msgs, tools, forcar=None):
            Router.n += 1
            if Router.n == 1:
                return "fake", {"content": "", "tool_calls": [
                    {"id": "1", "function": {"name": "fake_somar",
                                             "arguments": "{\"a\":\"2\",\"b\":\"3\"}"}}]}
            return "fake", {"content": "resultado 5"}

        def complete_messages(self, *a, **k):
            return "resultado 5"

    loop = AgentLoop(Router(), reg, max_iterations=4, nativo=True)
    eventos = []
    saida = loop.run("teste", [{"role": "user", "content": "some 2 e 3"}],
                     on_event=lambda t, d: eventos.append((t, d)))
    assert "resultado 5" in saida, saida
    assert any(t == "ferramenta" and d.get("nome") == "fake_somar" for t, d in eventos)
    print("  ✅ function calling — schema, coerção e execução nativa")


if __name__ == "__main__":
    test_memoria_qualidade()
    test_receitas()
    test_snapshots()
    test_telemetria()
    test_nativo()
