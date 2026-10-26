<!-- skill: descrever-anexo-imagem | tags: anexo, imagem, png, pillow, analise-visual | status: nova -->
# Descrever anexo de imagem (PNG/JPG) sem visualizador

## Quando usar
Quando o usuário pedir para "descrever o anexo" e o anexo for uma imagem (PNG, JPG, etc.) que a ferramenta de leitura devolveu apenas como base64 bruto, sem capacidade de interpretar pixels. Use para extrair dimensões, formato, cores dominantes e um resumo objetivo do conteúdo visual.

## Pré-requisitos
- Python 3 instalado e acessível no PATH (`python --version`)
- Biblioteca Pillow instalada (`pip install Pillow`)
- Caminho do arquivo de imagem conhecido (ex.: `{caminho_anexo}`)

## Procedimento

1. **Localize o arquivo do anexo**
   - Confirme o caminho completo do arquivo (ex.: `{caminho_anexo}`)
   - Verifique que existe e o tamanho em bytes:
     ```bash
     ls -la "{caminho_anexo}"
     ```

2. **Valide o formato pelo cabeçalho binário**
   - Leia os primeiros bytes para confirmar o tipo real (não confie só na extensão):
     ```bash
     python -c "print(open(r'{caminho_anexo}','rb').read(8))"
     ```
   - Assinatura PNG: começa com `b'\x89PNG\r\n\x1a\n'`
   - Assinatura JPG: começa com `b'\xff\xd8\xff'`

3. **Extraia metadados básicos com Pillow**
   ```python
   from PIL import Image
   img = Image.open(r"{caminho_anexo}")
   print("formato:", img.format)
   print("modo:", img.mode)          # ex.: RGB, RGBA, L
   print("tamanho:", img.size)       # (largura, altura)
   print("info:", img.info)          # metadados embutidos
   ```

4. **Extraia as cores dominantes**
   ```python
   from PIL import Image
   img = Image.open(r"{caminho_anexo}").convert("RGB")
   pequena = img.resize((64, 64))
   cores = pequena.getcolors(maxcolors=64*64)
   cores.sort(reverse=True)
   for qtd, cor in cores[:5]:
       print(qtd, cor)  # (R, G, B)
   ```

5. **Gere um resumo objetivo do conteúdo**
   - Se a imagem for pequena e com poucas cores → provavelmente padrão de teste, ícone ou forma geométrica simples
   - Se houver muitas cores e variação → foto ou ilustração
   - Descreva em texto: dimensões, formato, modo de cor, paleta dominante e classificação provável
   - **Deixe explícito** que é análise estatística de pixels, não leitura semântica (não há OCR/visão real)

6. **Se precisar de leitura semântica real**
   - Instale OCR para texto: `pip install pytesseract` + binário Tesseract
   - Ou use um modelo de visão (ex.: API multimodal) enviando o arquivo
   - Caso contrário, informe ao usuário que a descrição é limitada a metadados e cores

## Erros conhecidos e soluções
- **`ModuleNotFoundError: No module named 'PIL'`** → rodar `pip install Pillow`
- **`UnidentifiedImageError`** → arquivo corrompido ou não é imagem; validar cabeçalho binário (passo 2)
- **Ferramenta de leitura devolve só base64** → normal em ambientes sem visão; seguir este procedimento com Pillow
- **Imagem muito grande** → redimensionar antes de contar cores (`img.resize((64,64))`) para evitar lentidão
- **Modo `P` ou `L`** → converter para `RGB` antes de extrair cores (`img.convert("RGB")`)

## Exemplo real (da tarefa que originou esta skill)
Anexo `teste_anexo.png` (2.939 bytes, 360×360 px) enviado pelo usuário. A IA principal identificou pelo cabeçalho binário que era PNG válido 8 bits RGB, mas não conseguiu descrever o conteúdo visual — a ferramenta devolveu apenas base64. Solução proposta: rodar script Python com Pillow para extrair dimensões, cores dominantes e resumo dos pixels. O nome "teste_anexo" e o tamanho minúsculo indicam imagem de teste (padrão de cor ou forma gerada automaticamente), mas isso deve ser confirmado pela análise de cores do passo 4, não por suposição.