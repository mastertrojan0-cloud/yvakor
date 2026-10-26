# Auditoria Técnica YVAKOR v0.8 — Outubro/2026

> Análise profunda conduzida por um time de 5 agentes especialistas, cada um
> cobrindo uma frente do código, com verificação cruzada dos achados.
> Escopo: ~24k linhas / 98 arquivos Python.
>
> **Veredito:** o YVAKOR é um projeto ambicioso e funcional, mas está num
> estado de **protótipo avançado com risco de segurança grave**. Há uma cadeia
> de falhas que, combinadas, resultam em **execução remota de código (RCE) não
> autenticada acionável por qualquer site aberto no navegador** — enquanto o
> agente autônomo pode apagar arquivos, enviar e-mails e controlar dispositivos
> da rede **sem nenhuma confirmação**. Este é o bloco que precisa ser resolvido
> antes de qualquer outra melhoria.

---

## 0. Como ler este relatório

Cada achado tem severidade: **CRÍTICO** (explorável/perda de dados agora),
**ALTO**, **MÉDIO**, **BAIXO**. Os itens marcados com 🔁 foram encontrados por
mais de um agente de forma independente — alta confiança.

---

## 1. 🔴 O bloco crítico de segurança (resolver PRIMEIRO)

As falhas abaixo **se encadeiam**. Isoladas já são sérias; juntas transformam o
YVAKOR num vetor de RCE.

### 1.1 🔁 CRÍTICO — O Confirmation Guard está efetivamente DESLIGADO de fábrica
- `yvakor/tools/guard.py:53-66` — `confirm()` faz `if self.total: return True`
  **antes** de checar a lista `always_confirm`.
- `config/settings.yaml:62` — `privilegios: "total"` é o padrão entregue.
- **Efeito:** ações que o próprio settings diz que "NUNCA são auto-aprovadas"
  (`send_email`, `enviar_whatsapp`, `delete_file`, `executar_shell`,
  `rede_mqtt_publicar`, `rede_telefone_acao`, `rede_camera_credenciais`)
  executam **sem popup**. O `ConfirmationBroker` e o popup viram código morto.
- **Correção:** avaliar `always_confirm`/ações destrutivas **antes** de `self.total`;
  mudar o default para `privilegios: "protegido"` e `auto_approve: false`.

### 1.2 🔁 CRÍTICO — Ferramentas de arquivo destrutivas nunca passam pelo guard
- `config/settings.yaml:77-87` protege nomes **mortos** (`escrever_arquivo`,
  `executar_shell`, `delete_file`...).
- Os nomes **reais** registrados em `yvakor/arquivos.py:347-392` são
  `arquivos_apagar`, `arquivos_escrever`, `arquivos_editar`, `arquivos_mover`,
  `arquivos_extrair` — **nenhum casa** com a lista. Além disso são registrados
  via `registry.register` e não `reg_guarded`.
- **Efeito:** `arquivos_apagar(permanente=True)` → `shutil.rmtree`/`unlink`
  (`arquivos.py:291-312`) roda **sem confirmação mesmo no modo "protegido"** —
  independe do bug 1.1.
- **Correção:** registrar as ferramentas reais via `reg_guarded` e alinhar os
  nomes entre `settings.yaml` e `register(...)`.

### 1.3 🔁 CRÍTICO — Servidor `localhost:7777` sem autenticação, CSRF ou validação de Content-Type
- `yvakor/server.py:856-867` — `_body()` faz `json.loads` **sem checar
  `Content-Type`**; nenhum handler exige token/sessão.
- **Efeito:** qualquer página web aberta no navegador do usuário envia
  `fetch('http://localhost:7777/api/chat', {method:'POST',
  headers:{'Content-Type':'text/plain'}, body:'{"message":"rode no shell: ..."}'})`.
  `text/plain` é "safelisted" → **sem preflight CORS** → a requisição chega e o
  agente executa. A resposta é opaca, mas **o efeito colateral acontece**.
