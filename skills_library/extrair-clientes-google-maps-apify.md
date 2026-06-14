<!-- skill: extrair-clientes-google-maps-apify | tags: extracao, google-maps, clientes, apify | status: nova -->
# Coletar clientes potenciais do Google Maps via Apify

## Quando usar
- Quando o usuário precisa de listas de negócios (não concorrentes) em uma cidade
para prospecção, análise de mercado ou enriquecimento de CRM.
- Quando a extração deve ser feita sem interação manual, diretamente via API.

## Pré-requisitos
- Token da API da Apify (`{APIFY_API_TOKEN}`) com acesso ao ator `compass~google-maps-extractor`.
- Python 3.x com módulos `urllib.request` e `json` (biblioteca padrão).
- Conexão de internet estável e permissão para fazer requisições POST longas (timeout de 180s recomendado).

## Procedimento

1. **Definir os parâmetros de busca**:
   - `{CIDADE_ESTADO}`: localização no formato `Cidade, Estado` (ex.: `Manaus, Amazonas`).
   - `{TERMOS}`: lista de categorias de estabelecimentos desejados (ex.: `['clínica', 'restaurante', ...]`).
   - `{MAX_PLACES}`: número máximo de resultados por termo (padrão sugerido: `15`).
   - `{TOKEN}`: token da Apify.

2. **Preparar o payload JSON**:
   ```python
   payload = {
       'searchStringsArray': {TERMOS},
       'location': '{CIDADE_ESTADO}',
       'maxCrawledPlacesPerSearch': {MAX_PLACES},
       'language': 'pt-BR',
       'maxImages': 0,
       'maxReviews': 0,
       'includeOpeningHours': False,
       'includePopularTimes': False,
       'includePeopleAlsoSearch': False,
       'includeEmail': False,
       'includeMenu': False,
       'includeHotelData': False,
       'includeSimilarPlaces': False,
       'includeFoodDelivery': False,
       'includeStreetView': False,
       'includeGoogleUrl': False,
       'includeBusinessStatus': True
   }
   ```

3. **Montar a requisição POST para a API Apify**:
   ```python
   import urllib.request, json

   url = f'https://api.apify.com/v2/acts/compass~google-maps-extractor/run-sync-get-dataset-items?token={TOKEN}'
   data = json.dumps(payload).encode('utf-8')
   req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
   ```

4. **Executar a extração e salvar o resultado**:
   ```python
   try:
       with urllib.request.urlopen(req, timeout=180) as resp:
           result = json.loads(resp.read().decode('utf-8'))
           nome_arquivo = f'clientes_{CIDADE_ESTADO}.json'.replace(' ', '_').lower()
           with open(nome_arquivo, 'w', encoding='utf-8') as f:
               json.dump(result, f, indent=2, ensure_ascii=False)
           print(f'{len(result)} lugares salvos em {nome_arquivo}')
   except Exception as e:
       print('Erro na extração:', str(e))
   ```

5. **Verificar o arquivo JSON gerado** — ele conterá a lista de lugares com campos como `title`, `address`, `categoryName`, `phone`, `location`, etc., prontos para uso.

## Erros conhecidos e soluções
- **Timeout (erro de rede)**: use `timeout=180` e, se persistir, reduza o número de termos ou o `maxCrawledPlacesPerSearch` para aliviar a carga.
- **Erro de autorização**: confira se o token é válido e se o ator está habilitado na conta.
- **JSON inválido ou vazio**: verifique se os parâmetros obrigatórios (`searchStringsArray` e `location`) estão presentes e bem formatados.

## Exemplo real (da tarefa que originou esta skill)
- **Pedido do usuário**: “o que voce esta fazend eu estou pedindo clientes nao concorrentes”.
- **Implementação**: foi usada a localização `Manaus, Amazonas` com 16 termos (`clínica`, `restaurante`, `loja de roupas`, `oficina mecânica`, `mercado`, `academia`, `condomínio residencial`, `escola`, `pet shop`, `farmácia`, `salão de beleza`, `imobiliária`, `consultório odontológico`, `padaria`, `hotel`, `posto de gasolina`) e `maxCrawledPlacesPerSearch=15`.
- **Resultado**: lista de 240 lugares (15 por termo) salva em `clientes_manaus.json`, sem credenciais expostas no arquivo final.