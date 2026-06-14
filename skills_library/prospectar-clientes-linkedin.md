<!-- skill: prospectar-clientes-linkedin | tags: prospeccao, linkedin, b2b, automacao, vendas | status: nova -->
# Prospectar clientes B2B via LinkedIn Automation

## Quando usar
Para gerar leads qualificados para a ACM Digital, automatizando a busca por potenciais clientes B2B no LinkedIn e o envio de mensagens de contato inicial. Use quando precisar expandir a carteira de clientes de forma sistemática e escalável.

## Pré-requisitos
- Conta no LinkedIn (preferencialmente Premium ou Sales Navigator para filtros avançados).
- Ferramenta de automação de navegador (ex: Selenium, Playwright) ou extensão como Dux-Soup, Linked Helper.
- Planilha ou banco de dados para registrar leads (ex: Google Sheets, SQLite).
- Template de mensagem de prospecção aprovado pelo usuário.
- Conexão estável com internet.

## Procedimento

1. **Definir perfil de cliente ideal (ICP)**
   - Liste 3-5 critérios: setor (ex: segurança eletrônica), cargo (ex: gerente de facilities, TI), localização (ex: Manaus, AM), porte da empresa (ex: médio/grande).
   - Exemplo: "Gerentes de facilities em Manaus, empresas com mais de 50 funcionários, setor industrial ou comercial."

2. **Configurar busca no LinkedIn**
   - Acesse o LinkedIn e use a barra de pesquisa ou Sales Navigator.
   - Aplique filtros: palavras-chave (ex: "segurança eletrônica", "automação predial"), localização, cargo, setor.
   - Salve a busca como "Alerta de vagas" ou "Lead List" se aplicável.

3. **Extrair leads manualmente ou com automação**
   - Se manual: copie nome, cargo, empresa, perfil URL para a planilha.
   - Se automatizado: configure script para coletar dados da página de resultados. Exemplo de comando Playwright:
     ```python
     from playwright.sync_api import sync_playwright
     with sync_playwright() as p:
         browser = p.chromium.launch(headless=False)
         page = browser.new_page()
         page.goto('https://www.linkedin.com/search/results/people/?keywords={palavra_chave}')
         # login manual ou com cookies salvos
         # extrair elementos com page.query_selector_all('.entity-result__title-text')
     ```
   - Registre no mínimo 20 leads por sessão.

4. **Qualificar leads rapidamente**
   - Verifique perfil: tem conexões em comum? Posta conteúdo relevante? Empresa parece ativa?
   - Marque como "quente", "morno" ou "frio" na planilha.

5. **Enviar solicitação de conexão personalizada**
   - Para cada lead quente/morno, envie convite com nota personalizada (máx. 300 caracteres).
   - Template base:
     ```
     Olá {nome}, vi que você atua em {setor} em Manaus. Sou da ACM Digital, especializada em automação para segurança eletrônica. Gostaria de conectar para trocar ideias sobre otimização de processos. Abs, Antonio
     ```
   - Limite: 20-30 convites/dia para evitar bloqueio.

6. **Aguardar aceitação e iniciar conversa**
   - Após aceitação (1-3 dias), envie mensagem de agradecimento e introdução curta.
   - Template:
     ```
     Obrigado por conectar, {nome}! Como comentei, na ACM Digital ajudamos empresas em Manaus a reduzir custos com automação de segurança. Tem 5 min para um bate-papo rápido esta semana?
     ```
   - Se não responder em 5 dias, envie um follow-up leve.

7. **Registrar interações e agendar próximos passos**
   - Atualize planilha com status: "conectado", "conversando", "reunião agendada", "fechado".
   - Se houver interesse, agende call via Calendly ou similar.

## Erros conhecidos e soluções

- **Erro: Conta bloqueada por excesso de convites**
  - Solução: Reduza para 15 convites/dia. Use pausas aleatórias entre ações (5-15 min). Nunca automatize login.

- **Erro: Mensagens parecem genéricas e são ignoradas**
  - Solução: Personalize sempre com dado específico do perfil (ex: "Vi seu post sobre IoT"). Teste variações de template.

- **Erro: Ferramenta de automação não extrai dados corretamente**
  - Solução: Verifique se o seletor CSS mudou (LinkedIn atualiza layout). Use `page.wait_for_selector()` com timeout maior. Atualize script.

- **Erro: Leads não aceitam conexão**
  - Solução: Revise ICP. Talvez o cargo ou setor não seja ideal. Teste com perfis de empresas menores.

## Exemplo aplicado ao contexto do usuário

**Cenário**: Antonio quer prospectar gerentes de facilities de shoppings em Manaus para vender automação de câmeras e controle de acesso.

1. ICP: Gerentes de facilities, shoppings centers, Manaus, empresas com +100 funcionários.
2. Busca no LinkedIn: "gerente de facilities" + "Manaus" + "shopping".
3. Extrai 25 leads: nomes como "Carlos Silva", "Ana Oliveira", etc.
4. Qualifica: 15 quentes (perfis completos, conexões em comum), 5 mornos, 5 frios.
5. Envia convites personalizados: "Olá Carlos, vi que gerencia facilities no Shopping Ponta Negra. Sou da ACM Digital, especialista em segurança eletrônica. Vamos conectar?"
6. Após 3 dias, 10 aceitam. Envia mensagem de introdução.
7. Agenda 2 calls na semana seguinte.

**Resultado esperado**: 2-3 leads qualificados por semana, com potencial de fechamento em 30 dias.
