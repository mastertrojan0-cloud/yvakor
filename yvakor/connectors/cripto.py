"""YVAKOR — conectores de análise gráfica de cripto (somente leitura).

  Binance        preço, livro de ofertas (pressão compradora/vendedora), candles, destaques do dia
  TradingView    consenso técnico (Comprar/Vender) e osciladores por intervalo + link do gráfico
  CoinGecko      valor de mercado, ranking, máxima histórica, tendências e dominância do BTC
  CryptoPanic    notícias com votos da comunidade (chave grátis)
  Sentimento     StockTwits + Índice Medo & Ganância

Nenhum deles opera/negocia: só lê dados públicos. Cada conector se liga/desliga em
Configurações → Conectores, e quando ligado também alimenta a `mercado_analisar`
(o relatório com os gráficos que aparece no chat).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

UA = "YVAKOR/1.0 (agente local; analise de mercado)"
TV_ESCANER = "https://scanner.tradingview.com/{tela}/scan"

# intervalo do YVAKOR -> sufixo de coluna do TradingView
_TV_SUFIXO = {"1m": "|1", "5m": "|5", "15m": "|15", "30m": "|30", "1h": "|60", "2h": "|120",
              "4h": "|240", "1d": "", "1w": "|1W", "1M": "|1M"}
_TV_CHART = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240",
             "1d": "D", "1w": "W", "1M": "M"}
_APELIDOS = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana", "bnb": "binancecoin", "xrp": "ripple",
             "ada": "cardano", "doge": "dogecoin", "ltc": "litecoin", "avax": "avalanche-2", "link": "chainlink",
             "dot": "polkadot", "zec": "zcash", "trx": "tron", "shib": "shiba-inu", "pepe": "pepe",
             "matic": "matic-network", "ton": "the-open-network", "sui": "sui", "near": "near", "atom": "cosmos"}


def _req(url: str, cabecalhos: dict | None = None, corpo: dict | None = None, timeout: int = 15):
    data = json.dumps(corpo).encode() if corpo is not None else None
    h = {"User-Agent": UA, "Accept": "application/json", **({"Content-Type": "application/json"} if corpo is not None else {}),
         **(cabecalhos or {})}
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
        return json.loads(r.read(2_000_000).decode("utf-8", "replace"))


def _seguro(fn):
    def interno(*a, **k):
        try:
            return fn(*a, **k)
        except urllib.error.HTTPError as exc:
            msg = {401: "chave recusada", 403: "acesso negado (chave/limite)", 429: "limite de uso atingido — tente em instantes"}.get(
                exc.code, f"HTTP {exc.code}")
            return {"ok": False, "erro": msg}
        except Exception as exc:
            return {"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:100]}"}
    interno.__name__ = fn.__name__
    return interno


def par_binance(simbolo: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]", "", str(simbolo or "")).upper()
    if not s:
        raise ValueError("informe o ativo (ex.: BTC)")
    return s if s.endswith(("USDT", "BUSD", "USDC", "BTC", "ETH", "BRL")) and len(s) > 4 else s + "USDT"


def _fmt(v, casas=None) -> str:
    v = float(v)
    n = casas if casas is not None else (0 if abs(v) >= 1000 else 2 if abs(v) >= 1 else 6 if abs(v) < 0.01 else 4)
    return f"{v:,.{n}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _grande(v) -> str:
    v = float(v)
    for lim, suf in ((1e12, " tri"), (1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if abs(v) >= lim:
            return f"{v / lim:,.2f}".replace(".", ",") + suf
    return _fmt(v, 2)


# --------------------------------------------------------------------------- #
# Binance
# --------------------------------------------------------------------------- #
@_seguro
def binance_preco(simbolo: str = "BTC") -> dict:
    par = par_binance(simbolo)
    d = _req(f"https://api.binance.com/api/v3/ticker/24hr?symbol={par}")
    p, var = float(d["lastPrice"]), float(d["priceChangePercent"])
    return {"ok": True, "par": par, "preco": p, "var_24h_pct": var, "maxima_24h": float(d["highPrice"]),
            "minima_24h": float(d["lowPrice"]), "volume_usdt": float(d["quoteVolume"]),
            "resumo": f"{par}: US$ {_fmt(p)} ({var:+.2f}% em 24h) · máx. {_fmt(d['highPrice'])} · mín. {_fmt(d['lowPrice'])} · "
                      f"volume {_grande(d['quoteVolume'])} USDT"}


@_seguro
def binance_livro(simbolo: str = "BTC", limite: int = 50) -> dict:
    par = par_binance(simbolo)
    d = _req(f"https://api.binance.com/api/v3/depth?symbol={par}&limit={max(5, min(int(limite), 500))}")
    bids = [(float(p), float(q)) for p, q in d["bids"]]
    asks = [(float(p), float(q)) for p, q in d["asks"]]
    vb, va = sum(q for _, q in bids), sum(q for _, q in asks)
    desequilibrio = (vb - va) / (vb + va) if (vb + va) else 0.0
    spread = (asks[0][0] - bids[0][0]) / bids[0][0] * 100
    parede_c = max(bids, key=lambda x: x[1])
    parede_v = max(asks, key=lambda x: x[1])
    leit = ("pressão compradora" if desequilibrio > .15 else "pressão vendedora" if desequilibrio < -.15 else "equilibrado")
    return {"ok": True, "par": par, "volume_compra": vb, "volume_venda": va, "desequilibrio": round(desequilibrio, 3),
            "spread_pct": round(spread, 4), "parede_compra": parede_c, "parede_venda": parede_v, "leitura": leit,
            "resumo": f"Livro {par} ({len(bids)} níveis/lado): compra {vb:,.2f} × venda {va:,.2f} → {leit} "
                      f"({desequilibrio:+.0%}) · spread {spread:.3f}% · maior parede de compra em {_fmt(parede_c[0])} "
                      f"({parede_c[1]:,.2f}), de venda em {_fmt(parede_v[0])} ({parede_v[1]:,.2f})".replace(",", "")}


@_seguro
def binance_klines(simbolo: str = "BTC", intervalo: str = "1d", limite: int = 100) -> dict:
    par = par_binance(simbolo)
    iv = {"1W": "1w"}.get(intervalo, intervalo)
    d = _req(f"https://api.binance.com/api/v3/klines?symbol={par}&interval={iv}&limit={max(10, min(int(limite), 500))}")
    c = [float(k[4]) for k in d]
    h, l = max(float(k[2]) for k in d), min(float(k[3]) for k in d)
    ult = [{"abertura": float(k[1]), "maxima": float(k[2]), "minima": float(k[3]), "fechamento": float(k[4]),
            "volume": float(k[5])} for k in d[-8:]]
    var = (c[-1] / c[0] - 1) * 100
    return {"ok": True, "par": par, "intervalo": iv, "candles": len(d), "fechamento": c[-1], "variacao_periodo_pct": round(var, 2),
            "maxima": h, "minima": l, "ultimos": ult,
            "resumo": f"{par} {iv}: {len(d)} candles · {var:+.1f}% no período · faixa {_fmt(l)} – {_fmt(h)} · último fechamento {_fmt(c[-1])}"}


@_seguro
def binance_destaques(limite: int = 8) -> dict:
    d = _req("https://api.binance.com/api/v3/ticker/24hr", timeout=25)
    usdt = [x for x in d if x["symbol"].endswith("USDT") and float(x["quoteVolume"]) > 5e6
            and not re.search(r"(UP|DOWN|BULL|BEAR)USDT$", x["symbol"])]
    usdt.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)
    f = lambda x: {"par": x["symbol"], "var_24h_pct": float(x["priceChangePercent"]), "preco": float(x["lastPrice"]),
                   "volume_usdt": float(x["quoteVolume"])}
    n = max(1, min(int(limite), 25))
    sobem, caem = [f(x) for x in usdt[:n]], [f(x) for x in usdt[-n:][::-1]]
    linhas = lambda xs: ", ".join(f"{x['par'][:-4]} {x['var_24h_pct']:+.1f}%" for x in xs)
    return {"ok": True, "sobem": sobem, "caem": caem,
            "resumo": f"Maiores altas (24h, vol>5 mi USDT): {linhas(sobem)}.\nMaiores quedas: {linhas(caem)}."}


# --------------------------------------------------------------------------- #
# TradingView (escâner público)
# --------------------------------------------------------------------------- #
def _recomendacao(v: float) -> str:
    return ("COMPRA FORTE" if v >= .5 else "COMPRA" if v >= .1 else "NEUTRO" if v > -.1 else
            "VENDA" if v > -.5 else "VENDA FORTE")


@_seguro
def tradingview_analise(simbolo: str = "BTC", intervalo: str = "1d", exchange: str = "BINANCE") -> dict:
    suf = _TV_SUFIXO.get(intervalo, _TV_SUFIXO.get(intervalo.lower(), ""))
    base = ["Recommend.All", "Recommend.MA", "Recommend.Other", "RSI", "MACD.macd", "MACD.signal", "Stoch.K",
            "Stoch.D", "ADX", "CCI20", "close", "SMA20", "SMA50", "SMA200", "EMA20", "BB.upper", "BB.lower"]
    ticker = f"{exchange.upper()}:{par_binance(simbolo)}"
    d = _req(TV_ESCANER.format(tela="crypto"), corpo={"symbols": {"tickers": [ticker], "query": {"types": []}},
                                                      "columns": [c + suf for c in base]})
    if not d.get("data"):
        return {"ok": False, "erro": f"TradingView não conhece {ticker}"}
    v = dict(zip(base, d["data"][0]["d"]))
    preco = v["close"]
    nome = lambda x: _recomendacao(x) if x is not None else "—"
    bb = (preco - v["BB.lower"]) / (v["BB.upper"] - v["BB.lower"]) if v.get("BB.upper") and v.get("BB.lower") else None
    osc = {"RSI": round(v["RSI"], 1), "MACD": round(v["MACD.macd"], 2), "MACD sinal": round(v["MACD.signal"], 2),
           "Estocástico %K": round(v["Stoch.K"], 1), "ADX": round(v["ADX"], 1), "CCI(20)": round(v["CCI20"], 1)}
    link = f"https://www.tradingview.com/chart/?symbol={urllib.parse.quote(ticker)}&interval={_TV_CHART.get(intervalo, 'D')}"
    return {"ok": True, "ticker": ticker, "intervalo": intervalo, "consenso": nome(v["Recommend.All"]),
            "medias_moveis": nome(v["Recommend.MA"]), "osciladores": nome(v["Recommend.Other"]), "indicadores": osc,
            "posicao_bollinger": None if bb is None else round(bb, 2), "link_grafico": link,
            "resumo": f"TradingView {ticker} ({intervalo}): consenso **{nome(v['Recommend.All'])}** "
                      f"(médias móveis: {nome(v['Recommend.MA'])} · osciladores: {nome(v['Recommend.Other'])}) · "
                      f"RSI {osc['RSI']} · MACD {osc['MACD']} (sinal {osc['MACD sinal']}) · ADX {osc['ADX']} · "
                      f"preço {'acima' if preco > v['SMA50'] else 'abaixo'} da SMA50 · gráfico: {link}"}


def tradingview_grafico_link(simbolo: str = "BTC", intervalo: str = "1d", exchange: str = "BINANCE") -> dict:
    ticker = f"{exchange.upper()}:{par_binance(simbolo)}"
    return {"ok": True, "link": f"https://www.tradingview.com/chart/?symbol={urllib.parse.quote(ticker)}"
                                f"&interval={_TV_CHART.get(intervalo, 'D')}"}


# --------------------------------------------------------------------------- #
# CoinGecko
# --------------------------------------------------------------------------- #
def _cg_cab(creds: dict) -> dict:
    k = str((creds or {}).get("api_key") or "").strip()
    return {"x-cg-demo-api-key": k} if k else {}


def _cg_id(moeda: str, cab: dict) -> str:
    m = str(moeda or "").strip().lower()
    if m in _APELIDOS:
        return _APELIDOS[m]
    if re.fullmatch(r"[a-z0-9-]{3,}", m) and "-" in m:
        return m
    d = _req(f"https://api.coingecko.com/api/v3/search?query={urllib.parse.quote(m)}", cab)
    achados = d.get("coins") or []
    if not achados:
        raise ValueError(f"moeda não encontrada: {moeda}")
    return achados[0]["id"]


def _coingecko_moeda(creds):
    @_seguro
    def f(moeda: str = "bitcoin") -> dict:
        cab = _cg_cab(creds)
        cid = _cg_id(moeda, cab)
        d = _req("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + cid
                 + "&price_change_percentage=24h,7d,30d", cab)
        if not d:
            return {"ok": False, "erro": f"sem dados para {moeda}"}
        x = d[0]
        ath = x.get("ath_change_percentage")
        return {"ok": True, "id": cid, "nome": x["name"], "simbolo": x["symbol"].upper(), "preco": x["current_price"],
                "ranking": x.get("market_cap_rank"), "valor_mercado": x.get("market_cap"), "volume_24h": x.get("total_volume"),
                "var_24h": x.get("price_change_percentage_24h_in_currency"), "var_7d": x.get("price_change_percentage_7d_in_currency"),
                "var_30d": x.get("price_change_percentage_30d_in_currency"), "maxima_historica": x.get("ath"),
                "dist_maxima_pct": ath, "oferta_circulante": x.get("circulating_supply"),
                "resumo": f"{x['name']} ({x['symbol'].upper()}): US$ {_fmt(x['current_price'])} · #{x.get('market_cap_rank')} em valor de mercado "
                          f"({_grande(x['market_cap'])} US$) · volume 24h {_grande(x['total_volume'])} · "
                          f"24h {x.get('price_change_percentage_24h_in_currency') or 0:+.1f}% · 7d {x.get('price_change_percentage_7d_in_currency') or 0:+.1f}% · "
                          f"30d {x.get('price_change_percentage_30d_in_currency') or 0:+.1f}% · "
                          f"{abs(ath or 0):.1f}% abaixo da máxima histórica (US$ {_fmt(x['ath'])})"}
    return f


def _coingecko_tendencias(creds):
    @_seguro
    def f() -> dict:
        d = _req("https://api.coingecko.com/api/v3/search/trending", _cg_cab(creds))
        itens = [{"nome": c["item"]["name"], "simbolo": c["item"]["symbol"], "ranking": c["item"].get("market_cap_rank")}
                 for c in d.get("coins", [])][:10]
        return {"ok": True, "moedas": itens,
                "resumo": "Em alta nas buscas (CoinGecko): " + ", ".join(f"{i['nome']} ({i['simbolo']})" for i in itens)}
    return f


def _coingecko_global(creds):
    @_seguro
    def f() -> dict:
        d = _req("https://api.coingecko.com/api/v3/global", _cg_cab(creds))["data"]
        cap, dom = d["total_market_cap"]["usd"], d["market_cap_percentage"]
        return {"ok": True, "valor_mercado_total_usd": cap, "var_24h_pct": d["market_cap_change_percentage_24h_usd"],
                "dominancia": {k.upper(): round(v, 1) for k, v in list(dom.items())[:5]}, "moedas_ativas": d["active_cryptocurrencies"],
                "resumo": f"Mercado cripto: {_grande(cap)} US$ ({d['market_cap_change_percentage_24h_usd']:+.1f}% em 24h) · "
                          f"dominância BTC {dom.get('btc', 0):.1f}% · ETH {dom.get('eth', 0):.1f}% · {d['active_cryptocurrencies']:,} moedas ativas".replace(",", ".")}
    return f


# --------------------------------------------------------------------------- #
# CryptoPanic (chave grátis)
# --------------------------------------------------------------------------- #
def _cryptopanic(creds):
    @_seguro
    def f(moeda: str = "", filtro: str = "hot", limite: int = 8) -> dict:
        tok = str((creds or {}).get("token") or "").strip()
        if not tok:
            return {"ok": False, "erro": "configure o token do CryptoPanic em Configurações → Conectores"}
        q = f"auth_token={urllib.parse.quote(tok)}&public=true&kind=news&filter={urllib.parse.quote(filtro)}"
        if moeda:
            q += "&currencies=" + urllib.parse.quote(par_binance(moeda).replace("USDT", ""))
        d = _req("https://cryptopanic.com/api/v1/posts/?" + q)
        posts = (d.get("results") or [])[:max(1, min(int(limite), 20))]
        itens, pos, neg = [], 0, 0
        for p in posts:
            v = p.get("votes") or {}
            pos += int(v.get("positive", 0)) + int(v.get("liked", 0))
            neg += int(v.get("negative", 0)) + int(v.get("disliked", 0)) + int(v.get("toxic", 0))
            itens.append({"titulo": p.get("title", ""), "fonte": (p.get("source") or {}).get("title", ""),
                          "url": p.get("url", ""), "votos_positivos": v.get("positive", 0), "votos_negativos": v.get("negative", 0)})
        saldo = (pos - neg) / (pos + neg) if (pos + neg) else 0.0
        return {"ok": True, "noticias": itens, "saldo_votos": round(saldo, 2),
                "resumo": f"{len(itens)} notícias ({filtro}) · votos {pos}↑ {neg}↓:\n" +
                          "\n".join(f"- {i['titulo']} — {i['fonte']}" for i in itens)}
    return f


# --------------------------------------------------------------------------- #
# Sentimento
# --------------------------------------------------------------------------- #
@_seguro
def stocktwits_sentimento(ativo: str = "BTC") -> dict:
    from yvakor import mercado as M
    simbolo, tipo = M.resolver_ativo(ativo)
    st = M.sentimento_stocktwits(simbolo, tipo)
    leit = "otimista" if st["saldo"] > .25 else "pessimista" if st["saldo"] < -.25 else "dividido"
    return {"ok": True, **st, "leitura": leit,
            "resumo": f"StockTwits {st['simbolo']}: {st['altistas']} altistas · {st['baixistas']} baixistas · {st['neutras']} sem rótulo → {leit} "
                      f"(saldo {st['saldo']:+.0%})"}


@_seguro
def medo_ganancia() -> dict:
    from yvakor import mercado as M
    fg = M.medo_ganancia()
    return {"ok": True, **fg, "resumo": f"Índice Medo & Ganância: {fg['valor']} — {fg['classe']} "
                                        f"(30 dias: mín. {min(fg['historico'])}, máx. {max(fg['historico'])})"}


# --------------------------------------------------------------------------- #
# registro das ferramentas por conector
# --------------------------------------------------------------------------- #
def _reg_binance(reg, reg_guarded, creds):
    reg("binance_preco", binance_preco, "Preço e estatísticas de 24h de um par da Binance (ex.: BTC).", {"simbolo": "str"})
    reg("binance_livro", binance_livro, "Livro de ofertas da Binance: pressão compradora/vendedora, spread e paredes.",
        {"simbolo": "str", "limite": "int?"})
    reg("binance_klines", binance_klines, "Resumo dos candles da Binance (intervalo 1m…1w).",
        {"simbolo": "str", "intervalo": "str?", "limite": "int?"})
    reg("binance_destaques", binance_destaques, "Maiores altas e quedas de 24h entre os pares USDT.", {"limite": "int?"})


def _reg_tradingview(reg, reg_guarded, creds):
    reg("tradingview_analise", tradingview_analise,
        "Consenso técnico do TradingView (compra/venda), médias móveis e osciladores de um ativo cripto.",
        {"simbolo": "str", "intervalo": "str?", "exchange": "str?"})
    reg("tradingview_grafico_link", tradingview_grafico_link,
        "Link do gráfico do TradingView para abrir no navegador (navegador_abrir).",
        {"simbolo": "str", "intervalo": "str?", "exchange": "str?"})


def _reg_coingecko(reg, reg_guarded, creds):
    reg("coingecko_moeda", _coingecko_moeda(creds), "Valor de mercado, ranking, volume, variações e máxima histórica (CoinGecko).",
        {"moeda": "str"})
    reg("coingecko_tendencias", _coingecko_tendencias(creds), "Moedas em alta nas buscas (CoinGecko).", {})
    reg("coingecko_global", _coingecko_global(creds), "Visão do mercado cripto: valor total e dominância do BTC.", {})


def _reg_cryptopanic(reg, reg_guarded, creds):
    reg("cryptopanic_noticias", _cryptopanic(creds), "Notícias de cripto com votos da comunidade (moeda opcional; filtro hot|rising|bullish|bearish|important).",
        {"moeda": "str?", "filtro": "str?", "limite": "int?"})


def _reg_sentimento(reg, reg_guarded, creds):
    reg("stocktwits_sentimento", stocktwits_sentimento, "Sentimento da comunidade no StockTwits (altistas × baixistas).", {"ativo": "str"})
    reg("medo_ganancia", medo_ganancia, "Índice Medo & Ganância do mercado cripto (hoje e histórico de 30 dias).", {})


_ATIVO = {"key": "ativo", "label": "Ativar (deixe como está e clique em Conectar)", "default": "sim"}

CATALOGO_CRIPTO: dict[str, dict] = {
    "cripto_binance": {
        "name": "Binance · mercado", "icon": "🟡",
        "desc": "Preço, livro de ofertas, candles e destaques do dia. Só leitura, sem chave.",
        "fields": [_ATIVO], "required": ["ativo"], "register": _reg_binance},
    "cripto_tradingview": {
        "name": "TradingView · indicadores", "icon": "📈",
        "desc": "Consenso técnico (compra/venda), médias e osciladores por intervalo, mais o link do gráfico.",
        "fields": [_ATIVO], "required": ["ativo"], "register": _reg_tradingview},
    "cripto_coingecko": {
        "name": "CoinGecko · mercado", "icon": "🦎",
        "desc": "Valor de mercado, ranking, máxima histórica, tendências e dominância do BTC. A chave (grátis) só aumenta o limite de uso.",
        "fields": [_ATIVO, {"key": "api_key", "label": "Chave demo da API (opcional)", "type": "password"}],
        "required": ["ativo"], "register": _reg_coingecko},
    "cripto_cryptopanic": {
        "name": "CryptoPanic · notícias", "icon": "📰",
        "desc": "Notícias de cripto com votos da comunidade. Precisa do token grátis de cryptopanic.com/developers/api.",
        "fields": [{"key": "token", "label": "Token da API (auth_token)", "type": "password"}],
        "required": ["token"], "register": _reg_cryptopanic},
    "cripto_sentimento": {
        "name": "Sentimento · StockTwits e Medo&Ganância", "icon": "💬",
        "desc": "O que a comunidade está sentindo agora: altistas × baixistas e o índice de medo e ganância.",
        "fields": [_ATIVO], "required": ["ativo"], "register": _reg_sentimento},
}
