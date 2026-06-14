# YVAKOR v0.2 — Agente Pessoal Evolutivo

> **YVAKOR** — do tupi *ybaka* (céu) + *kor* (núcleo): "o núcleo do céu".
> Agente de IA autônomo que **executa tarefas reais no computador**, aprende
> com cada interação e acumula independência progressiva de IA externa.
>
> © 2026 Antonio José Cordero Martinez — ACM Digital, Manaus-AM.
> Todos os direitos reservados.

---

## O que ele faz

| Capacidade | Como |
|---|---|
| **Executa código e comandos** | Python, shell, PowerShell no seu PC |
| **Lê, cria e edita arquivos** | Acesso real ao sistema de arquivos |
| **Gera imagens** | Higgsfield (GPT Image 2) + Perchance (gratuito, sem login) |
| **Pesquisa na web** | HTTP GET com extração de conteúdo |
| **Tarefas em segundo plano** | Cowork: dispara e acompanha múltiplas tarefas |
| **Múltiplas conversas** | Cria, alterna, renomeia e apaga conversas |
| **Auto-aprendizado** | Absorve padrões, cria skills, consolida memória |
| **Progresso ao vivo** | Mostra cada passo no terminal enquanto trabalha |
| **Interface 3D** | Servidor web com visualização Three.js em `localhost:7777` |
| **Valida documentos** | CPF e CNPJ com dígitos verificadores |

---

## Instalação

```bash
git clone https://github.com/mastertrojan0-cloud/yvakor.git
cd yvakor
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
cp .env.example .env        # insira sua DEEPSEEK_API_KEY

# (Opcional) Geração de imagens via Higgsfield:
npm i -g @higgsfield/cli
higgsfield auth login
```

## Uso

```bash
python -m yvakor.main        # Terminal interativo
python -m yvakor.server      # Interface 3D → http://localhost:7777
python -m yvakor.learning.bootstrap  # Auto-aprendizado em lote
```

### Comandos no chat

```
[cowork] gerar relatorio de seguranca       → tarefa em segundo plano
[cowork-status]                             → status das tarefas
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

---

## Arquitetura

```
yvakor/
├── identity/               # Personalidade do agente (editável por chat)
│   ├── core_identity.md    # Quem ele é, tom, postura, limites
│   └── principles.md       # Comportamentos herdados das melhores IAs
├── config/settings.yaml    # Modelos, roteamento, ferramentas, cowork
├── prompts/                # Templates de extração/destilação/avaliação
├── skills_library/         # Memória procedural (skills em markdown)
├── data/                   # SQLite, ChromaDB, sandbox, downloads
├── interface/
│   └── index.html          # Visualização 3D (Three.js, Encontro das Águas)
├── yvakor/
│   ├── main.py             # CLI
│   ├── server.py           # Servidor HTTP (API REST + interface 3D)
│   ├── orchestrator.py     # Cérebro: contexto, dispatch, reflexão, confirmação
│   ├── agent.py            # Loop ReAct: IA decide → ferramenta → observa → responde
│   ├── cowork.py           # Tarefas autônomas em segundo plano (threads)
│   ├── maintenance.py      # Auto-manutenção programada
│   ├── llm/
│   │   ├── adapter.py      # Provider OpenAI-compatible (DeepSeek, Ollama)
│   │   └── router.py       # Classifica tarefa → escolhe provider → fallback
│   ├── memory/
│   │   ├── episodic.py     # SQLite: sessões, conversas, ferramentas
│   │   ├── semantic.py     # Vetorial (ChromaDB) + keyword search
│   │   └── procedural.py   # Biblioteca de skills em markdown
│   ├── tools/
│   │   ├── registry.py     # Registro + manifesto para o agente
│   │   ├── builtin.py      # 14 ferramentas nativas (arquivos, shell, imagem, web)
│   │   └── guard.py        # Confirmação de ações perigosas (auto-approve + popup)
│   ├── connectors/         # Integrações: Google, GitHub, e-mail, WhatsApp
│   ├── reflection/         # Autoavaliação pós-tarefa + criação de skills
│   └── learning/           # Absorção de conhecimento + bootstrap
└── tests/test_smoke.py     # Teste de integridade offline
```

---

## Loop de Agente (Claude Code-like)

O YVAKOR não é um chatbot passivo. Ele usa um **loop ReAct**:

```
Usuário pede →
  IA decide: usar ferramenta?
    SIM → {"acao":"usar_ferramenta","ferramenta":"...","args":{...}}
         → executa → recebe OBSERVAÇÃO → decide próximo passo
    NÃO → responde em texto (markdown, português)
```

Cada passo aparece no terminal em tempo real. O modelo encadeia ferramentas
autonomamente até concluir a tarefa.

---

## Segurança

- **Confirmation Guard**: ações destrutivas ou de envio externo exigem popup de
  confirmação no navegador (modo servidor) ou `sim/não` no terminal (CLI)
- **Auto-approve configurável**: ações de trabalho aprovadas automaticamente;
  envio externo (e-mail, WhatsApp) e comandos shell sempre confirmam
- Sandbox isolado para execução de código (`data/sandbox/`)
- Chaves de API apenas em `.env` — nunca em código, logs ou commits

---

## Independência progressiva de IA externa

| Fase | Estratégia |
|---|---|
| 1 | DeepSeek V4 para tudo (qualidade, baixo custo) |
| 2 | Router: tarefas simples → Ollama local; complexas → DeepSeek |
| 3 | Skills acumuladas reduzem dependência de API externa |
| 4 | Fine-tuning de modelo local com logs de tarefas bem-sucedidas |

---

## Stack

Python 3.11+ | SQLite | ChromaDB (opcional) | DeepSeek V4 API | Ollama (opcional)
Higgsfield CLI | Perchance.org | Three.js | stdlib-first (pyyaml único hard dep)

---

## Licença

© 2026 Antonio José Cordero Martinez / ACM Digital. Todos os direitos reservados.
Ver arquivo `LICENSE`.
