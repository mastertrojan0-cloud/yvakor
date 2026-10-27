"""YVAKOR — Otimizador de consumo de APIs (menos tokens, mesmo resultado).

Objetivo: entregar o melhor resultado com o MENOR número de tokens cobrados nas
APIs conectadas (hoje DeepSeek; qualquer provedor OpenAI-compatível entra pelo
mesmo caminho). O consumo é decidido em camadas, da mais barata para a mais cara:

  1. CACHE          resposta já conhecida (exata ou quase-duplicada) = 0 token.
  2. ROTEAMENTO     o modelo local (grátis) responde o que dá conta; a nuvem só
                    entra quando a tarefa pede ou quando o local falha na
                    verificação (cascata). A decisão é APRENDIDA: um bandit
                    (Thompson) por faixa de dificuldade usa os resultados reais.
  3. COMPRESSÃO     o prompt é enxugado sem chamar IA (espaços, duplicatas,
                    observações longas cortadas no meio, histórico antigo virando
                    um resumo extrativo) até caber no orçamento do provedor —
                    de forma estável, para preservar o cache de prefixo da API.
  4. TETO DE SAÍDA  `max_tokens` adaptativo (p90 do que a tarefa realmente gasta).
  5. VERIFICAÇÃO    heurística barata de qualidade (vazio, repetição, idioma, JSON,
                    truncamento) decide se escalona para um modelo mais forte.
  6. ORÇAMENTO      limite diário/mensal (USD e tokens) com zonas: normal →
                    econômico → crítico → bloqueado, que aperta tudo acima.
  7. LIVRO-RAZÃO    cada chamada (tokens reais da API, custo, economia) em
                    data/consumo.db, base de todas as decisões e do /api/consumo.

Nada aqui levanta para quem chama: se o otimizador falhar, o roteador usa o
caminho original (o otimizador nunca pode ser pior que não ter otimizador).
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sqlite3
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #
PADRAO = {
    "ativo": True,
    "razao_chars_por_token": 3.6,        # pt-BR; recalibrada com o uso real da API
    "orcamento_prompt_tokens": {"local": 1800, "nuvem": 7000},
    "histerese": 0.65,                    # comprime até 65% do teto (prefixo estável)
    "manter_ultimos": 6,
    "limiar_qualidade": 0.6,              # abaixo disso o local escalona para a nuvem
    "espera_extra_max_s": 35,             # quanto de espera extra tolerar p/ tentar o local
    "tps_local_padrao": 7.0,
    "cache": {"ativo": True, "ttl_s": 43200, "similaridade": 0.92, "max_entradas": 4000},
    "orcamento": {"diario_usd": 0.0, "mensal_usd": 0.0, "diario_tokens": 0},   # 0 = sem limite
    "precos_usd_por_milhao": {},          # {"deepseek": {"entrada": .28, "cache": .028, "saida": .42}}
}

# prior de dificuldade por tipo de tarefa (0 = trivial, 1 = pesada)
PRIOR_TAREFA = {
    "classificacao": 0.10, "resposta_simples": 0.15, "formatacao": 0.15,
    "resumo_curto": 0.25, "geracao_imagem": 0.45, "prospeccao": 0.5,
    "pesquisa_sintese": 0.6, "codigo": 0.65, "analise_complexa": 0.7,
    "arquitetura": 0.8,
}
TETO_SAIDA_PADRAO = {            # tokens de saída enquanto não há histórico
    "classificacao": 48, "resposta_simples": 420, "formatacao": 700,
    "resumo_curto": 380, "geracao_imagem": 300, "prospeccao": 1400,
    "pesquisa_sintese": 1500, "codigo": 2600, "analise_complexa": 1800,
    "arquitetura": 2400,
}
CACHEAVEIS = {"classificacao", "resposta_simples", "formatacao", "resumo_curto",
              "codigo", "arquitetura"}
TTL_TAREFA = {"classificacao": 7 * 86400, "formatacao": 7 * 86400, "codigo": 86400,
              "arquitetura": 86400, "resposta_simples": 6 * 3600, "resumo_curto": 86400}

_SENSIVEL_AO_TEMPO = re.compile(
    r"\b(hoje|agora|atual(?:mente)?|cota[cç][aã]o|pre[cç]o|clima|tempo em|not[ií]cias?|"
    r"[uú]ltimas?|ao vivo|que dia|que horas?|data de|amanh[aã]|ontem|esta semana|"
    r"neste momento|bitcoin|d[oó]lar|placar|resultado do jogo)\b", re.I)
_MARCAS_AGENTE = ("usar_ferramenta", "OBSERVAÇÃO", "OBSERVACAO", "<observacao")
_PT = {"o", "a", "de", "que", "e", "do", "da", "em", "para", "um", "uma", "os",
       "as", "com", "não", "nao", "é", "se", "na", "no", "por", "mais"}
_EN = {"the", "and", "is", "of", "to", "in", "that", "it", "for", "with", "this", "are"}
_RECUSA = re.compile(
    r"(como (um )?modelo de linguagem|n[aã]o consigo (acessar|fazer|ajudar)|"
    r"i('m| am) (sorry|unable)|as an ai|n[aã]o tenho acesso)", re.I)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t.lower())).strip()


def _texto(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):                    # multimodal: só o texto conta aqui
        return " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
    return ""


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def estimar_tokens(texto: str, razao: float = 3.6) -> int:
    return max(1, int(len(texto) / razao)) if texto else 0


def tokens_mensagens(msgs: list[dict], razao: float = 3.6) -> int:
    return sum(estimar_tokens(_texto(m), razao) + 4 for m in msgs)


# --------------------------------------------------------------------------- #
# Compressão de prompt (sem chamar IA)
# --------------------------------------------------------------------------- #
def _enxugar(texto: str) -> str:
    t = texto.replace("\r\n", "\n").replace("​", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _meio(texto: str, alvo_chars: int, cabeca: float = 0.6) -> str:
    """Corta o MEIO (começo e fim costumam ter a instrução e o resultado)."""
    if len(texto) <= alvo_chars:
        return texto
    h = int(alvo_chars * cabeca)
    t = max(0, alvo_chars - h)
    omit = len(texto) - h - t
    return f"{texto[:h].rstrip()}\n[… {omit} caracteres omitidos …]\n{texto[len(texto) - t:].lstrip()}"


def _resumo_extrativo(msgs: list[dict], limite_chars: int = 700) -> str:
    itens = []
    for m in msgs:
        t = _enxugar(_texto(m))
        if not t:
            continue
        primeira = re.split(r"(?<=[.!?])\s|\n", t, maxsplit=1)[0][:130]
        itens.append(f"{'U' if m.get('role') == 'user' else 'A'}: {primeira}")
    out, usado = [], 0
    for i in itens[-12:]:
        if usado + len(i) > limite_chars:
            break
        out.append(i)
        usado += len(i) + 1
    return "\n".join(out)


def comprimir(mensagens: list[dict], teto_tokens: int, razao: float = 3.6,
              manter_ultimos: int = 6, histerese: float = 0.65) -> tuple[list[dict], dict]:
    """Devolve (mensagens enxutas, info). Nunca remove a última mensagem do usuário
    nem a mensagem de sistema; só comprime além do teto (com folga: `histerese`)."""
    antes = tokens_mensagens(mensagens, razao)
    msgs: list[dict] = []
    for m in mensagens:                                       # 1) normaliza e tira duplicatas seguidas
        if isinstance(m.get("content"), str):
            m = dict(m, content=_enxugar(m["content"]))
        if msgs and msgs[-1].get("role") == m.get("role") and \
                msgs[-1].get("content") == m.get("content") and m.get("role") != "system":
            continue
        msgs.append(m)
    atual = tokens_mensagens(msgs, razao)
    info = {"antes": antes, "depois": atual, "etapas": []}
    if atual <= teto_tokens:
        info["economizados"] = max(0, antes - atual)
        return msgs, info
    alvo = int(teto_tokens * histerese)                       # comprime além do mínimo: o prefixo fica estável
    n = len(msgs)
    protegidos = set(range(max(0, n - manter_ultimos), n))
    protegidos |= {i for i, m in enumerate(msgs) if m.get("role") == "system"}

    # 2) observações/mensagens antigas longas: corta o meio
    for i, m in enumerate(msgs):
        if i in protegidos or not isinstance(m.get("content"), str):
            continue
        if estimar_tokens(m["content"], razao) > 350:
            msgs[i] = dict(m, content=_meio(m["content"], int(350 * razao)))
    atual = tokens_mensagens(msgs, razao)
    info["etapas"].append(("cortar_meio_antigas", atual))

    # 3) histórico antigo -> um resumo extrativo (mantém a 1ª mensagem do usuário = a tarefa)
    if atual > alvo:
        sistema = [m for m in msgs if m.get("role") == "system"]
        resto = [m for m in msgs if m.get("role") != "system"]
        primeira_user = next((m for m in resto if m.get("role") == "user"), None)
        cauda = resto[-manter_ultimos:] if len(resto) > manter_ultimos else resto
        meio = [m for m in resto if m is not primeira_user and m not in cauda]
        novo = list(sistema)
        if primeira_user is not None and primeira_user not in cauda:
            novo.append(primeira_user)
        if meio:
            novo.append({"role": "user", "content":
                         f"(resumo de {len(meio)} mensagens anteriores)\n" + _resumo_extrativo(meio)})
        novo += cauda
        msgs = novo
        atual = tokens_mensagens(msgs, razao)
        info["etapas"].append(("resumir_historico", atual))

    # 4) ainda acima: encolhe as mensagens da cauda (menos a última) e, por fim, o sistema
    for passo in (0.6, 0.4, 0.25):
        if atual <= alvo:
            break
        for i, m in enumerate(msgs[:-1]):
            if m.get("role") == "system" or not isinstance(m.get("content"), str):
                continue
            msgs[i] = dict(m, content=_meio(m["content"], int(len(m["content"]) * passo) + 200))
        atual = tokens_mensagens(msgs, razao)
        info["etapas"].append((f"encolher_{passo}", atual))
    if atual > teto_tokens:                                   # último recurso: o system (cauda dinâmica)
        for i, m in enumerate(msgs):
            if m.get("role") == "system" and isinstance(m.get("content"), str):
                msgs[i] = dict(m, content=_meio(m["content"], int(teto_tokens * razao * 0.55), 0.7))
        atual = tokens_mensagens(msgs, razao)
        info["etapas"].append(("encolher_system", atual))
    if atual > teto_tokens and msgs and isinstance(msgs[-1].get("content"), str):
        resto_chars = max(400, int((teto_tokens - (atual - estimar_tokens(msgs[-1]["content"], razao))) * razao))
        msgs[-1] = dict(msgs[-1], content=_meio(msgs[-1]["content"], resto_chars))
        atual = tokens_mensagens(msgs, razao)
    info["depois"] = atual
    info["economizados"] = max(0, antes - atual)
    return msgs, info


# --------------------------------------------------------------------------- #
# Dificuldade e verificação
# --------------------------------------------------------------------------- #
_VERBOS_ACAO = re.compile(r"\b(abra|crie|criar|execut|instal|apag|mova|baix|pesquis|naveg|clic|"
                          r"preench|analis|compar|refator|implement|corrij|organiz)", re.I)
_PROFUNDO = re.compile(r"\b(por que|porque|como funciona|compare|analise|an[aá]lise|estrat[eé]gia|"
                       r"arquitetura|planeje|passo a passo|em detalhes|trade-?off|otimiz|"
                       r"demonstre|prove|calcule)\b", re.I)


def complexidade(mensagens: list[dict], tarefa: str) -> float:
    """0..1. Prior da tarefa + sinais baratos do pedido atual e do contexto."""
    ultima = next((_texto(m) for m in reversed(mensagens) if m.get("role") == "user"), "")
    sistema = " ".join(_texto(m) for m in mensagens if m.get("role") == "system")
    sinais = 0.0
    sinais += min(0.25, math.log10(1 + len(ultima)) / 12)        # pedido longo
    sinais += 0.2 if "```" in ultima or re.search(r"\b(def |class |function|SELECT )", ultima) else 0
    sinais += min(0.2, 0.07 * len(_VERBOS_ACAO.findall(ultima)))
    sinais += 0.15 if _PROFUNDO.search(ultima) else 0
    sinais += 0.25 if "usar_ferramenta" in sistema else 0         # loop de agente
    sinais += 0.1 if len(mensagens) > 8 else 0
    prior = PRIOR_TAREFA.get(tarefa, 0.4)
    return max(0.0, min(1.0, 0.55 * prior + 0.45 * min(1.0, sinais * 1.4)))


def avaliar(resposta: str, tarefa: str = "", finish: str | None = None,
            esperado_json: bool = False) -> float:
    """Qualidade 0..1 por heurística (custo zero). Alimenta cascata e bandit."""
    r = (resposta or "").strip()
    if not r:
        return 0.0
    if len(r) < 3:
        return 0.15
    q = 0.9
    palavras = re.findall(r"\w+", r.lower())
    if len(palavras) >= 40:
        gramas = [tuple(palavras[i:i + 4]) for i in range(len(palavras) - 3)]
        if gramas and len(set(gramas)) / len(gramas) < 0.4:
            q = min(q, 0.2)                                         # laço de repetição
    if finish in ("length", "max_tokens") and not r.endswith((".", "!", "?", "```", "}", ")")):
        q = min(q, 0.5)
    if _RECUSA.search(r[:300]):
        q = min(q, 0.55)
    if len(palavras) >= 25:
        pt = sum(1 for w in palavras if w in _PT)
        en = sum(1 for w in palavras if w in _EN)
        if pt == 0 and en >= 3:
            q = min(q, 0.4)                                         # respondeu em outro idioma
    if r.startswith("{") and (esperado_json or '"acao"' in r):
        try:
            json.loads(r)
        except Exception:
            if not re.search(r"\{.*\}", r, re.S):
                q = min(q, 0.3)
    if tarefa in ("analise_complexa", "arquitetura", "codigo", "pesquisa_sintese") and len(r) < 40:
        q = min(q, 0.45)
    return q


# --------------------------------------------------------------------------- #
# Banco (livro-razão + cache + estatísticas do bandit)
# --------------------------------------------------------------------------- #
def hash_resposta(resposta: str) -> str:
    return hashlib.sha1((resposta or "").strip()[:1200].encode("utf-8")).hexdigest()[:16]


class Livro:
    def __init__(self, caminho: Path):
        from yvakor.memory.db import conectar
        self.caminho = Path(caminho)
        self.conn = conectar(self.caminho)
        self._lock = threading.Lock()
        with self._lock, self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS uso (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                    provedor TEXT, modelo TEXT, tarefa TEXT, origem TEXT,
                    tok_in INTEGER DEFAULT 0, tok_out INTEGER DEFAULT 0,
                    tok_cache INTEGER DEFAULT 0, custo REAL DEFAULT 0,
                    ms REAL DEFAULT 0, qualidade REAL DEFAULT 1, ok INTEGER DEFAULT 1,
                    economia_tok INTEGER DEFAULT 0, faixa INTEGER DEFAULT 0, detalhe TEXT DEFAULT '',
                    resp_hash TEXT DEFAULT '');
                CREATE INDEX IF NOT EXISTS idx_uso_ts ON uso(ts);
                CREATE INDEX IF NOT EXISTS idx_uso_prov ON uso(provedor, tarefa);
                CREATE TABLE IF NOT EXISTS cache (
                    chave TEXT PRIMARY KEY, tarefa TEXT, ts REAL, ttl REAL,
                    resposta TEXT, tok_in INTEGER, tok_out INTEGER,
                    sistema TEXT, assinatura TEXT, hits INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS idx_cache_sig ON cache(tarefa, sistema);
            """)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(uso)")}
            if "resp_hash" not in cols:                       # bancos criados antes do feedback
                self.conn.execute("ALTER TABLE uso ADD COLUMN resp_hash TEXT DEFAULT ''")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_uso_hash ON uso(resp_hash)")
            self.conn.execute("DELETE FROM uso WHERE ts < ?", (time.time() - 120 * 86400,))
            self.conn.execute("DELETE FROM cache WHERE ts + ttl < ?", (time.time(),))

    # ---- uso ----
    def registrar(self, **k) -> None:
        try:
            with self._lock, self.conn:
                self.conn.execute(
                    "INSERT INTO uso (ts, provedor, modelo, tarefa, origem, tok_in, tok_out, tok_cache,"
                    " custo, ms, qualidade, ok, economia_tok, faixa, detalhe, resp_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (time.time(), k.get("provedor", ""), k.get("modelo", ""), k.get("tarefa", ""),
                     k.get("origem", "api"), int(k.get("tok_in", 0)), int(k.get("tok_out", 0)),
                     int(k.get("tok_cache", 0)), float(k.get("custo", 0)), float(k.get("ms", 0)),
                     float(k.get("qualidade", 1)), 1 if k.get("ok", True) else 0,
                     int(k.get("economia_tok", 0)), int(k.get("faixa", 0)),
                     str(k.get("detalhe", ""))[:200], k.get("resp_hash", "")))
        except sqlite3.DatabaseError:
            pass

    def somar(self, desde: float, provedor: str | None = None, so_nuvem: bool = False) -> dict:
        sql = ("SELECT COALESCE(SUM(custo),0), COALESCE(SUM(tok_in),0), COALESCE(SUM(tok_out),0) "
               "FROM uso WHERE ts >= ? AND origem='api'")
        par: list = [desde]
        if provedor:
            sql += " AND provedor=?"
            par.append(provedor)
        if so_nuvem:
            sql += " AND custo > 0"
        try:
            c, i, o = self.conn.execute(sql, par).fetchone()
        except sqlite3.DatabaseError:
            c = i = o = 0
        return {"custo": float(c), "tok_in": int(i), "tok_out": int(o), "tokens": int(i) + int(o)}

    def resumo(self, dias: int = 7) -> dict:
        desde = time.time() - dias * 86400
        out: dict = {"dias": dias, "por_provedor": {}, "por_tarefa": {}}
        try:
            for r in self.conn.execute(
                    "SELECT provedor, origem, COUNT(*), SUM(tok_in), SUM(tok_out), SUM(tok_cache), SUM(custo),"
                    " AVG(ms), AVG(qualidade), SUM(economia_tok) FROM uso WHERE ts>=? GROUP BY provedor, origem",
                    (desde,)):
                d = out["por_provedor"].setdefault(r[0] or "-", {})
                d[r[1]] = {"chamadas": r[2], "tok_in": r[3] or 0, "tok_out": r[4] or 0,
                           "tok_cache": r[5] or 0, "custo_usd": round(r[6] or 0, 5),
                           "ms_medio": round(r[7] or 0), "qualidade": round(r[8] or 0, 2),
                           "economia_tok": r[9] or 0}
            for r in self.conn.execute(
                    "SELECT tarefa, COUNT(*), SUM(tok_in+tok_out), AVG(qualidade) FROM uso "
                    "WHERE ts>=? GROUP BY tarefa ORDER BY 3 DESC LIMIT 12", (desde,)):
                out["por_tarefa"][r[0] or "-"] = {"chamadas": r[1], "tokens": r[2] or 0,
                                                  "qualidade": round(r[3] or 0, 2)}
            tot, cache_n, eco = self.conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN origem='cache' THEN 1 ELSE 0 END), COALESCE(SUM(economia_tok),0)"
                " FROM uso WHERE ts>=?", (desde,)).fetchone()
            out.update(chamadas=tot, cache_hits=cache_n or 0,
                       cache_pct=round(100 * (cache_n or 0) / tot, 1) if tot else 0,
                       tokens_economizados=int(eco))
        except sqlite3.DatabaseError:
            pass
        return out

    def historico_saida(self, provedor: str, tarefa: str, n: int = 60) -> list[int]:
        try:
            return [r[0] for r in self.conn.execute(
                "SELECT tok_out FROM uso WHERE provedor=? AND tarefa=? AND origem='api' AND ok=1 "
                "AND tok_out>0 ORDER BY id DESC LIMIT ?", (provedor, tarefa, n))]
        except sqlite3.DatabaseError:
            return []

    def placar(self, provedor: str, faixa: int, dias: int = 45) -> tuple[int, int]:
        """(sucessos, falhas) do provedor naquela faixa de dificuldade."""
        try:
            r = self.conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN qualidade>=? AND ok=1 THEN 1 ELSE 0 END),0),"
                " COALESCE(SUM(CASE WHEN qualidade<? OR ok=0 THEN 1 ELSE 0 END),0)"
                " FROM uso WHERE provedor=? AND faixa=? AND origem='api' AND ts>=?",
                (PADRAO["limiar_qualidade"], PADRAO["limiar_qualidade"], provedor, faixa,
                 time.time() - dias * 86400)).fetchone()
            return int(r[0]), int(r[1])
        except sqlite3.DatabaseError:
            return 0, 0

    def tps(self, provedor: str) -> float | None:
        try:
            r = self.conn.execute(
                "SELECT SUM(tok_out), SUM(ms) FROM (SELECT tok_out, ms FROM uso WHERE provedor=? AND "
                "origem='api' AND ok=1 AND tok_out>10 ORDER BY id DESC LIMIT 25)", (provedor,)).fetchone()
            return (r[0] / (r[1] / 1000)) if r and r[0] and r[1] else None
        except sqlite3.DatabaseError:
            return None

    def feedback(self, resposta: str, nota: int) -> dict:
        """👍/👎 do usuário: corrige a qualidade registrada daquela resposta (alimenta o bandit) e,
        se foi ruim, apaga a resposta do cache para ela não ser servida de novo."""
        h = hash_resposta(resposta)
        q, ok = (1.0, 1) if nota >= 4 else (0.0, 0)
        try:
            with self._lock, self.conn:
                n = self.conn.execute("UPDATE uso SET qualidade=?, ok=? WHERE resp_hash=?", (q, ok, h)).rowcount
                m = 0
                if nota <= 2:
                    m = self.conn.execute("DELETE FROM cache WHERE substr(trim(resposta),1,1200)=?", ((resposta or "").strip()[:1200],)).rowcount
            return {"atualizadas": n, "cache_removido": m}
        except sqlite3.DatabaseError:
            return {"atualizadas": 0, "cache_removido": 0}

    # ---- cache ----
    def cache_get(self, chave: str) -> dict | None:
        try:
            r = self.conn.execute("SELECT resposta, tok_in, tok_out, ts, ttl FROM cache WHERE chave=?",
                                  (chave,)).fetchone()
            if r and r[3] + r[4] >= time.time():
                with self._lock, self.conn:
                    self.conn.execute("UPDATE cache SET hits=hits+1 WHERE chave=?", (chave,))
                return {"resposta": r[0], "tok_in": r[1], "tok_out": r[2]}
        except sqlite3.DatabaseError:
            pass
        return None

    def cache_parecido(self, tarefa: str, sistema: str, assinatura: str, minimo: float) -> dict | None:
        try:
            linhas = self.conn.execute(
                "SELECT chave, assinatura, resposta, tok_in, tok_out FROM cache WHERE tarefa=? AND sistema=? "
                "AND ts+ttl>=? ORDER BY ts DESC LIMIT 250", (tarefa, sistema, time.time())).fetchall()
        except sqlite3.DatabaseError:
            return None
        a = set(assinatura.split())
        if len(a) < 3:
            return None
        melhor, nota = None, 0.0
        for l in linhas:
            b = set(l[1].split())
            if not b:
                continue
            j = len(a & b) / len(a | b)
            if j > nota:
                melhor, nota = l, j
        if melhor and nota >= minimo:
            return {"resposta": melhor[2], "tok_in": melhor[3], "tok_out": melhor[4], "similaridade": nota}
        return None

    def cache_put(self, chave, tarefa, ttl, resposta, tok_in, tok_out, sistema, assinatura, maximo) -> None:
        try:
            with self._lock, self.conn:
                self.conn.execute(
                    "INSERT OR REPLACE INTO cache (chave, tarefa, ts, ttl, resposta, tok_in, tok_out, sistema,"
                    " assinatura, hits) VALUES (?,?,?,?,?,?,?,?,?,0)",
                    (chave, tarefa, time.time(), ttl, resposta, tok_in, tok_out, sistema, assinatura))
                n = self.conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
                if n > maximo:
                    self.conn.execute(
                        "DELETE FROM cache WHERE chave IN (SELECT chave FROM cache ORDER BY hits ASC, ts ASC LIMIT ?)",
                        (n - maximo,))
        except sqlite3.DatabaseError:
            pass


