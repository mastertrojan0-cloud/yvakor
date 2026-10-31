"""
YVAKOR — Resolvedor do cérebro (conhecimento antes da IA)

Lógica em três degraus, do mais barato para o mais caro:

  1. CÉREBRO   — a pergunta é respondida com o que já está no vault/fatos.
                 Zero IA, zero API.
  2. LOCAL     — há conhecimento relacionado, mas é preciso redigir/raciocinar:
                 o modelo local (Qwen) responde com o cérebro no contexto.
  3. API       — nada relevante ou tarefa de ação: DeepSeek, e o resultado
                 aprendido volta para o cérebro (skill/fato).

A confiança é a cobertura dos termos da pergunta no conhecimento recuperado
(FTS5). Verbos de ação nunca são respondidos direto: no máximo vão para o local.
"""
from __future__ import annotations

import re

from yvakor.memory.db import normalizar
import logging

_log = logging.getLogger(__name__)

STOPWORDS = {
    "qual", "quais", "quando", "onde", "como", "porque", "por", "para", "the",
    "que", "uma", "um", "uns", "umas", "dos", "das", "com", "sem", "meu",
    "minha", "meus", "minhas", "seu", "sua", "isso", "este", "esta", "esse",
    "essa", "aquilo", "tem", "ter", "foi", "ser", "sao", "está", "voce", "você", "pode", "poderia", "favor", "sobre", "mais", "menos",
    "aqui", "ali", "agora", "hoje", "ontem", "e", "ou", "de", "do", "da",
    "em", "no", "na", "nos", "nas", "ao", "aos", "é", "eu", "ele", "ela",
    "nós", "eles", "elas", "não", "sim", "já", "muito", "bem", "tudo",
}

# Verbos que indicam AÇÃO (não podem ser respondidos só com conhecimento).
ACOES = ("abra", "abrir", "crie", "criar", "list", "edit", "apag", "mova",
         "mover", "copi", "baix", "instal", "execut", "rodar", "rode",
         "grav", "tire", "tirar", "ligu", "ligar", "deslig", "envi", "salv",
         "pesquis", "naveg", "clic", "preench", "organiz", "corrija",
         "refator", "implement", "faça", "faca", "fazer", "gere", "gerar",
         "monte", "montar", "analise", "analisar", "compare", "comparar")


