<!-- skill: pesquisar-no-youtube | tags: navegador, automação, gui, youtube, pesquisa | status: atualizada -->
# Pesquisar no YouTube pelo navegador

## Quando usar
Use quando o usuário pedir para abrir o YouTube **e pesquisar** por um termo (artista, vídeo, canal, música). Gatilhos: "abre o YouTube e pesquisa por {termo}", "procura {termo} no YouTube", "pesquisa {termo} no YouTube".

## Pré-requisitos
- Navegador instalado e sessão gráfica ativa (ver skill `abrir-site-navegador`)
- Termo de pesquisa definido (ex: nome de artista, música, canal)
- Conexão com a internet

## Procedimento
1. Extraia o termo de pesquisa do pedido do usuário (ex: "Ricardo Arjona"). Preserve acentos e maiúsculas.
2. Monte a URL de resultados de pesquisa, codificando o termo para URL (espaços → `+` ou `%20`):
   `https://www.youtube.com/results?search_query={termo_codificado}`
   - Exemplo: `Ricardo Arjona` → `https://www.youtube.com/results?search_query=Ricardo+Arjona`
3. Abra o navegador diretamente nessa URL de resultados (não é necessário abrir a home e digitar na barra de busca):
   - Windows (Edge): `start msedge "{url_resultados}"`
   - Windows (Chrome): `start chrome "{url_resultados}"`
   - Linux: `xdg-open "{url_resultados}"`
   - macOS: `open "{url_resultados}"`
4. Aguarde o carregamento (2–5 segundos).
5. Verifique se a página de resultados carregou: a URL deve conter `results?search_query=` e a página deve listar vídeos/canais/sugestões relacionados ao termo.
6. **Confirme pelo título da aba** que a busca foi aplicada: o título deve seguir o padrão `{termo} - YouTube`. Se o título não corresponder ao termo, a busca falhou — volte ao passo 2 e recodifique.
7. Confirme ao usuário que a pesquisa foi feita, cite o termo pesquisado e informe **qual navegador** foi usado; ofereça próximos passos (ex: abrir um vídeo, filtrar por canal).

## Erros conhecidos e soluções
| Erro | Solução |
|------|---------|
| Navegador não abre | Verifique o executável; use o navegador padrão (`start "" "{url}"` no Windows) |
| Página em branco / não carrega | Verifique conexão; recarregue com F5 |
| Termo com acento/emoji quebra a URL | Codifique o termo (ex: `%C3%A9` para "é"); use `+` para espaços |
| Resultados não correspondem ao termo | Confira a URL: deve conter `search_query={termo}`; recodifique se necessário |
| Página de resultados vazia | Termo muito específico; simplifique o termo ou remova filtros |
| Múltiplas abas abertas | Use janela nova (`--new-window`) ou feche abas antigas |
| Navegador abre mas não é o Chrome (ex: Edge) | Se o pedido exigir navegador específico, use o executável correspondente (`start chrome`); caso contrário, o navegador padrão é aceitável — informe qual foi usado na resposta |
| Título da aba não contém o termo pesquisado | A busca não foi aplicada; recodifique o termo e reabra a URL de resultados |

## Exemplo real (da tarefa que originou esta skill)
**Pedido:** "abre o youtube e pesquise por Ricardo Arjona"
**Ação:** Aberto o Chrome diretamente na URL `https://www.youtube.com/results?search_query=Ricardo+Arjona`.
**Verificação:** a página de resultados carregou e o título da aba ficou `Ricardo Arjona - YouTube`, confirmando que a busca foi aplicada.
**Resposta ao usuário:** YouTube aberto e pesquisando **Ricardo Arjona** — a página de resultados carregou (título: "Ricardo Arjona - YouTube").