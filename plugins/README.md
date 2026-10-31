# Plugins do YVAKOR

Um plugin é um pacote de skills, comandos e servidores MCP. O layout é o mesmo
dos plugins do Claude, então um plugin feito para o Claude pode ser copiado
para cá.

```
plugins/<nome>/
  .yvakor-plugin/plugin.json   # ou .claude-plugin/plugin.json, ou plugin.json
  skills/<skill>/SKILL.md      # vira a skill "<plugin>:<skill>" (só leitura)
  commands/<comando>.md        # vira "/<comando>" no chat; $ARGUMENTS = o resto
  agents/<agente>.md           # subagente "<plugin>:<agente>" (veja agents/README.md)
  hooks/hooks.json             # hooks somados ao config/hooks.json
  .mcp.json                    # {"mcpServers": {...}}; ${CLAUDE_PLUGIN_ROOT} = esta pasta
```

`plugin.json` mínimo:

```json
{"name": "meu-plugin", "description": "O que ele faz", "version": "1.0.0"}
```

## Ligar e desligar

Plugin novo começa **desligado**: ele pode trazer servidores MCP e hooks
(programas que rodam no seu PC) e textos que entram no prompt. Leia os arquivos e, no chat:

- `/plugins` lista os plugins e o que cada um traz
- `/plugins ligar <nome>` liga (os servidores MCP sobem no próximo início)
- `/plugins desligar <nome>` desliga

Skills e comandos com padrão de prompt-injection são bloqueados e aparecem em
`/plugins` com o motivo. O estado fica em `data/plugins_estado.json`.
