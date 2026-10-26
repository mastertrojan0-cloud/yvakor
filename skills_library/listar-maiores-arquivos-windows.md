<!-- skill: listar-maiores-arquivos-windows | tags: windows, powershell, disco, auditoria, tamanho, arquivos | status: nova -->
# Listar os maiores arquivos de uma pasta no Windows

## Quando usar
Quando o usuário pedir "quais os maiores arquivos", "o que está ocupando espaço",
"top N arquivos por tamanho" ou uma auditoria de disco em uma pasta Windows.
Também serve como etapa de diagnóstico antes de uma limpeza de disco.

## Pré-requisitos
- Shell PowerShell no Windows (não CMD — os cmdlets abaixo são PowerShell).
- Caminho da pasta-alvo conhecido: `{caminho}` (ex.: `E:\YVAKOR`).
- Número de resultados desejado: `{N}` (padrão 5).
- Não requer administrador; `-Force` inclui arquivos ocultos/sistema.

## Procedimento
1. **Executar a listagem recursiva, ordenar por tamanho decrescente e cortar os N primeiros** em um único pipeline:
   ```powershell
   Get-ChildItem -LiteralPath '{caminho}' -Recurse -File -Force -ErrorAction SilentlyContinue |
     Sort-Object Length -Descending |
     Select-Object -First {N} |
     Select-Object @{n='MB';e={[math]::Round($_.Length/1MB,1)}}, Length, FullName
   ```
   - `-File` ignora diretórios; `-Force` inclui ocultos/sistema.
   - `-ErrorAction SilentlyContinue` evita abortar por pastas sem permissão.
   - `-LiteralPath` evita que `[` `]` no caminho sejam interpretados como curinga.
2. **Conferir o resultado**: deve retornar exatamente `{N}` linhas (ou menos, se a pasta tiver menos arquivos). Se retornar 0, verificar se `{caminho}` existe.
3. **Apresentar em tabela** ao usuário com colunas: `#`, `Tamanho` (MB e bytes), `Caminho`.
4. **Interpretar o resultado** (opcional, útil para o usuário): se os maiores forem binários de dependências (`venv`, `node_modules`, `site-packages`), caches de navegador (`browser_profiles`) ou modelos (`*.tflite`, `*.fst`, `*.dll`), avisar que são arquivos de programa/cache — não dados do usuário — e que apagá-los pode quebrar aplicações.

## Erros conhecidos e soluções
- **Texto descritivo passado como comando:** a falha mais comum. O shell precisa do comando PowerShell real (passo 1), não de uma frase como "listar os maiores arquivos". Sempre enviar o pipeline literal.
- **"Acesso negado" em subpastas:** esperado em `System Volume Information`, perfis de outros usuários etc. O `-ErrorAction SilentlyContinue` já contorna; não insistir.
- **Caminho com espaços/acentos/colchetes:** usar `-LiteralPath '{caminho}'` entre aspas simples.
- **Resultado vazio:** confirmar que `{caminho}` existe (`Test-Path -LiteralPath '{caminho}'`) e que há arquivos (`-File`).
- **Comando não reconhecido (`Get-ChildItem`):** está no CMD, não no PowerShell. Abrir PowerShell (`powershell.exe`) e repetir.
- **Ordenação errada (ordem alfabética):** faltou `Sort-Object Length -Descending`; `Length` é o tamanho em bytes.

## Exemplo real (da tarefa que originou esta skill)
Pedido: listar os 5 maiores arquivos de `E:\YVAKOR`. Comando executado (returncode 0):
```powershell
Get-ChildItem -LiteralPath 'E:\YVAKOR' -Recurse -File -Force |
  Sort-Object Length -Descending |
  Select-Object -First 5
```
Resultado (top 5):

| # | Tamanho | Caminho |
|---|---------|---------|
| 1 | 89,2 MB (93.580.104 B) | `E:\YVAKOR\yvakor\venv\Lib\site-packages\playwright\driver\node.exe` |
| 2 | 35,1 MB (36.778.224 B) | `E:\YVAKOR\yvakor\data\browser_profiles\chrome\...\model.tflite` |
| 3 | 25,4 MB (26.619.146 B) | `E:\YVAKOR\yvakor\venv\Lib\site-packages\vosk\libstdc++-6.dll` |
| 4 | 25,2 MB (26.447.872 B) | `E:\YVAKOR\yvakor\venv\Lib\site-packages\vosk\libvosk.dll` |
| 5 | 20,8 MB (21.818.215 B) | `E:\YVAKOR\yvakor\data\vosk\vosk-model-small-es-0.42\graph\Gr.fst` |

Observação: todos os maiores eram binários de dependências (Playwright, Vosk) e cache de perfil do Chrome — nenhum dado do usuário.