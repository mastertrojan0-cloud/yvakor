# YVAKOR v0.8 — Agente Pessoal Autônomo

> **YVAKOR** — do tupi *ybaka* (céu) + *kor* (núcleo): "o núcleo do céu".
> Agente de IA autônomo que **executa tarefas reais no computador, na web e na
> sua rede local**, fala, ouve, aprende com cada interação e acumula
> independência progressiva de IA externa.
>
> © 2026 Antonio José Cordero Martinez — ACM Digital, Manaus-AM.
> Todos os direitos reservados.

---

## O que ele faz

| Capacidade | Como |
|---|---|
| **Navega em Edge e Chrome** | Chrome real via CDP, perfil dedicado, sem flags de automação |
| **Alcança a rede local** | Descobre câmeras, TVs, celulares e IoT; controla os autorizados |
| **Fala e ouve** | Vosk (STT local) + edge-tts/SAPI; voz também no painel do Chrome |
| **Cérebro em markdown** | Vault estilo Obsidian (`data/vault`) indexado em FTS5 |
| **Memória que escala** | SQLite com índices, FTS5, dedup e poda — não desacelera |
| **Tarefas autônomas** | Cowork com plano, checkpoint, verificação e retomada |
| **Pesquisa profunda** | Múltiplas fontes, síntese com citações e relatório salvo |
| **OCR e PDFs** | Windows OCR, PDF nativo/digitalizado, upload no chat |
| **Visão local** | `moondream` no Ollama descreve telas/fotos; OCR complementa |
| **Agenda** | Lembretes e tarefas diárias/semanais persistentes |
| **MCP** | Ferramentas externas pelo padrão aberto Model Context Protocol |
| **Extensão Chrome** | Side panel compacto com chat e processo ao vivo |
| **Qualidade** | Avaliação automática 1–5 por resposta em segundo plano |
| **Entregáveis** | PDF, DOCX, XLSX, CSV, HTML, fotos com licença e links |
| **Gera imagens** | Pollinations/OpenAI (quando configurado) |
| **Executa código** | Python, shell e PowerShell no seu PC |

---

## Instalação

```bash
git clone https://github.com/mastertrojan0-cloud/yvakor.git
cd yvakor
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
cp .env.example .env        # insira sua DEEPSEEK_API_KEY

# Navegador: usa o Edge/Chrome já instalado. Se não houver nenhum:
python -m playwright install chromium

# (Opcional) Geração de imagens via Higgsfield:
npm i -g @higgsfield/cli
higgsfield auth login
```

> No Windows, `INICIAR.bat` faz tudo isso (venv, dependências, teste do
> navegador, smoke test) e abre o menu de inicialização.

## Uso

```bash
python -m yvakor.main        # Terminal interativo
python -m yvakor.server      # Interface 3D → http://localhost:7777
python -m yvakor.voz         # Conversa por voz (STT + TTS pt-BR)
python -m yvakor.browser.setup   # Verifica/prepara o navegador controlado
python -m yvakor.learning.bootstrap  # Auto-aprendizado em lote
```

### Interface (v0.5)

- **Histórico redesenhado** — conversas agrupadas por data (Hoje, Ontem, 7 dias,
  este ano), prévia da última mensagem, contagem, horário e filtros por período.
- **Busca inteligente** — procura no título **e** no conteúdo; `Ctrl+K` foca a
  busca, `Ctrl+N` cria conversa, `Esc` limpa.
- **Lateral recolhível** — botão `«` e estado lembrado entre sessões.
- **🖥 Navegador** — tela ao vivo do navegador controlado (abrir, ir, fechar,
  alternar janela visível/invisível).
- **🧩 Tarefas** — dispare, acompanhe passos, cancele e leia resultados.
- **🌐 Rede** — varredura e inventário de câmeras, TVs, celulares e IoT.
- **🎙 Voz** — microfone no navegador (Web Speech API ou Vosk) e 🔊 para ouvir
  as respostas.

### Comandos no chat

