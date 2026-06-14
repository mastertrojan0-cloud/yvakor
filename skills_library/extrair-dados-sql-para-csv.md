<!-- skill: extrair-dados-sql-para-csv | tags: sql, exportacao, dados, csv, analise | status: nova -->
# Extração de dados SQL para CSV

## Quando usar
Quando precisar exportar dados de SQLite ou PostgreSQL para análise em Excel, Google Sheets, relatórios ou envio para clientes. Útil para gerar relatórios de vendas, inventário, logs de segurança ou qualquer consulta SQL que precise ser compartilhada em formato tabular.

## Pré-requisitos
- Acesso ao banco de dados (SQLite `.db` ou PostgreSQL via string de conexão)
- Python 3.8+ instalado
- Bibliotecas: `sqlite3` (nativa), `psycopg2` (para PostgreSQL) ou `sqlalchemy`
- Permissão de leitura nas tabelas consultadas

## Procedimento

### 1. Identificar o banco e a consulta
- Para SQLite: localize o arquivo `.db` (ex: `/dados/clientes.db`)
- Para PostgreSQL: tenha a string de conexão (ex: `postgresql://usuario:senha@host:5432/banco`)
- Escreva a consulta SQL desejada em uma variável ou arquivo `.sql`

### 2. Criar script de extração
Crie um arquivo Python com o seguinte template adaptado ao seu banco:

**Para SQLite:**
```python
import sqlite3
import csv
import os

# Configurações
DB_PATH = "{caminho_do_arquivo_db}"
SQL_QUERY = """
{sua_consulta_sql_aqui}
"""
OUTPUT_CSV = "{nome_do_arquivo_saida}.csv"

# Conectar e extrair
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute(SQL_QUERY)

# Obter nomes das colunas
colunas = [descricao[0] for descricao in cursor.description]

# Escrever CSV
with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow(colunas)
    writer.writerows(cursor.fetchall())

conn.close()
print(f"Arquivo {OUTPUT_CSV} gerado com sucesso!")
```

**Para PostgreSQL:**
```python
import psycopg2
import csv

# Configurações
CONN_STRING = "{string_de_conexao_postgres}"
SQL_QUERY = """
{sua_consulta_sql_aqui}
"""
OUTPUT_CSV = "{nome_do_arquivo_saida}.csv"

# Conectar e extrair
conn = psycopg2.connect(CONN_STRING)
cursor = conn.cursor()
cursor.execute(SQL_QUERY)

# Obter nomes das colunas
colunas = [descricao[0] for descricao in cursor.description]

# Escrever CSV
with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow(colunas)
    writer.writerows(cursor.fetchall())

conn.close()
print(f"Arquivo {OUTPUT_CSV} gerado com sucesso!")
```

### 3. Executar o script
```bash
python extrair_dados.py
```

### 4. Verificar o resultado
- Abra o arquivo CSV gerado em um editor de texto ou Excel
- Confirme que os dados estão corretos e com encoding adequado (UTF-8 com BOM para acentos)

## Erros conhecidos e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| `sqlite3.OperationalError: no such table` | Tabela não existe ou banco errado | Verifique o caminho do DB e o nome da tabela com `.tables` no SQLite |
| `psycopg2.OperationalError: could not connect` | Conexão recusada | Verifique host, porta, usuário e senha; teste com `psql` |
| `UnicodeDecodeError` | Encoding incompatível | Use `encoding='utf-8-sig'` no CSV writer |
| Dados truncados ou faltando | Limite de fetch | Adicione `LIMIT 1000` para teste antes de exportar tudo |
| CSV não abre no Excel | Delimitador ou encoding | Salve com `utf-8-sig` e use `;` como delimitador se necessário |

## Exemplo aplicado ao contexto do usuário

**Cenário:** Antonio precisa extrair relatório de vendas do banco SQLite de um cliente da ACM Digital para análise em Excel.

**Arquivo `relatorio_vendas.py`:**
```python
import sqlite3
import csv

DB_PATH = "/home/antonio/projetos/acm-digital/clientes/loja_virtual.db"
SQL_QUERY = """
SELECT 
    c.nome AS cliente,
    p.nome AS produto,
    v.quantidade,
    v.valor_unitario,
    v.data_venda
FROM vendas v
JOIN clientes c ON v.cliente_id = c.id
JOIN produtos p ON v.produto_id = p.id
WHERE v.data_venda >= '2026-01-01'
ORDER BY v.data_venda DESC
LIMIT 1000
"""
OUTPUT_CSV = "relatorio_vendas_2026.csv"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute(SQL_QUERY)

colunas = [descricao[0] for descricao in cursor.description]

with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow(colunas)
    writer.writerows(cursor.fetchall())

conn.close()
print(f"Relatório salvo em {OUTPUT_CSV}")
```

**Execução:**
```bash
python relatorio_vendas.py
```

**Resultado:** Arquivo `relatorio_vendas_2026.csv` pronto para abrir no Excel com acentos preservados.