- Combinado com 1.1 + `executar_shell` usando `subprocess.run(..., shell=True)`
  (`yvakor/tools/builtin.py:194`): **RCE não autenticado com os privilégios do
  usuário, acionável por qualquer site**.
- **Correção:** token anti-CSRF por sessão injetado no `index.html` e exigido em
  todas as rotas de efeito; rejeitar `Content-Type != application/json`.

### 1.4 CRÍTICO — Bypass do popup via `/api/confirm` usando `active_id` implícito
- `yvakor/server.py:1101-1104` e `:976` — tanto `/api/chat` quanto
  `/api/confirm` caem em `ag.episodic.active_id` quando `session` é omitido.
- **Efeito:** mesmo se o guard fosse reativado, um ataque CSRF faz
  (1) `POST /api/chat` sem `session` (cria pendência no `active_id`) e
  (2) `POST /api/confirm {"allow":true}` sem `session` → aprova a própria ação.
  Não precisa conhecer o `sid`.
- **Correção:** aprovação ligada a um `pending.id` específico + token de sessão.

### 1.5 CRÍTICO — Chrome aberto com `--remote-allow-origins=*`
- `yvakor/browser/chrome_cdp.py:75` — desliga a verificação de origem do
  WebSocket do DevTools em `127.0.0.1:9222`. O CDP dá controle total do
  navegador (cookies, sessões, JS, downloads).
- **Efeito:** com o Chrome-CDP aberto, um site malicioso abre
  `ws://127.0.0.1:9222/devtools/...` e assume o navegador (exfiltra cookies de
  banco/e-mail, age logado como o usuário).
- **Correção:** nunca `*`; usar o `webSocketDebuggerUrl` de `/json/version`
  (que embute token) ou restringir a origem mínima.

### 1.6 ALTO — CORS reflete `Origin: null` e **qualquer** `chrome-extension://`
- `yvakor/server.py:180-205` — aceita `origem == "null"` (iframes sandbox,
  `data:`/`file:`) e qualquer extensão instalada, não só a do YVAKOR.
- **Correção:** remover `"null"`; restringir ao **ID exato** da extensão.

### 1.7 ALTO — Sem validação de `Host` → DNS rebinding
- `yvakor/server.py` — bind em `127.0.0.1` é bom mas insuficiente; um
  `evil.com` com TTL curto re-resolvendo para `127.0.0.1` fala como "mesma
  origem". **Correção:** rejeitar `Host` ∉ {localhost:7777, 127.0.0.1:7777}.

### 1.8 ALTO — Extensão Chrome com permissões excessivas
- `chrome-extension/manifest.json:6-20` — `<all_urls>` + `http://*/*` +
  `https://*/*` (redundantes) + `scripting` + `tabs`; `audioCapture` declarada
  mas não usada. Comando vem do núcleo sem auth → injeta JS em qualquer aba.
- **Correção:** reduzir a `http://127.0.0.1:7777/*` + `activeTab` sob gesto;
  remover redundâncias e `audioCapture`.

### 1.9 ALTO — Servidor de mídia do Chromecast expõe a pasta inteira na LAN
- `yvakor/rede/cast.py:38-61,191-194` — para castar um arquivo, sobe
  `ThreadingHTTPServer` em `0.0.0.0` servindo a **pasta-mãe** inteira com
  directory listing ON, sem auth. Castar um vídeo em `Documents` deixa todo o
  `Documents` navegável pela LAN.
- **Correção:** servir só o arquivo pedido, token no path, bind restrito,
  parar o servidor após ativar.

### 1.10 Outros de rede (MÉDIO/ALTO)
- **IP fixo na voz** (`yvakor/voz/camera.py:65-76`): sem câmera registrada,
  "tire uma foto" mira `192.168.15.7` — pode ser aparelho de vizinho em rede
  compartilhada. Corrigir para erro falado.
