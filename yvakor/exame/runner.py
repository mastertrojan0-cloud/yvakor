"""YVAKOR — exame: roda as tarefas reais e mede se ele resolve.

Uso:  python -m yvakor.exame [--sem-navegador] [--casos id1,id2] [--sem-juiz]

Seguro: o orquestrador é o real, mas ferramentas que mudam o sistema
(apagar, mover, limpar, atualizar driver, controlar aparelho…) devolvem um
sucesso SIMULADO; shell só roda de verdade se for de leitura. Nada vai para o
histórico do usuário (private=True). Resultado em data/exame/.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime

from yvakor.config import ROOT
from yvakor.exame.casos import CASOS, PEDE_AVAL, Caso

DIR = ROOT / "data" / "exame"
FALHA_GERAL = [
    (r"(?i)interrompi a tarefa|excedi o limite", "estourou o tempo"),
    (r"(?i)n[aã]o executei nada|n[aã]o recebi sua aprova", "parou esperando aprovação"),
]
VERBOS_LEITURA = {"get", "select", "where", "format", "sort", "measure", "out",
                  "convertto", "convertfrom", "group", "test", "resolve", "write",
                  "foreach", "join", "split"}
SISTEMA_PERIGOSO = re.compile(r"\b(pnputil|dism|sfc|bcdedit|reg\s|winget\s+(install|"
                              r"upgrade|uninstall)|shutdown|format|diskpart|takeown)\b", re.I)

SIMULADOS_RESULTADO = {
    "limpar_temporarios": {"arquivos_apagados": 1200, "mb_liberados": 850.0,
                           "itens_restantes": 0},
    "esvaziar_lixeira": {"itens": 300, "mb_liberados": 1200.0},
    "organizar_executar": {"movidos": 170, "falhas": []},
    "sistema_drivers_atualizar": {"windows_update": "nenhuma atualização de driver pendente",
                                  "virtuais_ignorados": ["Microsoft RemoteFX Synth3D VSP "
                                                         "Driver: aparelho virtual"]},
}


# Mudam algo mas não estão nas listas do guard (auditado em 29/10).
SIMULAR_TAMBEM = {"organizar_desfazer", "arquivos_desfazer", "agenda_criar",
                  "cerebro_escrever", "navegador_enviar_arquivo", "navegador_js"}


def _shell_leitura(cmd: str) -> bool:
    from yvakor.tools.guard import destrutivo
    if destrutivo("executar_shell", cmd) or SISTEMA_PERIGOSO.search(cmd):
        return False
    verbos = {v.lower() for v in re.findall(r"\b([A-Za-z]+)-[A-Za-z]+\b", cmd)}
    return verbos <= VERBOS_LEITURA


# Ferramentas simuladas nesta rodada (o juiz sabe; o agente não vê marca —
# no 1º exame ele lia "simulado": true e, honesto, recusava-se a reportar).
SIMULADAS_NESTA_RODADA: list[str] = []


def _resultado_falso(nome: str) -> dict:
    SIMULADAS_NESTA_RODADA.append(nome)
    if nome in ("executar_shell", "executar_python"):
        return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}
    return {"ok": True, **SIMULADOS_RESULTADO.get(nome, {})}


def _simular(registry) -> set[str]:
    """Troca no registro as ferramentas que mudam o sistema por simulações."""
    from yvakor.tools.guard import destrutivo
    g = registry.guard
    alvos = (set(g.always_confirm) | set(g.guarded) | set(SIMULADOS_RESULTADO)
             | SIMULAR_TAMBEM) & set(registry.tools)
    for nome in alvos:
        original = registry.tools[nome]

        def falso(*a, _nome=nome, _orig=original, **k):
            texto = " ".join(str(v) for v in [*a, *k.values()])
            if _nome == "executar_shell" and _shell_leitura(texto):
                return _orig(*a, **k)
            if _nome == "executar_python" and not destrutivo("executar_python", texto):
                return _orig(*a, **k)
            return _resultado_falso(_nome)
        registry.tools[nome] = falso
    return alvos


JUIZ = """Você avalia um agente autônomo que roda no PC do usuário (pt-BR).
Ações que mudam o sistema (apagar, mover, limpar, atualizar driver) foram
SIMULADAS no teste e devolveram sucesso: trate-as como executadas. Julgue se o agente FEZ o que o usuário queria, usando
o contexto da conversa; se inventou dados; se devolveu ao usuário algo que
podia fazer sozinho (menu de opções, pedir confirmação já dada).

CONVERSA ANTERIOR:
{historico}

PEDIDO: {pedido}
FERRAMENTAS USADAS: {ferramentas}
RESPOSTA DO AGENTE:
{resposta}

