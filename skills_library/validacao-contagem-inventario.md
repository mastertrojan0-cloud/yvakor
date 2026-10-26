<!-- skill: validacao-contagem-inventario | tags: inventario, contagem, validacao, consistencia, windows, powershell | status: nova -->
# Validação de contagem por tipo em inventário de arquivos

## Quando usar
Quando já existe um inventário de arquivos (lista gerada por `dir /s /b /a`,
`Get-ChildItem -Recurse`, `find`, etc.) e é preciso **conferir se a soma das
contagens por tipo bate com o total de arquivos listados**, explicando
eventuais divergências antes de seguir para a próxima etapa.

## Pré-requisitos
- Arquivo de inventário bruto (uma linha por caminho) em `{caminho_inventario}`.
- Shell disponível (PowerShell no Windows, bash no Linux/macOS).
- Saber o diretório de saída para o relatório: `{dir_saida}`.

## Procedimento
1. **Contar o total de linhas do inventário** (total de arquivos listados).
   ```powershell
   $total = (Get-Content "{caminho_inventario}" | Measure-Object -Line).Lines
   $total
   ```
   No bash: `wc -l < "{caminho_inventario}"`.
2. **Extrair o "tipo" de cada linha.** Defina tipo como o sufixo após o último
   ponto do nome do arquivo; se não houver ponto no nome, o tipo é
   `sem_extensao`. Ignore o caminho — só o nome do arquivo conta.
   ```powershell
   $tipos = Get-Content "{caminho_inventario}" | ForEach-Object {
     $nome = Split-Path $_ -Leaf
     if ($nome -match '\.([^.]+)$') { $matches[1].ToLower() } else { 'sem_extensao' }
   }
   ```
3. **Agrupar e contar por tipo**, ordenando do maior para o menor.
   ```powershell
   $contagem = $tipos | Group-Object | Sort-Object Count -Descending |
     Select-Object Name, Count
   $soma = ($contagem | Measure-Object Count -Sum).Sum
   ```
4. **Comparar soma com total.**
   ```powershell
   $diferenca = $total - $soma
   $consistente = ($diferenca -eq 0)
   ```
   - Se `$consistente = $true`: registrar "Consistente: SIM".
   - Se `$diferenca -ne 0`: **não abortar** — ir ao passo 5 para explicar.
5. **Investigar divergências antes de declarar erro.** Cheque, nesta ordem:
   - **`sem_extensao` inflado:** inclui arquivos sem ponto no nome **e** nomes
     de pasta capturados por `dir /s /b /a` (ex.: `__pycache__`, `dist-info`,
     `typed`). Isso é esperado, não é erro de contagem.
   - **Sufixos de diretório virando "extensão":** `*.dist-info`, `*.typed`,
     `*.egg-info` são pastas de pacotes Python, não arquivos — mesma origem.
   - **Linhas em branco / CRLF:** remover linhas vazias antes de contar
     (`Where-Object { $_.Trim() -ne '' }`).
   - **Duplicatas:** `Sort-Object -Unique` para conferir.
   Só declarar inconsistência real se, após excluir essas categorias, a soma
   ainda diferir do total.
6. **Gerar o relatório** em `{dir_saida}/contagem_por_tipo.txt` (UTF-8) com:
   cabeçalho de validação (total, soma, diferença, consistente SIM/NÃO,
   nº de tipos distintos), tabela completa de tipos ordenada por quantidade e
   nota explicando as categorias especiais (`sem_extensao`, sufixos de pasta).
   ```powershell
   $out = @()
   $out += "Total de arquivos: $total"
   $out += "Soma das contagens: $soma"
   $out += "Diferenca: $diferenca"
   $out += "Consistente: $(if($consistente){'SIM'}else{'NAO'})"
   $out += "Tipos distintos: $($contagem.Count)"
   $out += ""
   $out += ($contagem | ForEach-Object { "{0}`t{1}" -f $_.Name, $_.Count })
   $out | Set-Content "{dir_saida}/contagem_por_tipo.txt" -Encoding UTF8
   ```
7. **Critério de pronto:** soma = total (ou divergência explicada pelas
   categorias do passo 5). Só então seguir para a próxima etapa.

## Erros conhecidos e soluções
- **`sem_extensao` com número alto (ex.: milhares):** normal em inventários
  gerados com `dir /s /b /a` — pastas entram na lista. Não "corrigir" a
  contagem; apenas documentar no relatório.
- **`dist-info`, `typed`, `egg-info` aparecendo como tipo:** são sufixos de
  diretório de pacotes Python. Tratar como categoria esperada, não como erro.
- **Soma maior que o total:** sinal de linhas duplicadas ou contagem dupla de
  pastas. Rodar `Sort-Object -Unique` e recontar.
- **Soma menor que o total:** linhas em branco ou encoding quebrado (BOM/CRLF).
  Filtrar linhas vazias e reler com `-Encoding UTF8`.
- **`Get-Content` lento em arquivos grandes (>100k linhas):** usar
  `[System.IO.File]::ReadLines("{caminho_inventario}")` para streaming.
- **Acentos corrompidos no relatório:** sempre gravar com `-Encoding UTF8`.

## Exemplo real (da tarefa que originou esta skill)
Inventário de `E:\YVAKOR\yvakor` gerado com `dir /s /b /a`:
- Total de arquivos: **10.770**
- Soma das contagens por tipo: **10.770**
- Diferença: **0** → **Consistente: SIM**
- Tipos distintos: **119**
- Top tipos: `sem_extensao` 2.914, `py` 2.818, `pyc` 2.808, `pyi` 385,
  `md` 385, `txt` 99, `pyd` 79, `wav` 70, `jpg` 63, `f90` 62, `afm` 61,
  `h` 60, `old` 57, `typed` 52, `dist-info` 52.
- Divergências aparentes (`sem_extensao`, `dist-info`, `typed`) explicadas
  como categorias esperadas — nenhuma inconsistência real.
- Relatório gravado em `{dir_saida}/contagem_por_tipo.txt` (1.218 bytes, UTF-8).