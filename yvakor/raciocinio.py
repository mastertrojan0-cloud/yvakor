"""
YVAKOR — Método de raciocínio do agente

Inspirado no jeito de trabalhar do Claude (o comportamento observável, não o
modelo): entender o pedido real → planejar tarefas de vários passos → agir um
passo por vez lendo cada observação → tratar erro como diagnóstico, não como
repetição → verificar com evidência antes de declarar pronto → responder de
forma honesta, começando pelo resultado.

Partes:
  METODO / METODO_COMPACTO  → entram no system prompt (como pensar).
  precisa_planejar / PEDIR_PLANO / ler_plano / bloco_plano
                            → plano explícito antes de tarefas de vários passos.
  Reflexao                  → acompanha falhas e anexa à observação uma
                              orientação (não repetir, mudar abordagem, parar).
  pedido_verificacao        → antes da resposta final, confere o plano e o
                              critério de pronto contra o que foi observado.
"""
from __future__ import annotations

import json
import re

METODO = """
## MÉTODO DE TRABALHO (pense assim antes e durante cada tarefa)
1. ENTENDA o pedido real: qual resultado o usuário quer no fim e que
   restrições ele deu. Pergunta → responda. Tarefa → execute.
2. FATOS ANTES DE SUPOSIÇÕES: se dá para descobrir com uma ferramenta (ler o
   arquivo, ver a página, listar a pasta), descubra. Nunca invente resultados,
   caminhos, números, refs ou conteúdo de páginas.
3. PLANEJE tarefas de vários passos: a sequência mínima até o resultado. Faça
   um passo por vez e leia a observação inteira antes de decidir o próximo.
4. ATUALIZE o que você sabe a cada observação: deu certo? O estado mudou como
   esperado? Se não, descubra o porquê antes de tentar de novo.
5. ERRO = DIAGNÓSTICO, não repetição. Leia a mensagem de erro, ajuste a causa
   (outro alvo, outro argumento, outra ferramenta). Depois de 2–3 falhas do
   mesmo tipo, pare e explique o bloqueio ao usuário.
6. VERIFIQUE antes de dizer "pronto": confirme por uma observação que o
   resultado existe (arquivo criado, página mudou, valor aparece na tela).
7. CUIDADO com o irreversível ou externo (enviar, comprar, apagar, publicar):
   faça exatamente o que foi pedido, nada além.
8. TERMINE O TRABALHO, NÃO OFEREÇA. Se o próximo passo é seguro (pesquisar,
   abrir, ler, rolar, digitar um CEP ou termo de busca, comparar), FAÇA antes
   de responder — não termine com "posso tentar…?", "se quiser, eu pesquiso…"
   nem mande o usuário fazer o que você consegue fazer. Devolva ao usuário só
   o que é dele: login/senha, captcha, pagamento, envio/compra, gosto pessoal.
9. MENSAGEM CURTA = CONTINUAÇÃO. "2", "sim", um CEP, um número ou "consulta"
   respondem à sua última pergunta ou retomam a tarefa anterior: use o dado e
   siga a tarefa, sem pedir de novo o que já foi dito.
10. RESPOSTA FINAL honesta e direta: comece pelo resultado; diga o que fez, o
   que NÃO conseguiu e por quê, e qualquer suposição feita. Sem enrolação, sem
   repetir a pergunta, sem afirmar o que as ferramentas não confirmaram.
Ferramentas de apoio (quando estiverem na lista): `pensar` para raciocinar
antes de uma decisão difícil ou depois de um erro; `tarefas_checklist` para
manter o progresso de tarefas com 3+ passos visível ao usuário; `arquivos_grep`
para achar um texto DENTRO de arquivos; `web_ler` para ler artigos e
documentação sem abrir o navegador.
"""

METODO_COMPACTO = """## MÉTODO
- Descubra com ferramentas em vez de chutar; não invente resultados.
- Um passo por vez; se falhar, mude a abordagem (não repita igual).
- Só diga que fez o que uma observação confirmou; diga o que não conseguiu.
- Faça o próximo passo seguro em vez de oferecer ("posso…?", "se quiser…").
"""


