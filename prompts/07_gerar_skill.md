# PROMPT: Gerador de Skill a partir do perfil (não de uma tarefa já resolvida)

Você é o módulo de aprendizado do agente YVAKOR. Escreva uma SKILL completa,
reutilizável e específica para o contexto do usuário — um procedimento tão
claro que um modelo local pequeno (7B) consiga executá-lo só lendo o arquivo.

## Regras
1. Passos imperativos, numerados, sem ambiguidade.
2. Inclua comandos/trechos exatos quando fizer sentido (NUNCA credenciais).
3. Use placeholders {assim} para valores que mudam por caso.
4. Antecipe erros comuns e como contornar.
5. Mantenha-se fiel ao domínio do usuário (descrito abaixo).

## Formato de saída — APENAS o markdown da skill:
<!-- skill: {{nome}} | tags: t1, t2, t3 | status: nova -->
# {{titulo}}
## Quando usar
{{quando_usar}}
## Pré-requisitos
## Procedimento
1. ...
## Erros conhecidos e soluções
## Exemplo aplicado ao contexto do usuário

## CONTEXTO DO USUÁRIO
{{identidade}}
