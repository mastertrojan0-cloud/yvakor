# Extensão YVAKOR para Chrome

Painel lateral de chat para dar instruções ao YVAKOR e acompanhar o processo
das tarefas enquanto o Chrome está aberto.

## Instalar (uma vez)

1. Rode `INSTALAR-CHROME-EXTENSAO.bat` na raiz do projeto.
   Ele abre `chrome://extensions` e a pasta `chrome-extension`.
2. Em `chrome://extensions`, ative **Modo do desenvolvedor**.
3. Clique em **Carregar sem compactação** e escolha a pasta
   `E:\YVAKOR\yvakor\chrome-extension`.
4. Permita **acesso aos sites** quando o Chrome pedir (necessário para ler o
   conteúdo da página).
5. Fixe o ícone do YVAKOR na barra e clique nele: o painel lateral abre.
5. Arraste a divisória do painel para ~360–400 px: ele fica compacto à direita
   e o Chrome continua visível à esquerda.

Requisitos: Chrome 114+ (Side Panel API) e o núcleo do YVAKOR rodando em
`http://127.0.0.1:7777`.

## O que o painel faz

- **Um único chat**, sem abas ou telas extras.
- **Lê o conteúdo da aba ativa** (título, URL, descrição, seções e seleção)
  automaticamente, mostra quantos caracteres leu e atualiza ao trocar de aba
  ou ao carregar a página.
- O núcleo seleciona os trechos relevantes da página para responder com
  fundamento, em vez de cortar o texto cegamente.
- Quando o texto é curto ou o pedido é visual, captura a tela automaticamente
  e o núcleo faz OCR — o usuário não precisa enviar print.
- Conversa com a página como contexto; se a página for protegida, usa ao menos
  título e URL.
- Mostra o **PROCESSO** ao vivo: passos reais de `/api/progress`.
- **Nova conversa** no mesmo painel.
- Renderiza respostas, imagens e arquivos gerados.
- **Voz neural** do núcleo (Antonio) com botão 🔊/🔇; botão “ouvir” quando o
  navegador bloqueia autoplay.
- Status online/offline do núcleo.

## Arquivos

- `manifest.json` — MV3, permissões `sidePanel`, `scripting` e host local.
- `background.js` — abre o painel ao clicar no ícone e verifica a versão.
- `sidepanel.html/css/js` — interface e integração com o núcleo.
- `build.json` — versão/build sincronizados pelo núcleo.
- `fonts/` — Inter e Lora (fontes locais).
- `icons/icon128.png`.

## Atualização sincronizada

O núcleo roda `python -m yvakor.extensao` ao iniciar: copia as fontes,
atualiza a versão do `manifest.json` e grava `build.json`. Se o build do
núcleo mudar, o ícone mostra **!** e o painel exibe **atualizar**. Clique no
botão (ou recarregue a extensão em `chrome://extensions`) para aplicar.

## Segurança

O painel fala apenas com `127.0.0.1:7777`. O servidor aceita CORS de origens
`chrome-extension://` e do próprio YVAKOR. Não exponha a API na internet sem
autenticação.
