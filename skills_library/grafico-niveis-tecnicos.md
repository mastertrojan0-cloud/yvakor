<!-- skill: grafico-niveis-tecnicos | tags: trading, grafico, analise-tecnica, tradingview, coingecko, binance, python | status: nova -->
# Gerar gráfico de níveis técnicos (suporte, gatilho, alvos) para um ativo

## Quando usar
Quando o usuário pede para "marcar no gráfico" níveis de suporte, entrada e alvos de um ativo (cripto, ação, etc.), ou pede análise técnica visual com dados reais de mercado. Também quando pergunta sobre integrar TradingView para análises automáticas.

## Pré-requisitos
- Python 3.9+ com `pandas`, `matplotlib`, `requests`.
- Acesso à internet (APIs gratuitas: CoinGecko para cripto, Binance para OHLC).
- Diretório de saída para imagens: `{DIR_SAIDA}` (ex: `E:\YVAKOR\yvakor\data\graficos`).
- **Nenhuma credencial necessária** — todas as APIs usadas são públicas e gratuitas.

## Procedimento

1. **Coletar preço atual e histórico**
   - Cripto (preço spot + histórico 30d):
     ```
     GET https://api.coingecko.com/api/v3/simple/price?ids={id_coingecko}&vs_currencies=usd
     GET https://api.coingecko.com/api/v3/coins/{id_coingecko}/market_chart?vs_currency=usd&days=30&interval=daily
     ```
   - OHLC (candles) via Binance:
     ```
     GET https://api.binance.com/api/v3/klines?symbol={PAR}USDT&interval=1d&limit=30
     ```
   - Salve em `pandas.DataFrame` com colunas `timestamp, open, high, low, close`.

2. **Calcular os níveis**
   - Suporte 30d: `min(low)` do período (ou percentil 5 dos fechamentos).
   - Resistência/gatilho de entrada: `max(high)` recente + margem de {X}% (ex: 2–5%).
   - Alvos 1/2/3: projeções Fibonacci a partir do suporte (ex: 1.20×, 1.35×, 1.45× do suporte) **ou** múltiplos definidos pelo usuário.
   - Registre cada nível em variável nomeada (`preco_atual`, `suporte`, `gatilho_min`, `gatilho_max`, `alvo1`, `alvo2`, `alvo3`).

3. **Plotar com matplotlib**
   - Use `matplotlib.use("Agg")` (headless, sem GUI).
   - Plote o preço de fechamento como linha principal.
   - Adicione `axhline` para cada nível com cores fixas:
     - preto → preço atual
     - azul → suporte
     - verde + `axhspan` → faixa de gatilho
     - roxo / laranja / vermelho → alvos 1/2/3
   - Anote o valor em US$ ao lado de cada linha (`ax.annotate`).
   - Título: `{ATIVO} — níveis técnicos ({data})`.

4. **Salvar e reportar**
   - Salve em `{DIR_SAIDA}/{ativo}-niveis-marcados-{timestamp}.png` (timestamp Unix para evitar sobrescrita).
   - Retorne ao usuário: caminho do arquivo + lista textual dos níveis com valores.

5. **Se o usuário pedir integração com TradingView**
   - Explique que **não existe API pública gratuita de dados do TradingView**.
   - Ofereça as alternativas:
     - **Widget HTML** (iframe/script) — gráfico interativo, mas sem dados programáticos.
     - **Lib `tradingview-ta`** (pip) — scraping não-oficial do resumo de indicadores (RSI, MACD, sinal compra/venda). Pode quebrar sem aviso.
     - **API oficial** — apenas planos pagos/parceiros.
   - Recomende **CoinGecko + Binance** para dados confiáveis e gratuitos, com `tradingview-ta` opcional para o resumo técnico.

## Erros conhecidos e soluções
- **CoinGecko 429 (rate limit)**: aguarde 60s ou use `?x_cg_demo_api_key={chave}` (chave gratuita no site). Reduza frequência de chamadas.
- **Binance bloqueado por região (HTTP 451)**: use endpoint alternativo `https://data-api.binance.vision/api/v3/klines` ou troque para CoinGecko OHLC.
- **`id_coingecko` errado** (ex: usar "ZEC" em vez de "zcash"): consulte `GET /coins/list` e busque pelo `symbol`.
- **Gráfico em branco / sem GUI**: sempre `matplotlib.use("Agg")` antes de importar `pyplot`.
- **`tradingview-ta` retorna vazio**: o scraping mudou; verifique versão da lib (`pip install -U tradingview-ta`) ou abandone em favor de cálculo próprio dos indicadores.
- **Símbolo não encontrado na Binance**: confirme par `{PAR}USDT` (ex: `ZECUSDT`, não `ZECUSD`).

## Exemplo real (da tarefa que originou esta skill)
Pedido: *"marca no gráfico, pode integrar o tradingview gratuito para fazer essas análises de agora em diante"* — ativo ZEC.

- Dados: CoinGecko (`zcash`) + Binance (`ZECUSDT`, 30d diário).
- Níveis calculados: preço atual US$ 1.163 · suporte 30d US$ 1.127 · gatilho US$ 1.250–1.270 · alvos US$ 1.400 / 1.560 / 1.653.
- Saída: `E:\YVAKOR\yvakor\data\graficos\zec-niveis-marcados-1792798404.png`.
- Sobre TradingView: informado que API gratuita de dados não existe; recomendado CoinGecko+Binance (usados) e oferecido `tradingview-ta` (resumo técnico) ou widget HTML como próximos passos.