<!-- skill: criar-automacao-web-scraping | tags: python, web-scraping, automação, dados | status: nova -->
# Criar automação de web scraping com Python

## Quando usar
Quando precisar extrair dados de sites de concorrentes, fornecedores ou portais técnicos para análise comercial ou de segurança. Ideal para coletar preços, especificações técnicas, contatos ou notícias de forma automatizada.

## Pré-requisitos
- Python 3.8+ instalado
- pip atualizado (`python -m pip install --upgrade pip`)
- Conhecimento básico de HTML/CSS (identificar seletores)
- Permissão legal para raspar o site alvo (verifique robots.txt)

## Procedimento

### 1. Analisar o site alvo
1.1. Acesse o site manualmente e identifique a estrutura dos dados desejados.
1.2. Verifique o arquivo `robots.txt` (ex: `https://exemplo.com/robots.txt`) para regras de scraping.
1.3. Use o DevTools do navegador (F12) para inspecionar elementos e identificar seletores CSS ou XPath.

### 2. Configurar ambiente virtual (opcional, mas recomendado)
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### 3. Instalar bibliotecas necessárias
```bash
pip install requests beautifulsoup4 lxml pandas
```
- `requests`: fazer requisições HTTP
- `beautifulsoup4`: parsear HTML
- `lxml`: parser rápido (opcional, mas recomendado)
- `pandas`: organizar dados em tabelas

### 4. Criar script base
4.1. Crie um arquivo `scraper.py` com a estrutura:
```python
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random

# Configurações
URL_BASE = "{url_base}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
DELAY = {delay_segundos}  # Entre 2 e 5 segundos para evitar bloqueio

def extrair_dados(url):
    """Extrai dados de uma página específica"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        
        # Exemplo: extrair itens de uma lista
        dados = []
        for item in soup.select("{seletor_css}"):
            dados.append({
                "titulo": item.select_one("{seletor_titulo}").get_text(strip=True),
                "preco": item.select_one("{seletor_preco}").get_text(strip=True),
                "link": item.select_one("a")["href"]
            })
        return dados
    except Exception as e:
        print(f"Erro ao acessar {url}: {e}")
        return []

# Loop principal
resultados = []
for pagina in range(1, {num_paginas} + 1):
    url = f"{URL_BASE}?page={pagina}"
    print(f"Raspando página {pagina}...")
    dados_pagina = extrair_dados(url)
    resultados.extend(dados_pagina)
    time.sleep(DELAY + random.uniform(0, 1))

# Salvar resultados
df = pd.DataFrame(resultados)
df.to_csv("{nome_arquivo}.csv", index=False, encoding="utf-8-sig")
print(f"Dados salvos em {nome_arquivo}.csv")
```

### 5. Personalizar seletores
5.1. Substitua os placeholders:
- `{url_base}`: URL base do site (ex: `https://exemplo.com/produtos`)
- `{seletor_css}`: seletor do container de cada item (ex: `.product-card`)
- `{seletor_titulo}`: seletor do título dentro do container (ex: `.product-title`)
- `{seletor_preco}`: seletor do preço (ex: `.price`)
- `{delay_segundos}`: delay entre requisições (ex: `3`)
- `{num_paginas}`: número de páginas para raspar (ex: `10`)
- `{nome_arquivo}`: nome do arquivo de saída (ex: `produtos_concorrente`)

### 6. Testar e depurar
6.1. Execute o script: `python scraper.py`
6.2. Verifique o CSV gerado. Se dados estiverem vazios, ajuste os seletores.
6.3. Use `print(soup.prettify()[:1000])` para inspecionar o HTML baixado.

### 7. Tratar paginação dinâmica (se aplicável)
Se o site carregar dados via JavaScript:
```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

chrome_options = Options()
chrome_options.add_argument("--headless")
driver = webdriver.Chrome(options=chrome_options)
driver.get("{url}")
time.sleep(3)  # Aguardar carregamento
soup = BeautifulSoup(driver.page_source, "lxml")
driver.quit()
```

## Erros conhecidos e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| `HTTP 403 Forbidden` | Site bloqueia scraping | Adicione headers realistas (User-Agent, Accept-Language) |
| `HTTP 429 Too Many Requests` | Muitas requisições rápidas | Aumente o delay para 5-10 segundos |
| Dados vazios no CSV | Seletor CSS incorreto | Verifique no DevTools se o seletor existe |
| `ConnectionError` | Site fora do ar ou bloqueio de IP | Use proxy rotativo ou VPN |
| Elementos não encontrados | Conteúdo carregado via JS | Use Selenium ou Playwright |
| Encoding errado | Caracteres especiais quebrados | Use `encoding="utf-8-sig"` no CSV |

## Exemplo aplicado ao contexto do usuário

**Cenário**: Antonio quer monitorar preços de câmeras de segurança no site de um concorrente para ajustar precificação na ACM Digital.

**Script adaptado**:
```python
URL_BASE = "https://concorrente-seguranca.com.br/cameras"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY = 4

def extrair_cameras(url):
    response = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(response.text, "lxml")
    cameras = []
    for card in soup.select(".product-card"):
        cameras.append({
            "modelo": card.select_one(".product-name").get_text(strip=True),
            "preco": card.select_one(".price-current").get_text(strip=True),
            "resolucao": card.select_one(".spec-resolution").get_text(strip=True),
            "link": card.select_one("a")["href"]
        })
    return cameras

resultados = []
for pagina in range(1, 6):
    url = f"{URL_BASE}?page={pagina}"
    resultados.extend(extrair_cameras(url))
    time.sleep(DELAY + random.uniform(0, 2))

df = pd.DataFrame(resultados)
df.to_csv("cameras_concorrente.csv", index=False, encoding="utf-8-sig")
print(f"{len(resultados)} câmeras extraídas e salvas!")
```

**Resultado**: Antonio obtém uma planilha com modelos, preços e especificações para comparar com seu catálogo e ajustar margens.