- **Snapshot/janela de câmera não-guardados** (`yvakor/rede/tools.py:416-422`):
  tirar foto é vigilância e deveria confirmar; `rede_camera_janela` lança
  `C:\Program Files (x86)\Yoosee\Yoosee.exe` hard-coded.
- **SSRF via `Location`/`XAddrs`** (`descoberta.py:274-315`, `onvif.py:203-213`):
  URL vinda do dispositivo é buscada sem validar origem.
- **Segredos em claro no disco:** `DEEPSEEK_API_KEY` no `.env` (✅ nunca
  commitada — verificado), credenciais de e-mail/OAuth em
  `data/connectors.json` (`connectors/manager.py`) e de câmera/TV em
  `data/rede.json` (`rede/registro.py`), ambos texto puro. Recomendado:
  **rotacionar a chave DeepSeek** e cifrar os JSON (DPAPI/keyring).

---

## 2. 🟠 Concorrência e integridade de dados

### 2.1 🔁 CRÍTICO — Conexão SQLite única compartilhada entre threads; leituras sem lock
- `yvakor/memory/db.py:30-39` — uma conexão `check_same_thread=False` por banco,
  usada por todas as threads. Escritas usam `RLock`; a maioria das **leituras
  não pega lock** (`episodic.history_messages/last_interactions`,
  `semantic.search`, `cerebro.buscar/nota/grafo`).
- A cada resposta o orquestrador dispara threads daemon concorrentes: absorção
  (`orchestrator.py:951`), avaliação (`:955`), sync do vault (`:1066`) + a
  thread de manutenção (`maintenance.py:172-183`) rodando `podar`/`otimizar`
  (`wal_checkpoint`, `incremental_vacuum`).
- **Efeito observável:** `sqlite3.ProgrammingError: Recursive use of cursors`,
  `OperationalError: database is locked`, rollback cruzado (exceção numa thread
  reverte gravação de outra), histórico truncado/errado.
- **Correção estrutural:** conexão **por thread** via `threading.local()` e
  confiar no WAL para leitura concorrente. Mínimo imediato: envolver todas as
  leituras no mesmo `RLock`.

### 2.2 🔁 CRÍTICO — Orchestrator e AgentLoop são instâncias únicas compartilhadas entre chat e cowork
- O cowork roda `self._orch.process()` em até 3 threads (`cowork.py:270`) junto
  com o chat, na **mesma instância**. Estado mutável vaza entre execuções:
  - `agent.py:368` `self.artefatos=[]` + `_coletar` → entregáveis vazam entre
    tarefas; `ultimos_artefatos` errado.
  - `orchestrator.py:683` `self._msg_atual` lido pelos wrappers → a thread A
    roteia com a mensagem da thread B.
  - `orchestrator.py:685` `_ponte.permitir_outro` (flag global) → cross-talk.
  - `agent.py:281/293` `self.ultima_selecao` compartilhada.
- **Correção:** estado por-requisição em `threading.local` / retorno por valor /
  um `AgentLoop` por execução.

### 2.3 CRÍTICO — Cancelamento e shutdown não funcionam para tarefas cowork retomadas
- `cowork.py:379` — `self._events` só é populado em `submit()`; `retomar()` e
  `_retomar_interrompidas()` não recriam a entrada (e `_events` é volátil).
- **Efeito:** supervisor reinicia → cowork auto-retoma → usuário cancela → UI
  diz "cancelando" mas a tarefa **roda até o fim**; `shutdown()` não a sinaliza.
- **Correção:** `setdefault` do `Event` em `retomar`/`_retomar_interrompidas`/
  `_run`, sob lock.

### 2.4 ALTO — Checkpoint de cowork grosso → efeitos colaterais duplicados na retomada
- `cowork.py:425-469` — `concluidas` só persiste ao fim de cada etapa. Crash no
  meio de uma etapa com efeito (e-mail enviado, arquivo salvo) → a retomada
  **re-executa a etapa inteira** (não idempotente). Com 1.1 (envio sem
  confirmação), risco de duplicação externa real.