# --------------------------------------------------------------------- plano
_CONECTORES = re.compile(
    r"(\be (depois|em seguida|então|entao|tamb[eé]m)\b|\bdepois\b|"
    r"\bem seguida\b|\bap[oó]s\b|\bpasso a passo\b|\betapas?\b|;|\n\s*(\d+[.)]|-)\s)",
    re.I)
# Radicais de verbos de ação (imperativo/infinitivo: "extraia", "extrair"…).
_VERBOS = re.compile(
    r"\b(abr[aei]|acess|pesquis|busqu|busc[ae]|procur|preench|cliqu|clic[ae]|"
    r"envi[ae]|baix[ae]|salv[ae]|cri[ae]|ger[ae]|compar|analis|extra[ií]|"
    r"resum|escrev|edit[ae]|mov[ae]|copi[ae]|consult|mont[ae]|instal|"
    r"configur|verifi|list[ae]|organiz|calcul|vej[ae]|leia|ler\b|traduz|"
    r"respond|apag|delet|instal|cadastr|agend|imprim)\w*", re.I)
_CONVERSA = re.compile(
    r"^\s*(oi|ol[aá]|bom dia|boa (tarde|noite)|obrigad[oa]|valeu|ok|blz|"
    r"beleza|tudo bem|sim|n[aã]o)\b[\s!.?]*$", re.I)


def precisa_planejar(mensagem: str) -> bool:
    """Tarefa de vários passos? (heurística barata, sem chamar o modelo)."""
    texto = (mensagem or "").strip()
    if len(texto) < 25 or _CONVERSA.match(texto):
        return False
    verbos = {m.group(0).lower()[:5] for m in _VERBOS.finditer(texto)}
    if len(verbos) >= 2:                  # duas ações ou mais = vários passos
        return True
    if verbos and _CONECTORES.search(texto):
        return True
    return len(texto) > 280 and len(verbos) >= 1


PEDIR_PLANO = (
    "ANTES DE AGIR, planeje. Responda SOMENTE com um JSON neste formato, sem "
    "texto extra e sem chamar ferramenta ainda:\n"
    '{"objetivo":"o resultado final que o usuário quer, em 1 frase",'
    '"pronto_quando":"como saber, por uma observação, que terminou",'
    '"passos":["passo 1 (ferramenta prevista)","passo 2", "..."],'
    '"riscos":"o que pode dar errado ou exigir o usuário (login, captcha, '
    'confirmação) — ou vazio"}\n'
    "Use de 2 a 7 passos, cada um curto e concreto. Não invente dados que "
    "ainda não foram observados.")


def ler_plano(raw: str) -> dict | None:
    """Extrai o plano JSON da resposta do modelo (tolerante a texto em volta)."""
    if not raw:
        return None
    dec = json.JSONDecoder()
    i = 0
    while True:
        j = raw.find("{", i)
        if j < 0:
            return None
        try:
            obj, fim = dec.raw_decode(raw[j:])
        except Exception:
            i = j + 1
            continue
        i = j + fim
        if not isinstance(obj, dict) or "acao" in obj:
            continue
        passos = obj.get("passos") or obj.get("etapas") or obj.get("steps")
        if isinstance(passos, str):
            passos = [p.strip(" -•") for p in re.split(r"\n|;", passos) if p.strip(" -•")]
        if not isinstance(passos, list):
            continue
        passos = [str(p).strip()[:160] for p in passos if str(p).strip()][:7]
        if not passos:
            continue
        return {"objetivo": str(obj.get("objetivo") or obj.get("goal") or "")[:240],
                "pronto_quando": str(obj.get("pronto_quando") or
                                     obj.get("criterio") or "")[:240],
                "passos": passos,
                "riscos": str(obj.get("riscos") or "")[:240]}


