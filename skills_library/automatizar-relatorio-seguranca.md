<!-- skill: automatizar-relatorio-seguranca | tags: seguranca-eletronica, relatorio, pg, security-dynamics | status: nova -->
# Automação de relatório de segurança eletrônica

## Quando usar
Quando precisar gerar relatórios padronizados de inspeção/manutenção de sistemas de segurança eletrônica para clientes como Security Dynamics ou P&G Manaus. Inclui CFTV, alarme, controle de acesso, cerca elétrica e sensores perimetrais.

## Pré-requisitos
- Acesso ao template do relatório (Word, Google Docs ou Markdown)
- Dados da visita técnica coletados em campo (fotos, medições, observações)
- Ferramenta de edição de texto instalada (Word, LibreOffice ou VS Code)
- Conexão com internet para upload de fotos (se aplicável)

## Procedimento

1. **Identifique o cliente e o tipo de serviço**
   - Verifique se é Security Dynamics ou P&G Manaus (ou outro)
   - Identifique se é manutenção preventiva, corretiva ou instalação nova
   - Anote data, horário e técnico responsável

2. **Abra o template de relatório**
   - Localize o arquivo `template-relatorio-{cliente}.{ext}` na pasta `\\servidor\relatorios\` ou no Google Drive
   - Faça uma cópia com nome: `relatorio-{cliente}-{data}-{tecnico}.{ext}`
   - Exemplo: `relatorio-security-dynamics-2026-06-12-antonio.docx`

3. **Preencha os dados do cabeçalho**
   - Cliente: {nome_do_cliente}
   - Endereço: {endereco_completo}
   - Data da visita: {data_visita}
   - Técnico responsável: {nome_tecnico}
   - Tipo de serviço: {preventiva / corretiva / instalacao}

4. **Registre os equipamentos inspecionados**
   - Liste cada equipamento em formato de tabela:
     | Equipamento | Marca/Modelo | Quantidade | Status | Observações |
     |-------------|--------------|------------|--------|-------------|
     | CFTV câmera | Hikvision DS-2CD2T47G2-L | 8 | OK | Limpeza realizada |
     | DVR | Hikvision DS-7608NI-I2 | 1 | OK | Firmware atualizado |
     | Alarme | Intelbras IVP 7000 | 1 | OK | Bateria substituída |
     | Sensor de presença | Intelbras IVP 1000 | 4 | OK | Teste de disparo OK |
     | Cerca elétrica | Intelbras CER 2000 | 1 | OK | Tensão 9.8kV |

5. **Documente as medições e testes realizados**
   - Para CFTV: verifique foco, ângulo, gravação, armazenamento
   - Para alarme: teste disparo, comunicação central, sensores
   - Para cerca elétrica: meça tensão, verifique isoladores, aterramento
   - Para controle de acesso: teste catracas, leitores, fechaduras
   - Anote valores exatos: `Tensão cerca: 9.8kV`, `Sinal RF: -65dBm`

6. **Insira as fotos no relatório**
   - Tire fotos de cada equipamento com identificação visível
   - Nomeie os arquivos: `{equipamento}_{data}_{local}.jpg`
   - Insira no relatório com legenda explicativa
   - Exemplo: `![Câmera Hikvision corredor principal](camera_hikvision_20260612_corredor.jpg)`

7. **Descreva as não conformidades encontradas**
   - Se houver problemas, descreva com detalhes técnicos
   - Exemplo: "Câmera 3 do estacionamento apresenta imagem com ruído excessivo. Recomenda-se substituição do cabo coaxial."
   - Classifique a gravidade: {critica / media / baixa}

8. **Registre os serviços executados**
   - Liste o que foi feito: limpeza, ajuste, substituição, configuração
   - Exemplo: "Substituída bateria do painel de alarme Intelbras IVP 7000 (bateria 12V 7Ah)"

9. **Preencha as recomendações**
   - Sugira melhorias ou próximas manutenções
   - Exemplo: "Recomenda-se upgrade do DVR para modelo com 16 canais para expansão futura"

10. **Finalize o relatório**
    - Revise ortografia e dados técnicos
    - Adicione assinatura digital ou campo para assinatura do cliente
    - Salve em PDF: `relatorio-{cliente}-{data}-final.pdf`
    - Envie por e-mail para o cliente e para o arquivo interno

## Erros conhecidos e soluções

| Erro | Causa | Solução |
|------|-------|---------|
| Template não encontrado | Caminho incorreto ou arquivo renomeado | Verifique na pasta `\\servidor\relatorios\templates\` ou peça ao Antonio |
| Foto não carrega no relatório | Nome do arquivo com caracteres especiais | Renomeie sem acentos ou espaços: `camera_hikvision_20260612.jpg` |
| Tabela de equipamentos desalinhada | Colagem de dados sem formatação | Use a ferramenta "Inserir Tabela" do Word e cole como texto simples |
| Medição de cerca elétrica abaixo do esperado | Sensor sujo ou mau contato | Limpe os isoladores e refaça a medição |
| Cliente não recebeu o e-mail | Anexo muito grande (>25MB) | Comprima as fotos para 800x600 pixels antes de anexar |

## Exemplo aplicado ao contexto do usuário

**Cenário:** Visita técnica à P&G Manaus para manutenção preventiva mensal do sistema de segurança.

**Dados coletados:**
- Data: 12/06/2026
- Técnico: Antonio Cordero
- Equipamentos: 12 câmeras Hikvision, 2 DVRs, 1 central de alarme Intelbras, 1 cerca elétrica CER 2000

**Relatório gerado:**
```
RELATÓRIO DE MANUTENÇÃO PREVENTIVA
Cliente: P&G Manaus
Endereço: Av. Torquato Tapajós, 5000 - Manaus/AM
Data: 12/06/2026
Técnico: Antonio Cordero

Equipamentos inspecionados:
| Equipamento | Marca/Modelo | Qtd | Status | Observações |
| CFTV câmera | Hikvision DS-2CD2T47G2-L | 12 | OK | Limpeza e ajuste de foco |
| DVR | Hikvision DS-7608NI-I2 | 2 | OK | Firmware atualizado |
| Alarme | Intelbras IVP 7000 | 1 | OK | Teste de comunicação OK |
| Cerca elétrica | Intelbras CER 2000 | 1 | OK | Tensão 9.8kV |

Serviços executados:
- Limpeza de todas as lentes das câmeras
- Atualização de firmware dos DVRs
- Teste de disparo do alarme (comunicação central OK)
- Medição e ajuste da tensão da cerca elétrica

Recomendações:
- Substituir cabo HDMI do DVR 2 (apresenta falha intermitente)
- Agendar manutenção corretiva para câmera do estoque 3 (imagem com ruído)

Assinatura: _________________________
Antonio Cordero - Técnico Responsável
```
