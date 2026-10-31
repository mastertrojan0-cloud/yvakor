<!-- skill: otimizar-windows-limpeza | tags: windows, limpeza, manutencao, disco, otimizar, drivers | status: nova -->
# Otimizar o computador Windows (executar, não orientar)

## Quando usar
"otimiza meu computador", "libera espaço", "deixa o PC mais rápido",
"executa o que você consegue fazer".

## Regra principal
O usuário pediu para EXECUTAR. Faça tudo o que as ferramentas permitem, numa
tarefa só, e responda com o resultado. Não devolva "pendências manuais" do que
uma ferramenta faz. Confirmações vêm sozinhas: popup do YVAKOR para apagar e
UAC do Windows para o que exige administrador — não pergunte antes delas.

## Procedimento
1. `limpar_temporarios(dias=2)` — apaga o %TEMP% antigo, mostra progresso;
   se `itens_restantes > 0`, chame de novo.
2. `esvaziar_lixeira()`.
3. `sistema_drivers()` e, em seguida, `sistema_drivers_atualizar(acao="auto")`
   — instala o que o Windows Update tiver e reinstala aparelhos com problema
   (aparelhos virtuais como RemoteFX são ignorados de propósito).
4. `organizar_analisar()` — informe duplicados e instaladores antigos (GB) que
   o usuário pode apagar; organizar só se ele pedir.
5. Responda: MB liberados por etapa, total, drivers instalados/reparados e o
   que ficou de fora com o motivo REAL (ex.: UAC recusado, arquivo em uso).

## Erros conhecidos
- **Terminar com "o que ficou pendente (ação manual sua)"** listando drivers e
  lixeira — foi o erro da tarefa original (29/10). Use as ferramentas.
- **UAC recusado** — diga isso; não tente de novo sem o usuário pedir.
- **Cache de navegador** — só com o navegador fechado; se aberto, avise.

## Exemplo real
Pedido: "executa o que voce consegue fazer, preciso otimizar meu computador".
Temporários: 18.471 arquivos, 927,8 MB. Lixeira: 1.898 itens, 3.133 MB.
Total ~4,06 GB.
