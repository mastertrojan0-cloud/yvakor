<!-- skill: criar-skill-procedural | tags: yvakor, documentacao, procedimento, reutilizavel | status: nova -->
# Criar uma skill procedural para o YVAKOR
## Quando usar
Sempre que você identificar um padrão de tarefa repetitiva que pode ser documentada como procedimento reutilizável. Isso inclui automações, configurações, processos de prospecção, deploys, troubleshooting, etc. O objetivo é transformar conhecimento tácito em instruções explícitas que você mesmo (ou outro agente) possa executar sem depender de contexto externo.

## Pré-requisitos
- Acesso ao repositório de skills (geralmente `skills/` no projeto do YVAKOR).
- Editor de texto (VS Code, vim, ou o próprio chat para gerar o conteúdo).
- Compreensão clara do procedimento a ser documentado (se não souber todos os passos, primeiro execute e documente depois).

## Procedimento
1. **Identifique o padrão.** Pergunte-se: "Esse procedimento será usado mais de uma vez? Ele pode ser padronizado?" Se sim, prossiga.
2. **Defina o título e as tags.** O título deve ser um verbo no infinitivo seguido de complemento (ex: "Configurar pipeline CI/CD com GitHub Actions"). As tags devem refletir o domínio (ex: `devops, github, automacao`). Use o formato `<!-- skill: {titulo-para-url} | tags: {tag1}, {tag2} | status: nova -->`.
3. **Escreva a seção "Quando usar".** Descreva em uma ou duas frases o cenário exato em que essa skill se aplica. Seja específico.
4. **Liste os pré-requisitos.** Tudo que é necessário antes de começar: ferramentas instaladas, permissões, arquivos, conhecimento prévio. Use checklist.
5. **Crie o procedimento numerado.** Cada passo deve ser uma ação imperativa e clara. Se houver comandos, inclua-os em blocos de código. Use placeholders `{assim}` para valores que mudam por caso. Exemplo:
   ```
   1. Acesse o diretório do projeto: `cd {caminho/do/projeto}`
   2. Execute o comando de build: `npm run build`
   ```
6. **Antecipe erros comuns.** Na seção "Erros conhecidos e soluções", liste pelo menos 2-3 erros que podem ocorrer e como resolvê-los. Seja prático.
7. **Inclua um exemplo aplicado ao contexto do usuário.** Mostre como a skill se aplica a um caso real do Antonio/ACM Digital. Isso garante relevância e facilita a compreensão.
8. **Revise a skill.** Leia o arquivo do começo ao fim. Um modelo 7B consegue seguir? Os placeholders estão claros? Faltou algum passo?
9. **Salve o arquivo.** Nomeie como `{titulo-para-url}.md` e salve no diretório de skills. Commit e push se aplicável.

## Erros conhecidos e soluções
- **Erro: A skill ficou muito genérica.**  
  Solução: Adicione mais detalhes específicos do contexto do usuário. Ex: em vez de "configure o servidor", diga "configure o servidor Nginx no Ubuntu 22.04 para o domínio {dominio}".
- **Erro: Passos ambíguos.**  
  Solução: Substitua "verifique a conexão" por "execute `ping -c 4 google.com` e confirme que o retorno é 0% de perda de pacotes".
- **Erro: Faltou um pré-requisito.**  
  Solução: Execute o procedimento mentalmente e veja se algo trava. Adicione o pré-requisito faltante.

## Exemplo aplicado ao contexto do usuário
Suponha que você, YVAKOR, acabou de configurar um pipeline CI/CD para um micro-SaaS do Antonio usando GitHub Actions. Você percebeu que esse processo se repetirá para outros projetos. Então você cria a skill "configurar-cicd-github-actions.md" seguindo este procedimento. O resultado será uma skill que você pode reutilizar sempre que Antonio disser: "YVAKOR, configura o CI/CD do novo projeto".