- **Correção:** checkpoint por passo; persistir antes de ações externas;
  idempotência.

### 2.5 ALTO — `backup()` da memória sem lock durante escritas concorrentes
- `memory/episodic.py:493-502` — `self.conn.backup()` na conexão compartilhada
  sem `_lock`; pode gerar cópia inconsistente ou exceção.

---

## 3. 🟡 Qualidade do aprendizado (degradação auto-reforçante)

### 3.1 ALTO — O agente aprende "fatos" das próprias respostas e os serve como verdade sem IA
- `learning/absorber.py:48-63` — `absorb_facts` roda após **toda** resposta e
  grava `semantic.store(f)` com confiança 0.8.
- `cerebro/resolvedor.py:214-225` — extrai frase da conversa e persiste como
  fato; no turno seguinte `decidir` responde direto, rotulando "fonte de
  verdade" (`:250-252`), sem consultar a IA.
- **Efeito:** um chute do modelo ("câmera X usa porta 554, user admin") vira
  fato permanente e "oficial". O único freio (`_contraditorio`) só pega
  contradição numérica com Jaccard ≥ 0.8.
- **Correção:** fatos auto-gerados com confiança baixa (`<0.6` → `revisar=1`) e
  **nunca** promovidos a resposta direta "cerebro"; registrar e filtrar `fonte`.

### 3.2 ALTO — A avaliação 1-5 é "write-only" (feedback loop quebrado)
- `orchestrator.py:954-957,1027-1042` — a nota só é gravada em
  `data/avaliacoes.jsonl`. A absorção/destilação (`absorber.after_response`)
  **nunca lê a nota** — baseia-se só na autoavaliação do modelo. Uma resposta
  1/5 tem seus fatos/skills absorvidos igual a uma 5/5.
- **Resposta direta:** hoje a nota 1-5 **não influencia nada** no comportamento.
- **Correção:** só absorver/destilar quando `nota >= 4`; unificar as duas
  passagens pós-resposta (hoje são 2 chamadas LLM concorrentes redundantes).

### 3.3 ALTO — Skills auto-destiladas entram no contexto sem gating de estabilidade
- `learning/absorber.py:68-88` + `memory/procedural.py:142-169` — `find_relevant`
  injeta o conteúdo de **qualquer** skill por BM25, sem filtrar status. O gating
  "nova → estável após N usos" descrito em `reflection/loop.py:8-10` **não
  existe no uso**. Skill ruim é injetada e enviesa respostas futuras, que são
  reabsorvidas → degradação composta.
- **Correção:** persistir `status` e só injetar skills estáveis/aprovadas
  (há `skill_success_count` em `episodic.py` mas não é usado para gating).

---

## 4. 🟡 Escalabilidade ("escala sem desacelerar" não se sustenta)

- **ALTO — `semantic._contraditorio` é O(N) por gravação, dentro do lock**
  (`semantic.py:125-147`): cada fato novo carrega **todos** os fatos e compara
  em Python, segurando o lock de escrita. Com 10k fatos, cada `store` trava a
  memória por segundos. → Pré-filtrar candidatos por FTS5; mover cálculo para
  fora da transação; índice em `obsoleto`.
- **MÉDIO — vault relê e re-hasheia TODOS os `.md` a cada ~2 min**
  (`cerebro/vault.py:277-305`): o docstring promete reindexar só o que mudou,
  mas lê e hasheia tudo. → Comparar `mtime` (coluna já existe), como em
  `procedural.py:98-110`.
- **MÉDIO — N+1 de queries por mensagem no resolvedor**
  (`resolvedor.py:185-210,102-109,253-259`): `buscar` + `nota()` por resultado,
  dezenas de queries na thread principal. → JOIN para trazer conteúdo no
  `buscar`; cachear `nota()`.

---

## 5. 🟡 Robustez e bugs de correção

