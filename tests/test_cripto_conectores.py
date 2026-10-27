"""Conectores de análise gráfica de cripto: catálogo, ligar/desligar, parsing e integração ao relatório."""
from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

from yvakor.config import load_settings
from yvakor.connectors import cripto as C
from yvakor.connectors.manager import ConnectorManager
from yvakor.connectors.providers import CATALOGO
from yvakor.tools.registry import ToolRegistry

IDS = ["cripto_binance", "cripto_tradingview", "cripto_coingecko", "cripto_cryptopanic", "cripto_sentimento"]


def _gerente(tmp_path):
    reg = ToolRegistry(load_settings())
    return reg, ConnectorManager(reg, tmp_path / "connectors.json")


def test_catalogo_tem_os_cinco_conectores_com_forma_valida():
    for cid in IDS:
        spec = CATALOGO[cid]
        assert spec["name"] and spec["icon"] and spec["desc"] and callable(spec["register"])
        assert set(spec["required"]) <= {f["key"] for f in spec["fields"]}
    assert CATALOGO["cripto_cryptopanic"]["required"] == ["token"]               # esse precisa de chave
    assert CATALOGO["cripto_binance"]["fields"][0]["default"] == "sim"           # os públicos: um clique


def test_ligar_registra_as_ferramentas_e_desligar_remove(tmp_path):
    reg, m = _gerente(tmp_path)
    assert not m.is_connected("cripto_binance") and "binance_preco" not in reg.tools
    assert m.connect("cripto_binance", {})["connected"] is True                  # sem digitar nada
    assert {"binance_preco", "binance_livro", "binance_klines", "binance_destaques"} <= set(reg.tools)
    m.connect("cripto_tradingview", {})
    m.connect("cripto_coingecko", {"api_key": "demo-chave"})
    m.connect("cripto_sentimento", {})
    for nome in ("tradingview_analise", "tradingview_grafico_link", "coingecko_moeda", "coingecko_tendencias",
                 "coingecko_global", "stocktwits_sentimento", "medo_ganancia"):
        assert nome in reg.tools, nome
    r = m.connect("cripto_cryptopanic", {})                                       # sem token não liga
    assert r["ok"] is False and "token" in r["erro"] and "cryptopanic_noticias" not in reg.tools
    assert m.connect("cripto_cryptopanic", {"token": "abc-token"})["connected"] and "cryptopanic_noticias" in reg.tools
    publico = json.dumps(m.catalog())
    assert "demo-chave" not in publico and "abc-token" not in publico            # a chave não aparece no catálogo
    m.disconnect("cripto_binance")
    assert "binance_preco" not in reg.tools and "tradingview_analise" in reg.tools
    prefixos = ("binance", "tradingview", "coingecko", "cryptopanic", "stocktwits", "medo")
    assert not any(n in reg.guard.always_confirm for n in reg.tools if n.split("_")[0] in prefixos)   # só leitura


def test_par_binance_e_recomendacao():
    assert C.par_binance("btc") == "BTCUSDT" and C.par_binance("ETH/USDT") == "ETHUSDT" and C.par_binance("solusdt") == "SOLUSDT"
    with pytest.raises(ValueError):
        C.par_binance("  ")
    assert [C._recomendacao(x) for x in (.7, .2, 0, -.2, -.7)] == ["COMPRA FORTE", "COMPRA", "NEUTRO", "VENDA", "VENDA FORTE"]


def test_binance_livro_calcula_pressao_spread_e_paredes(monkeypatch):
    monkeypatch.setattr(C, "_req", lambda *a, **k: {"bids": [["100", "5"], ["99.9", "1"]], "asks": [["100.1", "1"], ["100.2", "0.5"]]})
    r = C.binance_livro("btc")
    assert r["ok"] and r["leitura"] == "pressão compradora" and r["desequilibrio"] > .5
    assert r["parede_compra"] == (100.0, 5.0) and round(r["spread_pct"], 3) == 0.1


