"""Otimizador de consumo de APIs: compressão, cache, cascata, bandit, orçamento."""
from __future__ import annotations

import json
import random
import threading
import time

import pytest

from yvakor.config import load_settings
from yvakor.llm import economia as E
from yvakor.llm.adapter import ProviderErro
from yvakor.llm.router import LLMRouter

BOA = "Claro. O sistema usa uma memória local e consulta o modelo apenas quando precisa, para economizar."


class Falso:
    """Provedor de mentira: responde roteiros e simula o uso REAL (tokens) da API."""

    def __init__(self, name, respostas, max_tokens=1024):
        self.name, self.model, self.max_tokens = name, name + "-m", max_tokens
        self.respostas = list(respostas)
        self.chamadas = []
        self._uso = None

    @property
    def ultimo_uso(self):
        return self._uso

    def chat_messages(self, msgs, timeout=None, max_tokens=None):
        self.chamadas.append({"msgs": msgs, "max_tokens": max_tokens})
        r = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(r, Exception):
            raise r
        chars = sum(len(m.get("content") or "") for m in msgs)
        self._uso = {"prompt": chars // 4, "saida": max(5, len(r) // 4), "cache": 0, "finish": "stop"}
        return r


def _router(local, nuvem, modo="auto", cfg=None):
    r = LLMRouter(load_settings())
    r.providers = {"deepseek": nuvem, "ollama": local}
    r.modo = modo
    r.otim.providers = r.providers
    r.otim.rng = random.Random(7)            # Thompson sampling determinístico no teste
    r.otim.cfg.update(cfg or {})
    r.otim.precos = r.otim._precos()
    r.otim._zona_cache = (0.0, "normal")
    return r


def _msgs(pergunta, extra=None, sistema="Você é o YVAKOR."):
    return [{"role": "system", "content": sistema}, *(extra or []),
            {"role": "user", "content": pergunta}]


# --------------------------------------------------------------------------- #
# compressão
# --------------------------------------------------------------------------- #
def test_comprimir_nao_mexe_no_que_cabe_e_tira_ruido():
    m = [{"role": "system", "content": "Sistema   com   espaços\n\n\n\nmuitos"},
         {"role": "user", "content": "oi"}, {"role": "user", "content": "oi"}]
    novo, info = E.comprimir(m, 5000)
    assert len(novo) == 2 and "\n\n\n" not in novo[0]["content"] and "   " not in novo[0]["content"]
    assert info["depois"] <= info["antes"]


def test_comprimir_corta_meio_resume_antigas_e_protege_o_essencial():
    historico = []
    for i in range(30):
        historico.append({"role": "user", "content": f"passo {i}: " + "dados " * 400})
        historico.append({"role": "assistant", "content": f"feito {i}. " + "x " * 300})
    msgs = _msgs("Qual foi o resultado final? PERGUNTA-FINAL", historico, sistema="SISTEMA-ESTAVEL " * 50)
    antes = E.tokens_mensagens(msgs)
    novo, info = E.comprimir(msgs, 3000, manter_ultimos=6)
    depois = E.tokens_mensagens(novo)
    assert antes > 20000 and depois <= 3000                       # coube no teto
    assert novo[0]["role"] == "system" and novo[0]["content"].startswith("SISTEMA-ESTAVEL")
    assert "PERGUNTA-FINAL" in novo[-1]["content"]                # a última pergunta é intocável
    assert any("resumo de" in (m["content"] or "") for m in novo)  # histórico virou resumo
    assert info["economizados"] > 15000


def test_comprimir_usa_histerese_para_manter_o_prefixo_estavel():
    base = _msgs("pergunta", [{"role": "user", "content": "contexto " * 900},
                              {"role": "assistant", "content": "ok " * 900}] * 3)
    novo, _ = E.comprimir(base, 2000, histerese=0.65)
    assert E.tokens_mensagens(novo) <= 2000 * 0.65 + 60           # desce abaixo do teto, com folga
    de_novo, info2 = E.comprimir(novo + [{"role": "user", "content": "mais uma"}], 2000)
    assert info2["economizados"] == 0                              # a próxima rodada não recomprime


# --------------------------------------------------------------------------- #
# verificação e dificuldade
# --------------------------------------------------------------------------- #
def test_avaliar_pega_vazio_repeticao_idioma_e_truncamento():
    assert E.avaliar("") == 0.0
    assert E.avaliar(BOA) >= 0.85
    assert E.avaliar("blá " * 120) < 0.3                                       # laço de repetição
    assert E.avaliar("The system keeps the memory on this machine and the model is called only when it is needed, "
                     "so that the cost stays low for the user and the answers remain fast with this setup.") < 0.5
    assert E.avaliar("texto que foi cortado no meio da frase " * 20, finish="length") <= 0.5
    assert E.avaliar("Como um modelo de linguagem, não consigo ajudar com isso agora.") <= 0.55
    assert E.avaliar("ok", "analise_complexa") < 0.5


def test_complexidade_separa_trivial_de_pesado():
    leve = E.complexidade(_msgs("oi, tudo bem?"), "resposta_simples")
    pesado = E.complexidade(_msgs("Compare a arquitetura A e B passo a passo e implemente o refator em Python",
                                  sistema="use usar_ferramenta"), "arquitetura")
    assert leve < 0.25 < 0.6 < pesado


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
def test_cache_exato_zera_tokens_na_repeticao_e_registra_economia():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    m = _msgs("Explique o que é um índice de banco de dados.")
    a = r.complete_messages("resposta_simples", m)
    b = r.complete_messages("resposta_simples", m)
    assert a == b == BOA and len(local.chamadas) + len(nuvem.chamadas) == 1   # 2ª foi do cache
    rel = r.otim.relatorio()
    assert rel["cache_hits"] == 1 and rel["tokens_economizados"] > 0


def test_cache_aceita_quase_duplicata_de_pergunta_avulsa():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    r.complete_messages("resposta_simples", _msgs("Explique o que é um índice de banco de dados relacional"))
    r.complete_messages("resposta_simples", _msgs("explique o que é um índice de banco de dados relacional?!"))
    assert len(local.chamadas) + len(nuvem.chamadas) == 1
    r.complete_messages("resposta_simples", _msgs("Como fazer um bolo de chocolate fofinho com cobertura"))
    assert len(local.chamadas) + len(nuvem.chamadas) == 2                    # assunto diferente: chama


@pytest.mark.parametrize("pergunta,tarefa,extra", [
    ("Qual a cotação do dólar agora?", "resposta_simples", None),            # sensível ao tempo
    ("Quais as últimas notícias?", "resposta_simples", None),
    ("Faça isso", "analise_complexa", None),                                  # tarefa não cacheável
    ("Liste os arquivos", "resposta_simples",
     [{"role": "user", "content": "OBSERVAÇÃO: arquivos a.txt b.txt"}]),      # passo de agente
])
def test_cache_nao_guarda_o_que_nao_deve(pergunta, tarefa, extra):
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    m = _msgs(pergunta, extra)
    r.complete_messages(tarefa, m)
    r.complete_messages(tarefa, m)
    assert len(local.chamadas) + len(nuvem.chamadas) == 2


def test_voo_unico_chamadas_identicas_simultaneas_pagam_uma_vez():
    class Lento(Falso):
        def chat_messages(self, msgs, timeout=None, max_tokens=None):
            time.sleep(0.4)
            return super().chat_messages(msgs, timeout, max_tokens)
    local, nuvem = Lento("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    m = _msgs("Explique o que é uma chave estrangeira em SQL.")
    saidas = []
    ts = [threading.Thread(target=lambda: saidas.append(r.complete_messages("resposta_simples", m)))
          for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert saidas == [BOA] * 6 and len(local.chamadas) + len(nuvem.chamadas) == 1


# --------------------------------------------------------------------------- #
# roteamento / cascata
# --------------------------------------------------------------------------- #
def test_tarefa_facil_fica_no_local_e_nao_toca_na_nuvem():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    for pergunta in ("Quem é você?", "Me diga um sinônimo de rápido", "O que significa API?"):
        r.complete_messages("resposta_simples", _msgs(pergunta))
    assert len(nuvem.chamadas) == 0 and len(local.chamadas) == 3
    assert r.otim.relatorio()["tokens_economizados"] > 0             # tokens que a nuvem não cobrou


def test_cascata_local_ruim_escala_para_a_nuvem_com_o_mesmo_prompt_enxuto():
    local, nuvem = Falso("ollama", [""]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    out = r.complete_messages("resposta_simples", _msgs("Explique o que é recursão em programação."))
    assert out == BOA and len(local.chamadas) == 1 and len(nuvem.chamadas) == 1
    local2 = Falso("ollama", ["blá " * 150])                          # laço de repetição também escala
    nuvem2 = Falso("deepseek", [BOA])
    out = _router(local2, nuvem2).complete_messages("resposta_simples", _msgs("Explique o que é um ponteiro."))
    assert out == BOA and len(nuvem2.chamadas) == 1


def test_tarefa_pesada_vai_direto_para_a_nuvem_sem_gastar_o_local():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    pedido = ("Compare a arquitetura de microsserviços com a monolítica passo a passo, em detalhes, "
              "e planeje a migração com a estratégia de otimização. " * 3)
    r.complete_messages("arquitetura", _msgs(pedido, sistema="regras. use usar_ferramenta"))
    assert len(nuvem.chamadas) == 1 and len(local.chamadas) == 0


def test_bandit_aprende_que_o_local_nao_da_conta_naquela_faixa():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    pergunta = "Explique a diferença entre processo e thread em sistemas operacionais."
    dif = E.complexidade(_msgs(pergunta), "resposta_simples")
    faixa = r.otim.faixa(dif)
    antes = r.otim.planejar("resposta_simples", _msgs(pergunta), [local, nuvem], "auto")
    assert antes.ordem[0] is local                                      # sem histórico: aposta no local
    for _ in range(40):                                                 # o local falhou 40x nessa faixa
        r.otim.livro.registrar(provedor="ollama", tarefa="resposta_simples", origem="api",
                               qualidade=0.1, ok=1, faixa=faixa, tok_in=100, tok_out=50)
    for _ in range(40):                                                 # e a nuvem acertou
        r.otim.livro.registrar(provedor="deepseek", tarefa="resposta_simples", origem="api",
                               qualidade=0.95, ok=1, faixa=faixa, tok_in=100, tok_out=50, custo=0.0001)
    primeiros = {r.otim.planejar("resposta_simples", _msgs(pergunta), [local, nuvem], "auto").ordem[0].name
                 for _ in range(15)}
    assert primeiros == {"deepseek"}


def test_modo_local_nunca_chama_a_nuvem_mesmo_otimizado():
    local, nuvem = Falso("ollama", [""]), Falso("deepseek", [BOA])
    r = _router(local, nuvem, modo="local")
    with pytest.raises(RuntimeError):
        r.complete_messages("resposta_simples", _msgs("Explique recursão."))
    assert nuvem.chamadas == []


def test_modo_deepseek_respeita_a_ordem_do_usuario_mas_ainda_comprime():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem, modo="deepseek")
    longo = [{"role": "user", "content": "contexto " * 3000}, {"role": "assistant", "content": "certo " * 3000}] * 3
    r.complete_messages("resposta_simples", _msgs("Resuma.", longo))
    assert len(nuvem.chamadas) == 1 and local.chamadas == []
    enviado = nuvem.chamadas[0]["msgs"]
    assert E.tokens_mensagens(enviado) <= 7000                         # cabia no orçamento da nuvem


def test_falha_da_nuvem_cai_no_local_e_cooldown_respeita_retry_after():
    nuvem = Falso("deepseek", [ProviderErro("HTTP 429", codigo=429, espera_s=90)])
    local = Falso("ollama", [BOA])
    r = _router(local, nuvem, modo="deepseek")
    assert r.complete_messages("resposta_simples", _msgs("Explique hashing.")) == BOA
    assert r._cooldown["deepseek"] - time.time() > 60                    # esperou o Retry-After da API


# --------------------------------------------------------------------------- #
# teto de saída, custo real, orçamento
# --------------------------------------------------------------------------- #
def test_max_tokens_comeca_pelo_padrao_da_tarefa_e_adapta_ao_p90_real():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem, modo="deepseek")
    r.complete_messages("classificacao", _msgs("Classifique: ótimo produto"))
    assert nuvem.chamadas[-1]["max_tokens"] == 64                         # padrão: classificação é curta
    for n in [200] * 20:
        r.otim.livro.registrar(provedor="deepseek", tarefa="resposta_simples", origem="api",
                               tok_out=n, ok=1, tok_in=50)
    # histórico curto não derruba o teto abaixo do padrão (cortava respostas longas)
    assert r.otim.max_saida("deepseek", "resposta_simples", 4096) == E.TETO_SAIDA_PADRAO["resposta_simples"]
    for n in [800] * 20:
        r.otim.livro.registrar(provedor="deepseek", tarefa="resposta_simples", origem="api",
                               tok_out=n, ok=1, tok_in=50)
    assert r.otim.max_saida("deepseek", "resposta_simples", 4096) == 800 * 13 // 10 + 32  # sobe pelo p90


def test_custo_usa_tokens_reais_e_o_desconto_de_cache_de_prefixo():
    o = E.Otimizador({"precos_usd_por_milhao": {"deepseek": {"entrada": 0.28, "cache": 0.028, "saida": 0.42}}},
                     {"deepseek": Falso("deepseek", [BOA]), "ollama": Falso("ollama", [BOA])})
    cheio = o.custo("deepseek", 10000, 500, 0)
    com_cache = o.custo("deepseek", 10000, 500, 9000)
    assert cheio == pytest.approx((10000 * 0.28 + 500 * 0.42) / 1e6)
    assert com_cache < cheio * 0.4                                         # prefixo em cache custa 10×
    assert o.custo("ollama", 10000, 500) == 0.0


def test_orcamento_aperta_por_zonas_e_bloqueia_a_nuvem():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem, modo="deepseek")
    o = r.otim
    o.definir_orcamento(diario_usd=1.0, mensal_usd=0, diario_tokens=0)
    assert o.zona() == "normal"
    o.livro.registrar(provedor="deepseek", origem="api", custo=0.75, tok_in=1, tok_out=1)
    o._zona_cache = (0.0, "normal")
    assert o.zona() == "economico"
    o.livro.registrar(provedor="deepseek", origem="api", custo=0.2, tok_in=1, tok_out=1)
    o._zona_cache = (0.0, "normal")
    assert o.zona() == "critico"
    r.complete_messages("resposta_simples", _msgs("Explique cache."))
    assert nuvem.chamadas == [] and len(local.chamadas) == 1               # modo deepseek, mas o orçamento manda
    o.livro.registrar(provedor="deepseek", origem="api", custo=0.5, tok_in=1, tok_out=1)
    o._zona_cache = (0.0, "normal")
    assert o.zona() == "bloqueado"
    assert [p.name for p in o.planejar("resposta_simples", _msgs("x"), [nuvem, local], "deepseek",
                                       forcar="deepseek").ordem] == ["ollama"]


def test_orcamento_de_tokens_diarios_tambem_conta():
    o = E.Otimizador({"orcamento": {"diario_usd": 0, "mensal_usd": 0, "diario_tokens": 1000}},
                     {"deepseek": Falso("deepseek", [BOA])})
    o.livro.registrar(provedor="deepseek", origem="api", tok_in=800, tok_out=250, custo=0.0001)
    o._zona_cache = (0.0, "normal")
    assert o.zona() == "bloqueado"


def test_ledger_guarda_tokens_reais_da_api_e_calibra_a_razao():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem, modo="deepseek")
    r.complete_messages("resposta_simples", _msgs("Explique o que é um banco de dados " * 20))
    rel = r.otim.relatorio()
    api = rel["por_provedor"]["deepseek"]["api"]
    assert api["chamadas"] == 1 and api["tok_in"] > 0 and api["tok_out"] > 0 and api["custo_usd"] > 0
    assert "deepseek" in rel["razao_chars_por_token"]                       # aprendeu chars/token real


