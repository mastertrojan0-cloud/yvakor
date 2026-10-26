<!-- skill: abrir-site-navegador | tags: navegador, automação, gui, youtube | status: nova -->
# Abrir um site no navegador do computador

## Quando usar
Use quando o usuário pedir para abrir um site específico (ex: "abre o YouTube", "abre o Gmail") no navegador do computador, sem pedir pesquisa ou conteúdo específico.

## Pré-requisitos
- Navegador instalado no computador (ex: Edge, Chrome, Firefox)
- Acesso à área de trabalho / sessão gráfica ativa
- URL do site a abrir (ex: `https://www.youtube.com`)

## Procedimento
1. Identifique a URL do site pedido. Se o usuário citar só o nome, use o domínio principal (ex: "YouTube" → `https://www.youtube.com`).
2. Abra o navegador padrão com a URL:
   - Windows (Edge): `start msedge "{url}"`
   - Windows (Chrome): `start chrome "{url}"`
   - Linux: `xdg-open "{url}"`
   - macOS: `open "{url}"`
3. Aguarde o carregamento da página (2–5 segundos).
4. Verifique se a página carregou: confira o título da janela/aba (deve corresponder ao site, ex: "YouTube").
5. Confirme ao usuário que o site está aberto e ofereça próximos passos (ex: pesquisar vídeo/canal).

## Erros conhecidos e soluções
| Erro | Solução |
|------|---------|
| Navegador não abre | Verifique se o executável existe; tente o navegador padrão do sistema (`start "" "{url}"` no Windows) |
| Página em branco / não carrega | Verifique conexão de internet; recarregue com F5 |
| Título da aba diferente do esperado | Pode ser redirecionamento; aguarde mais alguns segundos e reconfira |
| Múltiplas abas abertas | Feche abas antigas ou use janela nova (`--new-window`) |

## Exemplo real (da tarefa que originou esta skill)
**Pedido:** "enquanto isso eu preciso que abra YouTube no computador"
**Ação:** Aberto `https://www.youtube.com` no Microsoft Edge.
**Verificação:** Título da página confirmado como "YouTube", visível na tela.
**Resposta ao usuário:** "YouTube aberto no Edge. 🎬 A página carregou certinho. Se quiser, posso pesquisar algum vídeo ou canal específico."