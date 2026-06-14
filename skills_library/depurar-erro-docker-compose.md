<!-- skill: gerar-skill-procedural | tags: yvakor, skill, documentacao, procedimento | status: nova -->
# Geração de Skill Procedural a partir do Perfil do Usuário
## Quando usar
Quando você, YVAKOR, identifica um padrão de tarefa repetitiva que merece ser transformada em uma skill reutilizável, ou quando o usuário solicita a criação de uma skill para um procedimento específico.

## Pré-requisitos
- Perfil do usuário carregado (arquivo de identidade mestre).
- Compreensão clara do domínio e contexto do usuário (técnico, empreendedor, stack preferida).
- Tarefa ou procedimento bem definido (pode ser uma tarefa já resolvida ou um novo requisito).

## Procedimento
1. **Identifique o domínio e o contexto do usuário**  
   - Leia o arquivo de identidade mestre para entender quem é o usuário, seu stack, prioridades e regras.
   - Exemplo: Se o usuário é técnico em eletrônica de segurança e empreendedor digital, foque em automações, chatbots, micro-SaaS, Docker, Python, Node.js.

2. **Defina o escopo da skill**  
   - Pergunte-se: "Qual problema específico essa skill resolve?"  
   - Exemplo: "Depuração de erro em Docker Compose" ou "Criação de proposta comercial para ACM Digital".

3. **Escreva o cabeçalho da skill**  
   - Use o formato: `<!-- skill: {nome-da-skill} | tags: {tag1}, {tag2} | status: nova -->`  
   - Tags relevantes ao domínio (ex: docker, python, automacao, prospeccao).

4. **Crie a seção "Quando usar"**  
   - Descreva em uma ou duas frases quando a skill deve ser acionada.  
   - Exemplo: "Quando um container não sobe, rede falha ou volume não monta em projetos com Docker."

5. **Liste os pré-requisitos**  
   - Ferramentas, conhecimentos ou arquivos necessários antes de iniciar.  
   - Exemplo: "Docker e Docker Compose instalados", "Acesso ao terminal", "Arquivo docker-compose.yml presente".

6. **Escreva o procedimento em passos imperativos e numerados**  
   - Cada passo deve ser uma ação clara, sem ambiguidade.  
   - Use placeholders `{assim}` para valores que mudam por caso.  
   - Inclua comandos exatos quando fizer sentido (NUNCA credenciais).  
   - Exemplo:  
     1. Execute `docker-compose logs {nome-do-servico}` para ver logs do container com problema.  
     2. Verifique se a porta `{porta}` está disponível com `lsof -i :{porta}`.

7. **Antecipe erros comuns e soluções**  
   - Liste erros frequentes e como contorná-los.  
   - Exemplo:  
     - Erro: "port is already allocated" → Solução: Pare o container que está usando a porta ou mude a porta no docker-compose.yml.

8. **Inclua um exemplo aplicado ao contexto do usuário**  
   - Use um caso real ou simulado do domínio do usuário.  
   - Exemplo: "No projeto ACM Digital de chatbot, o container do Redis não sobe. Siga os passos acima para depurar."

9. **Revise a skill**  
   - Verifique se está completa, reutilizável e específica.  
   - Certifique-se de que um modelo local pequeno (7B) consiga executar só lendo o arquivo.

## Erros conhecidos e soluções
- **Erro: Skill muito genérica**  
  Solução: Releia o perfil do usuário e refine o escopo para algo específico do domínio dele.
- **Erro: Passos ambíguos**  
  Solução: Reescreva cada passo como uma ação única e clara, sem margem para interpretação.
- **Erro: Falta de placeholders**  
  Solução: Identifique valores que mudam por caso (nomes, portas, caminhos) e substitua por `{placeholder}`.

## Exemplo aplicado ao contexto do usuário
**Cenário:** Antonio pede para criar uma skill para depurar erros em Docker Compose, algo que ele enfrenta frequentemente nos projetos da ACM Digital.

**Skill gerada:**  
`<!-- skill: depurar-erro-docker-compose | tags: docker, devops, automacao | status: nova -->`  
... (conteúdo da skill conforme o procedimento acima)

**Resultado:** Uma skill pronta para ser usada sempre que um container não subir, economizando tempo e evitando retrabalho.
