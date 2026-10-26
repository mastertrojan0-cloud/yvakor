<!-- skill: abrir-chamado-protocolo-virtual-am | tags: protocolo, chamado, peticionamento, amazonas, sefaz, govbr | status: nova -->
# Abrir chamado no Protocolo Virtual do Amazonas

## Quando usar
Use quando o usuário pedir para "abrir um chamado", "abrir protocolo", "peticionar" ou "registrar solicitação" em órgãos do Amazonas (SEFAZ-AM, JUCAM, SEDECTI etc.) pelo Protocolo Virtual. Gatilhos: usuário está na tela de login do Protocolo Virtual e quer prosseguir.

## Pré-requisitos
- Acesso ao site do Protocolo Virtual do Amazonas (página de login aberta)
- Uma das 3 formas de autenticação:
  - **Login e Senha** da Nota Fiscal Amazonense (CPF + senha)
  - **gov.br** nível **prata** ou **ouro** (recomendado — mais rápido)
  - **Certificado Digital** e-CPF/e-CNPJ + Assinador instalado
- Documentos a anexar em PDF (limite típico: 5–10 MB por arquivo)
- Definido: assunto do chamado, tipo de pessoa (CPF/CNPJ), órgão destinatário

## Procedimento
1. Confirme que a página aberta é a **tela de login** do Protocolo Virtual. Se não estiver logado, não é possível peticionar.
2. Pergunte ao usuário qual forma de login ele possui. Se tiver conta gov.br prata/ouro, **recomende gov.br**.
3. Autentique-se pela forma escolhida e aguarde o redirecionamento para a área logada.
4. Antes de clicar, colete do usuário as 3 informações essenciais:
   - **Assunto** do chamado (ex.: "restituição de ICMS", "consulta de débito", "recurso de auto de infração", "abertura de empresa")
   - **Tipo de pessoa**: CPF (física) ou CNPJ (jurídica)
   - **Órgão destinatário** (ex.: SEFAZ-AM, JUCAM, SEDECTI)
5. No menu logado, entre em **Peticionamento** (ou **Novo Processo**).
6. Selecione o **tipo de processo** adequado (Consulta, Recurso, Defesa, Solicitação etc.).
7. Selecione o **órgão destinatário**.
8. Preencha os **dados do interessado** (CPF/CNPJ e nome).
9. Preencha **assunto** e **texto/descrição** do pedido. Se o usuário pedir, redija o corpo do chamado pronto para colar.
10. **Anexe os documentos** em PDF (respeitando o limite por arquivo).
11. **Assine digitalmente** se exigido, ou confirme o envio.
12. Registre e informe ao usuário o **número do protocolo** gerado — oriente a guardá-lo.

## Erros conhecidos e soluções
| Erro | Solução |
|------|---------|
| Usuário não consegue logar com senha | Verifique se tem conta na Nota Fiscal Amazonense; senão, ofereça gov.br ou certificado digital |
| gov.br recusado | Conta precisa ser nível **prata** ou **ouro**; nível bronze não serve — oriente elevar o nível |
| Certificado digital não reconhecido | Confirme que o **Assinador** está instalado e o e-CPF/e-CNPJ conectado |
| Anexo rejeitado | Verifique formato (PDF) e tamanho (≤ 5–10 MB); comprima ou divida o arquivo |
| Não encontra "Peticionamento" no menu | Procure por "Novo Processo"; o rótulo varia conforme o órgão |
| Assinatura exigida e não configurada | Instale o Assinador e refaça a assinatura antes de confirmar |

## Exemplo real (da tarefa que originou esta skill)
**Pedido:** "PRECISO ABRIR UM CHAMADO"
**Situação:** usuário estava na tela de login do Protocolo Virtual do Amazonas.
**Ação:** IA explicou as 3 formas de login (recomendando gov.br), descreveu o fluxo de peticionamento em 8 etapas e pediu as 3 informações essenciais (assunto, CPF/CNPJ, órgão) para montar o texto do chamado e guiar clique a clique.
**Próximo passo:** com as 3 respostas, redigir o corpo do chamado e conduzir o peticionamento até a emissão do número de protocolo.