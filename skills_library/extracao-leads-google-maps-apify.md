<!-- skill: extracao-leads-google-maps-apify | tags: apify, google-maps, extracao-dados, leads | status: nova -->
# Extração de leads do Google Maps com Apify
## Quando usar
- Quando precisar obter dados estruturados de empresas (nome, endereço, telefone, site, etc.) a partir de buscas no Google Maps usando a plataforma Apify.
- Ideal para gerar listas de leads segmentadas por cidade, categoria e palavras-chave.

## Pré-requisitos
- Token de API do Apify com acesso ao ator `compass~google-maps-extractor` (obtido em https://console.apify.com).
- Python 3.6+ com as bibliotecas `requests`, `json` e `time` instaladas.
- Conexão com internet.

## Procedimento
1. **Coletar o token** da API do Apify (disponível no console) e armazená-lo em uma variável de ambiente ou diretamente no script (use placeholder, nunca compartilhe o token real).
2. **Definir os parâmetros de busca**:
   - `{termo}` ou lista de termos (ex.: `'segurança eletrônica'`, `'câmeras de segurança'`).
   - `{localizacao}` no formato `'Cidade, UF, País'` (ex.: `'Manaus, AM, Brasil'`).
   - `{max_lugares_por_busca}` (inteiro, ≤ 20 recomendado para evitar bloqueios; ex.: `20`).
   - `{idioma}` (ex.: `'pt-BR'`).
   - Opcionalmente, ajustar flags de dados extras (horários, avaliações, etc.) conforme necessidade.
3. **Construir o payload JSON** usando o schema do ator:
   ```python
   payload = {
       'searchStringsArray': {termos},
       'location': '{localizacao}',
       'maxCrawledPlacesPerSearch': {max_lugares_por_busca},
       'language': '{idioma}',
       'maxImages': 0,
       'maxReviews': 0,
       'includeOpeningHours': False,
       'includePopularTimes': False,
       # Desative todas as opções desnecessárias para acelerar a extração
   }
   ```
4. **Montar a requisição**:
   - URL: `'https://api.apify.com/v2/acts/compass~google-maps-extractor/run-sync-get-dataset-items'`
   - Parâmetro GET: `'token': {seu_token}`
   - Cabeçalho: `'Content-Type': 'application/json'`
   ```python
   import requests, json, time

   token = '{SEU_TOKEN}'
   url = 'https://api.apify.com/v2/acts/compass~google-maps-extractor/run-sync-get-dataset-items'
   params = {'token': token}
   headers = {'Content-Type': 'application/json'}
   ```
5. **Executar a chamada** com timeout generoso (pelo menos 120 segundos):
   ```python
   start = time.time()
   resp = requests.post(url, params=params, json=payload, headers=headers, timeout=120)
   print(f'Status: {resp.status_code}, Tempo: {time.time() - start:.1f}s')
   ```
6. **Processar a resposta**:
   - Se `resp.status_code == 200`, converter para JSON: `data = resp.json()`.
   - `len(data)` indicará o número de lugares retornados.
   - Perceba que o resultado é uma lista de objetos, cada um contendo campos como `title`, `address`, `phone`, `website`, `categoryName`, etc.
7. **Filtrar os dados** (opcional):
   - Para obter apenas leads válidos, remova itens sem telefone ou com campos vazios.
   - Exemplo rápido via list comprehension:
     ```python
     leads_validos = [item for item in data if item.get('phone')]
     ```
8. **Salvar o resultado** em um arquivo JSON:
   ```python
   with open('{nome_arquivo_saida}.json', 'w', encoding='utf-8') as f:
       json.dump(leads_validos, f, indent=2, ensure_ascii=False)
   ```

## Erros conhecidos e soluções
- **TimeoutError**: a execução síncrona pode demorar. Aumente o timeout progressivamente (até 300s). Se persistir, use a execução assíncrona (run + get dataset items separadamente).
- **Resposta vazia (`[]`)**: verifique se a localização está correta e se os termos de busca são muito restritivos. Teste com um termo genérico primeiro.
- **Status != 200**: imprima `resp.text[:500]` para identificar a causa. Geralmente é token inválido, falta de créditos ou payload mal formatado.
- **Erro de permissão no token**: confirme que o token tem acesso ao ator e que a conta Apify possui créditos disponíveis.

## Exemplo real (da tarefa que originou esta skill)
- **Objetivo**: extrair empresas de segurança eletrônica em Manaus.
- **Termos**: `['segurança eletrônica', 'câmeras de segurança', 'cerca elétrica', 'alarmes residenciais', 'CFTV', 'portaria remota', 'automação de portões', 'monitoramento 24 horas']`
- **Localização**: `'Manaus, AM, Brasil'`
- **Máximo por busca**: 20
- **Idioma**: pt-BR
- **Resultado**: 160 lugares extraídos, salvos em `leads_manaus.json`. A API levou 43 segundos.
- **Pós-processamento**: filtragem para manter apenas registros com telefone preenchido.