# --------------------------------------------------------------------------- #
# Otimizador
# --------------------------------------------------------------------------- #
@dataclass
class Plano:
    tarefa: str
    ordem: list                                   # provedores, do primeiro ao último
    dificuldade: float
    faixa: int
    mensagens: dict = field(default_factory=dict)  # nome do provedor -> mensagens comprimidas
    economia: dict = field(default_factory=dict)   # nome -> tokens poupados pela compressão
    max_tokens: dict = field(default_factory=dict)
    zona: str = "normal"
    cache_chave: str | None = None
    cache_sistema: str = ""
    cache_assinatura: str = ""
    cacheavel: bool = False
    motivo: str = ""


class Otimizador:
    def __init__(self, cfg: dict | None, providers: dict, caminho_db: Path | None = None,
                 rng: random.Random | None = None):
        c = json.loads(json.dumps(PADRAO))
        for k, v in (cfg or {}).items():
            if isinstance(v, dict) and isinstance(c.get(k), dict):
                c[k].update(v)
            else:
                c[k] = v
        self.cfg = c
        self.ativo = bool(c["ativo"])
        self.providers = providers
        self.rng = rng or random.Random()
        self._caminho_db = Path(caminho_db or (ROOT / "data" / "consumo.db"))
        self._livro: Livro | None = None
        self._razao: dict[str, float] = {}
        self._voando: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._zona_cache = (0.0, "normal")
        self.precos = self._precos()

    @property
    def livro(self) -> "Livro":
        """Abre o banco só no primeiro uso (instanciar o roteador não cria arquivos)."""
        if self._livro is None:
            with self._lock:
                if self._livro is None:
                    self._livro = Livro(self._caminho_db)
        return self._livro

    # ---------------- preços e tokens ----------------
    def _precos(self) -> dict:
        out = {}
        cfg = self.cfg.get("precos_usd_por_milhao") or {}
        for nome in self.providers:
            if self.eh_local(nome):
                out[nome] = {"entrada": 0.0, "cache": 0.0, "saida": 0.0}
            else:
                p = cfg.get(nome) or {}
                out[nome] = {"entrada": float(p.get("entrada", 0.28)),
                             "cache": float(p.get("cache", 0.028)),
                             "saida": float(p.get("saida", 0.42))}
        return out

    @staticmethod
    def eh_local(nome: str) -> bool:
        return "ollama" in nome or "local" in nome

    def razao(self, nome: str) -> float:
        return self._razao.get(nome, float(self.cfg["razao_chars_por_token"]))

    def custo(self, nome: str, tok_in: int, tok_out: int, tok_cache: int = 0) -> float:
        p = self.precos.get(nome) or {"entrada": 0, "cache": 0, "saida": 0}
        miss = max(0, tok_in - tok_cache)
        return (miss * p["entrada"] + tok_cache * p["cache"] + tok_out * p["saida"]) / 1e6

    def aprender_razao(self, nome: str, msgs: list[dict], tok_in_real: int) -> None:
        chars = sum(len(_texto(m)) for m in msgs)
        if tok_in_real > 20 and chars > 80:
            novo = max(1.8, min(6.0, chars / tok_in_real))
            ant = self._razao.get(nome, float(self.cfg["razao_chars_por_token"]))
            self._razao[nome] = 0.8 * ant + 0.2 * novo

    # ---------------- orçamento ----------------
    def zona(self) -> str:
        """normal | economico | critico | bloqueado (olha o maior uso relativo)."""
        agora = time.time()
        if agora - self._zona_cache[0] < 5:
            return self._zona_cache[1]
        o = self.cfg["orcamento"]
        t = time.localtime(agora)
        ini_dia = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
        ini_mes = time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        d = self.livro.somar(ini_dia)
        m = self.livro.somar(ini_mes)
        fr = []
        if o.get("diario_usd"):
            fr.append(d["custo"] / o["diario_usd"])
        if o.get("mensal_usd"):
            fr.append(m["custo"] / o["mensal_usd"])
        if o.get("diario_tokens"):
            fr.append(d["tokens"] / o["diario_tokens"])
        uso = max(fr) if fr else 0.0
        z = "bloqueado" if uso >= 1 else "critico" if uso >= 0.9 else "economico" if uso >= 0.7 else "normal"
        self._zona_cache = (agora, z)
        self._uso_rel = uso
        return z

    def definir_orcamento(self, **kw) -> dict:
        for k in ("diario_usd", "mensal_usd", "diario_tokens"):
            if k in kw and kw[k] is not None:
                self.cfg["orcamento"][k] = max(0, float(kw[k]))
        self._zona_cache = (0.0, "normal")
        return self.cfg["orcamento"]

    # ---------------- dificuldade → faixa ----------------
    @staticmethod
    def faixa(dificuldade: float) -> int:
        return min(3, int(dificuldade * 4))        # 0 fácil … 3 pesada

    # ---------------- teto de saída ----------------
    def max_saida(self, nome: str, tarefa: str, teto_provedor: int) -> int:
        hist = self.livro.historico_saida(nome, tarefa)
        if len(hist) >= 8:
            hist = sorted(hist)
            p90 = hist[min(len(hist) - 1, int(len(hist) * 0.9))]
            alvo = int(p90 * 1.3) + 32
        else:
            alvo = TETO_SAIDA_PADRAO.get(tarefa, 900)
        return max(64, min(int(teto_provedor or 4096), alvo))

    # ---------------- cache ----------------
    def _cacheavel(self, tarefa: str, msgs: list[dict]) -> bool:
        if not self.cfg["cache"].get("ativo") or tarefa not in CACHEAVEIS:
            return False
        for m in msgs:
            t = _texto(m)
            if any(x in t for x in _MARCAS_AGENTE):
                return False
        ultima = next((_texto(m) for m in reversed(msgs) if m.get("role") == "user"), "")
        return not _SENSIVEL_AO_TEMPO.search(ultima)

    @staticmethod
    def _chave(tarefa: str, msgs: list[dict]) -> str:
        base = tarefa + "\n" + "\n".join(f"{m.get('role')}:{_enxugar(_texto(m))}" for m in msgs)
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]

    def cache_buscar(self, plano: Plano) -> dict | None:
        if not plano.cacheavel:
            return None
        hit = self.livro.cache_get(plano.cache_chave)
        if hit:
            hit["tipo"] = "exato"
            return hit
        nao_sistema = [m for m in plano.mensagens.get("_base", []) if m.get("role") != "system"]
        if len(nao_sistema) == 1:                                 # pergunta avulsa: aceita quase-duplicata
            hit = self.livro.cache_parecido(plano.tarefa, plano.cache_sistema, plano.cache_assinatura,
                                            float(self.cfg["cache"]["similaridade"]))
            if hit:
                hit["tipo"] = "parecido"
                return hit
        return None

    def cache_guardar(self, plano: Plano, resposta: str, tok_in: int, tok_out: int, q: float) -> None:
        if plano.cacheavel and q >= 0.75 and resposta.strip():
            ttl = TTL_TAREFA.get(plano.tarefa, self.cfg["cache"]["ttl_s"])
            self.livro.cache_put(plano.cache_chave, plano.tarefa, ttl, resposta, tok_in, tok_out,
                                 plano.cache_sistema, plano.cache_assinatura,
                                 int(self.cfg["cache"]["max_entradas"]))

    def voo_unico(self, chave: str | None):
        """Chamadas idênticas simultâneas: só a primeira paga; as outras esperam e releem o cache."""
        if not chave:
            return None, True
        with self._lock:
            ev = self._voando.get(chave)
            if ev is None:
                ev = threading.Event()
                self._voando[chave] = ev
                return ev, True
        ev.wait(timeout=120)
        return ev, False

    def voo_fim(self, chave: str | None, ev) -> None:
        if chave and ev is not None:
            with self._lock:
                self._voando.pop(chave, None)
            ev.set()

    # ---------------- planejamento ----------------
    def planejar(self, tarefa: str, mensagens: list[dict], ordem_base: list, modo: str = "auto",
                 forcar: str | None = None) -> Plano:
        dif = complexidade(mensagens, tarefa)
        faixa = self.faixa(dif)
        zona = self.zona()
        locais = [p for p in ordem_base if self.eh_local(p.name)]
        nuvens = [p for p in ordem_base if not self.eh_local(p.name)]
        motivo = []

        # nuvem bloqueada/crítica: só local (a menos que o chamador force e a zona não seja "bloqueado")
        if locais and (zona == "bloqueado" or (zona == "critico" and not forcar)):
            nuvens = []
            motivo.append(f"orçamento {zona}: só local")
        permitidos = {p.name for p in locais + nuvens}
        ordem = [p for p in ordem_base if p.name in permitidos]
        if modo == "auto" and not forcar and locais and nuvens:
            ordem = self._decidir(locais, nuvens, tarefa, dif, faixa, zona, mensagens, motivo)
        # várias nuvens conectadas: a de menor custo esperado por sucesso vem antes
        if not forcar and len(nuvens) > 1:
            ranque = iter(sorted(nuvens, key=self._custo_por_sucesso(faixa)))
            ordem = [next(ranque) if not self.eh_local(p.name) else p for p in ordem]

        plano = Plano(tarefa=tarefa, ordem=ordem, dificuldade=round(dif, 3), faixa=faixa, zona=zona,
                      motivo="; ".join(motivo))
        base_comp, _ = comprimir(mensagens, 10 ** 9, 3.6)
        plano.mensagens["_base"] = base_comp
        reducao = 0.7 if zona == "economico" else 1.0
        for p in ordem:
            tipo = "local" if self.eh_local(p.name) else "nuvem"
            teto = int(self.cfg["orcamento_prompt_tokens"][tipo] * reducao)
            msgs, info = comprimir(mensagens, teto, self.razao(p.name),
                                   int(self.cfg["manter_ultimos"]), float(self.cfg["histerese"]))
            plano.mensagens[p.name] = msgs
            plano.economia[p.name] = info.get("economizados", 0)
            teto_prov = getattr(p, "max_tokens", 4096) or 4096
            mt = self.max_saida(p.name, tarefa, teto_prov)
            plano.max_tokens[p.name] = int(mt * (0.75 if zona == "economico" and tipo == "nuvem" else 1))
        plano.cacheavel = self._cacheavel(tarefa, mensagens)
        if plano.cacheavel:
            plano.cache_chave = self._chave(tarefa, base_comp)
            sis = " ".join(_texto(m) for m in base_comp if m.get("role") == "system")
            plano.cache_sistema = hashlib.sha1(sis.encode("utf-8")).hexdigest()[:12]
            ultima = next((_texto(m) for m in reversed(base_comp) if m.get("role") == "user"), "")
            plano.cache_assinatura = " ".join(sorted(set(w for w in _norm(ultima).split() if len(w) > 2)))
        return plano

    def _custo_por_sucesso(self, faixa: int):
        def chave(p):
            s, f = self.livro.placar(p.name, faixa)
            theta = (s + 4 * 0.9) / (s + f + 4)
            pr = self.precos.get(p.name, {})
            return (pr.get("entrada", 0) * 3 + pr.get("saida", 0)) / max(theta, 0.05)
        return chave

    def _decidir(self, locais, nuvens, tarefa, dif, faixa, zona, mensagens, motivo) -> list:
        """Local primeiro? Thompson sobre o placar real da faixa; só tenta o local se a
        espera extra esperada (falha × tempo do local) cabe na tolerância."""
        local = locais[0]
        s, f = self.livro.placar(local.name, faixa)
        prior_sucesso = max(0.05, 1.0 - 0.95 * dif)               # o que se espera do 3B antes de medir
        a, b = s + 4 * prior_sucesso, f + 4 * (1 - prior_sucesso)
        theta = self.rng.betavariate(max(a, 0.01), max(b, 0.01))
        tps = self.livro.tps(local.name) or float(self.cfg["tps_local_padrao"])
        saida = TETO_SAIDA_PADRAO.get(tarefa, 600) * 0.5
        t_local = saida / max(tps, 0.5)
        espera_extra = (1 - theta) * t_local
        tol = float(self.cfg["espera_extra_max_s"])
        if zona == "economico":
            tol *= 2
            theta += 0.1
        pede_nuvem = dif >= 0.8 and zona != "economico"
        local_primeiro = (theta >= 0.5 and espera_extra <= tol and not pede_nuvem)
        motivo.append(f"dif={dif:.2f} faixa={faixa} θ_local={theta:.2f} espera_extra={espera_extra:.0f}s → "
                      f"{'local' if local_primeiro else 'nuvem'} primeiro")
        return (locais + nuvens) if local_primeiro else (nuvens + locais)

    # ---------------- resultado ----------------
    def deve_escalar(self, q: float, p, proximo) -> bool:
        return (proximo is not None and self.eh_local(p.name) and not self.eh_local(proximo.name)
                and q < float(self.cfg["limiar_qualidade"]))

    def registrar_chamada(self, plano: Plano, p, mensagens: list[dict], resposta: str, ms: float,
                          uso: dict | None, q: float, ok: bool = True, detalhe: str = "") -> dict:
        uso = uso or {}
        razao = self.razao(p.name)
        tok_in = int(uso.get("prompt") or tokens_mensagens(mensagens, razao))
        tok_out = int(uso.get("saida") or estimar_tokens(resposta, razao))
        tok_cache = int(uso.get("cache") or 0)
        if uso.get("prompt"):
            self.aprender_razao(p.name, mensagens, tok_in)
        custo = self.custo(p.name, tok_in, tok_out, tok_cache)
        eco = int(plano.economia.get(p.name, 0))
        if self.eh_local(p.name):
            # tokens que a nuvem teria cobrado se ela fosse a primeira da fila
            eco += (tok_in + tok_out) if any(not self.eh_local(x.name) for x in plano.ordem) else 0
        self.livro.registrar(provedor=p.name, modelo=getattr(p, "model", ""), tarefa=plano.tarefa,
                             origem="api", tok_in=tok_in, tok_out=tok_out, tok_cache=tok_cache,
                             custo=custo, ms=ms, qualidade=q, ok=ok, economia_tok=eco,
                             faixa=plano.faixa, detalhe=detalhe or plano.motivo,
                             resp_hash=hash_resposta(resposta) if resposta else "")
        self._zona_cache = (0.0, self._zona_cache[1])
        return {"tok_in": tok_in, "tok_out": tok_out, "custo": custo}

    def registrar_cache(self, plano: Plano, hit: dict) -> None:
        self.livro.registrar(provedor="cache", tarefa=plano.tarefa, origem="cache",
                             economia_tok=int(hit.get("tok_in", 0)) + int(hit.get("tok_out", 0)),
                             faixa=plano.faixa, detalhe=hit.get("tipo", ""))

    def feedback(self, resposta: str, nota: int) -> dict:
        return self.livro.feedback(resposta, nota)

    # ---------------- relatório ----------------
    def relatorio(self, dias: int = 7) -> dict:
        r = self.livro.resumo(dias)
        t = time.localtime()
        ini_dia = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
        ini_mes = time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        z = self.zona()
        r.update(zona=z, orcamento=self.cfg["orcamento"], hoje=self.livro.somar(ini_dia),
                 mes=self.livro.somar(ini_mes), ativo=self.ativo,
                 precos_usd_por_milhao=self.precos, uso_relativo=round(getattr(self, "_uso_rel", 0.0), 3))
        r["razao_chars_por_token"] = {k: round(v, 2) for k, v in self._razao.items()}
        return r
