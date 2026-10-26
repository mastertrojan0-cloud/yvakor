<!-- skill: listar-conteudo-pasta-windows | tags: windows, powershell, cmd, listagem, diretorio, auditoria | status: atualizada -->
# Listar o conteúdo de uma pasta no Windows (arquivos e subpastas)

## Quando usar
Quando o usuário pedir "liste o conteúdo de {pasta}", "o que tem nesse diretório",
"quais arquivos e subpastas existem em {caminho}" ou uma verificação rápida de
estrutura antes de outra etapa (ex.: conferir se uma interface tem os HTMLs esperados).
Para ranking por tamanho, use a skill `listar-maiores-arquivos-windows`.

## Pré-requisitos
- Shell PowerShell no Windows (preferencial; o CMD também serve como alternativa).
- Caminho da pasta-alvo conhecido: `{caminho}` (ex.: `E:\YVAKOR\yvakor\interface`).
- Não requer administrador; `-Force` inclui arquivos/pastas ocultos e de sistema.

## Procedimento
1. **Confirmar que a pasta existe** antes de listar:
   ```powershell
   Test-Path -LiteralPath '{caminho}'
   ```
   Deve retornar `True`. Se `False`, parar e avisar que o caminho não existe.
2. **Listar o conteúdo de primeiro nível** (sem recursão), com tipo e tamanho:
   ```powershell
   Get-ChildItem -LiteralPath '{caminho}' -Force |
     Select-Object Name,
       @{n='Tipo';e={if ($_.PSIsContainer) {'pasta'} else {'arquivo'}}},
       @{n='Bytes';e={if ($_.PSIsContainer) {$null} else {$_.Length}}},
       @{n='KB';e={if ($_.PSIsContainer) {$null} else {[math]::Round($_.Length/1KB,1)}}}
   ```
   - `-Force` inclui itens ocultos/sistema; `-LiteralPath` evita que `[` `]` no caminho sejam tratados como curinga.
   - **Não** usar `-Recurse` aqui: o pedido é o conteúdo direto da pasta.
3. **Contar itens e separar arquivos de subpastas** (para o resumo):
   ```powershell
   $itens = Get-ChildItem -LiteralPath '{caminho}' -Force
   "Total: $($itens.Count) | Arquivos: $(($itens | Where-Object {-not $_.PSIsContainer}).Count) | Pastas: $(($itens | Where-Object {$_.PSIsContainer}).Count)"
   ```
4. **Apresentar em tabela** ao usuário com colunas: `Item`, `Tipo`, `Tamanho` (KB e bytes).
   Para pastas, deixar o tamanho em branco (não somar recursivamente sem pedido explícito).
5. **Resumir**: informar total de itens, quantos são arquivos e quantas subpastas
   (ex.: "3 itens — todos arquivos, nenhuma subpasta"). Se houver um arquivo
   dominante em tamanho, destacá-lo como provável página/arquivo principal.
6. **Alternativa em CMD** (se o PowerShell não estiver disponível):
   ```cmd
   dir /a "{caminho}"
   ```
   `/a` inclui ocultos/sistema. Interpretar as colunas `<DIR>` (pasta) e o tamanho em bytes.

## Erros conhecidos e soluções
- **Texto descritivo passado como comando:** a falha mais comum. O shell precisa do
  comando real (passo 2), não de uma frase como "listar o conteúdo da pasta".
- **"Acesso negado":** ocorre em pastas protegidas; adicionar `-ErrorAction SilentlyContinue`
  e seguir, ou avisar o usuário que aquele item não pôde ser lido.
- **Caminho com espaços/acentos/colchetes:** usar `-LiteralPath '{caminho}'` entre aspas simples.
- **Resultado vazio:** confirmar `Test-Path` (passo 1); pasta vazia é resultado válido — informar isso.
- **`Get-ChildItem` não reconhecido:** está no CMD, não no PowerShell. Abrir `powershell.exe`
  ou usar a alternativa `dir /a` do passo 6.
- **Listagem recursiva indesejada:** se aparecerem arquivos de subpastas, faltou remover
  `-Recurse`; o pedido padrão é apenas o primeiro nível.
- **Tamanho de pasta em branco:** esperado — `Length` só existe para arquivos; não inventar
  tamanho de pasta sem calcular recursivamente.

## Exemplo real (da tarefa que originou esta skill)
Pedido: listar o conteúdo de `E:\YVAKOR\yvakor\interface`.
Comando executado (returncode 0):
```powershell
Get-ChildItem -LiteralPath 'E:\YVAKOR\yvakor\interface' -Force |
  Select-Object Name,
    @{n='Tipo';e={if ($_.PSIsContainer) {'pasta'} else {'arquivo'}}},
    @{n='Bytes';e={if ($_.PSIsContainer) {$null} else {$_.Length}}}
```
Resultado:
| Item | Tipo | Tamanho |
|---|---|---|
| `dispositivos.html` | arquivo | 9.807 bytes (~9,6 KB) |
| `galeria.html` | arquivo | 3.572 bytes (~3,5 KB) |
| `index.html` | arquivo | 97.282 bytes (~95,0 KB) |

Resumo: 3 itens — todos arquivos, nenhuma subpasta. `index.html` é o dominante
(≈95 KB), provavelmente a página principal da interface; os outros dois são páginas secundárias.