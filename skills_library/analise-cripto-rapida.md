<!-- skill: analise-cripto-rapida | tags: cripto, cotacao, analise-mercado, coingecko, binance, tradingview, indicadores, niveis, grafico, timeframe-diario, timeframe-semanal, stock-to-flow, s2f | status: atualizada -->
# Análise rápida de criptoativo (cotação + histórico + indicadores + níveis operacionais + S2F)

## Quando usar
Quando o usuário pedir para "analisar", "ver como está" ou "dar uma leitura" de um criptoativo específico (ex.: "analisa o ZEC", "como está o SOL hoje", "analise bnb", "analise do btc com gráficos e análise stock to flow"). Gatilho: verbo de análise + nome/ticker de cripto.

**Regra de timeframe (obrigatória):** a análise é gerada **sempre em timeframe diário (`1d`)** por padrão. Só usar semanal (`1w`) quando o usuário pedir explicitamente ("semanal", "semana", "longo prazo") ou passar a flag `--semana`. Nunca gerar análise em timeframes intraday (1h, 4h, 15m) a menos que o usuário peça explicitamente.

**Regra de S2F (obrigatória quando o usuário citar "stock to flow", "S2F" ou "escassez"):** incluir a seção Stock-to-Flow **com o status honesto do modelo** (ver passo 9). Nunca apresentar S2F como sinal de timing.

## Pré-requisitos
- Acesso à API pública da CoinGecko (sem chave para endpoints básicos).
- Acesso à API pública da Binance (`api.binance.com`) como **fonte primária de histórico** e fallback de cotação.
- Saber o **id** do ativo na CoinGecko (ex.: `zcash`, `ethereum`, `bitcoin`, `solana`, `binancecoin`). Se não souber, resolver via endpoint de busca (passo 1).
- Saber o **par na Binance** (ex.: `ZECUSDT`, `ETHUSDT`, `BNBUSDT`). Regra: `{TICKER}USDT` em maiúsculas.
- Acesso aos **indicadores do TradingView** (bloco de resumo técnico: osciladores + médias móveis) — pode ser via captura/consulta do painel técnico do ativo no timeframe diário.
- Capacidade de **gerar gráfico com níveis** e salvar em `{DIRETORIO_GRAFICOS}` (ex.: `E:\YVAKOR\yvakor\data\graficos\{ticker}_niveis.png`).
- Script `scripts/analise_cripto.py` disponível no projeto.
- Para S2F: saber o **supply circulante** e a **produção anual** do ativo (para BTC, usar dados pós-halving vigente).

## Procedimento
1. **Definir o timeframe.** Padrão = `1d`. Se o usuário pedir semanal, usar `1w` (ver passo 8 para o mapeamento obrigatório na Binance).
2. **Resolver o id do ativo** (pule se já souber). Consultar:
   `https://api.coingecko.com/api/v3/search?query={ticker_ou_nome}`
   e pegar o campo `id` do primeiro resultado relevante.
3. **Buscar cotação e métricas** em uma chamada:
   `https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies=usd,brl&include_24hr_change=true&include_24hr_vol=true&include_market_cap=true`
4. **Buscar supply e ranking** (opcional, enriquece a análise):
   `https://api.coingecko.com/api/v3/coins/{id}?localization=false&tickers=false&community_data=false&developer_data=false`
   Extrair `market_cap_rank`, `circulating_supply`, `max_supply` (se `null`, informar "sem supply máximo / inflacionário").
5. **Buscar histórico na Binance** (fonte primária para variação histórica — CoinGecko costuma dar 429 nesse endpoint). Usar o timeframe definido no passo 1:
   - 7 dias: `https://api.binance.com/api/v3/klines?symbol={TICKER}USDT&interval={tf}&limit=8`
   - 30 dias: `https://api.binance.com/api/v3/klines?symbol={TICKER}USDT&interval={tf}&limit=31`
   - Calcular variação: `(fechamento_último / fechamento_primeiro - 1) * 100`. Usar o **fechamento** (índice 4 do array de klines), não o preço atual.
