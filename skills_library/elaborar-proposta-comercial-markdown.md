<!-- skill: elaborar-proposta-comercial-markdown | tags: proposta, comercial, markdown, pricing, acm-digital | status: nova -->
# Elaborar proposta comercial em Markdown com pricing

## Quando usar
Quando for criar uma proposta técnica-comercial para cliente da ACM Digital, incluindo escopo, prazos e valores. Ideal para propostas que serão enviadas por e-mail ou apresentadas em formato legível sem depender de editores pesados.

## Pré-requisitos
- Editor de texto Markdown (VS Code, Obsidian, ou qualquer um que suporte preview)
- Conhecimento básico de Markdown (títulos, listas, tabelas, links)
- Informações do cliente coletadas (nome, empresa, necessidade, orçamento estimado)
- Definição clara do escopo do projeto

## Procedimento

1. **Crie o cabeçalho da proposta**
   - Use `#` para o título principal: `# Proposta Comercial — {Nome do Cliente}`
   - Abaixo, insira metadados: data, versão, número da proposta
   - Exemplo:
     ```markdown
     # Proposta Comercial — Empresa XYZ Ltda
     **Data:** {data_atual}  
     **Versão:** 1.0  
     **Proposta Nº:** {ACM-{ano}-{sequencial}}  
     **Responsável:** Antonio Cordero — ACM Digital
     ```

2. **Adicione um resumo executivo**
   - Parágrafo curto explicando o objetivo da proposta
   - Exemplo:
     ```markdown
     ## Resumo Executivo
     Esta proposta apresenta a solução de {tipo_solucao} para {nome_cliente}, 
     visando {beneficio_principal}. O prazo estimado é de {prazo_dias} dias 
     úteis, com investimento de {valor_total}.
     ```

3. **Descreva o escopo do projeto**
   - Use listas ou tópicos numerados
   - Seja específico: o que será entregue, o que NÃO está incluso
   - Exemplo:
     ```markdown
     ## Escopo do Projeto
     ### Incluso
     - {Item 1}: {descrição detalhada}
     - {Item 2}: {descrição detalhada}
     - {Item 3}: {descrição detalhada}
     
     ### Não incluso
     - {Item excluído 1}
     - {Item excluído 2}
     ```

4. **Detalhe a metodologia e cronograma**
   - Use tabela Markdown para fases e prazos
   - Exemplo:
     ```markdown
     ## Metodologia e Cronograma
     | Fase | Atividades | Prazo |
     |------|------------|-------|
     | 1. Levantamento | Reunião inicial, análise de requisitos | {dias_fase1} dias |
     | 2. Desenvolvimento | Codificação, testes unitários | {dias_fase2} dias |
     | 3. Homologação | Testes com cliente, ajustes | {dias_fase3} dias |
     | 4. Entrega | Implantação, treinamento, documentação | {dias_fase4} dias |
     ```

5. **Apresente o pricing**
   - Use tabela com itens, descrição, quantidade e valor
   - Inclua totais parciais e total geral
   - Exemplo:
     ```markdown
     ## Investimento
     | Item | Descrição | Qtd | Valor Unitário | Total |
     |------|-----------|-----|----------------|-------|
     | {item1} | {desc1} | {qtd1} | R$ {valor_unit1} | R$ {total1} |
     | {item2} | {desc2} | {qtd2} | R$ {valor_unit2} | R$ {total2} |
     | **Total** | | | | **R$ {valor_total}** |
     
     **Condições de pagamento:** {ex: 50% na assinatura, 50% na entrega}
     ```

6. **Inclua termos e condições**
   - Tópicos obrigatórios: forma de pagamento, prazo de validade da proposta, garantia, suporte
   - Exemplo:
     ```markdown
     ## Termos e Condições
     - **Validade da proposta:** {dias_validade} dias corridos
     - **Forma de pagamento:** {detalhes_pagamento}
     - **Garantia:** {prazo_garantia} meses contra defeitos de implementação
     - **Suporte pós-entrega:** {periodo_suporte} meses inclusos
     - **Revisões:** até {numero_revisoes} revisões sem custo adicional
     ```