Responda só JSON: {{"nota": 1-5, "motivo": "uma frase"}}"""


def _julgar(router, caso: Caso, ferramentas: list[str], resposta: str,
            provedor: str = "") -> tuple[int, str]:
    hist = "\n".join(f"Usuário: {u}\nAgente: {a}" for u, a in caso.historico) or "(nenhuma)"
    try:
        raw = router.complete_messages(
            "analise_complexa",
            [{"role": "system", "content": "Responda apenas JSON válido."},
             {"role": "user", "content": JUIZ.format(
                 historico=hist, pedido=caso.pedido,
                 ferramentas=(", ".join(ferramentas) or (
                     f"atalho direto '{provedor}' (lê os dados locais, sem modelo)"
                     if provedor in caso.atalhos else "nenhuma")),
                 resposta=resposta[:3000])}],
            forcar="deepseek", timeout=60)
        m = re.search(r"\{.*\}", raw or "", re.S)
        dados = json.loads(m.group(0)) if m else {}
        return int(dados.get("nota") or 0), str(dados.get("motivo") or "")[:200]
    except Exception as exc:
        return 0, f"juiz indisponível: {str(exc)[:80]}"


def _avaliar(caso: Caso, chamadas: list[dict], resposta: str, segundos: float,
             perguntas: int, provedor: str) -> list[tuple[str, bool]]:
    usadas = {c["nome"] for c in chamadas}
    args = " ".join(json.dumps(c.get("args", {}), ensure_ascii=False) for c in chamadas).lower()
    crit: list[tuple[str, bool]] = []
    atalho = provedor in caso.atalhos          # resposta direta legítima (sem LLM)
    for grupo in caso.deve_usar:
        crit.append((f"usou {' ou '.join(sorted(grupo))}", atalho or bool(usadas & grupo)))
    for proibida in sorted(caso.nao_usar):
        crit.append((f"não usou {proibida}", proibida not in usadas))
    for texto in caso.args_contem:
        crit.append((f"argumentos com \"{texto}\"", texto.lower() in args))
    for rx in caso.deve_conter:
        crit.append((f"resposta tem /{rx}/", bool(re.search(rx, resposta))))
    for rx in caso.nao_conter:
        nome = "não pediu aval/menu" if rx == PEDE_AVAL else f"resposta sem /{rx[:40]}/"
        crit.append((nome, not re.search(rx, resposta[-900:], re.I)))
    if caso.sem_ferramentas:
        crit.append(("respondeu sem ferramentas", not chamadas))
    elif caso.deve_usar and not atalho:
        crit.append(("não respondeu pelo modelo local sem ferramentas",
                     not (provedor == "ollama" and not chamadas)))
    crit.append((f"tempo ≤ {int(caso.max_s)} s", segundos <= caso.max_s))
    if not caso.sem_ferramentas:
        crit.append(("não parou para perguntar", perguntas == 0))
    for rx, nome in FALHA_GERAL:
        crit.append((f"não {nome}", not re.search(rx, resposta)))
    return crit


def rodar(ids: list[str] | None = None, navegador: bool = True,
          juiz: bool = True) -> dict:
    from yvakor import raciocinio
    from yvakor.orchestrator import Orchestrator

    casos = [c for c in CASOS if (not ids or c.id in ids)
             and (navegador or not c.navegador)]
    o = Orchestrator()
    simulados = _simular(o.tools)
    perguntas: list = []
    o.confirm_broker.request = lambda sid, acao, det: True
    o.confirm_broker.perguntar = lambda sid, tipo, *a, **k: (
        perguntas.append((sid, tipo, str(a[0] if a else "")[:100])) or
        {"allow": True, "resposta": raciocinio.OPCAO_APROVAR if tipo == "plano"
         else "decida você e execute"})
    provedor = {"ultimo": ""}
    registrar = o.telemetria.registrar

    def _tel(origem, ms, ok=True, **k):       # qual modelo respondeu cada caso
        provedor["ultimo"] = k.get("provedor") or origem
        return registrar(origem, ms, ok, **k)
    o.telemetria.registrar = _tel

    resultados = []
    try:
        for n, caso in enumerate(casos, 1):
            print(f"[{n}/{len(casos)}] {caso.id}: {caso.titulo} …", flush=True)
            chamadas: list[dict] = []
            antes = len(perguntas)
            provedor["ultimo"] = ""

            def ev(tipo, dado, _ch=chamadas):
                if tipo == "ferramenta" and isinstance(dado, dict):
                    _ch.append({"nome": dado.get("nome"), "args": dado.get("args") or {}})
            hist = []
            for u, a in caso.historico:
                hist += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
            t0 = time.time()
            try:
                resposta = o.process(caso.pedido, session_id=f"exame-{caso.id}",
                                     private=True, history_override=hist, on_event=ev)
            except Exception as exc:
                resposta = f"ERRO: {type(exc).__name__}: {exc}"
            seg = round(time.time() - t0, 1)
            nperg = len(perguntas) - antes
            crit = _avaliar(caso, chamadas, resposta, seg, nperg, provedor["ultimo"])
            nota_juiz, motivo = (_julgar(o.router, caso, [c["nome"] for c in chamadas],
                                         resposta, provedor["ultimo"]) if juiz else (0, ""))
            ok = sum(1 for _, v in crit if v)
            pct = ok / len(crit)
            nota = (1 + 4 * pct + nota_juiz) / 2 if nota_juiz else 1 + 4 * pct
            resultados.append({
                "id": caso.id, "titulo": caso.titulo, "categoria": caso.categoria,
                "origem": caso.origem, "aprovado": ok == len(crit),
                "criterios": [{"nome": c, "ok": v} for c, v in crit],
                "nota_criterios": round(1 + 4 * pct, 2), "nota_juiz": nota_juiz,
                "motivo_juiz": motivo, "nota": round(nota, 2), "segundos": seg,
                "provedor": provedor["ultimo"], "perguntas": nperg, "perguntas_detalhe": [f"{p[1]}: {p[2]}" for p in perguntas[antes:]],
                "ferramentas": [c["nome"] for c in chamadas],
                "chamadas": [{"nome": c["nome"],
                              "args": json.dumps(c["args"], ensure_ascii=False)[:300]}
                             for c in chamadas],
                "resposta": resposta[:1500]})
            falhou = [c for c, v in crit if not v]
            print(f"    {'✅' if not falhou else '❌'} nota {nota:.1f}  {seg}s  "
                  f"[{provedor['ultimo']}] {', '.join(c['nome'] for c in chamadas)[:120]}"
                  + (f"\n    falhou: {'; '.join(falhou)}" if falhou else ""), flush=True)
    finally:
        o.shutdown()
    return _relatorio(resultados, simulados)


def _relatorio(resultados: list[dict], simulados: set[str]) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    quando = datetime.now()
    n = len(resultados) or 1
    resumo = {
        "quando": quando.isoformat(timespec="seconds"),
        "casos": len(resultados),
        "aprovados": sum(r["aprovado"] for r in resultados),
        "nota": round(sum(r["nota"] for r in resultados) / n, 2),
        "nota_juiz": round(sum(r["nota_juiz"] for r in resultados) / n, 2),
        "tempo_medio_s": round(sum(r["segundos"] for r in resultados) / n, 1),
        "por_categoria": {},
    }
    for r in resultados:
        cat = resumo["por_categoria"].setdefault(r["categoria"], {"casos": 0, "aprovados": 0})
        cat["casos"] += 1
        cat["aprovados"] += r["aprovado"]
    historico = DIR / "historico.jsonl"
    anterior = None
    if historico.exists():
        linhas = [json.loads(x) for x in historico.read_text(encoding="utf-8").splitlines() if x]
        anterior = linhas[-1] if linhas else None
    base = DIR / quando.strftime("exame_%Y%m%d_%H%M")
    base.with_suffix(".json").write_text(json.dumps(
        {"resumo": resumo, "resultados": resultados, "simulados": sorted(simulados)},
        ensure_ascii=False, indent=1), encoding="utf-8")
    with historico.open("a", encoding="utf-8") as f:
        f.write(json.dumps(resumo, ensure_ascii=False) + "\n")
    md = [f"# Exame do YVAKOR — {quando:%d/%m/%Y %H:%M}", "",
          f"**Nota: {resumo['nota']}/5** · aprovados {resumo['aprovados']}/{resumo['casos']} · "
          f"juiz {resumo['nota_juiz']}/5 · tempo médio {resumo['tempo_medio_s']} s"]
    if anterior:
        md.append(f"\nAnterior ({anterior['quando'][:16]}): nota {anterior['nota']} · "
                  f"aprovados {anterior['aprovados']}/{anterior['casos']}")
    md += ["", "| Caso | Nota | Tempo | Modelo | Falhas |", "|---|---|---|---|---|"]
    for r in resultados:
        falhas = "; ".join(c["nome"] for c in r["criterios"] if not c["ok"]) or "—"
        md.append(f"| {'✅' if r['aprovado'] else '❌'} {r['titulo']} | {r['nota']} | "
                  f"{r['segundos']} s | {r['provedor']} | {falhas} |")
    base.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    resumo["relatorio"] = str(base.with_suffix(".md"))
    resumo["anterior"] = anterior
    return resumo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m yvakor.exame")
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--sem-juiz", action="store_true")
    ap.add_argument("--casos", default="")
    a = ap.parse_args(argv)
    ids = [x.strip() for x in a.casos.split(",") if x.strip()] or None
    r = rodar(ids, navegador=not a.sem_navegador, juiz=not a.sem_juiz)
    print(f"\nNOTA {r['nota']}/5 · aprovados {r['aprovados']}/{r['casos']} · "
          f"juiz {r['nota_juiz']} · {r['tempo_medio_s']} s/caso\nRelatório: {r['relatorio']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