def test_binance_destaques_filtra_baixo_volume_e_tokens_alavancados(monkeypatch):
    dados = [{"symbol": "AAAUSDT", "priceChangePercent": "30", "lastPrice": "1", "quoteVolume": "9000000"},
             {"symbol": "LIXOUSDT", "priceChangePercent": "90", "lastPrice": "1", "quoteVolume": "1000"},
             {"symbol": "BTCUPUSDT", "priceChangePercent": "50", "lastPrice": "1", "quoteVolume": "9000000"},
             {"symbol": "BBBUSDT", "priceChangePercent": "-10", "lastPrice": "2", "quoteVolume": "9000000"},
             {"symbol": "ETHBTC", "priceChangePercent": "5", "lastPrice": "2", "quoteVolume": "9000000"}]
    monkeypatch.setattr(C, "_req", lambda *a, **k: dados)
    r = C.binance_destaques(5)
    assert [x["par"] for x in r["sobem"]] == ["AAAUSDT", "BBBUSDT"] and r["caem"][0]["par"] == "BBBUSDT"


def test_tradingview_interpreta_colunas_por_intervalo_e_gera_link(monkeypatch):
    vistos = {}
    nomes = ["Recommend.All", "Recommend.MA", "Recommend.Other", "RSI", "MACD.macd", "MACD.signal", "Stoch.K", "Stoch.D",
             "ADX", "CCI20", "close", "SMA20", "SMA50", "SMA200", "EMA20", "BB.upper", "BB.lower"]
    valores = [.6, .8, .1, 61.2, 10.0, 5.0, 70.0, 65.0, 30.0, 110.0, 100.0, 95, 90, 80, 96, 110.0, 90.0]

    def falso(url, cab=None, corpo=None, timeout=15):
        vistos.update(corpo)
        return {"data": [{"d": valores[:len(corpo["columns"])]}]}
    monkeypatch.setattr(C, "_req", falso)
    r = C.tradingview_analise("btc", "4h")
    assert r["ok"] and r["consenso"] == "COMPRA FORTE" and r["medias_moveis"] == "COMPRA FORTE" and r["osciladores"] == "COMPRA"
    assert "Recommend.All|240" in vistos["columns"] and vistos["symbols"]["tickers"] == ["BINANCE:BTCUSDT"]
    assert r["posicao_bollinger"] == 0.5 and "interval=240" in r["link_grafico"]
    C.tradingview_analise("btc", "1d")
    assert "Recommend.All" in vistos["columns"]                                   # diário: coluna sem sufixo
    monkeypatch.setattr(C, "_req", lambda *a, **k: {"data": []})
    assert C.tradingview_analise("xxx")["ok"] is False


def test_cryptopanic_exige_token_resume_votos_e_nao_vaza_o_token(monkeypatch):
    assert C._cryptopanic({})("btc")["ok"] is False
    usado = {}

    def falso(url, *a, **k):
        usado["url"] = url
        return {"results": [{"title": "BTC sobe", "source": {"title": "Site"}, "url": "u1", "votes": {"positive": 8, "negative": 1}},
                            {"title": "Taxa cai", "source": {"title": "Outro"}, "url": "u2", "votes": {"positive": 1, "negative": 5}}]}
    monkeypatch.setattr(C, "_req", falso)
    r = C._cryptopanic({"token": "meu-token"})("btc", "hot", 5)
    assert r["ok"] and len(r["noticias"]) == 2 and r["saldo_votos"] == round((9 - 6) / 15, 2)
    assert "currencies=BTC" in usado["url"] and "meu-token" not in json.dumps(r)


def test_coingecko_resolve_apelido_busca_e_manda_a_chave_demo(monkeypatch):
    chamadas = []

    def falso(url, cab=None, corpo=None, timeout=15):
        chamadas.append((url, dict(cab or {})))
        if "/search?query=" in url:
            return {"coins": [{"id": "zcash"}]}
        return [{"id": "zcash", "name": "Zcash", "symbol": "zec", "current_price": 50.0, "market_cap_rank": 90, "market_cap": 8e8,
                 "total_volume": 5e7, "ath": 3000, "ath_change_percentage": -98.0, "price_change_percentage_24h_in_currency": 2.0,
                 "price_change_percentage_7d_in_currency": 5.0, "price_change_percentage_30d_in_currency": -3.0}]
    monkeypatch.setattr(C, "_req", falso)
    r = C._coingecko_moeda({"api_key": "k1"})("btc")
    assert r["ok"] and "ids=bitcoin" in chamadas[0][0] and chamadas[0][1] == {"x-cg-demo-api-key": "k1"}
    chamadas.clear()
    r = C._coingecko_moeda({})("zcash coin")                                       # nome livre → busca → id
    assert r["ok"] and r["id"] == "zcash" and "/search?query=" in chamadas[0][0]


