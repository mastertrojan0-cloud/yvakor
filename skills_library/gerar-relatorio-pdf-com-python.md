<!-- skill: gerar-relatorio-pdf-com-python | tags: python, pdf, reportlab, weasyprint, relatorio | status: nova -->
# Gerar relatório PDF com Python (ReportLab/WeasyPrint)

## Quando usar
Quando precisar criar relatórios de segurança, propostas comerciais ou documentos técnicos em PDF com formatação profissional, incluindo tabelas, gráficos, cabeçalhos/rodapés e imagens.

## Pré-requisitos
- Python 3.8+ instalado
- Pip atualizado
- Acesso à internet para instalar dependências (ou repositório local configurado)

## Procedimento

### 1. Instalar dependências
```bash
pip install reportlab weasyprint matplotlib
```

### 2. Estruturar dados do relatório
Crie um dicionário com os dados que serão inseridos no PDF:
```python
dados_relatorio = {
    "titulo": "Relatório de Inspeção de Segurança",
    "cliente": "P&G Manaus",
    "data": "2026-06-12",
    "responsavel": "Antonio Cordero",
    "itens": [
        {"descricao": "Câmera IP modelo X", "status": "OK", "observacao": "Firmware atualizado"},
        {"descricao": "Sensor de presença Y", "status": "Falha", "observacao": "Substituir bateria"},
    ],
    "conclusao": "Sistema operacional, exceto sensor Y que requer manutenção."
}
```

### 3. Gerar PDF com WeasyPrint (recomendado para relatórios com formatação rica)
Crie um arquivo HTML com o template e converta para PDF:

```python
from weasyprint import HTML
import json

def gerar_pdf_weasyprint(dados, nome_arquivo="relatorio.pdf"):
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #3498db; color: white; }}
            .status-ok {{ color: green; font-weight: bold; }}
            .status-falha {{ color: red; font-weight: bold; }}
            .footer {{ margin-top: 30px; font-size: 12px; color: #7f8c8d; }}
        </style>
    </head>
    <body>
        <h1>{dados['titulo']}</h1>
        <p><strong>Cliente:</strong> {dados['cliente']}</p>
        <p><strong>Data:</strong> {dados['data']}</p>
        <p><strong>Responsável:</strong> {dados['responsavel']}</p>
        
        <h2>Itens Inspecionados</h2>
        <table>
            <tr>
                <th>Descrição</th>
                <th>Status</th>
                <th>Observação</th>
            </tr>
            {''.join(f"<tr><td>{item['descricao']}</td><td class='status-{item['status'].lower()}'>{item['status']}</td><td>{item['observacao']}</td></tr>" for item in dados['itens'])}
        </table>
        
        <h2>Conclusão</h2>
        <p>{dados['conclusao']}</p>
        
        <div class="footer">
            <p>Documento gerado automaticamente por ACM Digital - {dados['data']}</p>
        </div>
    </body>
    </html>
    """
    
    HTML(string=html_template).write_pdf(nome_arquivo)
    print(f"PDF gerado: {nome_arquivo}")

# Uso:
gerar_pdf_weasyprint(dados_relatorio, "relatorio_seguranca.pdf")
```

### 4. Alternativa: Gerar PDF com ReportLab (para controle pixel a pixel)
```python
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

def gerar_pdf_reportlab(dados, nome_arquivo="relatorio.pdf"):
    doc = SimpleDocTemplate(nome_arquivo, pagesize=A4)
    estilos = getSampleStyleSheet()
    elementos = []
    
    # Título
    elementos.append(Paragraph(dados['titulo'], estilos['Title']))
    elementos.append(Spacer(1, 12))
    
    # Metadados
    elementos.append(Paragraph(f"<b>Cliente:</b> {dados['cliente']}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>Data:</b> {dados['data']}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>Responsável:</b> {dados['responsavel']}", estilos['Normal']))
    elementos.append(Spacer(1, 20))
    
    # Tabela de itens
    dados_tabela = [["Descrição", "Status", "Observação"]]
    for item in dados['itens']:
        dados_tabela.append([item['descricao'], item['status'], item['observacao']])
    
    tabela = Table(dados_tabela, colWidths=[250, 80, 200])
    tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elementos.append(tabela)
    elementos.append(Spacer(1, 20))
    
    # Conclusão
    elementos.append(Paragraph("<b>Conclusão:</b>", estilos['Heading2']))
    elementos.append(Paragraph(dados['conclusao'], estilos['Normal']))
    
    doc.build(elementos)
    print(f"PDF gerado: {nome_arquivo}")

# Uso:
gerar_pdf_reportlab(dados_relatorio, "relatorio_reportlab.pdf")
```

