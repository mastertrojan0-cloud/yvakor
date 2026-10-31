<!-- skill: organizacao-pastas-usuario-windows | tags: windows, organizacao, pastas, downloads, duplicados, limpeza, lixo, temp | status: nova -->
# Organização de pastas do usuário no Windows (organizar de verdade, com desfazer)

## Quando usar
"organize minhas pastas", "arrume os Downloads", "limpe o lixo do PC",
"tire os duplicados", "a área de trabalho está uma bagunça".

## Regra principal
**Organize — não devolva perguntas.** Organizar só MOVE arquivos e tudo pode
ser desfeito, então não há o que perguntar antes. A ferramenta já protege
pastas de sistema, ocultas, atalhos, downloads em andamento e as subpastas
que o usuário criou. Pergunte só se o usuário pedir para APAGAR de vez.

## Procedimento
1. `organizar_analisar()` — sem argumentos cobre Desktop, Downloads,
   Documentos, Imagens, Músicas e Vídeos (segue o redirecionamento; neste PC
   Downloads/Documentos ficam em `F:\`). Para uma pasta só: `pastas="Downloads"`.
2. `organizar_plano(pastas, modo="auto")` — auto = por tipo (Documentos,
   Imagens, Instaladores, Compactados, Codigo, Outros); em Imagens/Vídeos/Músicas
   = por ano. Duplicados (mesmo conteúdo, por hash) vão para `_Duplicados`.
3. `organizar_executar(plano_id)` — executa o plano inteiro de uma vez.
4. "Lixo": `limpar_temporarios(dias=2)` manda o %TEMP% antigo para a Lixeira
   (recuperável). Instaladores antigos e `_Duplicados` ficam separados para o
   usuário esvaziar quando quiser — informe o tamanho.
5. Responda com: quantos arquivos foram para cada pasta, MB de duplicados e
   temporários, falhas (arquivo em uso) e `organizar_desfazer(plano_id)`.

## Erros conhecidos
- **Parar para perguntar "qual bloco primeiro?"** — foi o erro da tarefa que
  originou esta skill (29/10). Faça todos os blocos.
- **Mover arquivo a arquivo com arquivos_mover/shell** — cada um pede
  confirmação; use o plano em lote.
- **"mudou desde o plano"** — o arquivo foi alterado; gere um plano novo.
- **Raiz do disco do sistema (C:\), AppData, Windows, Program Files** — a
  ferramenta recusa; não tente contornar pelo shell.
