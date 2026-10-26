# YVAKOR — Roadmap de evolução

## Fase 1 — MVP ✅
- CLI de chat com identidade injetada
- Memória episódica (SQLite) + semântica (keyword/Chroma) + procedural (skills .md)
- Router DeepSeek/Ollama com fallback
- Comandos [perfil], [skill], [memoria]
- Loop de reflexão pós-tarefa

## Fase 2 — Ferramentas ✅
- [x] Function calling no orquestrador (protocolo JSON {tool, args})
- [x] web_search via HTTP GET com extração de conteúdo
- [x] code_executor em sandbox com timeout
- [x] file_manager com Confirmation Guard
- [x] Ponte com conectores (e-mail, WhatsApp, GitHub, Google)

## Fase 3 — Navegador real + Cowork 2.0 ✅ (v0.4)
- [x] Playwright em thread dedicada, perfil persistente (`browser/session.py`)
- [x] 16 ferramentas `navegador_*` (abrir, ver, clicar, preencher, extrair, abas…)
- [x] Snapshot por refs (`e1`, `e2`…) — funciona com modelo de texto
- [x] Painel ao vivo do navegador na interface (screenshot ~2,6 s)
- [x] Cowork persistente (SQLite), fila, passos ao vivo, cancelamento
- [x] Sessão isolada por tarefa + workspace `data/cowork/<id>/`
- [x] Recuperação de tarefas órfãs e shutdown limpo
- [x] Testes offline do navegador, do loop e do cowork

## Fase 4 — Independência gradual
- [ ] Instalar Ollama + qwen2.5:7b (ou deepseek-r1:8b)
- [ ] classify() do router via modelo local
- [ ] Extração de fatos para memória semântica via modelo local
- [ ] Skills 'estáveis' (3+ usos ok) roteadas para o modelo local
- [ ] Dashboard simples de custo: % de chamadas locais vs API

## Fase 5 — Alcance físico: rede local + voz ✅ (v0.5)
- [x] Escopo autorizado (sub-redes da máquina; internet bloqueada por padrão)
- [x] Descoberta: TCP + ARP + SSDP/UPnP + mDNS + classificação de aparelhos
- [x] Registro persistente (data/rede.db) com nomes e credenciais locais
- [x] Câmeras: ONVIF (WS-Discovery, snapshot, PTZ) + RTSP/ffmpeg (foto e clipe)
- [x] Chromecast/Google TV (tocar mídia, volume, pausa) e TVs Samsung/LG
- [x] Android via ADB (print, toque, texto, apps) + instalador do platform-tools
- [x] IoT: Wake-on-LAN, MQTT e HTTP de dispositivos (Tasmota/Shelly)
- [x] Voz: Vosk local pt-BR (STT), edge-tts/SAPI (TTS), palavra de ativação
- [x] Testes offline (escopo, registro, ONVIF, WoL, HTTP, TTS→STT)

## Fase 6 — Memória escalável + cérebro Obsidian ✅ (v0.6)
- [x] Índices B-tree nas consultas quentes + contadores denormalizados
- [x] FTS5 nas conversas, fatos e skills (bm25 + trecho destacado)
- [x] Deduplicação de fatos por hash (não cresce com repetição)
- [x] Poda de logs operacionais + ANALYZE + VACUUM incremental + backup
- [x] Vault markdown estilo Obsidian (`data/vault`) com wikilinks, tags e grafo
- [x] Índice incremental (só reindexa o que mudou) e ferramentas `cerebro_*`
- [x] Benchmarks: histórico 0,07 ms · busca 1,8 ms (5.500) · 4,5 ms (22 mil)

## Fase 7 — Edge + Chrome + cowork ✅ (v0.7)
- [x] Gerenciador multi-motor com perfil próprio por navegador
- [x] Ferramentas com `navegador="edge"|"chrome"` (18 ferramentas)
- [x] Aba isolada por tarefa cowork (sem tarefas atropelando a página)
- [x] Modo CDP: anexar a navegador já aberto (`navegador_conectar`)
- [x] Seletor de motor no painel ao vivo + endpoint com `motor=`
- [x] Teste offline dos dois motores e do isolamento por aba

## Fase 8 — Avançado
- [ ] Downloads via navegador (`expect_download`) e PDF (`print to pdf`)
- [ ] Um contexto de navegador por tarefa cowork (paralelismo real)
- [ ] Agendador de tarefas recorrentes (prospecção diária, relatórios)
- [ ] Acesso remoto: Flask + Cloudflare Tunnel (padrão Gestor Master)
- [ ] Docker p/ rodar em qualquer computador
- [ ] Fine-tuning de modelo local com dataset dos próprios logs de sucesso
- [ ] Visão multimodal para canvas/CAPTCHA assistido
- [ ] Reconhecimento de voz contínuo com modelo maior + interrupção ("barge-in")

## Critério de sucesso
> 80% das tarefas rotineiras resolvidas pelo modelo local lendo skills,
> com DeepSeek V4 reservado apenas para o que é genuinamente novo/complexo.