### 5. Adicionar gráfico ao PDF (com matplotlib)
```python
import matplotlib.pyplot as plt
import io
from weasyprint import HTML

def gerar_grafico_status(itens):
    status_count = {}
    for item in itens:
        s = item['status']
        status_count[s] = status_count.get(s, 0) + 1
    
    fig, ax = plt.subplots()
    ax.bar(status_count.keys(), status_count.values(), color=['green', 'red', 'orange'])
    ax.set_title('Distribuição de Status')
    ax.set_ylabel('Quantidade')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150)
    buf.seek(0)
    plt.close()
    return buf

# Incorpore no HTML do WeasyPrint:
# <img src="data:image/png;base64,{base64.b64encode(buf.read()).decode()}" />
```

## Erros conhecidos e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| `ModuleNotFoundError: No module named 'weasyprint'` | Dependência não instalada | Execute `pip install weasyprint` |
| `OSError: cannot load library 'pango'` | Faltam bibliotecas do sistema (Linux) | `sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0` |
| `UnicodeDecodeError` | Caractere especial no HTML | Use `encoding='utf-8'` no HTML e dados |
| PDF gerado em branco | Dados vazios ou HTML mal formado | Verifique se `dados['itens']` não está vazio |
| `PermissionError` | Arquivo PDF aberto em outro programa | Feche o visualizador de PDF e tente novamente |
| Gráfico não aparece | Caminho da imagem incorreto | Use base64 embutido no HTML (exemplo acima) |

## Exemplo aplicado ao contexto do usuário

**Cenário:** Antonio precisa gerar um relatório de inspeção semanal para a P&G Manaus, com 15 câmeras e 10 sensores, incluindo status e observações.

**Solução completa (script executável):**
```python
# relatorio_semanal_pg.py
import json
from datetime import datetime
from weasyprint import HTML

def gerar_relatorio_pg():
    dados = {
        "titulo": "Relatório Semanal de Segurança - P&G Manaus",
        "cliente": "P&G Manaus - Planta Industrial",
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "responsavel": "Antonio Cordero - Security Dynamics",
        "itens": [
            {"descricao": "Câmera Domo - Entrada Principal", "status": "OK", "observacao": "Operacional"},
            {"descricao": "Câmera Bullet - Estacionamento", "status": "OK", "observacao": "Lente limpa"},
            {"descricao": "Sensor Magnético - Portaria", "status": "Falha", "observacao": "Trocar bateria CR123"},
            # ... adicione mais itens conforme necessário
        ],
        "conclusao": "Sistema de segurança operacional. Agendar manutenção do sensor da portaria para amanhã."
    }
    
    html = f"""<!DOCTYPE html>
    <html><head><meta charset="utf-8"><style>
        body {{ font-family: Arial; margin: 30px; }}
        h1 {{ color: #1a5276; }}
        .ok {{ color: green; }} .falha {{ color: red; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border: 1px solid #999; padding: 8px; }}
        th {{ background: #1a5276; color: white; }}
    </style></head><body>
        <h1>{dados['titulo']}</h1>
        <p><b>Data:</b> {dados['data']}</p>
        <p><b>Responsável:</b> {dados['responsavel']}</p>
        <table><tr><th>Item</th><th>Status</th><th>Obs</th></tr>
        {''.join(f"<tr><td>{i['descricao']}</td><td class='{i['status'].lower()}'>{i['status']}</td><td>{i['observacao']}</td></tr>" for i in dados['itens'])}
        </table>
        <h2>Conclusão</h2><p>{dados['conclusao']}</p>
        <p style='font-size:10px;color:gray;'>Gerado por ACM Digital - Security Automation</p>
    </body></html>"""
    
    nome = f"relatorio_pg_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    HTML(string=html).write_pdf(nome)
    print(f"✅ Relatório salvo: {nome}")

if __name__ == "__main__":
    gerar_relatorio_pg()
```

**Automação adicional:** Agende com cron (Linux) ou Task Scheduler (Windows) para rodar toda segunda-feira às 8h.