class Resolvedor:
    def __init__(self, cerebro, cfg: dict):
        self.c = cerebro
        self.cfg = cfg or {}
        self.limiar_direto = float(self.cfg.get("limiar_direto", 0.7))
        self.limiar_local = float(self.cfg.get("limiar_local", 0.45))

    # ------------------------------------------------------------------ #
    @staticmethod
    def termos(mensagem: str) -> list[str]:
        palavras = re.findall(r"\w+", normalizar(mensagem))
        vistos = []
        for p in palavras:
            if len(p) >= 3 and p not in STOPWORDS and p not in vistos:
                vistos.append(p)
        return vistos

    @staticmethod
    def _tem_acao(mensagem: str) -> bool:
        low = normalizar(mensagem)
        return any(a in low for a in ACOES)

    @staticmethod
    def _resumo_nota(nota: dict) -> str:
        corpo = nota.get("conteudo") or ""
        corpo = re.sub(r"^---.*?---", "", corpo, flags=re.DOTALL)  # frontmatter
        corpo = corpo.split("## Ligações")[0]                      # sem o hub
        linhas = [l.strip() for l in corpo.splitlines()
                  if l.strip() and not l.startswith("#")]
        return " ".join(linhas)

    def _extrair(self, nota: dict, termos: list[str]) -> tuple[float, str]:
        texto = normalizar(nota.get("conteudo") or "")
        titulo = normalizar(nota.get("titulo") or "")
        achados = sum(1 for t in termos if t in texto or t in titulo)
        cobertura = achados / max(1, len(termos))
        corpo = self._resumo_nota(nota)
        fonte = nota.get("titulo") or nota.get("caminho") or "cérebro"
        if nota.get("tipo") == "memoria":
            # fato = uma linha curta; nunca despeja a nota inteira
            fato = re.sub(r"^[^\w]+", "", (corpo.split("\n")[0] or "").strip())[:300]
            return cobertura, f"{fato}\n\n— do cérebro: [[{fonte}]]"
        # frases mais relevantes (até 3), preservando o texto original
        frases = re.split(r"(?<=[.!?])\s+", corpo)
        relevantes = [f for f in frases
                      if sum(1 for t in termos if t in normalizar(f))]
        trecho = " ".join(relevantes[:3]).strip() or corpo[:400]
        resposta = f"{trecho.strip()} \n\n— do cérebro: [[{fonte}]]"
        return cobertura, resposta[:900]

    # ------------------------------------------------------------------ #
    def _limpar_conversa(self, corpo: str) -> str:
        corpo = re.sub(r"<!--.*?-->", "\n", corpo or "", flags=re.DOTALL)
        corpo = corpo.split("## Ligações")[0]
        corpo = re.sub(r"\*\*(Você|YVAKOR):\*\*", "\n", corpo)
        corpo = re.sub(r"\[\[[^\]]+\]\]", " ", corpo)
        corpo = re.sub(r"^#.*$", "\n", corpo, flags=re.MULTILINE)
        corpo = re.sub(r"[ \t]+", " ", corpo)
        return "\n".join(l.strip() for l in corpo.splitlines() if l.strip())

    def _melhor_conversa(self, mensagem: str, termos: list[str]):
        melhor = None
        try:
            for nota in self.c.buscar(mensagem, 8, incluir_conteudo=True):
                completa = nota if nota.get("conteudo") is not None \
                    else (self.c.nota(nota["caminho"]) or {})
                if completa.get("tipo") != "conversa":
                    continue
                texto = self._limpar_conversa(completa.get("conteudo", ""))
                for linha in texto.splitlines():
                    for frase in re.split(r"(?<=[.!?])\s+", linha):
                        frase = re.sub(r"^[^\w]+", "", frase.strip())
                        if frase.rstrip().endswith("?"):   # pergunta não é fato
                            continue
                        if not (8 <= len(frase) <= 240):
                            continue
                        baixo = frase.lower()
                        tem_valor = bool(re.search(r"\d", frase)) or bool(re.search(
                            r"\b(é|e|fica|está|esta|tem|usa|mora|trabalha|"
                            r"prefere|gosta|foi|vai)\b", baixo))
                        if not tem_valor:      # frase nominal não é fato
                            continue
                        acertos = sum(1 for t in termos if t in normalizar(frase))
                        if acertos < max(2, len(termos) - 1):
                            continue
                        cobertura = acertos / max(1, len(termos))
                        chave = (cobertura, 1 if tem_valor else 0, len(frase))
                        if melhor is None or chave > melhor[0]:
                            melhor = (chave, frase)
        except Exception:
            return None
        if not melhor:
            return None
        return (melhor[0][0], melhor[1])

    def decidir(self, mensagem: str) -> dict | None:
        # receita aprovada tem prioridade: executa sem IA
        try:
            receita = self.c.casar_receita(mensagem)
        except Exception:
            receita = None
        if receita is not None:
            return {"modo": "receita", "confianca": 1.0, "receita": receita,
                    "resposta": "", "fontes": [receita.nome], "contexto": ""}

        # Pergunta com IP explícito: a ficha do equipamento vence fatos genéricos.
        ips = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", mensagem or "")
        for ip in ips:
            try:
                for resumo in self.c.buscar(ip, 8, incluir_conteudo=True):
                    completa = resumo if resumo.get("conteudo") is not None \
                        else (self.c.nota(resumo.get("caminho")) or {})
                    texto = completa.get("conteudo", "") or ""
                    if texto.startswith("---"):
                        partes = texto.split("---", 2)
                        if len(partes) >= 3:
                            texto = partes[2]
                    if ip not in texto:
                        continue
                    tags = completa.get("tags") or []
                    tags_txt = " ".join(tags) if isinstance(tags, list) else str(tags)
                    titulo = completa.get("titulo") or ""
                    if ("equipamento" not in tags_txt.lower()
                            and "equipamento" not in titulo.lower()):
                        continue
                    linhas = [l.strip() for l in texto.splitlines()
                              if l.strip() and not l.strip().startswith("#")]
                    corpo = " ".join(linhas[:8])[:600]
                    return {"modo": "cerebro", "confianca": 1.0,
                            "resposta": f"{corpo}\n\n— do cérebro: [[{titulo}]]",
                            "fontes": [titulo], "contexto": ""}
            except Exception:
                continue

        termos = self.termos(mensagem)
        if not termos:
            return None
        acao = self._tem_acao(mensagem)
        low = normalizar(mensagem)
        interrogativa = ("?" in mensagem or
                         (low.split()[0] if low.split() else "") in
                         {"qual", "quais", "quando", "onde", "como", "quanto",
                          "quem", "cade", "tem", "existe", "o", "que"})
        pode_direto = interrogativa and not acao

        candidatos = []
        try:
            for nota in self.c.buscar(mensagem, 6, incluir_conteudo=True):
                completa = nota if nota.get("conteudo") is not None \
                    else (self.c.nota(nota["caminho"]) or {})
                # conversa não serve como resposta direta (é transcript)
                if completa and completa.get("tipo") != "conversa":
                    cobertura, resposta = self._extrair(completa, termos)
                    candidatos.append({
                        "tipo": completa.get("tipo", "nota"),
                        "titulo": completa.get("titulo", ""),
                        "cobertura": cobertura + (0.1 if completa.get("tipo") ==
                                                  "memoria" else 0.05),
                        "resposta": resposta,
                    })
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

        # fatos fora do vault (semântica) também entram
        try:
            for fato in self.c.semantic.search(mensagem, 4):
                cobertura = sum(1 for t in termos if t in normalizar(fato)) / len(termos)
                candidatos.append({"tipo": "memoria", "titulo": "Memória",
                                   "cobertura": cobertura,
                                   "resposta": f"{fato}\n\n— do cérebro: [[Memória]]"})
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

        if pode_direto and (not candidatos or
                            max(c["cobertura"] for c in candidatos) < self.limiar_direto):
            # aprende com a conversa: extrai o fato limpo e persiste na memória
            conv = self._melhor_conversa(mensagem, termos)
            if conv and conv[0] >= self.limiar_direto:
                fato = conv[1]
                try:
                    # Fato extraído de transcript de conversa: confiança baixa
                    # (revisar=1), não reaproveitado como verdade direta sem
                    # revisão. Evita compor o loop auto-reforçante.
                    self.c.semantic.store(fato, fonte="conversa", confianca=0.5)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
                return {"modo": "cerebro", "confianca": round(conv[0], 2),
                        "resposta": f"{fato}\n\n— do cérebro: [[Memória]]",
                        "fontes": ["Memória"],
                        "contexto": self.contexto(mensagem)}

        if not candidatos:
            return None
        melhor = max(candidatos, key=lambda x: x["cobertura"])
        confianca = round(min(1.0, melhor["cobertura"]), 2)
        segundo = max((c["cobertura"] for c in candidatos if c is not melhor),
                      default=0.0)
        margem = confianca - segundo
        contexto = self.contexto(mensagem)

        if pode_direto and confianca >= self.limiar_direto and (
                margem >= 0.12 or len(candidatos) == 1):
            return {"modo": "cerebro", "confianca": confianca,
                    "resposta": melhor["resposta"], "fontes": [melhor["titulo"]],
                    "contexto": contexto}
        if (not acao and confianca >= self.limiar_local
                and melhor["tipo"] != "conversa" and margem >= 0.12):
            # perguntas com conhecimento parcial: modelo local (barato).
            # AÇÃO nunca vai para o local (3B com 64 ferramentas trava).
            return {"modo": "local", "confianca": confianca, "resposta": "",
                    "fontes": [melhor["titulo"]], "contexto": contexto}
        return None

    def contexto(self, mensagem: str, limite: int = 2500) -> str:
        partes = ["## CÉREBRO — CONHECIMENTO JÁ APRENDIDO",
                  "Use isto como fonte de verdade. Se resolve a pergunta, "
                  "responda com base nisto (cite a nota)."]
        try:
            for nota in self.c.buscar(mensagem, 5, incluir_conteudo=True):
                completa = nota if nota.get("conteudo") is not None \
                    else (self.c.nota(nota["caminho"]) or {})
                resumo = self._resumo_nota(completa)[:600]
                if resumo:
                    partes.append(f"### {nota.get('titulo')} "
                                  f"({nota.get('tipo')})\n{resumo}")
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        texto = "\n\n".join(partes)
        return texto[:limite]
