# Grafico ao vivo (candlestick em tempo real)

## Quando usar
Quando o usuario pedir "grafico ao vivo", "ver o ativo em tempo real", "candlestick ao vivo", "acompanhar preco" ou similar.

## Procedimento
1. Rodar o script com o par desejado:
   ```cmd
   cd /d E:\YVAKOR\yvakor
   python scripts\grafico_ao_vivo.py BNBUSDT --interval 1m --candles 120
   ```
2. Intervalos validos: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1d.
3. A janela abre com candlestick + volume, atualizando a cada 1s via WebSocket da Binance.
4. Fechar a janela encerra o stream.

## Observacoes
- Dados: Binance WebSocket publico (sem chave).
- Se a janela nao abrir, verificar backend TkAgg (`python -c "import tkinter"`).
- Para ativos fora da Binance, usar `analise_cripto.py --exchange` (nao ao vivo).
