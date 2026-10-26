<!-- skill: inventariar-arquivos-recursivo-windows | tags: windows, inventario, arquivos, dir, recursao, yvakor | status: nova -->
# Inventariar arquivos recursivamente no Windows (lista de caminhos completos)

## Quando usar
Quando for preciso gerar uma lista de **todos os arquivos** de uma árvore de diretórios no Windows, com **caminho completo por linha**, de forma rápida e sem interrupção por pastas sem permissão. Gatilhos: "listar todos os arquivos de {pasta}", "inventário de arquivos", "varredura recursiva", "gerar lista de caminhos".

## Pré-requisitos
- Windows (cmd/PowerShell disponível).
- Acesso de leitura à pasta raiz `{pasta_raiz}` (ex.: `E:\YVAKOR`).
- Uma pasta de destino gravável para o arquivo de saída `{arquivo_saida}` (ex.: `E:\YVAKOR\yvakor\data\cowork\{id}\inventario_arquivos.txt`).
- **Não** use Python nem `Get-ChildItem` para árvores grandes: estouram timeout (15s/25s observados). Use o `dir` nativo.

## Procedimento
1. Abra o **Prompt de Comando (cmd)** — não o PowerShell — para usar `dir` com os switches abaixo.
2. Execute a varredura recursiva, gravando um caminho completo por linha e suprimindo erros de acesso:
   ```cmd
   dir /s /b /a "{pasta_raiz}" > "{arquivo_saida}" 2>nul
   ```
   - `/s` = recursivo em subpastas
   - `/b` = formato "bare" (só o caminho completo, um por linha)
   - `/a` = inclui arquivos ocultos e de sistema (ex.: `.claude\settings.local.json`)
   - `2>nul` = descarta mensagens de "Acesso negado" sem interromper a varredura
3. Confirme que o arquivo foi gerado e conte as linhas:
   ```cmd
   find /c /v "" "{arquivo_saida}"
   ```
   O número retornado deve ser igual à quantidade de arquivos encontrados.
4. Verifique o formato com uma amostra do início:
   ```cmd
   more +0 "{arquivo_saida}"
   ```
   Confirme: caminhos **absolutos**, **um por linha**, incluindo ocultos.
5. (Opcional) Confira o tamanho do arquivo para sanidade:
   ```cmd
   dir "{arquivo_saida}"
   ```
6. Registre no relatório: total de arquivos, caminho do arquivo gerado, tamanho e encoding (UTF-8 quando gerado por redirecionamento padrão do cmd em locale compatível).

## Erros conhecidos e soluções
- **Timeout ao usar Python (`os.walk`) ou `Get-ChildItem -Recurse`.**  
  Solução: use `dir /s /b /a` (nativo, muito mais rápido). Não insista nas alternativas.
- **Varredura para no meio por "Acesso negado".**  
  Solução: sempre acrescente `2>nul` para descartar erros de permissão; a varredura continua.
- **Arquivos ocultos ausentes na lista.**  
  Solução: inclua o switch `/a` (sem ele, ocultos/sistema são omitidos).
- **Saída com cabeçalhos/colunas em vez de caminhos puros.**  
  Solução: garanta o switch `/b` (bare). Sem `/b`, o `dir` mostra data/tamanho.
- **Encoding inesperado ao abrir em outro editor.**  
  Solução: trate como UTF-8; se necessário, reconverta com `iconv`/PowerShell `Set-Content -Encoding UTF8`.

## Exemplo real (da tarefa que originou esta skill)
Varredura de `E:\YVAKOR` para a Etapa 2/8 do projeto:
```cmd
dir /s /b /a "E:\YVAKOR" > "E:\YVAKOR\yvakor\data\cowork\acd04f11\inventario_arquivos.txt" 2>nul
```
Resultado: **10.770 arquivos**, arquivo de **1.729.402 bytes / 10.770 linhas (UTF-8)**, caminhos absolutos um por linha, incluindo ocultos como `.claude\settings.local.json`. Python e `Get-ChildItem` haviam estourado o timeout antes; o `dir` nativo concluiu dentro do limite.