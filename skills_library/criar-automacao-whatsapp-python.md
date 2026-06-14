<!-- skill: criar-automacao-whatsapp-python | tags: whatsapp, automacao, python, selenium, prospeccao | status: nova -->
# Criar automação de envio de mensagens no WhatsApp com Python

## Quando usar
Quando precisar enviar notificações automáticas, lembretes ou campanhas de prospecção via WhatsApp para clientes da ACM Digital. Ideal para disparos controlados (não spam) com lista de contatos pré-aprovada.

## Pré-requisitos
- Python 3.8+ instalado
- Google Chrome instalado
- Conexão com internet estável
- Lista de contatos em CSV (nome, telefone com DDD e país, ex: 5592999999999)
- Conta WhatsApp ativa no celular principal

## Procedimento

### 1. Instalar dependências
```bash
pip install selenium webdriver-manager pandas pyperclip
```

### 2. Criar estrutura de pastas
```
whatsapp-automation/
├── contatos.csv
├── mensagem.txt
├── automacao.py
└── logs/
```

### 3. Preparar arquivo de contatos (contatos.csv)
```csv
nome,telefone
João Silva,5592999999999
Maria Santos,5592988888888
```

### 4. Preparar mensagem (mensagem.txt)
```
Olá {nome}, tudo bem?

Aqui é da ACM Digital. Gostaria de apresentar nossas soluções em automação digital para otimizar seus processos.

Podemos conversar 5 minutos?

Atenciosamente,
Antonio Cordero
```

### 5. Criar script principal (automacao.py)
```python
import pandas as pd
import pyperclip
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
import logging
from datetime import datetime

# Configurar logging
logging.basicConfig(
    filename=f'logs/disparo_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def carregar_contatos(caminho_csv):
    """Carrega contatos do CSV"""
    try:
        df = pd.read_csv(caminho_csv)
        logging.info(f"Carregados {len(df)} contatos")
        return df
    except Exception as e:
        logging.error(f"Erro ao carregar CSV: {e}")
        raise

def carregar_mensagem(caminho_txt):
    """Carrega template de mensagem"""
    try:
        with open(caminho_txt, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logging.error(f"Erro ao carregar mensagem: {e}")
        raise

def enviar_mensagem_whatsapp(driver, telefone, mensagem):
    """Envia mensagem para um contato específico"""
    try:
        # Abrir conversa
        url = f"https://web.whatsapp.com/send?phone={telefone}"
        driver.get(url)
        
        # Aguardar carregamento (30 segundos máx)
        wait = WebDriverWait(driver, 30)
        
        # Aguardar campo de mensagem
        campo_msg = wait.until(
            EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]'))
        )
        
        # Aguardar 3 segundos extras para garantir carregamento
        time.sleep(3)
        
        # Copiar mensagem para área de transferência e colar
        pyperclip.copy(mensagem)
        campo_msg.click()
        campo_msg.send_keys(Keys.CONTROL + 'v')
        
        # Aguardar 1 segundo
        time.sleep(1)
        
        # Clicar no botão enviar
        botao_enviar = driver.find_element(By.XPATH, '//button[@data-testid="compose-btn-send"]')
        botao_enviar.click()
        
        # Aguardar envio
        time.sleep(2)
        
        logging.info(f"Mensagem enviada para {telefone}")
        return True
        
    except Exception as e:
        logging.error(f"Erro ao enviar para {telefone}: {e}")
        return False

def main():
    # Carregar dados
    contatos = carregar_contatos('contatos.csv')
    template_msg = carregar_mensagem('mensagem.txt')
    
    # Configurar driver
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument('--disable-notifications')
    options.add_argument('--start-maximized')
    
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        # Abrir WhatsApp Web
        driver.get('https://web.whatsapp.com')
        print("Escaneie o QR Code com seu WhatsApp")
        input("Pressione ENTER após escanear o QR Code...")
        
        # Enviar mensagens
        for _, contato in contatos.iterrows():
            nome = contato['nome']
            telefone = str(contato['telefone'])
            
            # Personalizar mensagem
            mensagem_personalizada = template_msg.replace('{nome}', nome)
            
            print(f"Enviando para {nome} ({telefone})...")
            sucesso = enviar_mensagem_whatsapp(driver, telefone, mensagem_personalizada)
            
            if sucesso:
                print(f"✓ Enviado para {nome}")
            else:
                print(f"✗ Falha ao enviar para {nome}")
            
            # Intervalo entre mensagens (evitar bloqueio)
            time.sleep(5)
            
    finally:
        driver.quit()
        logging.info("Automação finalizada")

if __name__ == "__main__":
    main()
```

### 6. Executar automação
```bash
cd whatsapp-automation
python automacao.py
```

### 7. Monitorar logs
```bash
tail -f logs/disparo_*.log
```

## Erros conhecidos e soluções

### Erro: "Element not found" ou timeout
**Causa:** WhatsApp Web não carregou completamente ou mudou estrutura HTML
**Solução:** Aumentar timeout no `WebDriverWait` ou atualizar seletores XPath

### Erro: "ChromeDriver version mismatch"
**Causa:** Versão do ChromeDriver incompatível com Chrome instalado
**Solução:** Executar `webdriver-manager update` ou reinstalar ChromeDriver

### Erro: "Número inválido" no WhatsApp
**Causa:** Telefone sem código do país ou formato incorreto
**Solução:** Verificar formato: 55 (Brasil) + DDD + número (ex: 5592999999999)

### Erro: "Mensagem não enviada" sem erro aparente
**Causa:** Número bloqueou contato ou não existe no WhatsApp
**Solução:** Verificar log e remover contato da lista

### Erro: "Connection refused" ao iniciar ChromeDriver
**Causa:** ChromeDriver não encontrado ou permissão negada
**Solução:** Executar com `sudo` (Linux) ou verificar antivírus (Windows)

## Exemplo aplicado ao contexto do usuário

**Cenário:** Antonio quer enviar proposta de automação para 5 clientes potenciais da ACM Digital

**Arquivo contatos.csv:**
```csv
nome,telefone
João da Silva,5592999999999
Maria Oliveira,5592988888888
Carlos Santos,5592977777777
Ana Pereira,5592966666666
Pedro Costa,5592955555555
```

**Mensagem personalizada (mensagem.txt):**
```
Olá {nome}, tudo bem?

Sou Antonio Cordero, da ACM Digital. Vi que sua empresa pode se beneficiar de automações inteligentes para reduzir custos operacionais.

Gostaria de agendar uma conversa rápida para apresentar nossas soluções. Topa?

Abraço,
Antonio
```

**Resultado esperado:** 5 mensagens enviadas com sucesso, cada uma personalizada com o nome do contato, em aproximadamente 1 minuto (considerando intervalos de segurança).
