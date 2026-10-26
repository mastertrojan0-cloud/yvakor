# Análise Técnica de Qualquer Ativo (cripto, ação, forex)

## Quando usar
Quando o usuário pedir "analisa X", "análise da moeda Y", "como está o ativo Z",
"marca entradas e alvos de W" ou qualquer pedido de análise técnica de um ativo
negociável (cripto, ação, forex, commodity).

## Pré-requisitos
- Python com matplotlib, requests, tradingview-ta instalados
- Script: `E:\YVAKOR\yvakor\scripts\analise_cripto.py`
- Acesso à internet (Binance API + TradingView)

## Procedimento

1. **Identificar o símbolo**
   - Cripto na Binance: `{BASE}USDT` (ex.: ZECUSDT, BTCUSDT, ETHUSDT, SOLUSDT)
   - Se o usuário disser só o nome ("zcash", "bitcoin"), converter para o par USDT.
   - Ações/forex: usar `--exchange` do TradingView (ex.: NASDAQ, FX_IDC).

2. **Rodar o script**
   ```
   cd /d E:\YVAKOR\yvakor && python scripts\analise_cripto.py {SYMBOL} --interval {INTERVALO}
   ```
   - Intervalos aceitos: 1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1W, 1M
   - Padrão: 1d, 60 candles

3. **Ler a saída**
   - Preço atual
   - Resumo TV (BUY/SELL/NEUTRAL) — sinal geral
   - Osciladores (RSI, MACD, Stoch, etc.)
   - Médias móveis (EMA/SMA 10 a 200)
   - Caminho do gráfico gerado

4. **Montar a análise para o usuário**
   - Tabela de cotação (preço, variação, volume, market cap se cripto)
   - Tendência (curto/médio prazo) cruzando preço vs médias
   - Suporte e resistência (mínima/máxima dos últimos 30 candles)
   - Cenários de entrada com gatilho, stop e alvos (R:R calculado)
   - Aviso: não é recomendação de investimento

5. **Entregar o gráfico**
   - Informar o caminho absoluto do PNG gerado
   - Se o usuário quiser níveis específicos, ajustar o dict `niveis` no script
     ou gerar gráfico customizado via matplotlib

## Observações
- TradingView pode falhar (scraping não-oficial) — o script avisa e segue com Binance.
- Para market cap/ranking de cripto, complementar com CoinGecko:
  `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={id}`
- Nunca prometer retorno; sempre incluir disclaimer.

## Exemplos de uso
- "analisa zcash" → `python scripts\analise_cripto.py ZECUSDT`
- "como está o bitcoin em 4h" → `python scripts\analise_cripto.py BTCUSDT --interval 4h`
- "marca entradas do ethereum" → rodar ETHUSDT e montar cenários com R:R
