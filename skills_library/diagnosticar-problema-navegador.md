<!-- skill: diagnosticar-problema-navegador | tags: navegador, diagnóstico, troubleshooting, gui | status: nova -->
# Diagnosticar problema no navegador

## Quando usar
Use quando o usuário relatar um problema genérico ou específico no navegador (ex.: "não abre", "trava", "página em branco", "erro de conexão", "login falhando") sem especificar a causa. Gatilhos: "problema no navegador", "navegador não funciona", "site não carrega".

## Pré-requisitos
- Navegador instalado (Edge, Chrome, Firefox) e sessão gráfica ativa
- Acesso ao terminal/execução de comandos do sistema
- Confirmação do usuário sobre qual navegador e qual sintoma

## Procedimento
1. Pergunte ao usuário, de forma objetiva, qual é o sintoma exato. Ofereça opções para facilitar: não abre / trava / página em branco / erro de conexão / login falhando.
2. Pergunte qual navegador está usando (Edge, Chrome, Firefox) e, se aplicável, qual site/URL apresenta o problema.
3. Com as respostas, verifique o estado do navegador:
   - Windows: `tasklist | findstr /i "{navegador}"` (ex.: `msedge`, `chrome`, `firefox`)
   - Linux: `pgrep -a "{navegador}"`
   - macOS: `pgrep -l "{navegador}"`
4. Verifique a conectividade de rede:
   - `ping -n 4 {host}` (Windows) ou `ping -c 4 {host}` (Linux/macOS), usando `8.8.8.8` ou o domínio do site
5. Se o navegador estiver aberto, identifique a página atual (título da janela/aba) e compare com o esperado.
6. Aplique a correção conforme o sintoma (ver tabela de erros).
7. Confirme ao usuário o resultado e ofereça próximo passo (ex.: reabrir o site, limpar cache).

## Erros conhecidos e soluções
| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| Navegador não abre | Processo travado / executável ausente | Encerre o processo (`taskkill /IM {navegador}.exe /F` no Windows; `pkill {navegador}` no Linux) e reabra |
| Navegador trava | Muitas abas / cache corrompido | Feche abas, limpe cache ou reinicie o navegador |
| Página em branco | Falha de renderização / cache | Recarregue com F5 ou Ctrl+F5 (hard reload) |
| Erro de conexão | Rede/DNS/proxy | Teste `ping {host}`; verifique conexão e configuração de proxy |
| Login falhando | Cookies/sessão inválidos | Limpe cookies do site ou use janela anônima |
| Site não carrega só em um navegador | Extensão ou perfil corrompido | Teste em janela anônima ou outro navegador |

## Exemplo real (da tarefa que originou esta skill)
**Pedido:** "estou com um problema no navegador"
**Ação:** A IA pediu esclarecimento do sintoma (não abre, trava, página em branco, erro de conexão, login falhando) e ofereceu verificar o estado dos navegadores (Edge/Chrome) e a página atual mediante confirmação.
**Lição aprendida:** diante de relato vago, primeiro qualificar o sintoma com opções fechadas antes de executar verificações — evita diagnóstico errado e ações desnecessárias.