- **ALTO — RTSP: laço infinito quando a câmera fecha a conexão**
  (`rede/rtsp.py:49-52`): `while len(corpo) < tamanho: corpo += sock.recv(...)`
  — `recv` devolve `b""` no fim, laço nunca cresce → 100% CPU.
  → `if not bloco: raise`.
- **ALTO — Uma operação travada congela o motor de navegador inteiro**
  (`browser/session.py:121-153`): worker único por motor; `_call` dá timeout ao
  chamador mas o worker fica preso no item (ex.: `page.goto` que ignora
  timeout); todos os comandos seguintes enfileiram para sempre.
  → Reciclar worker/contexto no timeout.
- **ALTO — `tv.volume()` repareia a TV LG a cada degrau** (`rede/tv.py:217-229`):
  0→100 = 100 handshakes websocket sequenciais (minutos). → Reutilizar a ws /
  usar `setVolume` absoluto.
- **ALTO — Typo `self._profile_dir` quebra o login do Google**
  (`browser/session.py:811`): o atributo é `self.profile_dir`; no caminho de
  **sucesso** levanta `AttributeError` → a ferramenta retorna erro apesar do
  login ter funcionado.
- **ALTO — Contexto do loop cresce sem limite → estoura a janela do modelo**
  (`agent.py:415-430`): acrescenta resposta bruta a cada passo sem truncar; em
  tarefas longas → HTTP 400 → fallback para `ollama qwen2.5:3b`
  (`max_tokens 512`) → resposta inútil, tarefa "concluída" com lixo (**falha
  silenciosa**). → Janela deslizante/sumarização por orçamento de tokens.
- **ALTO — Exceções engolidas mascaram falhas** (`agent.py:376-381` `except:
  pass`; 6 detectores de intenção no orchestrator): erro no loop nativo é
  descartado e cai no loop JSON reiniciando do zero (re-executa ferramentas com
  efeito colateral). → Logar; não cair para JSON após efeito colateral.
- **MÉDIO** — `login_google` bloqueia o motor por até 240 s (busy-wait no
  worker); `_run_nativo` sem timeout de parede (`agent.py:444-481`); sem
  retry/backoff a 429/500 no `llm/router.py` (cai direto no fallback 3B);
  `adapter.py:46` quebra com `KeyError` se a API devolver `{"error":...}` com
  200; estado de abas inconsistente após `close_tab`
  (`browser/session.py:1053-1066`); conexão CDP nunca liberada em
  `_close_browser`; ffmpeg chamado sem `shutil.which` em vários pontos
  (`rtsp.py:220`, `server.py:268`, `cast`); zip-slip verificado **depois** de
  extrair (`arquivos.py:327-339`); download do modelo Vosk silencioso sem
  checksum nem proteção zip-slip (`voz/stt.py:77`).
- **MÉDIO — Verificação de cowork é no-op silencioso** (`cowork.py:330-346`):
  `_verificar`/`_planejar` retornam `{"ok":True}` em qualquer exceção → tarefa
  "verificada" sem ter sido.

**Pontos bons confirmados (preservar):** degradação graciosa sem
Playwright/Ollama/VLC; `allow_public:false` com `EscopoRede` barrando fora da
LAN; mascaramento de credenciais RTSP em logs; não-adivinhação de senha de
câmera; FTS5 com binding parametrizado (injeção **não** explorável); serviço de
arquivos do servidor com `resolve()`+`relative_to` (sem traversal); fila única
de TTS com barge-in; snapshots antes de escrever/apagar arquivos.

---

## 6. 🔵 Arquitetura e processo

- **Arquivos-monólito:** `desktop.py` 162 KB (GUI Tkinter inteira numa classe
  `App` de ~2300 linhas/129 métodos), `server.py` 70 KB, `orchestrator.py`
  54 KB. Baixa coesão → difícil testar e manter.
  → Decompor `desktop.py` em `interface/` (`net.py`, `widgets.py`,
  `chat_view.py`, `cameras.py`, `telas/`, `app.py` como shell).
  → `orchestrator.process()` (`:663-974`) deveria ser pipeline de handlers.
