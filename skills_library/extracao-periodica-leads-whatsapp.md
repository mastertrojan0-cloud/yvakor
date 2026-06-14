<!-- skill: extracao-periodica-leads-whatsapp | tags: leads, whatsapp, automacao, apify, cron | status: nova -->
# Extração periódica de leads com Apify e preparação para WhatsApp
## Quando usar
Quando você precisa coletar novos leads de pesquisas no Google Maps em intervalos regulares (ex.: a cada hora) e deseja receber uma mensagem pronta para enviar manualmente a um número de WhatsApp, sem violar os termos de serviço da plataforma.

## Pré-requisitos
- Python 3.8+ instalado
- Conta na [Apify](https://apify.com/) com token de API (obtido em Settings > Integrations)
- ID do ator de Google Maps Scraper (ex.: `compass/Google-Maps-Scraper`)
- Permissão para agendar tarefas no sistema operacional (Windows Task Scheduler, cron no Linux)
- Biblioteca Python: `requests`, `pandas`, `python-dotenv` (instalar via pip)
- Um arquivo CSV histórico de leads já extraídos (para deduplicação)
- Número de telefone WhatsApp para onde enviar a mensagem resumo (fora do script)

## Procedimento
1. **Configure o ambiente do projeto**
   - Crie uma pasta dedicada, ex.: `C:\automacao_leads`
   - Dentro dela, crie um arquivo `.env` com as seguintes variáveis:
     ```
     APIFY_TOKEN=seu_token_aqui
     ACTOR_ID=compass/Google-Maps-Scraper
     SEARCH_QUERY=chaveiro 24 horas são paulo
     LOCATION=São Paulo, SP
     MAX_RESULTS=50
     CSV_HISTORICO=leads_extraidos.csv
     ```
     *Substitua `SEARCH_QUERY` e `LOCATION` pelos termos desejados, e `APIFY_TOKEN` pelo seu token real.*
   - Instale as dependências:
     ```bash
     pip install requests pandas python-dotenv
     ```

2. **Crie o script Python `coletar_leads.py`**
   - Copie o script completo abaixo. Ele:
     - Executa o ator Apify com os parâmetros da busca
     - Aguarda a finalização e baixa os resultados
     - Carrega o histórico de leads do CSV
     - Deduplica usando o telefone ou nome+endereço
     - Salva os novos leads no CSV
     - Gera uma mensagem formatada com os