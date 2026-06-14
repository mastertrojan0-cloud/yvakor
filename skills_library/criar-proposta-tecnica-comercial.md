<!-- skill: criar-proposta-tecnica-comercial | tags: proposta, comercial, tecnica, cliente, orcamento | status: nova -->
# Criação de proposta técnica e comercial

## Quando usar
Quando precisar montar uma proposta formal para cliente, combinando escopo técnico e valores comerciais. Ideal para prospecção ativa da ACM Digital ou projetos internos que exigem documentação profissional.

## Pré-requisitos
- Ter clareza do escopo do projeto (funcionalidades, entregáveis, prazos)
- Ter definido o modelo de precificação (fixo, por hora, recorrente)
- Acesso a template de proposta (Markdown, Google Docs ou PDF)
- Nome do cliente, contato e empresa

## Procedimento

1. **Identifique o cliente e o contexto**
   - Anote: nome do cliente, empresa, cargo, telefone/e-mail, data da solicitação
   - Resuma em 2-3 frases o problema que o cliente quer resolver

2. **Defina o escopo técnico detalhado**
   - Liste cada funcionalidade ou serviço em tópicos
   - Exemplo: "Módulo de login com Google OAuth", "Painel administrativo com gráficos"
   - Separe obrigatório vs. desejável (se aplicável)

3. **Estime horas ou recursos por item**
   - Use sua experiência ou quebre em tarefas menores
   - Some horas totais e defina prazo de entrega

4. **Calcule o valor comercial**
   - Escolha modelo: {valor_fixo} ou {valor_hora} x {horas_estimadas}
   - Se recorrente: {valor_mensal} com {periodo_minimo} meses
   - Adicione 15-20% de margem de segurança se for fixo

5. **Escreva a proposta no formato escolhido**
   - Estrutura mínima:
     - Cabeçalho: "Proposta Técnica e Comercial — {nome_cliente}"
     - Data e validade (ex: "válida por 15 dias")
     - Seção 1: Objetivo (2-3 linhas)
     - Seção 2: Escopo técnico (lista numerada)
     - Seção 3: Cronograma (datas ou marcos)
     - Seção 4: Investimento (tabela simples)
     - Seção 5: Condições de pagamento (ex: 50% entrada, 50% na entrega)
     - Seção 6: Assinatura digital ou campo para aceite

6. **Revise e envie**
   - Leia em voz alta para pegar erros
   - Converta para PDF se necessário
   - Envie por e-mail com assunto: "Proposta ACM Digital — {nome_projeto}"

## Erros conhecidos e soluções

| Erro | Solução |
|------|---------|
| Cliente pede escopo vago | Solicite reunião de 15 min para detalhar antes de escrever |
| Prazo muito apertado | Negocie entregas parciais ou aumente horas estimadas |
| Cliente quer desconto fora do padrão | Ofereça pacote menor ou parcelamento, nunca reduza hora |
| Proposta muito longa | Use bullet points e tabelas; evite parágrafos grandes |
| Esqueceu de incluir suporte | Adicione "1 mês de suporte incluso" ou valor separado |

## Exemplo aplicado ao contexto do usuário

**Cenário:** Cliente da ACM Digital quer um chatbot para WhatsApp com integração a banco de dados de produtos.

**Proposta resumida:**

```
Proposta Técnica e Comercial — Loja do João

Objetivo: Automatizar atendimento no WhatsApp com respostas sobre estoque e preços.

Escopo:
1. Conexão com API do WhatsApp Business
2. Banco SQLite com catálogo de 200 produtos
3. Fluxo de conversa: saudação → pergunta → resposta
4. Painel admin para editar produtos (React)

Cronograma: 3 semanas (início imediato)

Investimento:
- Desenvolvimento: R$ 4.500 (fixo)
- Manutenção mensal (opcional): R$ 200/mês

Pagamento: 50% entrada, 50% na entrega.
```

**Comandos úteis para gerar o documento:**

```bash
# Se for markdown, crie o arquivo:
touch proposta-{cliente}.md

# Se for PDF, use pandoc:
pandoc proposta-{cliente}.md -o proposta-{cliente}.pdf
```
