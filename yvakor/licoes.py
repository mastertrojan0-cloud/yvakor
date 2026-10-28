"""
YVAKOR — Lições aprendidas (memória de erros e preferências)

Inspirado na memória de feedback do Claude: o que deu errado e o que o
usuário corrigiu vira uma regra curta, guardada em data/licoes.json, e as
regras relevantes entram no system prompt das próximas tarefas.

De onde vêm as lições:
  erro        → a autoavaliação deu nota baixa e devolveu uma "licao" geral;
  correcao    → o usuário corrigiu a resposta anterior ("já mandei o CEP",
                "não era isso", "ja esta na conversa, aprenda");
  preferencia → instrução permanente ("tem que mostrar sempre na tela",
                "de agora em diante…", "lembre-se…").

Antes disso, resposta ruim era só descartada ("não vira fato nem skill") e
o mesmo erro se repetia na conversa seguinte.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from pathlib import Path

from yvakor import seguro
from yvakor.config import ROOT

ARQ = ROOT / "data" / "licoes.json"
MAX_LICOES = 80
SIMILAR = 0.55          # Jaccard acima disso = mesma lição (soma reforço)

_STOP = set("""a o e é de do da dos das em no na nos nas um uma uns umas para pra
por com sem que se ao aos à às ou mas como quando onde já não nao mais menos muito
seu sua seus suas meu minha isso isto esse essa este esta ele ela eles elas você
voce vc eu me te lhe nós nos foi ser ter tem está esta estão era sobre então entao
""".split())

# Correção da resposta anterior ou instrução permanente do usuário.
_CORRECAO = re.compile(
    r"(^\s*(n[aã]o|errado|errou)\b|j[aá] (mandei|disse|falei|te passei|informei|"
    r"est[aá] na conversa)|n[aã]o (era|foi) isso|n[aã]o (é|e) isso|"
    r"voc[eê] (esqueceu|n[aã]o fez|parou|inventou)|de novo\b|"
    r"\baprend[ae]\b|por que (voc[eê] )?(n[aã]o|parou)|continua (sem|n[aã]o))",
    re.I)
_PREFERENCIA = re.compile(
    r"(\bsempre\b|\bnunca\b|toda vez|daqui (pra|para) frente|de agora em diante|"
    r"\blembr[ae](-se)?\b|tem que\b|n[aã]o (quero|gosto) que)", re.I)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _tokens(texto: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", _norm(texto)) if w not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def tipo_feedback(mensagem: str) -> str | None:
    """"correcao", "preferencia" ou None para a mensagem do usuário."""
    m = (mensagem or "").strip()
    if not m or len(m) > 400:
        return None
    if _CORRECAO.search(m):
        return "correcao"
    if _PREFERENCIA.search(m):
        return "preferencia"
    return None


class Licoes:
    def __init__(self, arq: Path | None = None):
        self.arq = Path(arq or ARQ)
        self._lock = threading.Lock()

    def todas(self) -> list[dict]:
        dados = seguro.ler_json(self.arq, [])
        return dados if isinstance(dados, list) else []

    def _gravar(self, lista: list[dict]) -> None:
        seguro.gravar_json(self.arq, lista)

    def registrar(self, texto: str, origem: str = "erro", exemplo: str = "") -> dict | None:
        """Guarda a lição (ou reforça uma parecida). Devolve o item."""
        texto = " ".join(str(texto or "").split())[:300]
        if len(texto) < 15:
            return None
        tk = _tokens(texto)
        agora = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            lista = self.todas()
            for item in lista:
                if _jaccard(tk, _tokens(item.get("texto", ""))) >= SIMILAR:
                    item["vezes"] = int(item.get("vezes", 1)) + 1
                    item["ultima"] = agora
                    if origem in ("correcao", "preferencia"):
                        item["origem"] = origem          # o usuário pesa mais
                    self._gravar(lista)
                    return item
            item = {"id": f"L{int(time.time() * 1000) % 10**10}", "texto": texto,
                    "origem": origem, "vezes": 1, "criada": agora, "ultima": agora,
                    "exemplo": " ".join(str(exemplo or "").split())[:160]}
            lista.append(item)
            if len(lista) > MAX_LICOES:              # sai a menos reforçada e mais velha
                lista.sort(key=lambda x: (x.get("origem") == "erro",
                                          -int(x.get("vezes", 1)), x.get("ultima", "")))
                lista = lista[:MAX_LICOES]
            self._gravar(lista)
            return item

    def remover(self, ident: str) -> bool:
        with self._lock:
            lista = self.todas()
            nova = [x for x in lista if x.get("id") != ident]
            if len(nova) == len(lista):
                return False
            self._gravar(nova)
            return True

    def relevantes(self, mensagem: str, k: int = 5) -> list[dict]:
        """Preferências do usuário entram sempre (até 3); as demais por
        semelhança com o pedido, pesadas pelo reforço."""
        lista = self.todas()
        prefs = sorted((x for x in lista if x.get("origem") == "preferencia"),
                       key=lambda x: x.get("ultima", ""), reverse=True)[:3]
        tk = _tokens(mensagem)
        pontuadas = []
        for x in lista:
            if x in prefs:
                continue
            base = _tokens(x.get("texto", "") + " " + x.get("exemplo", ""))
            comum = len(tk & base)
            if comum:
                peso = comum * (1.5 if x.get("origem") == "correcao" else 1.0)
                pontuadas.append((peso + 0.3 * min(int(x.get("vezes", 1)), 5), x))
        pontuadas.sort(key=lambda p: p[0], reverse=True)
        escolhidas = prefs + [x for _, x in pontuadas[:max(0, k - len(prefs))]]
        # As lições são regras de comportamento ("use os dados já dados",
        # "preencha o campo em vez de pedir print") que raramente repetem as
        # palavras do pedido: as vagas que sobram vão para as mais reforçadas
        # e recentes (correção do usuário primeiro).
        resto = sorted((x for x in lista if x not in escolhidas),
                       key=lambda x: (x.get("origem") == "correcao",
                                      int(x.get("vezes", 1)), x.get("ultima", "")),
                       reverse=True)
        return escolhidas + resto[:max(0, k - len(escolhidas))]

    def bloco(self, mensagem: str, k: int = 5) -> str:
        itens = self.relevantes(mensagem, k)
        if not itens:
            return ""
        rotulo = {"preferencia": "preferência do usuário", "correcao": "o usuário corrigiu",
                  "erro": "erro seu"}
        linhas = [f"- {x['texto']} ({rotulo.get(x.get('origem'), 'lição')})" for x in itens]
        return ("## LIÇÕES APRENDIDAS (de erros seus e correções do usuário — siga-as)\n"
                + "\n".join(linhas))


PEDIR_LICAO = (
    "O usuário respondeu ao agente YVAKOR com uma {tipo}. Transforme isso em UMA "
    "regra geral, curta e acionável (máx. 2 frases, em português, no imperativo), "
    "que evite o mesmo problema em tarefas parecidas no futuro. Não inclua dados "
    "pessoais (CPF, datas, nomes, CEP) na regra. Se não houver nada a aprender, "
    "devolva texto vazio. Responda SOMENTE JSON: {{\"licao\": \"...\"}}\n\n"
    "PEDIDO ANTERIOR DO USUÁRIO: {pedido}\n\nRESPOSTA ANTERIOR DO AGENTE: {resposta}\n\n"
    "MENSAGEM DO USUÁRIO AGORA: {mensagem}")


def destilar_feedback(router, tipo: str, pedido: str, resposta: str,
                      mensagem: str) -> str:
    """Uma chamada curta ao modelo: correção/preferência → regra geral."""
    try:
        bruto = router.complete_messages("analise_complexa", [
            {"role": "system", "content": "Responda apenas JSON válido."},
            {"role": "user", "content": PEDIR_LICAO.format(
                tipo="correção" if tipo == "correcao" else "instrução permanente",
                pedido=(pedido or "")[:800], resposta=(resposta or "")[:1500],
                mensagem=(mensagem or "")[:400])}]) or ""
        i, f = bruto.find("{"), bruto.rfind("}")
        if i >= 0 and f > i:
            return str(json.loads(bruto[i:f + 1]).get("licao") or "").strip()
    except Exception:
        pass
    return ""


_PADRAO: Licoes | None = None


def padrao() -> Licoes:
    global _PADRAO
    if _PADRAO is None:
        _PADRAO = Licoes()
    return _PADRAO
