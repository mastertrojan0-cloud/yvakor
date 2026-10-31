# Subagentes do YVAKOR

Cada arquivo `<nome>.md` desta pasta é um subagente especialista. O formato é o
mesmo dos subagentes do Claude Code. O YVAKOR usa `agente_delegar` para mandar
uma parte da tarefa a um subagente, que trabalha num contexto isolado, só com as
ferramentas listadas, e devolve o resultado.

```markdown
---
name: meu-agente
description: Quando usar este agente (é o que o YVAKOR lê para decidir).
tools: arquivos_ler, navegador_*      # vazio = todas; aceita *
model: deepseek                       # local | deepseek | gemini | inherit
max_passos: 8
---
O prompt de sistema do agente.
```

- `geral` já vem embutido, com todas as ferramentas.
- Plugins ligados podem trazer agentes em `agents/`; o nome fica `plugin:agente`.
- Nenhum subagente pode delegar de novo nem fazer perguntas ao usuário.
- Arquivos com padrão de prompt-injection são ignorados.