# --------------------------------------------------------------------------- #
# robustez do próprio otimizador
# --------------------------------------------------------------------------- #
def test_se_o_otimizador_quebrar_o_caminho_original_responde(monkeypatch):
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    monkeypatch.setattr(r.otim, "planejar", lambda *a, **k: (_ for _ in ()).throw(ValueError("bug")))
    assert r.complete_messages("resposta_simples", _msgs("Explique recursão.")) == BOA


def test_provedor_antigo_sem_max_tokens_nem_ultimo_uso_continua_funcionando():
    class Velho:
        name, model, max_tokens = "ollama", "m", 512
        def chat_messages(self, msgs, timeout=None):
            return BOA
    r = _router(Velho(), Falso("deepseek", [BOA]))
    assert r.complete_messages("resposta_simples", _msgs("Explique recursão.")) == BOA


def test_complete_com_system_e_user_tambem_passa_pelo_otimizador():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    assert r.complete("resposta_simples", "Seja breve.", "Explique recursão.") == BOA
    assert r.complete("resposta_simples", "Seja breve.", "Explique recursão.") == BOA
    assert len(local.chamadas) + len(nuvem.chamadas) == 1


# --------------------------------------------------------------------------- #
# adapter: uso real e janela do Ollama
# --------------------------------------------------------------------------- #
def test_adapter_captura_uso_real_deepseek_e_ollama_e_fixa_num_ctx():
    from yvakor.llm.adapter import LLMProvider
    ds = LLMProvider("deepseek", "https://x", "m")
    ds._post_bruto = lambda url, payload, timeout=None: {
        "choices": [{"message": {"content": "oi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 30, "prompt_cache_hit_tokens": 1000}}
    assert ds.chat_messages([{"role": "user", "content": "x"}]) == "oi"
    assert ds.ultimo_uso == {"prompt": 1200, "saida": 30, "cache": 1000, "finish": "stop"}
    vistos = {}
    ol = LLMProvider("ollama", "http://localhost:11434", "q", num_thread=3, num_ctx=4096)
    def falso(url, payload, timeout=None):
        vistos.update(payload["options"])
        return {"message": {"content": "olá"}, "prompt_eval_count": 90, "eval_count": 12, "done_reason": "stop"}
    ol._post_bruto = falso
    assert ol.chat_messages([{"role": "user", "content": "x"}], max_tokens=77) == "olá"
    assert vistos["num_ctx"] == 4096 and vistos["num_predict"] == 77 and vistos["num_thread"] == 3
    assert ol.ultimo_uso["prompt"] == 90 and ol.ultimo_uso["saida"] == 12


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_endpoints_de_consumo_e_orcamento(tmp_path):
    import sys
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    if str(raiz / "tests") not in sys.path:
        sys.path.insert(0, str(raiz / "tests"))
    import test_seguranca_e_processos as base
    r = _router(Falso("ollama", [BOA]), Falso("deepseek", [BOA]))
    r.complete_messages("resposta_simples", _msgs("Explique recursão."))
    S, srv, port = base._servidor(base._AgenteFalso(r))
    try:
        st, corpo = base._req(port, "GET", "/api/consumo")
        assert st == 200
        j = json.loads(corpo)
        assert j["ok"] and j["zona"] == "normal" and "por_provedor" in j and "hoje" in j
        assert base._req(port, "POST", "/api/consumo/orcamento", body={"diario_usd": 2})[0] == 403
        st, corpo = base._req(port, "POST", "/api/consumo/orcamento", token=S.TOKEN,
                              body={"diario_usd": 2.5, "mensal_usd": 30})
        assert st == 200 and json.loads(corpo)["orcamento"]["diario_usd"] == 2.5
        assert base._req(port, "POST", "/api/consumo/orcamento", token=S.TOKEN,
                         body={"diario_usd": "abc"})[0] == 400
    finally:
        base._fechar(S, srv)


def test_resposta_vazia_do_local_escala_mas_nao_poe_o_local_em_cooldown():
    class Vazio(Falso):
        def chat_messages(self, msgs, timeout=None, max_tokens=None):
            raise ProviderErro("ollama: resposta vazia")
    local, nuvem = Vazio("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    assert r.complete_messages("resposta_simples", _msgs("Explique o que é um mutex.")) == BOA
    assert "ollama" not in r._cooldown                      # falha de qualidade ≠ provedor fora do ar
    assert len(nuvem.chamadas) == 1


# --------------------------------------------------------------------------- #
# regressões achadas na verificação geral
# --------------------------------------------------------------------------- #
def test_conta_em_linguagem_natural_e_extraida_e_calculada():
    from yvakor.capacidades import calcular
    from yvakor.voz.diretos import _expressao_da_conta as conta
    casos = {"quanto é 2+2? responda só o número": 4, "calcule 15% de 200": 30.0,
             "quanto e 10 x 3?": 30, "calcule 2^10": 1024, "quanto é 3,5 + 1,5": 5.0,
             "quanto é (3+4)*5 por favor": 35}
    for frase, esperado in casos.items():
        assert calcular(conta(frase))["resultado"] == esperado, frase
    assert calcular("__import__('os').system('x')")["ok"] is False        # continua seguro


def test_pdf_com_pouco_texto_e_lido_mesmo_sem_ocr(tmp_path):
    import pymupdf
    from yvakor import documentos
    pdf = tmp_path / "curto.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Texto curto do PDF")
    doc.save(str(pdf))
    doc.close()
    r = documentos.ler_documento(pdf)
    assert r["ok"] and "Texto curto" in r["texto"]


def test_avaliar_resposta_tolera_modelo_que_foge_do_json():
    from yvakor.colaboracao import avaliar_resposta

    class Router:
        def __init__(self, saidas):
            self.saidas, self.n = list(saidas), 0
        def complete_messages(self, tarefa, msgs, **k):
            self.n += 1
            return self.saidas.pop(0)
    r = Router(["Claro! A resposta é boa.", '{"nota": 4, "problemas": []}'])
    out = avaliar_resposta(r, "2+2?", "4")
    assert out["ok"] and out["nota"] == 4 and r.n == 2                 # reperguntou e conseguiu
    out = avaliar_resposta(Router(["Dou nota 5 porque está correta.", "Nota: 5, correta"]), "p", "r")
    assert out["ok"] and out["nota"] == 5 and out["aproximada"]       # nota solta no texto
    assert avaliar_resposta(Router(["sem nada", "ainda nada"]), "p", "r")["ok"] is False


# --------------------------------------------------------------------------- #
# análise de mercado (dados reais mockados) e exibição no chat
# --------------------------------------------------------------------------- #
def _candles_falsos(n=220, base=60000.0):
    import numpy as np
    rng = np.random.default_rng(1)
    c = base * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.01
    l = np.minimum(o, c) * 0.99
    t = 1_700_000_000 + np.arange(n) * 86400
    return {"t": t.astype(float), "o": o, "h": h, "l": l, "c": c, "v": rng.uniform(900, 1500, n),
            "fonte": "falsa"}


def test_indicadores_batem_com_calculo_de_referencia():
    import numpy as np
    from yvakor import mercado as M
    x = np.arange(1, 31, dtype=float)
    assert M.sma(x, 5)[-1] == pytest.approx(28.0)
    assert np.isnan(M.sma(x, 5)[3])
    assert M.rsi(x)[-1] == pytest.approx(100.0)                      # só subidas
    assert M.rsi(x[::-1].copy())[-1] == pytest.approx(0.0)           # só quedas
    assert M.ema(np.full(40, 7.0), 10)[-1] == pytest.approx(7.0)
    assert M._fmt(81189.43) == "81.189" and M._fmt(1234.5, 2) == "1.234,50" and M._pct(2.5) == "+2,50%"
    assert M.resolver_ativo("analise do bitcoin") == ("BTC", "cripto")
    assert M.resolver_ativo("faz uma analise do $TSLA") == ("TSLA", "acao")


def test_analisar_gera_resumo_completo_graficos_e_sentimento(monkeypatch, tmp_path):
    from yvakor import mercado as M
    monkeypatch.setattr(M, "PASTA_GRAFICOS", tmp_path)
    monkeypatch.setattr(M, "candles", lambda *a, **k: _candles_falsos())
    monkeypatch.setattr(M, "sentimento_stocktwits", lambda *a, **k: {
        "simbolo": "BTC.X", "mensagens": 30, "altistas": 12, "baixistas": 3, "neutras": 15, "saldo": 0.6,
        "watchlist": 685030, "destaques": [{"autor": "fulano", "sentimento": "Bullish", "curtidas": 5,
                                            "texto": "rompendo a resistência"}]})
    monkeypatch.setattr(M, "medo_ganancia", lambda n=30: {"valor": 48, "classe": "Neutral", "historico": list(range(30, 60))})
    r = M.analisar("bitcoin", "1d")
    assert r["ok"] and r["ativo"] == "BTC"
    md = r["resumo"]
    for pedaco in ("Veredito técnico", "| Indicador | Valor | Leitura |", "SMA 200", "RSI 14", "Suportes",
                   "Cenários de referência", "StockTwits (BTC.X)", "Medo & Ganância", "não é recomendação"):
        assert pedaco in md, pedaco
    assert len(r["arquivos"]) == 2 and all(__import__("pathlib").Path(a["arquivo"]).stat().st_size > 5000
                                           for a in r["arquivos"])
    assert -100 <= r["score"] <= 100


def test_analisar_tolera_fontes_fora_do_ar(monkeypatch, tmp_path):
    from yvakor import mercado as M
    monkeypatch.setattr(M, "PASTA_GRAFICOS", tmp_path)
    monkeypatch.setattr(M, "candles", lambda *a, **k: _candles_falsos())
    def cai(*a, **k):
        raise OSError("sem rede")
    monkeypatch.setattr(M, "sentimento_stocktwits", cai)
    monkeypatch.setattr(M, "medo_ganancia", cai)
    r = M.analisar("ETH")
    assert r["ok"] and any("StockTwits" in a for a in r["avisos"]) and "Veredito técnico" in r["resumo"]
    monkeypatch.setattr(M, "candles", cai)
    assert M.analisar("BTC")["ok"] is False                      # sem preço não há análise: erro claro


def test_pedido_de_analise_vira_resposta_completa_com_graficos_no_chat_sem_llm(monkeypatch, tmp_path):
    from yvakor import mercado as M
    from yvakor.voz.diretos import detectar, executar
    monkeypatch.setattr(M, "PASTA_GRAFICOS", tmp_path)
    monkeypatch.setattr(M, "candles", lambda *a, **k: _candles_falsos())
    monkeypatch.setattr(M, "sentimento_stocktwits", lambda *a, **k: None if False else {
        "simbolo": "BTC.X", "mensagens": 2, "altistas": 1, "baixistas": 1, "neutras": 0, "saldo": 0.0,
        "watchlist": None, "destaques": []})
    monkeypatch.setattr(M, "medo_ganancia", lambda n=30: {"valor": 20, "classe": "Extreme Fear", "historico": [20] * 30})
    intent = detectar("analise do btc com graficos e analise stocktwits")
    assert intent and intent["acao"] == "mercado"
    for frase in ("como esta o sol hoje", "analise o arquivo relatorio.pdf", "escreva um codigo python para analisar bitcoin"):
        assert (detectar(frase) or {}).get("acao") != "mercado", frase
    class Orq:
        ultimos_artefatos = []
    o = Orq()
    resposta = executar(o, intent)
    assert "Veredito técnico" in resposta and "StockTwits" in resposta
    imgs = [a for a in o.ultimos_artefatos if a["tipo"] == "imagem"]
    assert len(imgs) == 2 and all(a["url"].startswith("/midia/graficos/mercado_BTC_") for a in imgs)


def test_ferramenta_mercado_registrada_e_oferecida_ao_modelo():
    from yvakor.tools.registry import ToolRegistry
    from yvakor.tools.router import selecionar
    from yvakor import mercado as M
    reg = ToolRegistry(load_settings())
    M.registrar_ferramentas(reg)
    assert "mercado_analisar" in reg.tools
    escolhidas = selecionar(reg, "analise do btc com graficos e analise stocktwits")
    assert "mercado_analisar" in escolhidas[:3]


# --------------------------------------------------------------------------- #
# polegar do usuário ensina o roteador; pesquisa melhor; passos na resposta
# --------------------------------------------------------------------------- #
def test_polegar_para_baixo_derruba_a_qualidade_e_apaga_do_cache():
    local, nuvem = Falso("ollama", [BOA]), Falso("deepseek", [BOA])
    r = _router(local, nuvem)
    m = _msgs("Explique o que é um índice de banco de dados.")
    r.complete_messages("resposta_simples", m)
    assert r.complete_messages("resposta_simples", m) == BOA and len(local.chamadas) == 1     # veio do cache
    efeito = r.otim.feedback(BOA, 1)                                                           # 👎
    assert efeito["atualizadas"] >= 1 and efeito["cache_removido"] == 1
    r.complete_messages("resposta_simples", m)
    assert len(local.chamadas) + len(nuvem.chamadas) == 2                                       # recalculou: a ruim saiu do cache
    s, f = r.otim.livro.placar("ollama", r.otim.faixa(E.complexidade(m, "resposta_simples")))
    assert f >= 1                                                                              # e o bandit contou a falha
    assert r.otim.feedback(BOA, 5)["cache_removido"] == 0                                      # 👍 só reforça


def test_endpoint_feedback_ensina_o_otimizador(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    if str(raiz / "tests") not in sys.path:
        sys.path.insert(0, str(raiz / "tests"))
    import test_seguranca_e_processos as base
    r = _router(Falso("ollama", [BOA]), Falso("deepseek", [BOA]))
    r.complete_messages("resposta_simples", _msgs("Explique recursão em uma frase."))
    S, srv, port = base._servidor(base._AgenteFalso(r))
    monkeypatch.setattr(S, "ROOT", tmp_path)
    try:
        st, corpo = base._req(port, "POST", "/api/feedback", token=S.TOKEN,
                              body={"nota": 1, "pergunta": "p", "resposta": BOA})
        assert st == 200 and json.loads(corpo)["aprendizado"]["atualizadas"] >= 1
    finally:
        base._fechar(S, srv)


def test_pesquisa_limpa_pedido_filtra_lixo_e_usa_fontes_certas(monkeypatch):
    from yvakor import pesquisa as P
    assert P.limpar_consulta("pesquise sobre as últimas notícias do bitcoin") == "as últimas notícias do bitcoin"
    assert P.limpar_consulta("me diga como instalar docker") == "como instalar docker"
    lixo = [{"titulo": "Baixar Google Chrome", "url": "https://x.com/chrome"},
            {"titulo": "Docker no Windows: guia", "url": "https://x.com/docker-windows"}]
    monkeypatch.setattr(P, "_buscar_motores", lambda q, n=8: list(lixo))
    monkeypatch.setattr(P, "buscar_stackoverflow", lambda q, n=4: [{"titulo": "Erro docker", "url": "https://so/1", "fonte": "stackoverflow"}])
    monkeypatch.setattr(P, "buscar_brave", lambda q, n=8: [])
    achados = P.buscar("como instalar docker no windows", 5)
    urls = [a["url"] for a in achados]
    assert "https://x.com/chrome" not in urls and "https://x.com/docker-windows" in urls and "https://so/1" in urls
    # dicionário só aparece em pedido de definição
    dic = [{"titulo": "recursão significado", "url": "https://www.dicio.com.br/recursao/"},
           {"titulo": "Recursão em programação", "url": "https://x.com/recursao"}]
    assert P.reordenar(dic, "explique recursão em programação")[0]["url"] == "https://x.com/recursao"
    assert P.reordenar(dic, "qual o significado de recursão")[0]["url"].endswith("dicio.com.br/recursao/")


def test_pesquisa_web_sem_resultado_relevante_orienta_o_agente(monkeypatch):
    from yvakor import pesquisa as P
    from yvakor.tools.registry import ToolRegistry
    monkeypatch.setattr(P, "buscar", lambda q, n=8: [])
    reg = ToolRegistry(load_settings())
    P.registrar_ferramentas(reg, router=None)
    r = reg.run("pesquisa_web", pergunta="algo")
    assert r["ok"] and r["resultados"] == [] and "BRAVE_API_KEY" in r["aviso"] and "navegador_pesquisar" in r["aviso"]
