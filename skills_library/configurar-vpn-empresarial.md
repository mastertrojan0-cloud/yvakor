<!-- skill: gerar-skill-procedural | tags: documentacao, procedimento, skill, yvakor | status: nova -->
# Gerar skill procedural a partir de perfil de usuário
## Quando usar
Quando você, YVAKOR, identificar um padrão de tarefa repetitiva no contexto do usuário e precisar criar uma skill reutilizável e executável por um modelo local pequeno (7B). Use também quando o usuário solicitar explicitamente a criação de uma skill para um procedimento.

## Pré-requisitos
- Ter identificado claramente o procedimento a ser documentado.
- Conhecer o contexto de atuação do usuário (Antonio Cordero / ACM Digital / P&G / Security Dynamics).
- Ter acesso ao arquivo de identidade mestre do YVAKOR para referência de tom e regras.
- (Opcional) Ter executado o procedimento ao menos uma vez para validar os passos.

## Procedimento
1. **Identifique o procedimento e seu nome canônico.**
   - Extraia do contexto do usuário ou da tarefa solicitada o nome do procedimento (ex: "configurar-vpn-empresarial", "gerar-relatorio-diario-pg").
   - Use kebab-case, sem acentos, máximo 4 palavras.

2. **Defina as tags relevantes.**
   - Liste de 2 a 5 tags que categorizam a skill (ex: `vpn, seguranca, acesso-remoto, pg`).
   - Separe por vírgulas no formato `tags: t1, t2, t3`.

3. **Escreva o título da skill.**
   - Use o formato: `# {Nome do procedimento}`.
   - Seja descritivo e direto, ex: `# Configurar VPN empresarial para acesso remoto seguro`.

4. **Crie a seção "Quando usar".**
   - Descreva em 1-2 frases em quais situações este procedimento deve ser executado.
   - Use linguagem imperativa e referências ao contexto do usuário (P&G, Security Dynamics, ACM Digital).

5. **Liste os pré-requisitos.**
   - Ferramentas necessárias (ex: "OpenVPN client instalado", "Acesso ao portal de administração da VPN").
   - Informações que o usuário precisa ter em mãos (ex: "Endereço do servidor VPN", "Arquivo de configuração .ovpn").
   - Permissões ou acessos necessários (ex: "Credenciais de administrador da rede P&G").
   - **NUNCA** inclua credenciais reais; use placeholders como `{usuario_ad}`.

6. **Escreva o procedimento em passos numerados e imperativos.**
   - Cada passo deve ser uma ação clara e única.
   - Use comandos exatos quando fizer sentido (ex: `sudo openvpn --config /etc/openvpn/client.conf`).
   - Substitua valores variáveis por placeholders entre chaves: `{caminho_do_arquivo}`, `{ip_do_servidor}`.
   - Inclua verificações intermediárias (ex: "Verifique se a conexão foi estabelecida com `ping 10.8.0.1`").
   - Máximo de 15 passos; se for mais longo, considere dividir em sub-skills.

7. **Adicione a seção "Erros conhecidos e soluções".**
   - Liste erros comuns que podem ocorrer durante o procedimento.
   - Para cada erro, forneça:
     - Sintoma (ex: "A conexão falha com erro 'TLS handshake failed'")
     - Causa provável (ex: "Certificado do servidor expirou ou é inválido")
     - Solução (ex: "Solicite novo certificado ao administrador da VPN em {email_suporte}")
   - Mínimo de 2 erros, máximo de 5.

8. **Crie a seção "Exemplo aplicado ao contexto do usuário".**
   - Mostre um exemplo realista de uso da skill no dia a dia de Antonio Cordero.
   - Use placeholders preenchidos com valores fictícios mas plausíveis (ex: `vpn.pgmanaus.com.br`).
   - Inclua o resultado esperado (ex: "Após a execução, o acesso ao sistema interno P&G estará disponível via IP 10.8.0.x").

9. **Finalize com o cabeçalho da skill.**
   - No topo do arquivo, adicione o comentário HTML: `<!-- skill: {nome-da-skill} | tags: {tag1, tag2} | status: nova -->`
   - Substitua `{nome-da-skill}` pelo nome definido no passo 1.
   - Substitua `{tag1, tag2}` pelas tags definidas no passo 2.
   - Mantenha `status: nova` (a menos que seja uma atualização de skill existente).

