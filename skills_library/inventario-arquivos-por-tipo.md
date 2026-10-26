<!-- skill: inventario-arquivos-por-tipo | tags: inventario, contagem, extensao, windows, powershell, relatorio | status: nova -->
# Inventariar arquivos de um diretório e contar por tipo (extensão)

## Quando usar
Quando for preciso listar **todos** os arquivos de uma árvore de diretórios e produzir um **resumo completo por tipo/extensão** (contagem de cada tipo, do mais frequente ao menos frequente), com total geral e verificação de consistência. Gatilhos: "quantos arquivos de cada tipo", "inventário do diretório", "contagem por extensão".

## Pré-requisitos
- Windows com PowerShell (ou `cmd`).
- Caminho da raiz a inventariar (ex.: `{DIRETORIO_RAIZ}`).
- Espaço para gravar o relatório em `{ARQUIVO_SAIDA}` (ex.: `{DIRETORIO_RAIZ}\resumo_tipos.md`).

## Procedimento

1. **Definir variáveis** (troque pelos valores reais):
   - `{DIRETORIO_RAIZ}` = raiz a varrer.
   - `{ARQUIVO_SAIDA}` = caminho do relatório `.md`.

2. **Listar todos os arquivos** (inclui ocultos/sistema) e gravar em arquivo intermediário:
   ```powershell
   cmd /c dir "{DIRETORIO_RAIZ}" /s /b /a > "{DIRETORIO_RAIZ}\_lista_arquivos.txt"
   ```
   - `/s` = recursivo, `/b` = nomes simples, `/a` = inclui ocultos/sistema.

3. **Contar por tipo com PowerShell** (uma única passada, sem erro de sintaxe):
   ```powershell
   $linhas = Get-Content "{DIRETORIO_RAIZ}\_lista_arquivos.txt"
   $total = $linhas.Count
   $grupos = $linhas | ForEach-Object {
       $nome = Split-Path $_ -Leaf
       if ($nome -match '\.([^.]+)$') { $matches[1].ToLower() } else { 'sem_extensao' }
   } | Group-Object | Sort-Object Count -Descending
   $soma = ($grupos | Measure-Object Count -Sum).Sum
   "TOTAL=$total TIPOS=$($grupos.Count) SOMA=$soma"
   $grupos | ForEach-Object { "{0}`t{1}" -f $_.Name, $_.Count }
   ```

4. **Verificar consistência** antes de publicar:
   - `SOMA` deve ser **igual** a `TOTAL`. Se diferir, há linhas vazias ou duplicadas — limpe com `$linhas = $linhas | Where-Object { $_.Trim() -ne '' }` e repita o passo 3.

5. **Gerar a tabela markdown completa** (todos os tipos, sem truncar):
   ```powershell
   $i = 0
   $linhasMd = $grupos | ForEach-Object {
       $i++
       "| $i | $($_.Name) | $($_.Count) |"
   }
   $cab = "| # | Tipo | Qtd |`n|---:|---|---:|"
   $md = "# Contagem por tipo`n`n**Total de arquivos:** $total`n**Tipos distintos:** $($grupos.Count)`n**Soma das contagens:** $soma`n`n$cab`n" + ($linhasMd -join "`n")
   Set-Content -Path "{ARQUIVO_SAIDA}" -Value $md -Encoding UTF8
   ```

6. **Conferir o arquivo final**: abra `{ARQUIVO_SAIDA}` e confirme que a **última linha da tabela** tem o tipo de menor contagem (não termina em tipo sem valor). Confira também que o número de linhas da tabela = `TIPOS`.

7. **Apresentar o resumo na resposta**: inclua total, tipos distintos, soma (com ✅ se igual ao total) e a tabela completa. Nunca corte a tabela no meio.

## Erros conhecidos e soluções
- **Tabela truncada / termina em tipo sem valor**: a geração foi interrompida ou o loop foi cortado. Regenere a tabela a partir de `$grupos` (passo 5) e valide a última linha (passo 6) antes de responder.
- **Erro de sintaxe na etapa de contagem**: evite `ForEach-Object { ... } | Group-Object` com blocos multilinha mal fechados; use o script do passo 3 como bloco único e teste com `$grupos.Count` antes de gerar o markdown.
- **Soma ≠ total**: linhas vazias no arquivo intermediário — filtre com `Where-Object { $_.Trim() -ne '' }`.
- **Categorias estranhas** (`1`, `2`, `42`, hashes longos, `dist-info`, `typed`): são nomes de arquivo/pasta com ponto que não é extensão real. Mantenha como categoria própria e **documente** no relatório (ex.: `sem_extensao` para nomes sem ponto).
- **Acentuação quebrada**: grave com `-Encoding UTF8`.

## Exemplo real (da tarefa que originou esta skill)
Inventário de `E:\YVAKOR`: 10.770 arquivos, 119 tipos, soma das contagens = 10.770 (diferença zero). Top: `sem_extensao` 2.914, `py` 2.818, `pyc` 2.808, `md` 385, `pyi` 385. Relatório salvo em `E:\YVAKOR\yvakor\data\cowork\acd04f11\resumo_tipos.md` (3.141 bytes) com a tabela completa dos 119 tipos. A primeira tentativa falhou por truncamento da tabela e erro de sintaxe na contagem; a correção foi regenerar a tabela a partir do agrupamento validado e conferir a última linha antes de publicar.