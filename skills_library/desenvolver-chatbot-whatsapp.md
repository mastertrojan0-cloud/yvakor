<!-- skill: desenvolver-chatbot-whatsapp-twilio-python | tags: chatbot, whatsapp, twilio, python, automação | status: nova -->
# Desenvolver chatbot para WhatsApp com Twilio e Python

## Quando usar
Para criar ou manter chatbots de atendimento, prospecção ou suporte via WhatsApp para a ACM Digital ou clientes. Ideal para automação de respostas, captura de leads e integração com sistemas existentes.

## Pré-requisitos
- Conta Twilio ativa (com número de WhatsApp aprovado)
- Python 3.8+ instalado
- Flask ou FastAPI para servidor web
- ngrok ou servidor com HTTPS público (para webhook)
- Conhecimento básico de APIs REST e JSON
- Editor de código (VS Code recomendado)

## Procedimento

1. **Configurar ambiente Python**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   pip install twilio flask python-dotenv requests
   ```

2. **Criar arquivo de variáveis de ambiente (.env)**
   ```
   TWILIO_ACCOUNT_SID=seu_account_sid
   TWILIO_AUTH_TOKEN=seu_auth_token
   TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
   ```

3. **Criar servidor web básico (app.py)**
   ```python
   from flask import Flask, request
   from twilio.twiml.messaging_response import MessagingResponse
   import os
   from dotenv import load_dotenv

   load_dotenv()
   app = Flask(__name__)

   @app.route("/webhook", methods=["POST"])
   def webhook():
       incoming_msg = request.values.get("Body", "").lower()
       sender = request.values.get("From", "")
       resp = MessagingResponse()
       msg = resp.message()

       # Lógica do chatbot
       if "olá" in incoming_msg or "oi" in incoming_msg:
           msg.body("Olá! Como posso ajudar? Digite:\n1 - Serviços\n2 - Orçamento\n3 - Falar com atendente")
       elif "1" in incoming_msg:
           msg.body("Oferecemos: chatbots, automações, sites e sistemas sob medida. Qual seu interesse?")
       elif "2" in incoming_msg:
           msg.body("Para orçamento, informe seu nome e o que precisa. Em breve retornaremos.")
       elif "3" in incoming_msg:
           msg.body("Você será direcionado a um atendente. Aguarde...")
           # Aqui pode integrar com sistema de tickets ou notificação
       else:
           msg.body("Desculpe, não entendi. Digite:\n1 - Serviços\n2 - Orçamento\n3 - Falar com atendente")

       return str(resp)

   if __name__ == "__main__":
       app.run(port=5000, debug=True)
   ```

4. **Expor servidor local com ngrok**
   ```bash
   ngrok http 5000
   ```
   Copie a URL HTTPS gerada (ex: https://abc123.ngrok.io)

5. **Configurar webhook no Twilio Console**
   - Acesse console.twilio.com
   - Vá em Messaging > Try it out > Send a WhatsApp message
   - Em "When a message comes in", cole a URL: https://abc123.ngrok.io/webhook
   - Defina método como HTTP POST

6. **Testar o chatbot**
   - Envie "Olá" para seu número Twilio no WhatsApp
   - Verifique se recebe resposta automática
   - Teste diferentes entradas (1, 2, 3, texto aleatório)

7. **Adicionar funcionalidades avançadas (opcional)**
   - Integração com banco de dados (SQLite/PostgreSQL)
   - Envio de mídia (imagens, PDFs)
   - Captura de leads com formulários
   - Conexão com CRM ou sistema de tickets
   - Agendamento de mensagens

## Erros conhecidos e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| "403 Forbidden" no webhook | Token inválido ou SID errado | Verifique .env e recarregue variáveis |
| Mensagem não chega | Webhook não configurado ou URL expirou | Reinicie ngrok e atualize URL no Twilio |
| Resposta duplicada | Duas instâncias do servidor | Mate processos antigos: `pkill -f "python app.py"` |
| Erro de SSL | ngrok não iniciado | Execute `ngrok http 5000` e aguarde tunnel ativo |
| Mensagem não processada | Formato de requisição incorreto | Verifique se método é POST e Body está presente |

## Exemplo aplicado ao contexto do usuário

**Cenário:** ACM Digital precisa de um chatbot para captar leads de automação residencial no WhatsApp.

**Implementação específica:**
```python
# No webhook, adicione lógica para capturar leads
if "automação" in incoming_msg or "casa inteligente" in incoming_msg:
    msg.body("Ótimo! Temos soluções de automação residencial. Para receber um orçamento personalizado, informe:\n1 - Seu nome\n2 - Tipo de imóvel (casa/apartamento)\n3 - Principais necessidades")
    # Salvar lead em banco de dados
    save_lead(sender, incoming_msg)
```

**Integração com CRM:**
```python
import requests

def save_lead(phone, message):
    # Exemplo: enviar para API do CRM da ACM Digital
    data = {"phone": phone, "message": message, "source": "whatsapp"}
    requests.post("https://crm.acm.digital/api/leads", json=data)
```

**Dica para prospecção:** Configure respostas automáticas para horário comercial e fora dele, com mensagens personalizadas para cada segmento (residencial, comercial, industrial).