def test_erros_http_viram_mensagem_clara(monkeypatch):
    def limite(*a, **k):
        raise urllib.error.HTTPError("u", 429, "x", {}, None)
    monkeypatch.setattr(C, "_req", limite)
    assert "limite" in C.binance_preco("btc")["erro"]

    def cai(*a, **k):
        raise OSError("sem rede")
    monkeypatch.setattr(C, "_req", cai)
    assert C.binance_preco("btc")["ok"] is False


def test_relatorio_usa_so_os_conectores_ligados(monkeypatch, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_economia as E                                                       # candles falsos reaproveitados
    from yvakor import mercado as M
    monkeypatch.setattr(M, "PASTA_GRAFICOS", tmp_path)
    monkeypatch.setattr(M, "candles", lambda *a, **k: E._candles_falsos())
    monkeypatch.setattr(M, "sentimento_stocktwits", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(M, "medo_ganancia", lambda n=30: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(C, "tradingview_analise", lambda s, i="1d", e="BINANCE": {
        "ok": True, "consenso": "COMPRA", "medias_moveis": "COMPRA", "osciladores": "NEUTRO",
        "indicadores": {"ADX": 31.0}, "link_grafico": "https://tv/x"})
    monkeypatch.setattr(C, "binance_livro", lambda s, l=50: {"ok": True, "leitura": "pressão compradora", "desequilibrio": .4,
                                                            "spread_pct": .01, "parede_compra": (100.0, 5.0), "parede_venda": (101.0, 2.0)})
    monkeypatch.setattr(C, "_coingecko_moeda", lambda creds: (lambda m: {"ok": True, "ranking": 1, "valor_mercado": 1.6e12,
                                                                        "dist_maxima_pct": -36.0, "maxima_historica": 126000}))
    monkeypatch.setattr(C, "_coingecko_global", lambda creds: (lambda: {"ok": True, "dominancia": {"BTC": 59.4}}))
    monkeypatch.setattr(C, "_cryptopanic", lambda creds: (lambda m, f, n: {"ok": True, "noticias": [{"titulo": "Manchete X", "fonte": "Site"}]}))
    monkeypatch.setattr(M, "CONECTADO", lambda cid: False)
    sem = M.analisar("btc")["resumo"]
    assert "## Conectores" not in sem and "TradingView" not in sem                 # desligados: nada muda
    monkeypatch.setattr(M, "CONECTADO", lambda cid: True)
    com = M.analisar("btc")["resumo"]
    for pedaco in ("## Conectores", "**TradingView (1d):** consenso **COMPRA**", "https://tv/x", "pressão compradora (+40%)",
                   "#1 em valor de mercado", "dominância BTC 59.4%", "Manchete X"):
        assert pedaco in com, pedaco
    monkeypatch.setattr(M, "CONECTADO", lambda cid: cid == "cripto_tradingview")  # só um ligado
    parcial = M.analisar("btc")["resumo"]
    assert "TradingView" in parcial and "Livro de ofertas" not in parcial and "CoinGecko" not in parcial


def test_seletor_oferece_as_ferramentas_de_cripto():
    from yvakor.tools.router import selecionar
    reg = ToolRegistry(load_settings())
    for cid in ("cripto_binance", "cripto_tradingview", "cripto_sentimento"):
        CATALOGO[cid]["register"](lambda n, f, d="", a=None: reg.register(n, f, d, a), None, {})
    escolhidas = selecionar(reg, "analise o livro de ofertas e o tradingview do btc")
    assert "binance_livro" in escolhidas and "tradingview_analise" in escolhidas
