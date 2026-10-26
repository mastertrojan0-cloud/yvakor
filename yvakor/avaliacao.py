"""
YVAKOR — Avaliação contínua (golden set offline)

Mede as decisões que protegem a economia de IA e a qualidade:

  • cérebro responde fato conhecido (sem IA)
  • cérebro ignora comando/pergunta sem base
  • ação com skill → local; ação sem skill → API
  • receita aprovada é reconhecida
  • memória rejeita ruído, deduplica e resolve contradição
  • classificador manda ação para API e conversa curta para local

Uso:  python -m yvakor.avaliacao            # roda e imprime o relatório
      python -m yvakor.avaliacao --json     # saída JSON
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent


def _brain(tmp: Path):
    from yvakor.memory.episodic import EpisodicMemory
    from yvakor.memory.semantic import SemanticMemory
    from yvakor.memory.procedural import SkillLibrary
    from yvakor.cerebro import Cerebro

    m = EpisodicMemory(tmp / "m.db")
    sem = SemanticMemory(tmp / "sem")
    skills = tmp / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "pdf.md").write_text(
        "<!-- skill: Gerar relatorio PDF | tags: pdf -->\n# Gerar relatorio PDF\n"
        "## Quando usar\nquando pedem relatorio\n## Passos\nusar reportlab\n",
        encoding="utf-8")
    (skills / "disco.md").write_text(
        "<!-- skill: Status de disco | tags: disco -->\n# Status de disco\n"
        "## Receita\n```yaml\naprovada: true\ngatilhos: [\"status do disco\"]\n"
        "passos:\n  - ferramenta: fake\n    args: {}\n```\n", encoding="utf-8")
    sk = SkillLibrary(skills, tmp / "sk.db")
    sem.store("A camera da garagem fica no IP 192.168.15.7 e e Intelbras")
    c = Cerebro({"cerebro": {"limiar_direto": 0.7, "limiar_local": 0.45}},
                m, sem, sk, vault_dir=tmp / "vault", db_path=tmp / "c.db")
    c.sincronizar()
    return c, sem


def executar(json_saida: bool = False) -> dict:
    from yvakor.llm.router import LLMRouter
    from yvakor.config import load_settings

    casos = []
    tmp = Path(tempfile.mkdtemp(prefix="yvk-aval-"))
    c, sem = _brain(tmp)

    def caso(nome, obtido, esperado):
        casos.append({"caso": nome, "ok": obtido == esperado,
                      "obtido": str(obtido)[:80],
                      "esperado": str(esperado)[:80]})

    d = c.decidir("qual o IP da camera da garagem?")
    caso("fato conhecido → cerebro", d and d["modo"], "cerebro")
    caso("comando não é resposta", c.decidir("diga apenas: ok"), None)
    caso("conversa curta não é resposta", c.decidir("bom dia"), None)
    caso("ação vai para API (nunca local)", (c.decidir("crie um relatorio pdf") or {}).get("modo"), None)
    caso("ação sem base → None", c.decidir("implemente um blockchain"), None)
    caso("receita aprovada", (c.decidir("status do disco C:") or {}).get("modo"), "receita")

    caso("memória rejeita pergunta", sem.store("qual o ip da camera?"), False)
    caso("memória rejeita comando", sem.store("diga apenas ok"), False)
    caso("memória deduplica", sem.store("A camera da garagem fica no IP 192.168.15.7 e e Intelbras"), False)
    sem.store("O servidor fica no IP 10.0.0.5 hoje")
    caso("contradição aposenta antigo", sem.store("O servidor fica no IP 10.0.0.9 hoje"),
         True)
    caso("antigo não aparece na busca", any("10.0.0.5" in f for f in sem.search("servidor ip")), False)

    router = LLMRouter(load_settings())
    caso("classificador: ação → API",
         router.classify("abra o navegador e pesquise"), "analise_complexa")
    caso("classificador: conversa → local", router.classify("bom dia"), "resposta_simples")
    caso("classificador: resumo", router.classify("resuma este texto"), "resumo_curto")

    total = len(casos)
    ok = sum(1 for x in casos if x["ok"])
    resultado = {"total": total, "ok": ok, "falhas": total - ok,
                 "taxa": round(ok / total * 100, 1), "casos": casos}
    if json_saida:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        for x in casos:
            print(("  ✅ " if x["ok"] else "  ❌ ") + x["caso"] +
                  ("" if x["ok"] else f"  (obtido={x['obtido']}, esperado={x['esperado']})"))
        print(f"\n  {ok}/{total} ({resultado['taxa']}%)")
    return resultado


if __name__ == "__main__":
    r = executar("--json" in sys.argv)
    raise SystemExit(0 if r["falhas"] == 0 else 1)
