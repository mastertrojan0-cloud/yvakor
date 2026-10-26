# Arquitetura

## Visão geral

```
┌───────────────────────┐      HTTP/JSON       ┌────────────────────────┐
│ App desktop (Tkinter) │ ───────────────────► │ Núcleo (server.py)     │
│ Extensão Chrome       │                      │ ThreadingHTTPServer    │
│ Interface web         │                      │ 127.0.0.1:7777         │
└───────────────────────┘                      └──────────┬─────────────┘
                                                          │
                         ┌────────────────────────────────┼────────────────────────┐
                         │                │               │                        │
                    Orquestrador     Memória SQLite   Ferramentas             Cowork/Agenda
                    (planeja,        (episódios,      (browser, arquivos,      (threads,
                     roteia,          sessões,         shell, rede, mídia,      checkpoints,
                     aprende)         FTS5)            MCP, docs)              retomada)
                         │
                 LLM Router (DeepSeek / Ollama)
```

## Componentes

- **server.py**: HTTP local, CORS restrito, APIs de chat, voz, rede, tarefas,
  agenda, avaliações, MCP, mídia e uploads.
- **orchestrator.py**: cérebro → atalhos diretos → agente com ferramentas;
  sessão explícita, privacidade e telemetria.
- **agent.py**: loop de ferramentas com orçamento, watchdog e artefatos.
- **cowork.py**: planos, execução, verificação, checkpoint e retomada.
- **agenda.py**: tarefas persistentes, repetição e execução em segundo plano.
- **contexto.py**: seleciona parágrafos/seções relevantes da página dentro do
  orçamento e fundamenta respostas com citação.
- **pesquisa.py**: busca, leitura paralela de fontes e síntese com citações.
- **documentos.py**: OCR Windows e PDF (texto/OCR).
- **visao.py**: visão local via Ollama (`moondream`) + OCR para telas/fotos.
- **extensao_bridge.py**: fila de comandos para a extensão operar a mesma
  janela do Chrome; inclui cursor/clique/digitação visíveis.
- **mcp.py**: cliente MCP stdio/JSON-RPC.
- **browser/**: Playwright, Chrome real via CDP, perfis persistentes.
- **desktop.py**: interface nativa; **chrome-extension/**: side panel.
- **voz/**: STT Vosk, TTS edge/SAPI, sessão por palavra-chave.

## Dados

| Caminho | Conteúdo |
|---|---|
| `data/yvakor_memory.db` | episódios, sessões, memória |
| `data/vault/` | cérebro markdown |
| `data/uploads/` | anexos do chat |
| `data/pesquisas/` | relatórios de pesquisa |
| `data/agenda.json` | tarefas agendadas |
| `data/avaliacoes.jsonl` | notas de qualidade |
| `data/browser_profiles/` | perfis Chrome/Edge (cookies — sensível) |
| `data/logs/` | logs e falhas |

## Segurança

- servidor ligado apenas em loopback e IP Tailscale;
- CORS aceita somente `chrome-extension://` e o próprio YVAKOR;
- ferramentas protegidas exigem confirmação;
- perfis de navegador e `.env` são credenciais;
- modo privado não grava conversa/memória;
- MCP executa código local: habilitar apenas servidores confiáveis.

## Versionamento

`config/version.json` é a fonte da versão. O núcleo sincroniza a extensão
(`manifest.json`, `build.json`, fontes) a cada inicialização.