```
[cowork] gerar relatorio de seguranca       → tarefa em segundo plano
[cowork-status]                             → lista tarefas
[cowork-status] abc12345                    → detalhe de uma tarefa
[cowork-resultado] abc12345                 → resultado completo
[cowork-cancelar] abc12345                  → pede cancelamento
[nova]                                      → nova conversa (zera contexto)
[nova] Projeto ACME                         → nova conversa com título
[conversas]                                 → lista todas as conversas
[retomar] abc12345                          → alterna para outra conversa
[apagar-conversa] abc12345                  → remove conversa e mensagens
[perfil] ...                                → edita identidade do agente
[skill] ...                                 → cria skill procedural
[memoria] ...                               → busca na memória semântica
[ferramentas]                               → lista ferramentas disponíveis
[aprender]                                  → gera skills a partir do perfil
[manutencao]                                → ciclo de auto-manutenção
```

Você **não precisa** de comando para navegar: basta pedir
"abra o site X e faça Y" — o agente escolhe e encadeia as ferramentas.

---

## Duas formas de trabalhar

**1. No chat (síncrono).** Você pede, ele executa passo a passo e responde.
Bom para tarefas curtas: "veja o preço do dólar no site do BCB".

**2. Cowork (segundo plano).** A tarefa roda em sessão isolada, com workspace
próprio (`data/cowork/<id>/`), enquanto você continua conversando. Bom para
tarefas longas: "pesquise 10 concorrentes e monte uma planilha".

---

## Arquitetura

```
yvakor/
├── identity/               # Personalidade do agente (editável por chat)
│   ├── core_identity.md    # Quem ele é, tom, postura, limites
│   └── principles.md       # Comportamentos herdados das melhores IAs
├── config/settings.yaml    # Modelos, roteamento, ferramentas, navegador, cowork
├── prompts/                # Templates de extração/destilação/avaliação
├── skills_library/         # Memória procedural (skills em markdown)
├── data/                   # SQLite, ChromaDB, sandbox, downloads, perfil do navegador
├── interface/
│   └── index.html          # Visualização 3D + painéis (navegador, tarefas)
├── yvakor/
│   ├── main.py             # CLI
│   ├── server.py           # Servidor HTTP (API REST + interface 3D)
│   ├── orchestrator.py     # Cérebro: contexto, dispatch, reflexão, confirmação
│   ├── agent.py            # Loop ReAct: IA decide → ferramenta → observa → responde
│   ├── cowork.py           # Tarefas autônomas (SQLite, fila, cancelamento)
│   ├── maintenance.py      # Auto-manutenção programada
│   ├── browser/            # Controle do navegador
│   │   ├── session.py      # Playwright em thread dedicada + snapshot com refs
│   │   ├── tools.py        # 16 ferramentas navegador_*
│   │   └── setup.py        # Verifica/instala o navegador
│   ├── rede/               # NOVO — alcance de dispositivos
│   │   ├── escopo.py       # autorização (LAN da máquina, internet bloqueada)
│   │   ├── descoberta.py   # TCP + ARP + SSDP + mDNS + classificação
│   │   ├── registro.py     # SQLite de dispositivos + credenciais
│   │   ├── onvif.py        # WS-Discovery, snapshot, PTZ (SOAP/WSSE)
│   │   ├── camera.py       # foto/vídeo (ONVIF → RTSP/ffmpeg)
│   │   ├── cast.py         # Chromecast / Google TV
│   │   ├── tv.py           # Samsung Tizen / LG webOS
│   │   ├── telefone.py     # Android via ADB (com instalador)
│   │   ├── iot.py          # WoL, MQTT, HTTP de dispositivos
│   │   └── tools.py        # 22 ferramentas rede_*
│   ├── voz/                # Voz: fala e escuta
│   │   ├── stt.py          # Vosk local + VAD + transcrição de arquivo
│   │   ├── tts.py          # edge-tts + SAPI
│   │   ├── assistente.py   # modo mãos livres (palavra de ativação)
│   │   └── tools.py        # voz_falar, voz_ouvir, voz_transcrever
│   ├── cerebro/            # NOVO — vault markdown + índice (Obsidian)
│   │   ├── vault.py        # exporta memória/skills/conversas, indexa wikilinks
│   │   └── tools.py        # cerebro_buscar/nota/grafo/escrever/sincronizar
│   ├── memory/
│   │   ├── db.py           # NOVO — PRAGMAs, FTS5, dedup, helpers
│   │   ├── episodic.py     # SQLite + índices + FTS5 + poda/backup
│   │   ├── semantic.py     # fatos em SQLite/FTS5 (importa JSONL antigo)
│   │   └── procedural.py   # skills .md + índice incremental
│   ├── llm/
│   │   ├── adapter.py      # Provider OpenAI-compatible (DeepSeek, Ollama)
│   │   └── router.py       # Classifica tarefa → escolhe provider → fallback
│   ├── memory/
│   │   ├── episodic.py     # SQLite: sessões (chat/tarefa), conversas, ferramentas
│   │   ├── semantic.py     # Vetorial (ChromaDB) + keyword search
│   │   └── procedural.py   # Biblioteca de skills em markdown
│   ├── tools/
│   │   ├── registry.py     # Registro + manifesto para o agente
│   │   ├── builtin.py      # Ferramentas nativas (arquivos, shell, imagem, web)
│   │   └── guard.py        # Confirmação de ações perigosas
│   ├── connectors/         # Integrações: Google, GitHub, e-mail, WhatsApp
│   ├── reflection/         # Autoavaliação pós-tarefa + criação de skills
│   └── learning/           # Absorção de conhecimento + bootstrap
├── docs/                   # LEVANTAMENTO.md, NAVEGADOR.md, CONECTORES.md, ROADMAP.md
└── tests/                  # smoke, browser, agent_browser, cowork
```

