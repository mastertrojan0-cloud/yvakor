<!-- skill: gerar-skill-procedural | tags: documentacao, skill, yvakor, procedimento | status: nova -->
# Gerar skill procedural a partir do perfil do usuário
## Quando usar
Quando o YVAKOR identifica um padrão de tarefa repetitiva que pode ser transformada em skill reutilizável. A skill deve ser auto-contida para execução por modelo local 7B.

## Pré-requisitos
- Identificar claramente o domínio e a tarefa repetitiva
- Ter acesso ao perfil do usuário (contexto, stack, preferências)
- Conhecer os limites do modelo alvo (7B: sem RAG, sem ferramentas externas)

## Procedimento
1. **Identificar o padrão**
   - Analise o histórico de tarefas do usuário nos últimos 7 dias
   - Liste tarefas que apareceram 2+ vezes com variações mínimas
   - Exemplo: backup de banco, deploy de chatbot, formatação de relatório

2. **Definir o escopo da skill**
   - A skill deve resolver UM problema específico (não genérico)
   - Deve ser executável em 5-15 passos
   - Deve caber em 1-2 páginas de markdown

3. **Estruturar o cabeçalho**
   - Nome claro e acionável (verbo + objeto)
   - Tags relevantes ao domínio do usuário
   - Status: nova

4. **Escrever "Quando usar"**
   - Condições exatas para ativar a skill
   - Exemplo: "Quando precisar garantir a integridade de dados de sistemas em produção, com agendamento e notificação de falhas."

5. **Listar pré-requisitos**
   - Ferramentas instaladas (ex: `docker`, `pg_dump`, `cron`)
   - Acessos necessários (sem expor credenciais)
   - Conhecimentos prévios do executor

6. **Criar procedimento numerado**
   - Cada passo é uma ação imperativa
   - Use placeholders {assim} para valores variáveis
   - Inclua comandos exatos entre crases quando fizer sentido
   - Exemplo: `pg_dump -U {usuario} -h {host} {banco} > {arquivo}.sql`

7. **Antecipar erros comuns**
   - Liste 3-5 erros típicos com solução
   - Exemplo: "Erro: permissão negada → Solução: verificar usuário do PostgreSQL"

8. **Adicionar exemplo contextualizado**
   - Use dados reais do perfil do usuário
   - Exemplo: "Para o banco `acm_prod` do cliente ACM Digital..."

9. **Revisar para modelo 7B**
   - Remova ambiguidades (evite "talvez", "se possível")
   - Substitua referências externas por instruções diretas
   - Verifique se todos os placeholders são auto-explicativos

## Erros conhecidos e soluções
1. **Skill muito genérica** → Solução: Restringir a um caso específico do usuário
2. **Passos ambíguos** → Solução: Substituir por comandos exatos com placeholders
3. **Falta de contexto** → Solução: Incluir exemplo com dados do perfil do usuário
4. **Skill muito longa** → Solução: Dividir em skills menores ou simplificar passos

## Exemplo aplicado ao contexto do usuário
Para Antonio Cordero (ACM Digital, Manaus-AM), stack Python/Node.js/SQLite/PostgreSQL/Docker:

**Skill gerada:** "Automatizar backup de banco de dados SQLite/PostgreSQL"
- Quando usar: Backup noturno de sistemas em produção (chatbots, micro-SaaS)
- Pré-requisitos: `docker`, `pg_dump` (PostgreSQL), `sqlite3` (SQLite), `cron` no servidor
- Passo 1: Identificar tipo de banco (SQLite → arquivo .db; PostgreSQL → conexão)
- Passo 2: Para PostgreSQL: `pg_dump -U {user} -h {host} {db} > /backup/{db}_{data}.sql`
- Passo 3: Para SQLite: `cp {caminho}.db /backup/{db}_{data}.db`
- Erro comum: "Falha de conexão PostgreSQL" → Verificar se container está rodando: `docker ps | grep postgres`
- Exemplo: Backup do banco `acm_chatbot` (SQLite) → `cp /data/acm_chatbot.db /backup/acm_chatbot_2026-06-12.db`
