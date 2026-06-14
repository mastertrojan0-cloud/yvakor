<!-- skill: elaborar-termo-referencia-seguranca | tags: seguranca-eletronica, licitacao, especificacao-tecnica, cfTV, controle-acesso | status: nova -->
# Elaborar termo de referência para projetos de segurança eletrônica

## Quando usar
Quando precisar redigir especificações técnicas formais para licitações públicas, concorrências privadas ou propostas comerciais de sistemas de segurança eletrônica, incluindo CFTV, alarme de intrusão, controle de acesso e cerca elétrica.

## Pré-requisitos
1. Levantamento técnico do local (planta baixa, perímetro, pontos críticos) — documento {nome-arquivo-planta}
2. Lista de equipamentos pretendidos com marcas/modelos de referência — planilha {nome-planilha}
3. Normas técnicas aplicáveis (ABNT NBR, portarias, legislação local) — checklist {normas-checklist}
4. Template de TR da organização contratante — arquivo {template-tr}
5. Acesso ao sistema de protocolo ou pasta compartilhada para salvar versões

## Procedimento

### 1. Coletar dados do projeto
1.1. Abra o levantamento técnico {nome-arquivo-planta} e identifique:
   - Área total do perímetro (m² ou m linear)
   - Número de acessos (portas, portões, catracas)
   - Pontos cegos ou vulnerabilidades identificadas
1.2. Consulte a planilha {nome-planilha} e extraia:
   - Modelos de câmeras (resolução, lente, infravermelho)
   - Modelos de sensores (tipo, alcance, frequência)
   - Controladoras de acesso (marcas, protocolos, capacidade)
1.3. Verifique no checklist {normas-checklist} quais normas são obrigatórias (ex.: NBR 15247 para CFTV, NBR 14565 para cabeamento)

### 2. Estruturar o documento
2.1. Abra o template {template-tr} e crie uma cópia com nome: `TR_{cliente}_{data}.docx`
2.2. Preencha o cabeçalho com:
   - Órgão/empresa contratante: {nome-contratante}
   - Objeto: "Contratação de empresa especializada para fornecimento, instalação e manutenção de sistema de segurança eletrônica no(a) {local}"
   - Data prevista para abertura: {data-abertura}
2.3. Mantenha a numeração de seções do template, substituindo apenas o conteúdo técnico

### 3. Redigir especificações técnicas (seção principal)
3.1. Para cada subsistema, crie uma subseção seguindo o padrão:
   - **Descrição geral**: "Sistema de {subsistema} composto por {quantidade} {equipamento} com capacidade de {função}"
   - **Especificações mínimas**: liste parâmetros obrigatórios (ex.: "Resolução mínima de 2 MP", "Alcance IR de 30 m")
   - **Marcas de referência**: cite 2-3 marcas aceitas (ex.: "Intelbras, Hikvision, Dahua")
   - **Garantia e suporte**: "Garantia mínima de {x} anos, suporte técnico presencial em até {y} horas"
3.2. Exemplo de especificação para CFTV:
   ```
   Item 1.1 — Câmera IP bullet externa
   - Resolução: 2 MP (1920x1080) ou superior
   - Lente: 2.8 mm a 12 mm (varifocal)
   - IR: alcance mínimo 30 m
   - Proteção: IP67, IK10
   - Alimentação: PoE (802.3af)
   - Compressão: H.265
   - Marca referência: Intelbras VIP S3220 D ou similar técnico
   ```
3.3. Para controle de acesso:
   ```
   Item 2.1 — Controladora de acesso 2 portas
   - Capacidade: 2 portas, 5000 usuários
   - Protocolo: TCP/IP, Wiegand 26/34 bits
   - Alimentação: 12 VDC, 1 A
   - Bateria interna: backup mínimo 4 h
   - Marca referência: Intelbras IA 2000 ou similar
   ```

### 4. Incluir obrigações da contratada
4.1. Adicione cláusulas padrão:
   - "A contratada deverá apresentar ART (Anotação de Responsabilidade Técnica) do responsável pelo projeto"
   - "Fornecer manual de operação e manutenção em português"
   - "Treinar equipe do contratante por no mínimo {horas} horas"
   - "Garantir interoperabilidade entre subsistemas (CFTV, alarme, controle de acesso)"

### 5. Revisar e finalizar
5.1. Execute verificação ortográfica e gramatical (atalho F7 no Word ou comando `aspell check TR_*.docx`)
5.2. Confira se todas as normas do checklist {normas-checklist} foram citadas
5.3. Salve o arquivo na pasta {pasta-destino} com nome padronizado
5.4. Exporte para PDF com nome: `TR_{cliente}_{data}_assinavel.pdf`

## Erros conhecidos e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| Especificação muito genérica | Não usou marcas de referência | Adicione 2-3 marcas com "ou similar técnico" |
| Norma desatualizada | Copiou de TR antigo | Consulte site da ABNT ou portaria mais recente |
| Prazo de garantia inconsistente | Template com valor padrão | Ajuste para mínimo 3 anos (mercado segurança) |
| Falta de ART | Esqueceu cláusula | Insira no item "Obrigações da contratada" |
| Equipamento incompatível | Misturou protocolos (ex.: analógico + IP) | Especifique apenas um padrão por subsistema |

## Exemplo aplicado ao contexto do usuário

**Cenário**: Antonio precisa elaborar TR para licitação de segurança eletrônica da P&G Manaus (galpão logístico de 5000 m²).

**Dados de entrada**:
- Planta: `planta_PG_galpao_2026.dwg`
- Planilha: `equipamentos_referencia_PG.xlsx`
- Normas: NBR 15247 (CFTV), NBR 14565 (cabeamento), NR-10 (elétrica)
- Template: `template_TR_PG.docx`

**Passos executados**:
1. Abriu planta e identificou: 8 portas de acesso, 20 pontos de câmera, perímetro de 800 m lineares
2. Da planilha extraiu: câmeras Intelbras VIP S3220 D (20 unidades), controladoras IA 2000 (4 unidades), sensores IVP 4000 (30 unidades)
3. Criou `TR_PG_Manaus_2026-07-15.docx` a partir do template
4. Redigiu especificações seguindo o padrão do procedimento
5. Incluiu ART, treinamento de 8h, garantia de 3 anos
6. Salvou em `\\servidor\contratos\PG\TR_seguranca\` e exportou PDF

**Resultado**: TR completo e conforme normas, pronto para envio ao setor de licitações.
