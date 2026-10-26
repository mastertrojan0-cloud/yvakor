# YVAKOR — visão de produto

## Proposta

YVAKOR é um **agente pessoal autônomo** que roda no computador do usuário e
executa tarefas reais: navega no Chrome, controla câmeras e dispositivos da
rede, lê documentos, pesquisa com citações, agenda tarefas, fala e aprende.

Diferenciais:

- **local-first**: dados, memória e perfis ficam na máquina;
- **navegador real**: Chrome via CDP com perfil persistente, sem automação
  detectável por flags;
- **extensível**: MCP, skills, ferramentas e conectores;
- **auditável**: histórico SQLite, avaliações de qualidade e logs;
- **duas superfícies**: app desktop nativo e extensão do Chrome.

## Público

1. Profissionais que querem um assistente executivo no PC.
2. Pequenas empresas que precisam de automação local sem nuvem obrigatória.
3. Usuários técnicos que querem um agente extensível (MCP/Python).

## Edições sugeridas

| Edição | Conteúdo |
|---|---|
| **Personal** | app desktop, extensão, memória local, agenda, pesquisa |
| **Pro** | múltiplos perfis, políticas por ferramenta, backup, suporte |
| **Enterprise** | instalador assinado, SSO, auditoria, MCP gerenciado |

## Empacotamento

- `scripts/build_release.py` gera `dist/YVAKOR-<versão>.zip` + SHA-256.
- `scripts/doctor.py` valida a instalação (14 checagens).
- `installer/` (próximo passo): MSIX/Inno Setup com assinatura de código.

## Requisitos comerciais ainda pendentes

- assinatura digital do executável/instalador;
- política de privacidade e termos de uso revisados juridicamente;
- telemetria **opt-in** e anonimizada;
- atualização automática assinada;
- suporte e SLA;
- testes em Windows 10/11 e diferentes escalas de DPI;
- avaliação de segurança (segredos, permissões, prompt injection).

## Métricas de produto

- tempo até primeira tarefa concluída;
- taxa de sucesso por ferramenta;
- nota média de qualidade (1–5);
- custo médio por tarefa;
- retenção semanal e tarefas agendadas ativas.

## Roadmap

1. Visão semântica multimodal (foto/cena).
2. DAG de subagentes com ferramentas isoladas.
3. Instalador assinado + auto-update.
4. Painel de administração e perfis.
5. Marketplace de skills/MCP.
