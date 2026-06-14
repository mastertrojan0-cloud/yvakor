<!-- skill: relatorio-pdf-pg | tags: pdf, reportlab, p&g, security-dynamics | status: estavel -->
# Gerar relatório PDF profissional padrão Security Dynamics / P&G

## Quando usar
Quando o usuário pedir relatório técnico, inspeção ou análise em PDF para
P&G (Rio Negro / Rio Solimões) ou clientes Security Dynamics.

## Procedimento
1. Stack: Python + ReportLab (ou Playwright p/ HTML→PDF em layouts complexos).
2. Cores da marca: SD_RED #C0272D, SD_DARK #1A1A1A.
3. Estrutura: capa → sumário executivo (KPIs) → corpo técnico por zona → anexos.
4. Sempre incluir: data, responsável técnico, versão do documento.
5. Equipamentos citados devem ser NDAA-compliant (VIVOTEK, Axis, Bosch, Optex, Raytec).
6. Validar com o usuário antes de gerar versão final.

## Erros conhecidos
- Falsos alarmes em cerca Fence Lite: causa real é micro-vibração de vegetação,
  NÃO pontos cegos visuais. Não repetir esse erro de diagnóstico.
- Nunca incluir credenciais ou tokens em logs/anexos do relatório.
