# MCP no YVAKOR

O YVAKOR implementa um cliente do **Model Context Protocol (MCP)**, padrão
aberto criado pela Anthropic e mantido pela comunidade MCP. Servidores MCP
expõem ferramentas que entram automaticamente no registro do agente.

## Configuração

Edite `config/mcp.json`:

```json
{
  "servers": {
    "filesystem": {
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "E:\\YVAKOR"],
      "cwd": "E:\\YVAKOR\\yvakor"
    }
  }
}
```

- `command`: executável do servidor MCP (stdio).
- `args`: argumentos.
- `env`: variáveis de ambiente extras.
- `enabled`: só conecta se `true`.

As ferramentas aparecem como `mcp_<servidor>_<ferramenta>` e podem ser usadas
pelo agente como qualquer outra. `mcp_status` lista os servidores conectados.

## API

`GET /api/mcp` retorna servidores, ferramentas e erros.

## Segurança

Só habilite servidores cujo código você confia: eles rodam com os mesmos
privilégios do YVAKOR.
