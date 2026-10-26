# YVAKOR — Levantamento técnico e evolução para v0.4

> Data: 2026-10-22 · Escopo: auditoria do código existente (v0.2) + implementação
> da próxima evolução (controle do navegador e tarefas autônomas estilo Cowork).

---

## 1. Fotografia do projeto encontrado

**O que é:** agente pessoal em Python, "stdlib-first", que conversa, executa
ferramentas reais no PC e acumula memória/skills. Roda em CLI (`yvakor.main`)
e em servidor web com interface 3D (`yvakor.server`, porta 7777).

**Ambiente:**

| Item | Valor |
|---|---|
| Python do venv | 3.14.5 |
| Dependências instaladas | apenas `PyYAML 6.0.3` (mais `pip`) |
| Navegador disponível | Microsoft Edge 155 (via Playwright, após esta evolução) |
| Git | repositório limpo, branch `main`, 1 commit (v0.2) |
| Chave LLM | `DEEPSEEK_API_KEY` presente no `.env`, mas **rejeitada (401)** pela API |

**Componentes e responsabilidades:**

| Arquivo | Papel | Observação |
|---|---|---|
| `orchestrator.py` | Cérebro: contexto, comandos `[...]`, progresso, confirmação | já tinha `ConfirmationBroker` |
| `agent.py` | Loop ReAct com protocolo JSON próprio | 8 iterações máx. |
| `tools/registry.py` | Registro + manifesto + guard | embrulhava resultado 2x |
| `tools/builtin.py` | 15 ferramentas (arquivos, shell, imagem, web) | `http_get` sem JS |
| `cowork.py` | Tarefas em threads | só em memória |
| `server.py` | API REST + HTML | `ThreadingHTTPServer`, sem shutdown limpo |
| `memory/episodic.py` | SQLite: sessões/conversas | sessão ativa global |
| `llm/adapter.py` | Cliente OpenAI-compatible | urllib puro |
| `interface/index.html` | UI Three.js + chat | sem painel de tarefas/navegador |
| `connectors/` | Google/GitHub/e-mail/WhatsApp | injeta ferramentas no registry |

**Fluxo atual:** mensagem → comandos especiais? → monta system prompt
(identidade + princípios + skills + memórias) → classifica tarefa → loop do
agente (JSON tool call) → grava episódio → reflexão/absorção.

---

## 2. Diagnóstico: o que faltava para "controlar o navegador e fazer tarefas

Cada lacuna abaixo foi confirmada no código, não inferida:

1. **Nenhuma dependência de navegador.** `requirements.txt` listava
   `playwright` apenas como comentário "futuras ferramentas". `http_get` baixa
   o HTML cru: não executa JavaScript, não mantém cookies, não clica.
2. **Nada de ferramentas web interativas.** O manifesto tinha 15 ferramentas,
   nenhuma de navegação — o agente não conseguia nem abrir uma página.
3. **Cowork frágil.** `CoworkManager` guardava tudo em `dict` na memória:
   reiniciou, perdeu. Sem cancelamento, sem passos, sem resultado persistido,
   sem diretório de trabalho.
4. **Cowork contaminava o chat.** As tarefas rodavam no mesmo `process()` e na
   mesma sessão ativa: histórico intercalado, progresso sobrescrito, título da
   conversa trocado por tarefa de fundo, e `process()` não aceitava sessão.
5. **Limite de passos baixo.** `agent.max_iterations: 8` serve para conversa,
   mas navegar gasta 3–6 passos só para chegar ao alvo.
6. **Contrato de ferramenta inconsistente.** `registry.run` devolvia
   `{"ok": true, "result": {"ok": false, "erro": ...}}`: falha aninhada que o
   CLI/observação não detectava e que inflava o JSON enviado ao modelo.
7. **Servidor não tolerava cliente Windows.** Corpo em cp1252 (comum em
   PowerShell/curl) derrubava a requisição com erro 500 de decodificação UTF-8.
8. **Sem encerramento limpo.** `Ctrl+C` deixava navegador/threads pendurados;
   tarefas "executando" ficavam assim para sempre no próximo boot.
9. **UI sem observabilidade.** Não havia como ver o navegador nem acompanhar
   uma tarefa cowork — só texto no chat (`[cowork-status]`).

---

## 3. Decisões de arquitetura da v0.4

### 3.1 Playwright em thread dedicada

A API síncrona do Playwright é presa à thread que a criou, e o YVAKOR chama
ferramentas de threads diferentes (HTTP, cowork, CLI). Solução: **uma thread
dona** com fila de comandos; todo método público (`open`, `click`, `snapshot`…)
despacha para ela e espera o resultado. Isso dá um navegador único, estável e
compartilhado por chat e tarefas.

### 3.2 Snapshot por referências, não por visão

Modelos de texto (DeepSeek) não veem pixels. Em vez de "computer use" por
coordenadas, o agente recebe:

- URL, título, rolagem, texto visível truncado;
- lista de elementos interativos **visíveis** com `ref` estável (`e1`, `e2`…),
  tipo, nome acessível, valor e estado (marcado/desabilitado).

As refs são atributos `data-yvk-ref` no DOM, reatribuídos a cada snapshot. Se a
página mudar, a ref antiga falha com mensagem clara ("chame navegador_ver") em
vez de clicar no lugar errado.

### 3.3 Perfil persistente e isolado

`data/browser_profile/` guarda cookies e logins entre execuções. É separado do
perfil pessoal do usuário — o agente nunca mexe no Edge do dia a dia — e é
ignorado pelo git.