---

## Loop de Agente (Claude Code-like)

```
Usuário pede →
  IA decide: usar ferramenta?
    SIM → {"acao":"usar_ferramenta","ferramenta":"...","args":{...}}
         → executa → recebe OBSERVAÇÃO → decide próximo passo
    NÃO → responde em texto (markdown, português)
```

Cada passo aparece no terminal/interface em tempo real. O modelo encadeia
ferramentas autonomamente até concluir a tarefa (até 25 passos no chat e 40
numa tarefa cowork).

---

## Controle do navegador (novo na v0.4)

O agente não "raspa HTML": ele dirige um navegador real, com cookies, login e
JavaScript — como uma pessoa.

Ciclo típico:

```
navegador_abrir("https://site.com")     → snapshot da página
navegador_ver()                         → elementos com refs: e1, e2, e3…
navegador_clicar("e7")                  → clique real
navegador_ver()                         → refs novas após a mudança
navegador_preencher("e2", "texto")      → digitação real
navegador_extrair("table")              → conteúdo limpo, sem poluir contexto
```

- **Perfil persistente** em `data/browser_profile/`: uma vez logado, continua
  logado nas próximas execuções — separado do seu navegador pessoal.
- **Sem visão computacional:** o agente lê o texto e os elementos interativos
  (título, links, campos, botões) com refs estáveis, suficiente para agir.
- **Painel ao vivo:** a interface mostra a tela em tempo quase real.
- **Limites honestos:** CAPTCHA/2FA pedem intervenção humana; conteúdo dentro
  de iframes pode não aparecer no snapshot.

Detalhes e receitas: [`docs/NAVEGADOR.md`](docs/NAVEGADOR.md).

## Cowork 2.0 (novo na v0.4)

- **Persistente:** tarefas ficam em `data/cowork.db` e sobrevivem a reinícios.
- **Isolado:** cada tarefa tem sessão própria (não mistura com seu chat) e
  workspace em `data/cowork/<id>/` com `resultado.md` e artefatos.
- **Observável:** passos ao vivo (🖥 abrindo, 🖱 clicando…) na interface.
- **Cancelável:** para entre um passo e outro, sem deixar processo pendurado.
- **Recuperação:** tarefa que estava rodando quando o processo morreu aparece
  como `interrompida` (nunca fica "executando" para sempre).

## Rede local (novo na v0.5)

O agente enxerga e controla os aparelhos **da rede desta máquina** — e só ela.

```
rede_escanear()                     → câmeras, TVs, celulares, IoT, roteador
rede_camera_snapshot("garagem")     → JPEG salvo em data/rede_shots/
rede_tv("desligar", "tv da sala")   → Samsung/LG
rede_cast("tocar", "sala", url)     → Chromecast/Google TV
rede_telefone_tela()                → print do Android (ADB autorizado)
rede_mqtt_publicar("casa/luz", "ON")
```

