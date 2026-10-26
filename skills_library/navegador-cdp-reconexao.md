<!-- skill: navegador-cdp-reconexao | tags: navegador, chrome, cdp, reconexao, youtube, automacao, velocidade | status: nova -->
# Navegador: validar CDP antes de agir e executar ordens diretas sem confirmação

## Quando usar
Quando o YVAKOR for executar qualquer ação via navegador (abrir site, pesquisar, clicar, tocar música/vídeo) e o estado interno disser que o navegador está "aberto". Também ao receber ordens diretas do tipo "toca a música {X} no YouTube", "abre {site} e pesquisa {Y}" — o objetivo é executar rápido, sem pedir confirmação.

## Pré-requisitos
- Chrome/Chromium rodando com CDP habilitado (porta padrão `{PORTA_CDP}`, ex.: `9222`).
- Endpoint de status do CDP acessível: `http://127.0.0.1:{PORTA_CDP}/json/version`.
- Ferramentas internas do YVAKOR: `navegador_ver` (lista abas/refs), `navegador_abrir`, `navegador_pesquisar`, `navegador_clicar`.

## Procedimento
1. **Validar o CDP antes de qualquer ação.** Consultar `http://127.0.0.1:{PORTA_CDP}/json/version`.
   - Se responder JSON com `webSocketDebuggerUrl` → CDP vivo, seguir para o passo 2.
   - Se der erro de conexão/timeout → CDP morto, ir para o passo 3 (reconectar).
2. **Validar o estado real da aba.** Chamar `navegador_ver`.
   - Se retornar abas com URL e refs válidas → prosseguir com a ação.
   - Se retornar **vazio / página em branco / sem refs** → tratar como navegador fantasma: ir para o passo 3.
3. **Reconectar/reabrir em vez de insistir.** Não repetir a mesma ação na aba fantasma.
   - Fechar a aba/instância inválida e chamar `navegador_abrir` com a URL alvo.
   - Revalidar com `navegador_ver` (passo 2) antes de continuar.
4. **Executar a ordem direta sem pedir confirmação.** Para "tocar música {X} no YouTube":
   1. `navegador_abrir` em `https://www.youtube.com`
   2. `navegador_pesquisar` com `{X}`
   3. `navegador_clicar` no **primeiro resultado de vídeo**
   4. Confirmar que o vídeo carregou (título do player preenchido / player ativo) e reportar ao usuário.
5. **Reportar resultado objetivo** (o que foi aberto/tocado + confirmação de carregamento). Só pedir confirmação se a ordem for ambígua ou destrutiva.

## Erros conhecidos e soluções
- **CDP morto com estado "aberto":** YVAKOR trava o estado como aberto e envia ações para navegador fantasma (página vazia, sem refs). → Sempre validar CDP (passo 1) e `navegador_ver` (passo 2) antes de agir.
- **`navegador_ver` vazio:** não insistir na mesma aba; reconectar/reabrir (passo 3).
- **Lentidão por excesso de confirmação:** em ordens diretas e não destrutivas, executar o fluxo completo e só então reportar.
- **`cerebro.db` não persiste memórias:** causa raiz é `E:\YVAKOR\yvakor\core\cerebro.py` corrompido (dezenas de `__init__`/`_con` repetidos em loop), recriando o banco a cada conexão. → Corrigir/limpar o `cerebro.py` antes de confiar na persistência; até lá, gravar aprendizados em arquivos (`data/aprendizados/{tema}.md`).

## Exemplo real (da tarefa que originou esta skill)
Ordem: "toca a música {X} no YouTube". O estado dizia navegador aberto, mas o CDP estava morto e `navegador_ver` retornava vazio. Correção aplicada: validar CDP → detectar morto → reabrir YouTube → pesquisar → clicar no 1º resultado → confirmar carregamento, sem pedir confirmação. Aprendizado salvo em `E:\YVAKOR\yvakor\data\aprendizados\navegador.md`. Achado extra: `cerebro.py` corrompido impedia persistência no `cerebro.db`.