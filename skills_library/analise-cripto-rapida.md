<!-- skill: analise-cripto-rapida | tags: cripto, cotacao, analise-mercado, coingecko, binance, tradingview, indicadores, niveis, grafico, timeframe-diario, timeframe-semanal | status: atualizada -->
# Análise rápida de criptoativo (cotação + histórico + indicadores + níveis operacionais)

## Quando usar
Quando o usuário pedir para "analisar", "ver como está" ou "dar uma leitura" de um criptoativo específico (ex.: "analisa o ZEC", "como está o SOL hoje", "analise bnb"). Gatilho: verbo de análise + nome/ticker de cripto.

**Regra de timeframe (obrigatória):** a análise é gerada **sempre em timeframe diário (`1d`)** por padrão. Só usar semanal (`1w`) quando o usuário pedir explicitamente ("semanal", "semana", "longo prazo") ou passar a flag `--semana`. Nunca gerar análise em timeframes intraday (1h, 4h, 15m) a menos que o usuário peça explicitamente.

## Pré-requisitos
- Acesso à API pública da CoinGecko (sem chave para endpoints básicos).
- Acesso à API pública da Binance (`api.binance.com`) como **fonte de fallback** para histórico de preço.
- Saber o **id** do ativo na CoinGecko (ex.: `zcash`, `ethereum`, `bitcoin`, `solana`, `binancecoin`). Se não souber, resolver via endpoint de busca (passo 1).
- Saber o **par na Binance** (ex.: `ZECUSDT`, `ETHUSDT`, `BNBUSDT`). Regra: `{TICKER}USDT` em maiúsculas.
- Acesso aos **indicadores do TradingView** (bloco de resumo técnico: osciladores + médias móveis) — pode ser via captura/consulta do painel técnico do ativo no timeframe diário.
- Capacidade de **gerar gráfico com níveis** e salvar em `{DIRETORIO_GRAFICOS}` (ex.: `E:\YVAKOR\yvakor\data\graficos\{ticker}_niveis.png`).
- Script `scripts/analise_cripto.py` disponível no projeto.

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
   - Calcular variação: `(fechamento_último / fechamento_primeiro - 1) * 100`. Usar o **fechamento** (índice 4 do array) do primeiro candle como base.
   - Faixa 30d: `min(low)` e `max(high)` dos candles (índices 3 e 2).
6. **Montar a tabela de métricas** com: Preço USD, Preço BRL, Variação 24h USD, Variação 24h BRL, Volume 24h, Market cap, Ranking, Supply circulante, Supply máximo. Formatar valores grandes em "US$ X,XX bi" / "R$ X,XX bi".
7. **Montar a tabela de histórico** com: variação 7d, variação 30d, faixa 30d (mín–máx).
8. **Normalizar o intervalo para a Binance.** A Binance **rejeita `1W` maiúsculo** (retorna HTTP 400). Antes de qualquer chamada de klines, converter:
   ```python
   interval = {"1W": "1w"}.get(interval, interval)
   ```
   Essa linha deve ficar **logo após a assinatura da função `dados_binance`**, antes da montagem da URL. Não afeta `1d`, `1h`, etc.
9. **Interpretar a divergência USD vs BRL**: se a variação em BRL for mais negativa que em USD, explicar que vem da valorização do real frente ao dólar.
10. **Gerar o gráfico com níveis** e salvar em `{DIRETORIO_GRAFICOS}\{ticker}_niveis.png`. Marcar: suporte, entrada, alvo1, alvo2, alvo3, stop.
11. **Executar o script** (atalho que já faz tudo acima):
    ```bash
    python scripts\analise_cripto.py {TICKER}
    ```
    Para semanal:
    ```bash
    python scripts\analise_cripto.py {TICKER} --semana
    ```

## Erros conhecidos e soluções
- **HTTP 400 na Binance ao usar `--semana`**: causa = Binance usa `1w` minúsculo, não `1W`. Solução = aplicar o mapeamento do passo 8 dentro de `dados_binance()`. Se o erro persistir, verificar se a linha foi realmente inserida (a substituição pode falhar silenciosamente — conferir a linha logo após a assinatura da função).
- **HTTP 429 na CoinGecko** ao pedir histórico: usar Binance como fallback (passo 5).
- **`max_supply` nulo**: informar "sem supply máximo / inflacionário" em vez de deixar em branco.
- **Gráfico não aparece**: conferir se `{DIRETORIO_GRAFICOS}` existe; criar antes de salvar.

## Exemplo real (da tarefa que originou esta skill)
Comando:
```bash
python scripts\analise_cripto.py BNBUSDT
```
Saída:
- Intervalo: **1d**
- Preço: US$ 738,74
- Sinal TV: NEUTRAL
- Níveis: suporte 705,86 · entrada 797,84 · alvo1 886,49 · alvo2 989,91 · alvo3 809,99 · stop 701,80
- Gráfico: `E:\YVAKOR\yvakor\data\graficos\bnbusdt_niveis.png`

Pendência registrada: modo `--semana` falhava com HTTP 400 porque `1W` não era convertido para `1w` na função `dados_binance`. Correção de 1 linha documentada no passo 8.