- **Escopo autorizado:** sub-redes físicas da máquina + `allowed_hosts`.
  Internet é negada por padrão (`allow_public: false`).
- **Sem força bruta:** câmera que pede senha → o agente para e pede a você.
- **Ações com efeito** (PTZ, gravar, TV, celular, MQTT) passam pelo
  Confirmation Guard; senhas e ADB shell confirmam sempre.
- Detalhes: [`docs/REDE.md`](docs/REDE.md).

## Voz (novo na v0.5)

- **Ouvir:** Vosk local (pt-BR, ~31 MB, offline depois do download).
- **Falar:** edge-tts neural (online) com fallback SAPI/Microsoft Maria
  (offline).
- **Modo mãos livres:** `python -m yvakor.voz` — diga "yvakor" e fale.
- **Na interface:** botão 🎙 (microfone do navegador) e 🔊 (falar respostas).
- Sem microfone na máquina? `voz_transcrever(arquivo)` ou o microfone do
  navegador resolvem. Detalhes: [`docs/VOZ.md`](docs/VOZ.md).

## Cérebro e memória escalável (novo na v0.6)

Quatro camadas, todas indexadas — o tempo de resposta **não cresce** com o
aprendizado:

| Camada | Onde | Busca |
|---|---|---|
| Episódica | `data/yvakor_memory.db` | FTS5 nas conversas (bm25) |
| Semântica | `data/semantic/facts.db` | FTS5 + dedup por hash |
| Procedural | `data/skills.db` (fonte: `skills_library/`) | FTS5 incremental |
| Cérebro | `data/vault/` + `data/cerebro.db` | FTS5 + grafo de wikilinks |

- **Vault Obsidian:** abra `data/vault` no Obsidian — `Home.md`, `Identidade`,
  `Memoria/`, `Skills/`, `Conversas/`, com front-matter, tags e `[[wikilinks]]`.
- **Ferramentas:** `cerebro_buscar`, `cerebro_nota`, `cerebro_grafo`,
  `cerebro_escrever`, `cerebro_sincronizar`.
- **Números:** histórico em 0,07 ms, lista em 0,03 ms, busca em 1,8 ms
  (5.500 registros) e 4,5 ms com 22 mil episódios.
- **Manutenção automática:** poda de logs operacionais, `ANALYZE`, `optimize`
  do FTS e `VACUUM` incremental a cada ciclo.
- Detalhes: [`docs/MEMORIA.md`](docs/MEMORIA.md).

---

## Segurança

- **Confirmation Guard**: ações destrutivas ou de envio externo exigem popup de
  confirmação no navegador (modo servidor) ou `sim/não` no terminal (CLI).
- **Auto-approve configurável**: ações de trabalho aprovadas automaticamente;
  envio externo (e-mail, WhatsApp) e comandos shell sempre confirmam.
- **Navegador isolado**: perfil próprio em `data/browser_profile/` — o agente
  nunca mexe no seu Edge/Chrome do dia a dia.
- **Credenciais**: chaves só no `.env`; senhas digitadas ficam no perfil local
  do navegador (nunca em logs do YVAKOR).
- **Sem burlar proteções**: CAPTCHA/2FA são tratados como intervenção humana.

---

## Testes

Rodam offline (sem API, sem internet — exceto o que já está em cache):

```bash
python tests/test_smoke.py          # estrutura + config
python tests/test_browser.py        # Playwright: snapshot, refs, clique, abas
python tests/test_agent_browser.py  # loop do agente dirigindo o navegador
python tests/test_cowork.py         # fila, cancelamento, persistência
python tests/test_rede.py           # escopo, registro, ONVIF, WoL, HTTP
python tests/test_voz.py            # TTS → WAV → Vosk (ponta a ponta)
python tests/test_memoria.py        # índices/FTS, 5.500 registros, cérebro/vault
```

---

## Stack

Python 3.11+ | SQLite | ChromaDB (opcional) | DeepSeek V4 API | Ollama (opcional)
Playwright (Edge/Chrome) | Vosk (STT) | edge-tts/SAPI (TTS) | ffmpeg |
pychromecast | paho-mqtt | zeroconf | Three.js | stdlib-first

---

## Licença

© 2026 Antonio José Cordero Martinez / ACM Digital. Todos os direitos reservados.
Ver arquivo `LICENSE`.