6. **Coletar o resumo técnico do TradingView** no timeframe diário: sinal geral (STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL), contagem de osciladores e médias móveis em compra/venda/neutro.
7. **Extrair níveis operacionais** a partir do histórico diário (últimos ~90–120 candles):
   - **Suporte** = menor mínima relevante recente (índice 3 das klines).
   - **Stop** = suporte × 0,97 (ou mínima do candle de rompimento, se houver).
   - **Entrada (gatilho)** = máxima recente relevante + folga (ex.: máxima dos últimos 30 candles × 1,01).
   - **Alvo 1** = entrada + (entrada − stop) × 1,5.
   - **Alvo 2** = entrada + (entrada − stop) × 2,5.
   - Arredondar para inteiros quando o preço for > 1000.
8. **Gerar o gráfico com níveis** e salvar em `{DIRETORIO_GRAFICOS}/{ticker}_niveis.png`. Plotar: candles de fechamento, linha de suporte, linha de entrada, linhas de alvo 1/2 e stop, com legenda e preço atual anotado.
9. **Se o usuário pedir S2F (ou o ativo for BTC):** calcular `S2F = supply_circulante / produção_anual`. Para BTC pós-halving de 2024: produção ≈ 164.000 BTC/ano, supply ≈ 19,8M → S2F ≈ 110–120. Apresentar:
   - O valor calculado.
   - A projeção clássica do modelo (PlanB) — **explicitamente marcada como não confirmada**.
   - O **status honesto**: S2F ignora demanda, liquidez e fluxo de ETFs; errou projeções em 2021–2022; serve como narrativa de escassez de longo prazo, **não como ferramenta de timing**.
   - Comparar preço atual vs. curva S2F e registrar a divergência, sem tratar como sinal de compra.
10. **Montar a saída** com as seções: tabela de leitura técnica (preço, sinal, suporte, entrada, alvos, stop), estrutura/cenários (comprador acima da entrada, vendedor abaixo do suporte), seção S2F (se aplicável) e conclusão operacional (entrar / aguardar / stop).

## Erros conhecidos e soluções
- **CoinGecko 429 (rate limit)** no endpoint de histórico → usar Binance klines (passo 5) como fonte primária de histórico.
- **Par inexistente na Binance** (`{TICKER}USDT` retorna erro) → tentar `{TICKER}BUSD` ou `{TICKER}BTC`; se nada funcionar, usar apenas CoinGecko e avisar que não há histórico de exchange.
- **Timeframe semanal na Binance** → o intervalo correto é `1w` (não `7d`). Mapear: diário = `1d`, semanal = `1w`.
- **`max_supply` = null** → não é erro; informar "sem supply máximo / inflacionário" e não calcular S2F (S2F exige produção anual finita e conhecida).
- **S2F sem dados de halving** → não inventar número; informar que o cálculo exige supply circulante e produção anual e pedir/derivar da fonte.
- **Preço atual divergindo do último fechamento diário** → usar o preço da CoinGecko para "preço atual" e o fechamento da Binance para cálculos de variação; deixar claro qual é qual.
- **Gráfico não gerado** → verificar se `{DIRETORIO_GRAFICOS}` existe; criar diretório antes de salvar.

## Exemplo real (da tarefa que originou esta skill)
Pedido: "analise do btc com gráficos e análise stock to flow" (27/10/2026, timeframe diário).

- Gráfico salvo em `E:\YVAKOR\yvakor\data\graficos\btcusdt_niveis.png`.
- Leitura técnica (Binance `1d`): preço **US$ 80.606**, sinal TradingView **NEUTRAL**, suporte **79.220**, entrada **87.054**, alvo 1 **96.727**, alvo 2 **108.012**, stop **76.575**.
- Estrutura: preço abaixo da entrada e colado no suporte → zona de decisão; cenário comprador só acima de 87.054 com volume; cenário vendedor na perda de 79.220 com fechamento diário → stop 76.575.
- S2F: `~19,8M / ~164k ≈ 110–120`; projeção clássica de centenas de milhares de dólares **não se confirmou**; modelo contestado (ignora demanda, liquidez e ETFs) → tratado como contexto macro, não como sinal.
- Conclusão: tecnicamente **neutro e defensivo** — aguardar rompimento de 87k (long) ou perda de 79,2k (short/stop).