10. **Revise a skill contra as regras do YVAKOR.**
    - Verifique se não há credenciais, tokens ou informações sensíveis.
    - Confirme que o tom é direto e técnico, em português brasileiro.
    - Garanta que um modelo 7B conseguiria seguir os passos sem ambiguidade.
    - Se aplicável, proponha a skill ao usuário antes de registrá-la definitivamente.

## Erros conhecidos e soluções
1. **Erro: Skill muito genérica, não específica ao contexto do usuário.**
   - Causa: Não incorporar elementos do perfil do usuário (P&G, Security Dynamics, ACM Digital).
   - Solução: Releia o contexto do usuário e adicione referências específicas (ex: "relatório de manutenção P&G", "proposta comercial ACM Digital").

2. **Erro: Passos ambíguos que um modelo 7B não consegue interpretar.**
   - Causa: Uso de linguagem vaga (ex: "configure a VPN apropriadamente").
   - Solução: Substitua por comandos exatos e verificações (ex: "Edite o arquivo /etc/openvpn/client.conf e adicione a linha `remote {servidor_vpn} 1194`").

3. **Erro: Placeholders inconsistentes ou mal nomeados.**
   - Causa: Usar nomes diferentes para o mesmo placeholder (ex: `{servidor}` e `{vpn_server}`).
   - Solução: Padronize os nomes dos placeholders e use-os consistentemente em todo o documento.

## Exemplo aplicado ao contexto do usuário
**Situação:** Antonio Cordero precisa criar uma skill para configurar acesso VPN ao sistema de monitoramento da Security Dynamics em Manaus, usado para acessar câmeras e sensores remotamente.

**Skill gerada (trecho):**
```markdown
<!-- skill: configurar-vpn-security-dynamics | tags: vpn, seguranca, security-dynamics, acesso-remoto | status: nova -->
# Configurar VPN para acesso remoto ao sistema Security Dynamics
## Quando usar
Quando precisar acessar o sistema de monitoramento Security Dynamics (câmeras, sensores, alarmes) de forma remota, seja para manutenção, suporte ou operação fora da sede em Manaus.
## Pré-requisitos
- Cliente OpenVPN instalado (versão 2.5 ou superior)
- Arquivo de configuração `.ovpn` fornecido pelo administrador da Security Dynamics
- Credenciais de usuário do sistema Security Dynamics (não incluir neste documento)
- Acesso à internet com porta UDP 1194 liberada
## Procedimento
1. Copie o arquivo de configuração `{cliente}.ovpn` para o diretório `/etc/openvpn/client/`.
2. Edite o arquivo e verifique se a linha `remote` aponta para `{servidor_vpn_security_dynamics}` na porta `1194`.
3. Execute o comando: `sudo openvpn --config /etc/openvpn/client/{cliente}.ovpn --daemon`
4. Verifique se a interface `tun0` foi criada: `ip addr show tun0`
5. Teste a conectividade com o servidor interno: `ping 10.200.0.1`
6. Se o ping falhar, verifique os logs: `journalctl -u openvpn@client --no-pager | tail -20`
7. Acesse o sistema Security Dynamics via navegador: `https://10.200.0.50:8443`
## Erros conhecidos e soluções
1. **Erro: "Options error: Unrecognized option or missing parameter(s)"**
   - Causa: Arquivo `.ovpn` corrompido ou versão incompatível do OpenVPN.
   - Solução: Solicite um novo arquivo ao administrador ou atualize o OpenVPN: `sudo apt update && sudo apt upgrade openvpn -y`.
2. **Erro: Conexão estabelecida mas não acessa o sistema Security Dynamics**
   - Causa: Rota não adicionada automaticamente.
   - Solução: Adicione rota manualmente: `sudo ip route add 10.200.0.0/16 via 10.8.0.1`
## Exemplo aplicado ao contexto do usuário
Antonio precisa acessar as câmeras do galpão da P&G em Manaus durante uma viagem. Ele usa o arquivo `antoniocordero-pg.ovpn` e o servidor `vpn.securitydynamics.manaus.com.br`. Após seguir os passos, o sistema fica acessível em `https://10.200.0.50:8443` com as credenciais do Security Dynamics.
```