- **Monkeypatch de ferramentas em runtime** (`orchestrator.py:310-408`
  `_usar_extensao_como_alvo`): re-registra wrappers sobre `navegador_*`/
  `executar_shell` via closures — frágil e difícil de testar.
- **Sem sandbox no caminho perigoso:** `executar_shell` usa `shell=True` sem
  isolamento; só `cap_executar_codigo` (`capacidades.py:379-415`) usa `-I -S -B`,
  `PATH=""` e Job Object. Trazer esse rigor para `executar_shell`.
- **ALTO — Controle de versão:** o repositório tem **1 único commit (v0.2, de
  junho/2026)** com o código em **v0.8** — **111 arquivos modificados/não
  rastreados** não commitados. Toda a evolução v0.3→v0.8 existe só na árvore de
  trabalho; perda de disco = perda de meses. → Commitar em checkpoints lógicos.
- **ALTO — Testes e CI:** ~35 testes, em grande parte smoke/mock.
  `server.py`, `tools/guard.py`, `orchestrator.py`, `desktop.py`,
  `connectors/*`, `executar_shell` — **nenhum teste**. Sem `.github/workflows`.
  → Testes de guard (ação destrutiva deve confirmar mesmo em `total`), de
  servidor (rejeição sem token/Content-Type/Host) e CI com `pytest` + lint.
- **MÉDIO — Empacotamento:**
  - `scripts/build_release.py:32-33` empacota o `settings.yaml` **inseguro**
    (`privilegios: total`) → toda instalação nasce vulnerável.
  - Deps sem teto de versão (`>=` em tudo); `pyproject.toml` não lista
    `matplotlib`/`requests`/`tradingview-ta` que os scripts usam →
    `pip install .` deixa scripts quebrados.
  - `INICIAR.bat:43-44` faz `pip install --upgrade` a cada boot, sem lockfile.

---

## 7. Plano de ação priorizado

**Fase 0 — Segurança (bloqueante, antes de distribuir qualquer release)**
1. `guard.py`: checar `always_confirm`/ações destrutivas **antes** de `self.total`.
2. Alinhar nomes de `arquivos_*` com o guard (registrar via `reg_guarded`).
3. Mudar defaults: `privilegios: protegido`, `auto_approve: false`; empacotar
   settings endurecido no release.
4. Token anti-CSRF + validação de `Content-Type`/`Host`/`Origin` em todas as
   rotas de efeito; corrigir `/api/confirm` (id de pendência + token).
5. Remover `--remote-allow-origins=*`; remover `"null"` e `chrome-extension://*`
   genérico do CORS; reduzir permissões do manifest.
6. `cast.ServidorMidia`: servir só o arquivo pedido com token/bind restrito.
7. Rotacionar `DEEPSEEK_API_KEY`; cifrar `connectors.json`/`rede.json`.

**Fase 1 — Integridade e estabilidade**
8. Conexão SQLite por thread (`threading.local`).
9. Estado por-requisição fora das instâncias únicas (artefatos, msg_atual, etc.).
10. Consertar cancelamento/shutdown de cowork retomado; checkpoint por passo.
11. Janela deslizante de contexto; parar de engolir exceções do loop.
12. RTSP `recv()==b""`; reciclar worker de navegador no timeout; typo
    `profile_dir`; `tv.volume` reutilizar ws.

**Fase 2 — Qualidade do aprendizado**
13. Conectar a nota 1-5 ao gating de absorção/destilação.
14. Não servir fato auto-gerado como verdade; gating de estabilidade de skills.

**Fase 3 — Escala, arquitetura e processo**
15. `_contraditorio` por candidatos FTS5; vault por `mtime`; resolver N+1.
16. Decompor `desktop.py`/`orchestrator.py`; sandbox em `executar_shell`.
17. Commits em checkpoints; testes de guard/server + CI; pin de deps e
    sincronizar `pyproject` ↔ `requirements`.