def bloco_plano(plano: dict, aprovado: bool = False,
                ajustes: list[str] | None = None) -> str:
    linhas = ["PLANO DE TRABALHO (feito por você antes de agir; siga-o, mas "
              "ajuste se uma observação mostrar que ele está errado):"]
    if aprovado:
        linhas[0] = ("PLANO DE TRABALHO — APROVADO PELO USUÁRIO. Siga-o; se uma "
                     "observação mostrar que um passo é impossível, diga isso em "
                     "vez de fazer algo diferente do aprovado:")
    for ajuste in ajustes or []:
        linhas.append(f"Ajuste pedido pelo usuário: {ajuste}")
    if plano.get("objetivo"):
        linhas.append(f"Objetivo: {plano['objetivo']}")
    for n, passo in enumerate(plano.get("passos") or [], 1):
        linhas.append(f"{n}. {passo}")
    if plano.get("pronto_quando"):
        linhas.append(f"Pronto quando: {plano['pronto_quando']}")
    if plano.get("riscos"):
        linhas.append(f"Atenção: {plano['riscos']}")
    linhas.append("Agora execute o passo 1.")
    return "\n".join(linhas)


# --------------------------------------------------------------- modo plano
# O usuário pede para ver o plano antes ("modo plano", "me mostre o plano",
# "só execute depois que eu aprovar"…) → sempre pede aprovação.
_PEDIU_PLANO = re.compile(
    r"(modo plano|me mostr[ae] o plano|mostr[ae]-me o plano|"
    r"planej[ae] (antes|primeiro)|fa[cç]a (um|o) plano|monte (um|o) plano|"
    r"antes de (executar|fazer|come[cç]ar)[^.\n]{0,40}(plano|mostr|aprov)|"
    r"(s[oó]|somente) (execut|fa[cç])\w* (depois|quando) (que )?eu aprov)", re.I)
# Plano com efeito difícil de desfazer ou externo → pede aprovação no modo auto.
_RISCO = re.compile(
    r"\b(envi[ae]r?\b|envio|mand[ae]r? (o |a |um |uma )?(e-?mail|mensagem)|"
    r"apag\w*|exclu\w*|delet\w*|remov\w*|compr[ae]r?\b|compra\b|pag[ae]r?\b|"
    r"pagamento|transfer\w*|publi\w*|postar|instal\w*|desinstal\w*|format\w*|"
    r"sobrescrev\w*|mover|mova|renome\w*|commit|push|deploy|cancelar assinatura|"
    r"agend\w* (reuni|consulta|pagamento))", re.I)

OPCAO_APROVAR = "Aprovar e executar"
OPCAO_CANCELAR = "Cancelar"
OPCOES_PLANO = [OPCAO_APROVAR, OPCAO_CANCELAR]


def pediu_modo_plano(pedido: str) -> bool:
    return bool(_PEDIU_PLANO.search(pedido or ""))


def pedido_arriscado(pedido: str) -> bool:
    """Pedido de um passo só, mas com efeito difícil de desfazer ("apague os
    .tmp"): precisa de plano para o modo plano poder pedir aprovação."""
    return bool(_RISCO.search(pedido or ""))


def plano_arriscado(plano: dict, pedido: str = "") -> bool:
    texto = " ".join([pedido or "", plano.get("objetivo") or "",
                      *(plano.get("passos") or [])])
    return bool(_RISCO.search(texto))


def texto_plano(plano: dict) -> str:
    """O plano como o usuário lê na interface (sem jargão de ferramenta)."""
    linhas = []
    if plano.get("objetivo"):
        linhas.append(f"Objetivo: {plano['objetivo']}")
    linhas += [f"{n}. {p}" for n, p in enumerate(plano.get("passos") or [], 1)]
    if plano.get("pronto_quando"):
        linhas.append(f"Pronto quando: {plano['pronto_quando']}")
    if plano.get("riscos"):
        linhas.append(f"Atenção: {plano['riscos']}")
    linhas.append("Escreva abaixo se quiser ajustar algo.")
    return "\n".join(linhas)


