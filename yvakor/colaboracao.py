"""YVAKOR — subagentes paralelos e avaliação de qualidade."""
from __future__ import annotations

import re

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

_log = logging.getLogger(__name__)


def _json_ou_texto(bruto: str) -> dict:
    try:
        i, f = bruto.find("{"), bruto.rfind("}")
        if i >= 0 and f > i:
            return json.loads(bruto[i:f + 1])
    except Exception:
        _log.debug("exceção ignorada", exc_info=True)
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


def avaliar_resposta(router, pergunta: str, resposta: str, contexto: str = "",
                     ferramentas: list[str] | None = None) -> dict:
    """Nota 1-5 + problemas + uma LIÇÃO geral (o aprendizado usa a lição).
    Antes o avaliador via só pergunta e resposta: "2", "sim" ou um CEP viravam
    "pergunta ambígua — peça esclarecimento", o oposto do que o usuário quer,
    e ele não sabia se a resposta tinha usado alguma ferramenta."""
    usadas = ", ".join(ferramentas or []) or "NENHUMA"
    prompt = (
        "Você avalia o YVAKOR, um agente pessoal que EXECUTA tarefas com "
        "ferramentas (navegador, pesquisa, arquivos). O dono quer autonomia: "
        "mensagens curtas (\"2\", \"sim\", um CEP, \"continua\") são continuação "
        "da conversa e devem ser atendidas usando o contexto, sem pedir "
        "esclarecimento; dados já ditos na conversa não devem ser pedidos de "
        "novo; fato concreto (preço, endereço, telefone) sem ferramenta usada "
        "é provavelmente inventado; oferecer em vez de fazer é falha.\n"
        "Avalie de 1 a 5: correção, utilidade, aderência e clareza. Responda "
        "SOMENTE JSON:\n"
        '{"nota": 1-5, "correcao": 1-5, "utilidade": 1-5, "aderencia": 1-5, '
        '"clareza": 1-5, "problemas": ["..."], "melhoria": "...", '
        '"licao": "regra GERAL e curta para o agente não repetir o erro em '
        'tarefas parecidas (ex.: \\"Quando o site só mostra preço após o CEP, '
        'digite o CEP no campo em vez de extrair a página de novo\\"), ou \\"\\" '
        'se a resposta foi boa ou o erro não se generaliza"}\n\n'
        + (f"CONVERSA ANTERIOR (resumo):\n{contexto[-2500:]}\n\n" if contexto else "")
        + f"FERRAMENTAS USADAS NESTA RESPOSTA: {usadas}\n\n"
        f"PERGUNTA ATUAL: {pergunta}\n\nRESPOSTA: {resposta[:6000]}")
    try:
        mensagens = [{"role": "system", "content": "Responda apenas JSON válido."},
                     {"role": "user", "content": prompt}]
        dados, bruto = None, ""
        for tentativa in range(2):       # o modelo local às vezes foge do formato: 1 nova chance
            bruto = router.complete_messages("analise_complexa", mensagens) or ""
            dados = _json_ou_texto(bruto)
            if dados:
                break
            mensagens = mensagens + [
                {"role": "assistant", "content": bruto[:400]},
                {"role": "user", "content": 'Responda SOMENTE o JSON, ex.: {"nota": 4, "problemas": [], '
                                            '"melhoria": ""}'}]
        if not dados:
            m = re.search(r"nota\D{0,15}([1-5])", bruto, re.I)      # último recurso: a nota solta no texto
            if not m:
                return {"ok": False, "erro": "avaliação não retornou JSON"}
            dados = {"nota": int(m.group(1)), "aproximada": True}
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
