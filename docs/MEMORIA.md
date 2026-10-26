# YVAKOR — Memória escalável + cérebro Obsidian

O agente aprende a cada conversa. Sem desenho, isso vira uma bola de neve:
histórico faz varredura completa, fatos são relidos em arquivo, skills são
reabertas a cada mensagem. Esta versão resolve isso em quatro camadas.

---

## 1. Arquitetura da memória

| Camada | Arquivo | Para que serve | Índice |
|---|---|---|---|
| Episódica | `data/yvakor_memory.db` | conversas, ferramentas, sessões | B-tree + **FTS5** |
| Semântica | `data/semantic/facts.db` | fatos sobre você/clientes/projetos | hash único + **FTS5** |
| Procedural | `data/skills.db` | skills markdown (fonte: `skills_library/`) | **FTS5** incremental |
| Cérebro | `data/cerebro.db` + `data/vault/` | vault markdown estilo Obsidian | **FTS5** + grafo de links |

Cada banco usa os mesmos PRAGMAs de produção: WAL, `synchronous=NORMAL`,
`busy_timeout`, cache de 16 MB, mmap de 64 MB.

---

## 2. O que mudou no episódico

**Antes:** sem índice; cada consulta de sessão varria a tabela inteira
(`SCAN e`) e a lateral fazia 3 subqueries por conversa.

**Agora:**

```sql
-- consultas quentes passam a usar índice
CREATE INDEX idx_ep_session_kind ON episodes(session_id, kind, id DESC);
CREATE INDEX idx_ep_kind_id      ON episodes(kind, id DESC);
CREATE INDEX idx_usage_skill     ON skill_usage(skill, success);

-- contadores denormalizados: a lista de conversas não calcula nada
ALTER TABLE sessions ADD COLUMN last_at TEXT, last_preview TEXT, msg_count INTEGER;
```

- **Busca nas conversas:** `buscar("camera intelbras")` usa FTS5 (bm25) e
  devolve trecho destacado (`[camera]`), em vez de `LIKE %...%`.
- **Podação:** logs operacionais (`ferramenta`, `manutencao`, `bootstrap`) com
  mais de 30 dias ou acima de 20 mil registros são removidos; conversas e erros
  ficam. Depois roda `ANALYZE`, `optimize` do FTS e `VACUUM` incremental.
- **Backup:** `episodic.backup(caminho)` usa a API de backup do SQLite
  (consistente mesmo com o banco aberto).

## 3. Semântico e procedural

- Fatos agora têm **hash normalizado único**: repetir a mesma informação não
  cria linha nova. Busca por plural/acento funciona (`relatorio` acha
  `relatórios`) porque palavras longas viram prefixo no FTS.
- `facts.jsonl` é **importado uma vez** e continua disponível como exportação
  (`exportar_jsonl`) para portabilidade/fine-tuning.
- Skills continuam sendo arquivos `.md` (editáveis à mão); um índice
  incremental por `mtime`/`hash` evita reler os 28+ arquivos a cada mensagem.

---

## 4. Cérebro Obsidian (`data/vault/`)

Abra a pasta `data/vault` no Obsidian (File → Open folder as vault). Estrutura:

```
vault/
  Home.md                     mapa de conteúdo (hub)
  Identidade.md               identidade + princípios
  Memoria/<hash>.md           um fato por nota (Zettelkasten)
  Skills/<nome>.md            procedimentos aprendidos
  Conversas/<data>-<slug>.md  resumo + últimas 20 mensagens
```

Cada nota tem front-matter (`titulo`, `tipo`, `tags`, `id`, `atualizado`) e
links `[[Home]]` — o grafo do Obsidian mostra o mapa do conhecimento. Notas
manuais com `[[wikilinks]]` entram no índice e viram backlinks.

O vault é a **fonte legível**; o `cerebro.db` é só o índice rápido. A
sincronização é incremental: reescreve apenas o que mudou (nenhum I/O à toa).

### Ferramentas do agente

| Ferramenta | O que faz |
|---|---|
| `cerebro_buscar(termo)` | busca FTS no vault, com trecho |
| `cerebro_nota(nome)` | lê a nota + backlinks |
| `cerebro_grafo(nome?, profundidade?)` | grafo de ligações |
| `cerebro_escrever(titulo, corpo, tags)` | cria/anexa nota |
| `cerebro_sincronizar()` | exporta memória/skills/conversas e reindexa |
| `cerebro_status()` | notas, links, tipos, tamanho |

### API

```
GET  /api/cerebro                 → status
GET  /api/cerebro/buscar?q=...    → resultados com trecho
GET  /api/cerebro/nota?nome=Home  → nota + backlinks
GET  /api/cerebro/grafo?nome=&profundidade=2
POST /api/cerebro/sincronizar
```

---

## 5. Números medidos (nesta máquina)

| Cenário | Antes | Depois |
|---|---|---|
| Listar conversas (100×) | 3 subqueries por sessão | **0,03 ms** por chamada |
| Histórico de 10 turnos | varredura por sessão | **0,07 ms** por chamada |
| Busca no conteúdo | `LIKE` linear | **1,8 ms** (FTS5) |
| Inserção | commit por registro | **5.500 registros em 0,5 s** |
| 22 mil episódios | — | **4,6 MB** · busca **4,5 ms** |

O tempo de resposta não cresce com o aprendizado: cresce com `log(n)` no
histórico e o FTS mantém a busca em poucos milissegundos até dezenas de
milhares de registros.

---

## 6. Manutenção

Automática (settings → `maintenance`), a cada 12 h:

1. poda logs operacionais antigos;
2. `ANALYZE` (no máximo 1×/semana) + `optimize` do FTS + `VACUUM` incremental;
3. consolida fatos com a IA (se `consolidate_memory: true`);
4. sincroniza o vault (exporta + reindexa).

Manual: `[manutencao]` no chat, ou `POST /api/cerebro/sincronizar` para o vault.

Configuração nova:

```yaml
cerebro:
  habilitado: true
  vault_dir: "data/vault"
  exportar_conversas: true
  max_conversas: 50
  max_memorias: 300
```

---

## 7. Migração e compatibilidade

- Bancos antigos são migrados **na abertura**: colunas novas, índices, FTS e
  backfill de contadores. Nada é apagado.
- `facts.jsonl` é importado uma única vez (flag em `meta`).
- A API pública (`log`, `history_messages`, `listar_conversas`, `search`,
  `find_relevant`, `save`…) continua igual — o resto do agente não mudou.

## 8. Problemas comuns

| Sintoma | Solução |
|---|---|
| Vault não aparece no Obsidian | abra a pasta `data/vault` como vault |
| Nota não encontrada na busca | rode `cerebro_sincronizar` (ou `[manutencao]`) |
| Banco crescendo | reduza `max_operacionais`/`reter_operacionais_dias` e rode manutenção |
| FTS ausente (`fts: false`) | SQLite sem FTS5; o sistema cai para `LIKE` e índice simples |