def ler_decisao(res: dict | None) -> tuple[str, str]:
    """Resposta do usuário ao plano → ("aprovar"|"cancelar"|"ajustar"|
    "sem_resposta", texto do ajuste)."""
    if not res:
        return "sem_resposta", ""
    resposta = (res.get("resposta") or "").strip()
    if not res.get("allow") or resposta.lower() == OPCAO_CANCELAR.lower():
        return "cancelar", ""
    if not resposta or resposta.lower() in (OPCAO_APROVAR.lower(), "aprovar", "ok",
                                            "sim", "pode", "pode seguir", "segue"):
        return "aprovar", ""
    return "ajustar", resposta


def pedido_ajuste(plano: dict, ajuste: str) -> str:
    return (f"O usuário leu seu plano e pediu este AJUSTE: \"{ajuste}\".\n"
            "Plano anterior: " + json.dumps(plano, ensure_ascii=False) + "\n"
            + PEDIR_PLANO)


def pedido_verificacao(plano: dict | None) -> str:
    """Pede a conferência final: o que foi pedido × o que as observações provam."""
    partes = ["ANTES DE RESPONDER, confira seu trabalho contra as OBSERVAÇÕES "
              "desta tarefa:"]
    if plano:
        if plano.get("objetivo"):
            partes.append(f"- Objetivo: {plano['objetivo']}")
        if plano.get("pronto_quando"):
            partes.append(f"- Pronto quando: {plano['pronto_quando']}")
        partes.append("- Passos: " + " | ".join(plano.get("passos") or []))
    from yvakor.ferramentas_claude import ESTADOS, checklist_atual
    lista = checklist_atual()
    if lista:
        partes.append("- Checklist: " + " | ".join(
            f"{ESTADOS[i['estado']]} {i['texto']}" for i in lista))
        if any(i["estado"] in ("pendente", "fazendo") for i in lista):
            partes.append("  Há itens não concluídos: faça-os agora, ou diga ao "
                          "usuário por que não foi possível.")
    partes.append(
        "Se falta um passo que ainda dá para fazer, chame a ferramenta agora. "
        "Se está concluído (ou bloqueado), escreva a RESPOSTA FINAL ao usuário "
        "em texto puro: comece pelo resultado, cite só o que as observações "
        "confirmam e diga claramente o que não foi possível e por quê. Não "
        "mencione esta conferência nem escreva 'tarefa concluída' ou 'nada "
        "ficou pendente': vá direto ao resultado.")
    return "\n".join(partes)


# ------------------------------------------------- dados já dados pelo usuário
_CEP = re.compile(r"^\s*(\d{5}-?\d{3})\s*$")


def dados_informados(history: list[dict], maximo: int = 6) -> str:
    """Respostas curtas que o usuário já deu nesta conversa ("2", um CEP,
    "consulta"). O modelo perdia esses dados no meio do histórico e dizia
    "não tenho o seu CEP" dois turnos depois de recebê-lo."""
    curtas = []
    for item in history[:-1]:                      # a última é o pedido atual
        texto = item.get("content")
        if item.get("role") != "user" or not isinstance(texto, str):
            continue
        texto = texto.strip()
        if not texto or len(texto) > 30:
            continue
        curtas.append(f"\"{texto}\" (provável CEP)" if _CEP.match(texto)
                      else f"\"{texto}\"")
    if not curtas:
        return ""
    return ("\n\n## DADOS QUE O USUÁRIO JÁ INFORMOU NESTA CONVERSA\n"
            "Respostas curtas dele, em ordem: " + ", ".join(curtas[-maximo:])
            + ". Use-as na tarefa; não peça de novo nem diga que não as tem.")


# ------------------------------------------------------------------ reflexão
def _assinatura(nome: str, args) -> str:
    try:
        return nome + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return nome + str(args)


def _erro(resultado) -> str:
    if isinstance(resultado, dict):
        return str(resultado.get("error") or resultado.get("erro") or "")[:160]
    return ""


