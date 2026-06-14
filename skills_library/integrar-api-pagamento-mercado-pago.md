<!-- skill: gerar-relatorio-faturamento-mensal-sqlite | tags: sqlite, python, faturamento, relatorio | status: nova -->
# Gerar relatório de faturamento mensal a partir de banco SQLite
## Quando usar
Ao precisar extrair, formatar e exportar o faturamento mensal de um sistema que armazena transações em SQLite (ex.: chatbot de cobranças, micro-SaaS, automação de vendas).
## Pré-requisitos
- Banco SQLite com tabela `transacoes` contendo colunas: `id`, `valor`, `data_criacao` (TEXT no formato ISO 8601), `status` (TEXT com valores 'aprovada', 'recusada', 'estornada').
- Python 3.8+ instalado.
- Biblioteca `sqlite3` (nativa) e `pandas` (opcional, para formatação avançada).
## Procedimento
1. Conecte ao banco SQLite usando `sqlite3.connect('{caminho_do_banco}')`.
2. Execute a consulta SQL para agrupar transações aprovadas por mês:
   ```sql
   SELECT strftime('%Y-%m', data_criacao) AS mes,
          COUNT(*) AS total_transacoes,
          SUM(valor) AS faturamento
   FROM transacoes
   WHERE status = 'aprovada'
   GROUP BY mes
   ORDER BY mes;
   ```
3. Armazene o resultado em uma lista de dicionários ou DataFrame do pandas.
4. Formate a saída como tabela Markdown ou CSV, conforme necessidade:
   - Para Markdown: use `tabulate` ou loop manual com `|` separadores.
   - Para CSV: use `csv.writer` ou `df.to_csv()`.
5. Exporte o relatório para arquivo com nome padronizado: `relatorio_faturamento_{ano_mes_atual}.md` ou `.csv`.
6. Exiba o relatório no terminal com `print()` para validação imediata.
## Erros conhecidos e soluções
- **Erro: `sqlite3.OperationalError: no such table: transacoes`** → Verifique se o banco contém a tabela correta. Execute `.tables` no SQLite CLI ou `SELECT name FROM sqlite_master WHERE type='table';` no Python.
- **Erro: `strftime` retorna `None` para todas as linhas** → Confirme que `data_criacao` está no formato ISO 8601 (ex.: '2026-06-12T14:30:00'). Se estiver em timestamp Unix, use `datetime(data_criacao, 'unixepoch')`.
- **Erro: `SUM(valor)` retorna `None`** → Verifique se a coluna `valor` é numérica (REAL ou INTEGER). Se for TEXT, converta com `CAST(valor AS REAL)`.
- **Erro: arquivo de saída não é gerado** → Verifique permissões de escrita no diretório. Use caminho absoluto se necessário.
## Exemplo aplicado ao contexto do usuário
Suponha que você gerencia um chatbot de cobranças para um micro-SaaS de segurança eletrônica (ACM Digital). As transações são armazenadas em `/home/antonio/dados/transacoes.db`. Para gerar o relatório de junho de 2026:

```python
import sqlite3
import csv
from datetime import datetime

conn = sqlite3.connect('/home/antonio/dados/transacoes.db')
cursor = conn.cursor()

cursor.execute("""
    SELECT strftime('%Y-%m', data_criacao) AS mes,
           COUNT(*) AS total_transacoes,
           SUM(valor) AS faturamento
    FROM transacoes
    WHERE status = 'aprovada'
    GROUP BY mes
    ORDER BY mes;
""")

rows = cursor.fetchall()
conn.close()

# Exportar para CSV
with open('relatorio_faturamento_2026-06.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Mês', 'Total Transações', 'Faturamento (R$)'])
    writer.writerows(rows)

# Exibir no terminal
print("Relatório de Faturamento Mensal")
print("Mês       | Transações | Faturamento (R$)")
print("-" * 45)
for mes, total, valor in rows:
    print(f"{mes} | {total:>10} | R$ {valor:>10.2f}")
```

Isso gera um arquivo CSV e exibe uma tabela alinhada no terminal, pronta para ser anexada a um e-mail de prospecção ou relatório de desempenho.
