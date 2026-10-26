<!-- skill: separar-arquivos-de-subpastas | tags: powershell, listagem, arquivos, diretorios, filtro, windows | status: nova -->
# Separar nomes de arquivos de nomes de subpastas em uma listagem

## Quando usar
Quando uma listagem de diretório (via `dir`, `Get-ChildItem`, `find` etc.) mistura **arquivos e subpastas** e é preciso obter **apenas os nomes de arquivos** (ou apenas os de subpastas), para gerar uma lista limpa em arquivo. Gatilhos: "só os arquivos", "excluir pastas da lista", "separar arquivos de diretórios".

## Pré-requisitos
- Windows com PowerShell.
- Caminho do diretório a listar: `{DIRETORIO}` (ex.: `E:\YVAKOR\yvakor\interface`).
- Caminho do arquivo de saída: `{ARQUIVO_SAIDA}` (ex.: `{DIRETORIO}\interface_arquivos.txt`).

## Procedimento

1. **Listar apenas arquivos** (descarta subpastas) e gravar os nomes simples:
   ```powershell
   Get-ChildItem -Path "{DIRETORIO}" -File |
       Select-Object -ExpandProperty Name |
       Set-Content -Path "{ARQUIVO_SAIDA}" -Encoding UTF8
   ```
   - `-File` já exclui diretórios. Alternativa equivalente, se precisar filtrar manualmente:
     ```powershell
     Get-ChildItem -Path "{DIRETORIO}" | Where-Object { -not $_.PSIsContainer } |
         Select-Object -ExpandProperty Name |
         Set-Content -Path "{ARQUIVO_SAIDA}" -Encoding UTF8
     ```

2. **Listar apenas subpastas** (quando o pedido for o inverso):
   ```powershell
   Get-ChildItem -Path "{DIRETORIO}" -Directory |
       Select-Object -ExpandProperty Name |
       Set-Content -Path "{ARQUIVO_SAIDA}" -Encoding UTF8
   ```

3. **Conferir o resultado** — conte as entradas e valide que não há diretórios:
   ```powershell
   $itens = Get-Content "{ARQUIVO_SAIDA}"
   "ENTRADAS=$($itens.Count)"
   $itens
   ```
   - Confirme que cada linha é um nome de arquivo (tem extensão, ex.: `.html`) e que nenhuma corresponde a uma subpasta conhecida.

4. **Registrar na resposta** o total de entradas e a confirmação de que **0 diretórios** foram incluídos.

## Erros conhecidos e soluções
- **Lista contém nomes de pastas**: o filtro `-File` / `Where-Object { -not $_.PSIsContainer }` foi omitido. Reaplique o passo 1.
- **Saída com caminhos completos em vez de nomes**: faltou `Select-Object -ExpandProperty Name`. Use `-ExpandProperty FullName` se precisar do caminho completo.
- **Arquivo de saída vazio**: `{DIRETORIO}` não existe ou não contém arquivos. Verifique com `Test-Path "{DIRETORIO}"`.
- **Acentuação corrompida**: garanta `-Encoding UTF8` no `Set-Content`.

## Exemplo real (da tarefa que originou esta skill)
Diretório `E:\YVAKOR\yvakor\interface` listado com filtro `Where-Object { -not $_.PSIsContainer }`; saída gravada em `E:\YVAKOR\yvakor\data\cowork\4f12d58b\interface_arquivos.txt` com 3 entradas, todas arquivos:

```
dispositivos.html
galeria.html
index.html
```

Resultado: **3 arquivos, 0 diretórios** — critério da etapa atendido.