class Reflexao:
    """Acompanha os resultados das ferramentas e devolve uma orientação curta
    para anexar à observação quando algo falha (ou falha de novo)."""

    LIMITE_SEGUIDAS = 3
    # Leituras cujo resultado não muda entre um passo e outro: repetir a mesma
    # chamada só gasta passo (o teste real listou a mesma pasta duas vezes).
    # navegador_ver fica de fora: a página muda depois de cada ação.
    LEITURAS_ESTAVEIS = ("arquivos_listar", "arquivos_ler", "arquivos_grep",
                         "arquivos_buscar", "arquivos_info", "web_ler",
                         "http_get", "cerebro_buscar", "pesquisa_web",
                         "listar_diretorio", "ler_arquivo_local")

    # Leituras da mesma página com argumentos levemente diferentes (seletor
    # body/main, texto/html…): na consulta de planos da Nio foram 8 extrações
    # seguidas de uma página que só mostra preço depois de digitar o CEP.
    LEITURAS_DE_PAGINA = ("navegador_extrair", "web_ler", "http_get")
    LIMITE_LEITURAS = 3

    def __init__(self) -> None:
        self.falhas: dict[str, int] = {}
        self.sucessos: set[str] = set()
        self.seguidas = 0
        self.ultima = ""
        self.mesma_seguidas = 0

    def registrar(self, nome: str, args, resultado) -> str:
        ok = isinstance(resultado, dict) and bool(resultado.get("ok"))
        self.mesma_seguidas = self.mesma_seguidas + 1 if nome == self.ultima else 1
        self.ultima = nome
        if nome == "navegador_ver" and self.mesma_seguidas >= self.LIMITE_LEITURAS:
            # olhar a página é normal entre ações; 3 seguidas sem agir é laço
            # (na consulta da Nio foram 5 e a tarefa acabou sem digitar o CEP)
            return ("\nREFLEXÃO: você olhou a página {n} vezes seguidas sem agir. "
                    "Use as refs que já tem: digite/preencha o campo (ex.: CEP), "
                    "clique ou role AGORA; se não houver o que fazer aqui, troque "
                    "de fonte.").format(n=self.mesma_seguidas)
        if (nome in self.LEITURAS_DE_PAGINA
                and self.mesma_seguidas >= self.LIMITE_LEITURAS):
            self.seguidas = 0 if ok else self.seguidas
            return ("\nREFLEXÃO: {n} leituras seguidas com {f}. Ler de novo não "
                    "vai mostrar o que falta: se o dado depende de interação "
                    "(digitar CEP/busca, clicar em 'ver planos', rolar), use "
                    "navegador_ver para achar o campo e AJA nele; senão troque de "
                    "fonte (outro site, pesquisa_web). Não extraia esta página de novo."
                    ).format(n=self.mesma_seguidas, f=nome)
        if ok:
            self.seguidas = 0
            if nome not in self.LEITURAS_ESTAVEIS:
                return ""
            chave = _assinatura(nome, args)
            if chave in self.sucessos:
                return ("\nREFLEXÃO: você já tinha feito esta MESMA leitura com "
                        "sucesso; o resultado não mudou. Use o que já tem e "
                        "avance (ou responda).")
            self.sucessos.add(chave)
            return ""
        self.seguidas += 1
        chave = _assinatura(nome, args)
        self.falhas[chave] = self.falhas.get(chave, 0) + 1
        if self.seguidas >= self.LIMITE_SEGUIDAS:
            return ("\nREFLEXÃO: {n} falhas seguidas. Pare de tentar às cegas: "
                    "leia o estado atual (ex.: navegador_ver, arquivos_listar) "
                    "para entender o que mudou, ou responda ao usuário "
                    "explicando o que bloqueou e o que ele precisa fazer."
                    ).format(n=self.seguidas)
        if self.falhas[chave] >= 2:
            return ("\nREFLEXÃO: esta chamada IDÊNTICA já falhou antes. Não "
                    "repita: mude o alvo, os argumentos ou a ferramenta.")
        return ("\nREFLEXÃO: falhou. Identifique a causa provável no erro acima "
                "e ajuste antes do próximo passo (não repita igual).")
