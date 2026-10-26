<!-- skill: calculadora-cientifica-tkinter | tags: python, tkinter, calculadora, gui, eval-seguro | status: nova -->
# Criar calculadora científica em Python com Tkinter
## Quando usar
Quando o pedido for "calculadora científica", "calculadora em Python com interface gráfica" ou similar, exigindo operações básicas + funções matemáticas (sin, cos, log, sqrt, fatorial, constantes) com display, histórico e tratamento de erros.

## Pré-requisitos
- Python 3.8+ instalado (`python3 --version`).
- Tkinter disponível (vem com Python no Windows/macOS; no Linux: `sudo apt install python3-tk`).
- Arquivo único `{calculadora.py}` (sem dependências externas — usar apenas `math` e `tkinter`).

## Procedimento
1. Crie o arquivo `{calculadora.py}` e importe as bibliotecas:
   ```python
   import math
   import tkinter as tk
   from tkinter import messagebox
   ```
2. Defina a whitelist de funções/constantes permitidas no `eval` (NUNCA use `eval` puro):
   ```python
   FUNCOES_SEGURAS = {
       "sin": math.sin, "cos": math.cos, "tan": math.tan,
       "asin": math.asin, "acos": math.acos, "atan": math.atan,
       "log": math.log10, "ln": math.log, "sqrt": math.sqrt,
       "exp": math.exp, "abs": abs, "factorial": math.factorial,
       "pi": math.pi, "e": math.e,
   }
   ```
3. Crie a classe `Calculadora` com atributos `expressao` (string do display) e `historico` (lista).
4. Implemente o método de avaliação segura:
   ```python
   def calcular(self):
       try:
           expr = self.expressao.replace("^", "**").replace("%", "/100")
           resultado = eval(expr, {"__builtins__": {}}, FUNCOES_SEGURAS)
           self.historico.append(f"{self.expressao} = {resultado}")
           self.expressao = str(resultado)
       except ZeroDivisionError:
           self.expressao = "Erro: divisão por zero"
       except Exception:
           self.expressao = "Erro: expressão inválida"
       self.atualizar_display()
   ```
5. Monte a interface em `grid` com 3 áreas: display de entrada (topo), display de resultado/histórico (abaixo), teclado de botões.
6. Crie os botões com cores distintas por categoria:
   - Números `0-9` e `.`: fundo `#2d2d2d`, texto branco.
   - Operadores `+ - * / ^ ( ) %`: fundo `#ff9500`.
   - Funções científicas (`sin`, `cos`, `log`, `sqrt`, `factorial`, `pi`, `e`): fundo `#505050`.
   - `C` (limpar tudo) e `⌫` (backspace): fundo `#d32f2f`.
   - `=` (igual): fundo `#4caf50`.
7. Para cada botão, use `command=lambda v={texto}: self.inserir(v)` (evite closure tardia no loop).
8. Implemente `inserir(v)`: se `v` for função, insira `v+"("`; se for constante, insira o nome; senão concatene ao `self.expressao`.
9. Implemente `limpar()` (zera expressão) e `backspace()` (`self.expressao = self.expressao[:-1]`).
10. Adicione um painel de histórico (ex.: `tk.Listbox` ou `tk.Text` somente leitura) que exibe os últimos `{N}` cálculos.
11. Rode `python3 {calculadora.py}` e teste: `2+2`, `sin(pi/2)`, `5!` (via `factorial(5)`), `1/0` (deve mostrar erro), `sqrt(-1)` (deve mostrar erro).

## Erros conhecidos e soluções
- **`NameError: name 'sin' is not defined`** → a função não está na whitelist ou o `eval` recebeu `globals` vazio sem `locals`. Passe `FUNCOES_SEGURAS` como `locals` (3º argumento do `eval`).
- **`SyntaxError` ao usar `^`** → Python usa `**` para potência. Converta `^` → `**` antes do `eval` (passo 4).
- **`ZeroDivisionError` não capturado** → garanta o `try/except ZeroDivisionError` ANTES do `except Exception` genérico.
- **Botões executando o último valor do loop** → use `lambda v={texto}: ...` com argumento default para capturar o valor no momento da criação.
- **`ModuleNotFoundError: tkinter`** → instale com `sudo apt install python3-tk` (Linux) ou reinstale Python com a opção Tcl/Tk (Windows).
- **`factorial` com número negativo ou float** → `math.factorial` lança `ValueError`; o `except Exception` já cobre, mas exiba mensagem clara.

## Exemplo real (da tarefa que originou esta skill)
Pedido: "pode criar o código para uma calculadora cientista?". Solução entregue: arquivo único Python/Tkinter com display duplo, botões coloridos por categoria (números escuros, operadores laranja, funções cinza, `=` verde, `C`/`⌫` vermelhos), `eval` restrito via dicionário `FUNCOES_SEGURAS` (sem `__builtins__`), conversão de `^`→`**` e `%`→`/100`, histórico em lista, e tratamento explícito de `ZeroDivisionError` e expressões inválidas. Testado com `sin(pi/2)`, `factorial(5)`, `1/0` e `sqrt(-1)`.