<!-- skill: criar-pipeline-etl-seguranca | tags: etl, seguranca, automacao, dados | status: nova -->
# Criar pipeline ETL para dados de segurança
## Quando usar
Sempre que precisar consolidar dados de múltiplas fontes de segurança (logs de câmeras, registros de controle de acesso, alarmes, bancos SQL de sistemas legados, APIs de fabricantes) em um banco único ou relatório padronizado para análise, auditoria ou dashboard.

## Pré-requisitos
- Acesso às fontes de dados (credenciais, chaves de API, caminhos de arquivo)
- Ambiente Python 3.8+ com bibliotecas: pandas, sqlalchemy, requests, python-dotenv
- Banco de dados destino (SQLite para prototipação, PostgreSQL para produção)
- Arquivo `.env` com variáveis de conexão (NUNCA hardcoded)
- Conhecimento básico da estrutura dos dados de origem

## Procedimento
1. **Mapear fontes de dados**
   - Liste cada fonte: tipo (log CSV, tabela SQL, API REST), localização, frequência de atualização
   - Exemplo: "logs_acesso.csv" (diário), tabela "eventos_alarme" (PostgreSQL), API "camera_status" (JSON)

2. **Criar estrutura do projeto**
   ```
   pipeline_seguranca/
   ├── .env
   ├── extract.py
   ├── transform.py
   ├── load.py
   ├── pipeline.py
   └── requirements.txt
   ```

3. **Configurar variáveis de ambiente no `.env`**
   ```
   DB_ORIGEM=postgresql://user:pass@host:5432/seguranca
   DB_DESTINO=sqlite:///dados_consolidados.db
   API_CAMERAS=https://api.exemplo.com/v1/eventos
   API_KEY=chave_aqui
   ```

4. **Implementar extração (`extract.py`)**
   ```python
   import pandas as pd
   import requests
   from sqlalchemy import create_engine
   import os
   from dotenv import load_dotenv

   load_dotenv()

   def extract_csv(caminho):
       return pd.read_csv(caminho)

   def extract_sql(query):
       engine = create_engine(os.getenv("DB_ORIGEM"))
       return pd.read_sql(query, engine)

   def extract_api(endpoint):
       headers = {"Authorization": f"Bearer {os.getenv('API_KEY')}"}
       response = requests.get(endpoint, headers=headers)
       response.raise_for_status()
       return pd.DataFrame(response.json())
   ```

5. **Implementar transformação (`transform.py`)**
   ```python
   def padronizar_timestamps(df, coluna="data_hora"):
       df[coluna] = pd.to_datetime(df[coluna], errors="coerce")
       return df

   def limpar_nulos(df, threshold=0.5):
       return df.dropna(thresh=len(df)*threshold, axis=1)

   def mapear_tipos_evento(df, coluna="tipo"):
       mapa = {"acesso_negado": "negado", "acesso_liberado": "liberado", "alarme": "alerta"}
       df[coluna] = df[coluna].map(mapa).fillna("desconhecido")
       return df

   def consolidar_fontes(dataframes, chave_comum="id_evento"):
       from functools import reduce
       return reduce(lambda left, right: pd.merge(left, right, on=chave_comum, how="outer"), dataframes)
   ```

6. **Implementar carga (`load.py`)**
   ```python
   def carregar_sqlite(df, tabela="eventos_seguranca"):
       engine = create_engine(os.getenv("DB_DESTINO"))
       df.to_sql(tabela, engine, if_exists="replace", index=False)

   def carregar_csv(df, caminho_saida):
       df.to_csv(caminho_saida, index=False)
   ```

7. **Criar orquestrador (`pipeline.py`)**
   ```python
   from extract import extract_csv, extract_sql, extract_api
   from transform import padronizar_timestamps, limpar_nulos, mapear_tipos_evento, consolidar_fontes
   from load import carregar_sqlite

   def executar_pipeline():
       # Extrair
       logs_acesso = extract_csv("dados/logs_acesso.csv")
       eventos_alarme = extract_sql("SELECT * FROM eventos_alarme WHERE data >= NOW() - INTERVAL '7 dias'")
       cameras = extract_api(os.getenv("API_CAMERAS"))

       # Transformar
       logs_acesso = padronizar_timestamps(logs_acesso)
       logs_acesso = mapear_tipos_evento(logs_acesso)
       eventos_alarme = limpar_nulos(eventos_alarme)
       dados_consolidados = consolidar_fontes([logs_acesso, eventos_alarme, cameras])

       # Carregar
       carregar_sqlite(dados_consolidados, "relatorio_semanal")
       print("Pipeline executado com sucesso!")

   if __name__ == "__main__":
       executar_pipeline()
   ```

8. **Agendar execução (Linux/macOS)**
   ```bash
   crontab -e
   # Executar toda segunda às 6h
   0 6 * * 1 cd /caminho/pipeline_seguranca && python pipeline.py >> logs/pipeline.log 2>&1
   ```

## Erros conhecidos e soluções
| Erro | Causa | Solução |
|------|-------|---------|
| `pandas.errors.ParserError` | CSV mal formatado | Usar `pd.read_csv(..., error_bad_lines=False)` ou `on_bad_lines='skip'` |
| `requests.exceptions.ConnectionError` | API offline | Adicionar retry com `tenacity` ou `try/except` com log |
| `sqlalchemy.exc.OperationalError` | Banco origem inacessível | Verificar credenciais no `.env` e conectividade de rede |
| Dados duplicados | Múltiplas fontes com mesmo evento | Usar `df.drop_duplicates(subset='id_evento')` após merge |
| Timezone inconsistente | Timestamps sem fuso horário | Converter todos para UTC com `df[coluna].dt.tz_localize('America/Manaus').dt.tz_convert('UTC')` |

## Exemplo aplicado ao contexto do usuário
**Cenário**: Antonio precisa consolidar dados de três sistemas de segurança da P&G Manaus:
1. Logs de acesso (CSV exportado do sistema de catraca)
2. Eventos de alarme (tabela PostgreSQL do Security Dynamics)
3. Status de câmeras (API JSON do fabricante)

**Execução**:
```bash
cd pipeline_seguranca
python pipeline.py
```

**Resultado**: Banco `dados_consolidados.db` com tabela `relatorio_semanal` contendo:
- 15.423 registros de acesso
- 892 eventos de alarme
- 48 status de câmeras
- Todos com timestamps padronizados em UTC-4 (horário Manaus)
- Pronto para alimentar dashboard Power BI ou relatório semanal