7. **Finalize com call-to-action e assinatura**
   - Espaço para assinatura digital ou física
   - Exemplo:
     ```markdown
     ## Próximos Passos
     Para aceitar esta proposta, responda este e-mail com "ACEITO" ou assine 
     digitalmente abaixo.
     
     **Aceito os termos e condições:**
     
     Nome: ___________________________  
     Empresa: ________________________  
     Data: ___________________________  
     
     ---
     *ACM Digital — Automação e Soluções Digitais*  
     *Antonio Cordero*  
     *{seu_email}* | *{seu_telefone}*
     ```

## Erros conhecidos e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| Tabela de pricing quebra no preview | Colunas sem alinhamento correto | Use `|------|------------|-------|` com mesmo número de colunas |
| Cliente pede desconto após envio | Não definiu política de descontos | Inclua cláusula "Preço válido por {dias} dias" |
| Proposta muito longa | Escopo mal definido | Use seções colapsáveis com `<details>` em HTML |
| Esqueceu de incluir impostos | Omissão no pricing | Adicione linha "Impostos: {percentual}%" na tabela |
| Cliente não entende termos técnicos | Linguagem muito técnica | Adicione glossário no final |

## Exemplo aplicado ao contexto do usuário

**Cenário:** Cliente da ACM Digital solicita chatbot para WhatsApp com integração a banco de dados de produtos.

```markdown
# Proposta Comercial — Loja TechPlus Ltda
**Data:** 15/06/2026  
**Versão:** 1.0  
**Proposta Nº:** ACM-2026-001  
**Responsável:** Antonio Cordero — ACM Digital

## Resumo Executivo
Esta proposta apresenta a solução de chatbot para WhatsApp com integração a 
catálogo de produtos para Loja TechPlus, visando automatizar o atendimento 
ao cliente e reduzir o tempo de resposta. O prazo estimado é de 20 dias 
úteis, com investimento de R$ 4.500,00.

## Escopo do Projeto
### Incluso
- Chatbot WhatsApp com 10 fluxos de conversa
- Integração com banco SQLite de produtos (até 500 itens)
- Painel administrativo web para edição de respostas
- Relatório semanal de conversas

### Não incluso
- Hospedagem em nuvem (cliente contrata à parte)
- Integração com ERP ou sistemas legados
- Manutenção após 3 meses de garantia

## Metodologia e Cronograma
| Fase | Atividades | Prazo |
|------|------------|-------|
| 1. Levantamento | Reunião, definição de fluxos | 3 dias |
| 2. Desenvolvimento | Codificação do bot e painel | 10 dias |
| 3. Homologação | Testes com cliente, ajustes | 5 dias |
| 4. Entrega | Implantação, treinamento | 2 dias |

## Investimento
| Item | Descrição | Qtd | Valor Unitário | Total |
|------|-----------|-----|----------------|-------|
| Chatbot WhatsApp | Desenvolvimento completo | 1 | R$ 3.500,00 | R$ 3.500,00 |
| Painel Admin | Interface web de gestão | 1 | R$ 800,00 | R$ 800,00 |
| Treinamento | 2 horas com equipe | 1 | R$ 200,00 | R$ 200,00 |
| **Total** | | | | **R$ 4.500,00** |

**Condições de pagamento:** 50% na assinatura, 50% na entrega.

## Termos e Condições
- **Validade da proposta:** 15 dias corridos
- **Forma de pagamento:** Transferência bancária ou PIX
- **Garantia:** 3 meses contra defeitos de implementação
- **Suporte pós-entrega:** 1 mês inclusos
- **Revisões:** até 3 revisões sem custo adicional

## Próximos Passos
Para aceitar esta proposta, responda este e-mail com "ACEITO" ou assine 
digitalmente abaixo.

**Aceito os termos e condições:**

Nome: ___________________________  
Empresa: ________________________  
Data: ___________________________  

---
*ACM Digital — Automação e Soluções Digitais*  
*Antonio Cordero*  
*antonio@acmdigital.com.br* | *92 99999-0000*
```
