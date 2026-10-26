<!-- skill: gerar-planilha-xlsx-vendas | tags: xlsx, openpyxl, planilha, vendas, python | status: nova -->
# Gerar planilha XLSX de vendas (produto × valor) com total

## Quando usar
Quando o pedido for criar/exportar uma planilha `.xlsx` contendo linhas de
produtos (ou itens) com seus valores numéricos e, opcionalmente, uma linha de
total somado. Gatilhos: "gere uma planilha XLSX de vendas", "exporte produtos e
valores para Excel", "planilha com total".

## Pré-requisitos
- Python 3.8+ instalado.
- Biblioteca `openpyxl` instalada (`pip install openpyxl`).
- Diretório de saída existente e com permissão de escrita
  (ex.: `{diretorio_artefatos}`).

## Procedimento
1. Defina os dados de entrada como lista de pares `(produto, valor)`:
   ```python
   dados = [("{produto_1}", {valor_1}), ("{produto_2}", {valor_2}), ("{produto_3}", {valor_3})]
   ```
2. Importe a biblioteca e crie o workbook/aba:
   ```python
   from openpyxl import Workbook
   wb = Workbook()
   ws = wb.active
   ws.title = "Vendas"
   ```
3. Escreva o cabeçalho na primeira linha:
   ```python
   ws.append(["produto", "valor"])
   ```
4. Percorra os dados e escreva uma linha por item:
   ```python
   for produto, valor in dados:
       ws.append([produto, valor])
   ```
5. Calcule o total e escreva a linha de total (deixe a célula do produto vazia
   ou com o rótulo "Total"):
   ```python
   total = sum(valor for _, valor in dados)
   ws.append(["Total", total])
   ```
6. Monte o caminho de saída com nome único (slug + timestamp) e salve:
   ```python
   import time, os
   slug = "vendas-" + "-".join(p.lower() for p, _ in dados)
   nome = f"{slug}-{int(time.time())}.xlsx"
   caminho = os.path.join("{diretorio_artefatos}", nome)
   wb.save(caminho)
   ```
7. Confirme a existência do arquivo e reporte o caminho absoluto e o total
   calculado ao usuário.

## Erros conhecidos e soluções
- **`ModuleNotFoundError: No module named 'openpyxl'`** → Instale com
  `pip install openpyxl` antes de executar.
- **`PermissionError` ao salvar** → Verifique se `{diretorio_artefatos}` existe
  e tem permissão de escrita; crie o diretório com `os.makedirs(..., exist_ok=True)`
  ou use caminho absoluto.
- **Valores gravados como texto** → Garanta que `{valor_N}` seja numérico
  (`int`/`float`), não string; converta com `float(valor)` se vier de texto.
- **Total incorreto** → Confirme que a soma usa a mesma lista `dados` já
  convertida para números; evite somar strings.
- **Arquivo sobrescrito** → Sempre inclua timestamp no nome (passo 6) para
  evitar colisão.

## Exemplo real (da tarefa que originou esta skill)
Pedido: "Gere uma planilha XLSX de vendas com produtos A, B, C e valores 10, 20, 30."

Execução:
```python
from openpyxl import Workbook
import time, os

dados = [("A", 10), ("B", 20), ("C", 30)]
wb = Workbook()
ws = wb.active
ws.title = "Vendas"
ws.append(["produto", "valor"])
for produto, valor in dados:
    ws.append([produto, valor])
total = sum(v for _, v in dados)
ws.append(["Total", total])

slug = "vendas-" + "-".join(p.lower() for p, _ in dados)
nome = f"{slug}-{int(time.time())}.xlsx"
caminho = os.path.join(r"E:\YVAKOR\yvakor\data\artefatos", nome)
wb.save(caminho)
print(caminho, total)
```

Resultado:
- **Arquivo:** `E:\YVAKOR\yvakor\data\artefatos\vendas-produtos-a-b-c-1792796310.xlsx`
- **Conteúdo:**

| produto | valor |
|---------|-------|
| A | 10 |
| B | 20 |
| C | 30 |
| Total | 60 |

Total: **60** (soma dos três produtos).