### 3.4 Cowork: sessão isolada + SQLite + workspace

- Cada tarefa cria uma sessão `kind='task'` (não aparece na lista de conversas).
- Metadados em `data/cowork.db` (status, passos, resultado, erro, workspace).
- Workspace `data/cowork/<id>/` com `resultado.md` e artefatos.
- Fila com `max_concurrent_tasks`, cancelamento cooperativo checado **entre
  passos** do agente e recuperação de tarefas órfãs no boot.

### 3.5 Segurança mantida

Navegar/ler/clicar **não** pedem confirmação (é a tarefa em si). Escrita em
arquivo do PC, shell e Python continuam passando pelo `Confirmation Guard`;
numa tarefa cowork o popup aparece no painel de tarefas, roteado para a sessão
correta.

---

## 4. O que foi entregue

| Lacuna | Entrega | Onde |
|---|---|---|
| 1–2 | Pacote `browser/` com 16 ferramentas `navegador_*` | `yvakor/browser/{session,tools,setup}.py` |
| 2 | Prompt do agente ensina o ciclo ver→agir→ver | `agent.py` (seção CONTROLE DO NAVEGADOR) |
| 3 | Cowork 2.0 persistente, fila, passos, artefatos | `cowork.py` (reescrito) |
| 4 | `process(session_id, should_stop, extra_context)` + `episodic` por sessão | `orchestrator.py`, `memory/episodic.py` |
| 5 | `max_iterations: 25` (chat) e `cowork.max_steps: 40` | `config/settings.yaml` |
| 6 | `registry.run` achata `{"ok":...}` (sem aninhar) | `tools/registry.py` |
| 7 | Corpo aceita UTF-8 e cp1252 | `server.py` |
| 8 | `shutdown()` fecha navegador, sinaliza tarefas; recovery no boot | `server.py`, `orchestrator.py`, `cowork.py` |
| 9 | Painéis 🖥 (navegador ao vivo) e 🧩 (tarefas) + endpoints | `interface/index.html`, `server.py` |

**Novos endpoints:** `GET /api/browser`, `GET /api/browser/screenshot`,
`POST /api/browser/action`, `POST /api/cowork`, `GET /api/cowork`,
`GET /api/cowork/<id>`, `GET /api/cowork/<id>/artifacts`,
`POST /api/cowork/<id>/cancel`.

---

## 5. Validação executada

| Teste | Cobre | Resultado |
|---|---|---|
| `tests/test_smoke.py` | imports, config, memória | ✅ |
| `tests/test_browser.py` | snapshot, refs, fill, click, abas, JPEG, ref inválida | ✅ |
| `tests/test_agent_browser.py` | loop completo com LLM simulado + cancelamento | ✅ |
| `tests/test_cowork.py` | fila, concorrência, cancelar, persistência, recovery | ✅ |
| UI real (Playwright) | abrir painéis, erros de JS, frame ao vivo | ✅ sem erros de JS |
| Servidor | `/api/status`, `/api/browser/action`, screenshot, `/api/cowork` | ✅ |

**Não validado ponta a ponta com o modelo real** porque a chave do `.env` é
rejeitada pela DeepSeek:

```
HTTP 401 {"error":{"message":"Authentication Fails, Your api key: ****99b0 is
invalid","type":"authentication_error"}}
```

Trocar a chave por uma válida é o único passo que falta para o ciclo completo
com o modelo.

---

## 6. Riscos e limitações conhecidas

- **Iframes:** conteúdo dentro de `<iframe>` não entra no snapshot (aviso é
  emitido). Abrir a URL do iframe em nova aba resolve.
- **CAPTCHA/2FA:** sem solução automática por decisão de projeto; o agente para
  e pede intervenção.
- **Anti-bot:** alguns sites detectam automação. Usar janela visível e perfil
  persistente reduz o atrito, mas não elimina.
- **Um navegador por processo:** `max_concurrent_tasks > 1` faz tarefas
  dividirem o mesmo navegador/aba. Se isso incomodar, use 1 por vez ou
  evolua para um contexto por tarefa.
- **Custo de contexto:** snapshots trazem até 3.000 caracteres de texto e 120
  elementos; páginas muito longas exigem `navegador_extrair`.
- **Modelo:** sem visão, o agente depende do DOM. Sites que só funcionam por
  canvas (mapas complexos, editores gráficos) ficam fora do alcance.

---

## 7. Próximos passos sugeridos (v0.5)

1. **Trocar a chave DeepSeek** e rodar um roteiro real de aceitação
   (pesquisar → abrir → extrair → salvar) para medir passos e custo.
2. **Downloads de verdade:** `expect_download` + `navegador_baixar` para
   arquivos gerados por sites (notas fiscais, relatórios).
3. **PDF/print:** `navegador_pdf()` para transformar páginas em PDF no
   workspace da tarefa.
4. **Contexto por tarefa:** um contexto de navegador por tarefa cowork (hoje
   compartilham o mesmo), permitindo paralelismo real.
5. **Agendamento:** rodar tarefas cowork recorrentes (prospecção diária) com
   cron interno, como já previsto no ROADMAP.
6. **Visão:** quando houver modelo multimodal, anexar `navegador_captura` ao
   passo para desbloquear canvas/CAPTCHA assistido.
7. **Modelo local:** mover classificação e skills estáveis para Ollama,
   reduzindo custo por tarefa.
