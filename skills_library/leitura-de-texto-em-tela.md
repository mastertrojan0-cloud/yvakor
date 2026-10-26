<!-- skill: leitura-de-texto-em-tela | tags: ocr, leitura-tela, screenshot, chrome, texto-visivel, analise-imagem | status: nova -->
# Leitura de texto visível em tela (OCR / análise de screenshot)

## Quando usar
Quando o usuário enviar uma captura de tela (screenshot, print do Chrome, imagem de janela) e pedir "o que está escrito nesta tela?", "leia isso", "analise e responda" ou equivalente. Gatilho: imagem de tela + pedido de leitura/transcrição do conteúdo.

## Pré-requisitos
- Acesso à imagem/captura enviada pelo usuário (anexo ou caminho de arquivo).
- Capacidade de leitura visual (OCR nativo do modelo ou ferramenta de OCR).
- Nenhuma credencial ou API externa é necessária para telas simples.

## Procedimento
1. **Receber e localizar a imagem.** Confirme que há uma imagem anexada ou um caminho de arquivo (`{CAMINHO_IMAGEM}`). Se não houver imagem, peça ao usuário antes de prosseguir.
2. **Varrer a tela inteira** antes de responder: barra de título, barra de endereço, corpo central, rodapé, abas e qualquer texto em botões/menus.
3. **Transcrever o texto literalmente**, preservando maiúsculas, números e pontuação exatamente como aparecem. Não corrigir, traduzir nem "melhorar" o texto.
4. **Destacar o conteúdo principal** em negrito/aspas (ex.: o texto central da página) e listar separadamente textos secundários (título da aba, URL, botões) se existirem.
5. **Declarar explicitamente o que NÃO há**, quando a tela for quase vazia: "Não há mais conteúdo visível além de X." Isso evita que o usuário pense que algo foi omitido.
6. **Não inferir contexto ausente.** Se o texto parece um teste (ex.: "TESTE 123"), diga que "aparentemente é um teste", sem inventar propósito.
7. **Formatar a resposta** de forma curta: primeiro o texto encontrado, depois uma frase de contexto/observação.

## Erros conhecidos e soluções
- **Imagem ilegível ou muito pequena:** pedir ao usuário um print com mais zoom/resolução; não adivinhar caracteres.
- **Texto cortado nas bordas:** informar que parte do conteúdo pode estar fora do enquadramento e pedir nova captura.
- **Múltiplos blocos de texto (UI + conteúdo):** separar "conteúdo principal" de "elementos de interface" para não misturar.
- **Usuário espera interpretação, não só transcrição:** após transcrever, oferecer 1 frase de leitura (ex.: "parece um teste de OCR"), mas nunca substituir a transcrição pela interpretação.
- **Idioma diferente do esperado:** transcrever no idioma original e só traduzir se o usuário pedir.

## Exemplo real (da tarefa que originou esta skill)
Usuário enviou print de uma página do Chrome e pediu: "O que está escrito nesta tela? Analise e responda."

Resposta correta produzida:
> Na tela está escrito:
> **"YVAKOR OCR TESTE 123"**
> É isso — apenas esse texto, aparentemente um teste de OCR da própria página do Chrome. Não há mais conteúdo visível além dessa linha.

Aprendizado-chave: a tela tinha **apenas uma linha**; declarar a ausência de outro conteúdo foi tão importante quanto transcrever o texto.