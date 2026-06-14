# YVAKOR — Roadmap de evolução

## Fase 1 — MVP (este esqueleto) ✅
- CLI de chat com identidade injetada
- Memória episódica (SQLite) + semântica (keyword/Chroma) + procedural (skills .md)
- Router DeepSeek/Ollama com fallback
- Comandos [perfil], [skill], [memoria]
- Loop de reflexão pós-tarefa

## Fase 2 — Ferramentas (implementar com Claude Code / DeepSeek V4)
- [ ] Function calling no orquestrador (LLM devolve JSON {tool, args})
- [ ] web_search com citação de fontes
- [ ] code_executor em sandbox com timeout
- [ ] file_manager (escrita via Confirmation Guard)
- [ ] Ponte com Assistente Master (WhatsApp/e-mail, sempre via guard)

## Fase 3 — Independência gradual
- [ ] Instalar Ollama + qwen2.5:7b (ou deepseek-r1:8b)
- [ ] classify() do router via modelo local
- [ ] Extração de fatos para memória semântica via modelo local
- [ ] Skills 'estáveis' (3+ usos ok) roteadas para o modelo local
- [ ] Dashboard simples de custo: % de chamadas locais vs API

## Fase 4 — Avançado
- [ ] Acesso remoto: Flask + Cloudflare Tunnel (padrão Gestor Master)
- [ ] Docker p/ rodar em qualquer computador
- [ ] Fine-tuning de modelo local com dataset dos próprios logs de sucesso
- [ ] Modo proativo: agenda de tarefas recorrentes (prospecção diária, etc.)

## Critério de sucesso
> 80% das tarefas rotineiras resolvidas pelo modelo local lendo skills,
> com DeepSeek V4 reservado apenas para o que é genuinamente novo/complexo.
