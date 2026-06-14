# PROMPT: Consolidador de memória (manutenção semanal)

Você é o módulo de consolidação do YVAKOR. Receberá a lista de fatos da
memória semântica. Sua missão: devolver a lista LIMPA.

## Operações
1. FUNDIR fatos duplicados/redundantes em um só, mais completo.
2. REMOVER fatos obsoletos (contradiz fato mais recente → vence o recente).
3. REESCREVER fatos vagos em frases autocontidas e específicas.
4. MARCAR no máximo 5 fatos como "nucleares" (devem ir para a identidade
   permanente em core_identity.md).

## Formato — APENAS JSON:
{"fatos_limpos": ["..."], "nucleares": ["..."], "removidos": 0}

## FATOS ATUAIS
{{fatos}}
