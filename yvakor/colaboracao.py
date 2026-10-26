"""YVAKOR — subagentes paralelos e avaliação de qualidade."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed


def _json_ou_texto(bruto: str) -> dict:
    try:
        i, f = bruto.find("{"), bruto.rfind("}")
        if i >= 0 and f > i:
            return json.loads(bruto[i:f + 1])
    except Exception:
        pass
    return {}


def subagentes(router, tarefas: str, contexto: str = "",
               max_workers: int = 3) -> dict:
    lista = [t.strip() for t in str(tarefas or "").replace(";", "|").split("|")
             if t.strip()]
    if not lista:
        return {"ok": False, "erro": "informe ao menos uma tarefa"}
    lista = lista[:6]

    def executar(tarefa: str) -> dict:
        prompt = f"{contexto}\n\nTAREFA: {tarefa}".strip()
        try:
            r = router.complete_messages(
                "analise_complexa",
                [{"role": "system", "content":
                  "Você é um subagente especialista. Responda de forma objetiva, "
                  "em português, sem inventar fatos."},
                 {"role": "user", "content": prompt}]) or ""
            return {"tarefa": tarefa, "ok": True, "resposta": r.strip()}
        except Exception as exc:
            return {"tarefa": tarefa, "ok": False,
                    "erro": f"{type(exc).__name__}: {exc}"}

    respostas = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(lista)))) as ex:
        futuros = [ex.submit(executar, t) for t in lista]
        for fut in as_completed(futuros):
            respostas.append(fut.result())
    ordem = {t: i for i, t in enumerate(lista)}
    respostas.sort(key=lambda x: ordem.get(x["tarefa"], 99))
    return {"ok": True, "subagentes": respostas}


def avaliar_resposta(router, pergunta: str, resposta: str) -> dict:
    prompt = (
        "Avalie a resposta abaixo de 1 a 5 nos critérios: correção, "
        "utilidade, aderência à pergunta e clareza. Responda SOMENTE JSON:\n"
        '{"nota": 1-5, "correcao": 1-5, "utilidade": 1-5, "aderencia": 1-5, '
        '"clareza": 1-5, "problemas": ["..."], "melhoria": "..."}\n\n'
        f"PERGUNTA: {pergunta}\n\nRESPOSTA: {resposta[:6000]}")
    try:
        bruto = router.complete_messages(
            "analise_complexa",
            [{"role": "system", "content": "Responda apenas JSON válido."},
             {"role": "user", "content": prompt}]) or ""
        dados = _json_ou_texto(bruto)
        if not dados:
            return {"ok": False, "erro": "avaliação não retornou JSON"}
        dados["ok"] = True
        return dados
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def registrar_ferramentas(tools, router):
    def paralelo(tarefas: str, contexto: str = "", max_workers: int = 3) -> dict:
        return subagentes(router, tarefas, contexto, max_workers)

    def avaliar(pergunta: str, resposta: str) -> dict:
        return avaliar_resposta(router, pergunta, resposta)

    tools.register("subagentes", paralelo,
                   "Executa análises independentes em paralelo (subagentes). "
                   "Separe as tarefas por |.",
                   {"tarefas": "str", "contexto": "str?",
                    "max_workers": "int?"})
    tools.register("avaliar_resposta", avaliar,
                   "Avalia qualidade/correção/utilidade de uma resposta (1-5).",
                   {"pergunta": "str", "resposta": "str"})
