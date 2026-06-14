<!-- skill: destilar-skill | tags: meta, destilação, procedimento, reutilização | status: nova -->
# Destilar Skill a partir de solução de tarefa

## Quando usar
Use esta skill sempre que a IA principal resolver uma tarefa com sucesso e for necessário transformar a solução em um procedimento reutilizável (skill) para execução futura por modelos menores ou para documentação permanente.

## Pré-requisitos
- Tarefa resolvida com sucesso pela IA principal
- Contexto da solução (passos executados, comandos usados, erros encontrados)
- Skills existentes similares no repositório (para evitar duplicação)

## Procedimento

1. **Identificar o propósito central da solução**
   - Pergunte: "Qual problema específico esta solução resolve?"
   - Extraia o nome curto em kebab-case (ex: `destilar-skill`, `escrever-codigo-melhor`)
   - Defina 2-3 tags relevantes (ex: `meta`, `destilação`, `procedimento`)

2. **Analisar a solução da IA principal**
   - Leia o contexto da tarefa resolvida
   - Identifique os passos exatos que funcionaram
   - Anote comandos, trechos de código ou prompts específicos usados
   - Substitua valores específicos por placeholders `{assim}` (ex: `{nome_da_skill}`)

3. **Verificar skills existentes no contexto**
   - Se houver skill com nome similar, gere versão atualizada (mesmo nome) incorporando o novo aprendizado
   - Se não houver, crie skill nova com status `nova`
   - Nunca duplique skills

4. **Estruturar o conteúdo da skill**
   - Escreva o cabeçalho: `<!-- skill: {nome} | tags: {tags} | status: {status} -->`
   - Título: comece com verbo no infinitivo (ex: "Destilar Skill")
   - Seção "Quando usar": 1-2 frases com gatilhos claros
   - Seção "Pré-requisitos": liste condições necessárias
   - Seção "Procedimento": passos numerados, imperativos, sem ambiguidade
   - Seção "Erros conhecidos e soluções": registre erros vistos e como contornar
   - Seção "Exemplo real": use o contexto da tarefa que originou a skill

5. **Revisar e finalizar**
   - Verifique se todos os passos são executáveis por modelo 7B
   - Confirme que não há credenciais ou dados sensíveis
   - Garanta que placeholders estão claros (ex: `{nome_do_arquivo}`)
   - Saída: apenas o markdown da skill, sem comentários extras

## Erros conhecidos e soluções

| Erro | Solução |
|------|---------|
| Placeholder ambíguo (ex: `{valor}` sem contexto) | Use nomes descritivos: `{nome_do_usuario}`, `{caminho_do_arquivo}` |
| Passo muito genérico (ex: "Analise o problema") | Detalhe: "Leia o contexto da tarefa resolvida e identifique os 3 principais passos executados" |
| Esquecer de verificar skills existentes | Sempre faça busca no repositório antes de criar nova skill |
| Incluir dados sensíveis | Substitua por placeholders e anote em comentário interno |

## Exemplo real (da tarefa que originou esta skill)

**Tarefa resolvida:** "Preciso que voce comence a ornehnar a IA aperfeçoando a capacidade de escrever codigo"

**Solução da IA principal:** "Entendido, Antonio. Vou iniciar o processo de aperfeiçoamento da minha capacidade de escrever código. Para isso, preciso primeiro entender o estado atual e definir um plano. Vou começar analisando meu próprio repositório de skills e memórias para identificar pontos de melhoria."

**Skill gerada:** Esta skill (`destilar-skill`) foi criada a partir dessa tarefa, demonstrando o processo de destilação. O nome em kebab-case é `destilar-skill`, as tags são `meta, destilação, procedimento, reutilização`, e o status é `nova` (nenhuma skill similar existia).