<!-- skill: apify-google-maps-extractor | tags: apify, google-maps, scraping, data-extraction, crm | status: nova -->
# Extrair dados de lugares do Google Maps via Apify

## Quando usar
Quando você precisa obter uma lista de empresas, profissionais ou estabelecimentos detalhados (nome, telefone, endereço, avaliação, site) a partir de buscas por palavra-chave e localização geográfica. Ideal para prospecção de leads, enriquecimento de bases ou criação de planilhas de mercado.

## Pré-requisitos
- Conta gratuita no Apify (créditos mensais de $5) criada em [console.apify.com/sign-up](https://console.apify.com/sign-up).
- Token de API pessoal, obtido em [console.apify.com/account#/integrations](https://console.apify.com/account#/integrations).
- Conhecimento básico de terminal e JSON.

## Procedimento

1. **Obter o token da conta Apify**
   - Acesse **Settings → Integrations → API token** ou diretamente pela URL fornecida.
   - Copie o token e guarde-o como variável de ambiente ou em local seguro (`export APIFY_TOKEN=seu-token`).

2. **Definir os parâmetros da busca**
   - Escolha as palavras-chave que representam o segmento desejado (ex: `câmeras de segurança`, `alarmes residenciais`).
   - Determine a localização: cidade, coordenadas ou caixa delimitadora.
   - Prepare um corpo JSON com a estrutura esperada pelo ator `compass~google-maps-extractor`. Campos comuns:
     ```json
     {
       "searchStringsArray": ["{palavra-chave1}", "{palavra-chave2}"],
       "locationQuery": "{cidade, estado}",
       "maxCrawledPlaces": 50,
       "language": "en",
       "includeWebResults": false,
       "extendOutputFunction": "($, item) => { return item; }",
       "proxyConfiguration": {
         "useApifyProxy": true
       }
     }
     ```
   - Consulte a [documentação do ator](https://apify.com/compass/google-maps-extractor/input-schema) para todos os campos possíveis.

3. **Montar e disparar a requisição**
   - Use o endpoint síncrono que retorna os dados diretamente (sem necessidade de polling):
     ```
     POST https://api.apify.com/v2/acts/compass~google-maps-extractor/run-sync-get-dataset-items?token={TOKEN}
     Content-Type: application/json
     ```
   - No `curl`:
     ```bash
     curl -X POST \
       "https://api.apify.com/v2/acts/compass~google-maps-extractor/run-sync-get-dataset-items?token=${APIFY_TOKEN}" \
       -H "Content-Type: application/json" \
       -d '{
         "searchStringsArray": ["{palavra1}", "{palavra2}"],
         "locationQuery": "{localizacao}"
       }' > results.json
     ```
   - Caso precise de controle assíncrono (muitos lugares), use o endpoint `/runs` para iniciar e depois consulte o dataset.

4. **Processar a saída**
   - O resultado (`results.json`) é um array de objetos, cada um representando um lugar. Campos úteis:
     - `title` – nome do estabelecimento
     - `phone` – telefone (pode estar vazio)
     - `address` – endereço completo
     - `website` – URL do site
     - `totalScore` – nota (ex: 4.5)
     - `permanentlyClosed` – se está fechado permanentemente
     - `location` – coordenadas {lat, lng}
   - Converta para CSV/planilha com ferramentas como `jq`:
     ```bash
     jq -r '.[] | [.title, .phone, .address, .website, .totalScore] | @csv' results.json > leads.csv
     ```

5. **Validar e enriquecer**
   - Filtre registros sem telefone ou com `permanentlyClosed: true`.
   - Para prospecção ativa, valide os números via WhatsApp (formatação, existência no aplicativo).
   - Considere normalizar os DDDs para a região esperada (ex: `92` para Manaus).

## Erros conhecidos e soluções

- **`401 Unauthorized`**: token inválido, não enviado ou expirado. Regenere o token e verifique a sintaxe da query string.
- **`400 Bad Request`**: payload malformado. Confira se a chave `searchStringsArray` está presente e se os valores são strings.
- **Estouro de créditos**: execuções com muitos lugares podem consumir mais do que o saldo gratuito. Reduza `maxCrawledPlaces` ou restrinja palavras-chave.
- **Timeout (sem resposta)**: o endpoint síncrono tem limite de 60s; para volumes grandes, use o endpoint `/runs` e depois `/datasets/{datasetId}/items` (vide [documentação da API Apify](https://docs.apify.com/api/v2)).

## Exemplo real (da tarefa que originou esta skill)

Objetivo: levantar prestadores de segurança eletrônica em Manaus (AM) com telefones para abordagem comercial.

Consulta executada:
```json
{
  "searchStringsArray": [
    "segurança eletrônica",
    "câmeras de segurança",
    "cerca elétrica",
    "alarmes residenciais",
    "CFTV",
    "portaria remota",
    "automação de portões",
    "monitoramento 24 horas"
  ],
  "locationQuery": "Manaus, AM",
  "maxCrawledPlaces": 200
}
```
A execução retornou 134 lugares. Após filtro (remover sem telefone e fechados), restaram 87 leads válidos que foram convertidos em planilha CSV e ordenados por nota. O custo foi de aproximadamente $0,60.