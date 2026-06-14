# Conectores do YVAKOR — como configurar

Há dois tipos de login:

- **Token / senha de app** — você cola uma credencial. Não exige criar app OAuth.
  (E-mail SMTP/IMAP, Outlook, WhatsApp, Telegram.)
- **OAuth ("Entrar com X")** — clica, autoriza no site do provedor e volta. Exige
  criar **uma vez** um app OAuth e pôr o Client ID/Secret no `.env`.
  (Google: Calendar/Drive/Gmail · GitHub · Slack.)

> Por que o OAuth precisa do app? O botão "Entrar com X" sempre usa um app
> registrado no provedor. O YVAKOR não vem com um app embutido, então o primeiro
> passo é criar o seu (uma vez). Depois disso o login é um clique, pra sempre.

Em **todos** os apps OAuth, registre esta URI de redirecionamento:
`http://localhost:7777/api/oauth/callback`

---

## A) Gmail/e-mail SEM criar projeto — Senha de App (mais rápido)

Use o conector **"E-mail (SMTP/IMAP)"** (não o Gmail OAuth).

1. Ative a verificação em 2 etapas na sua Conta Google (obrigatório p/ senha de app).
2. Vá em **myaccount.google.com → Segurança → Senhas de app**.
3. Gere uma senha (16 caracteres) — copie.
4. No YVAKOR → 🔌 Conectores → **E-mail (SMTP/IMAP)** → Conectar, preencha:
   - E-mail: `voce@gmail.com`
   - Senha de app: a senha de 16 caracteres (NÃO a senha normal)
   - Servidor SMTP: `smtp.gmail.com` · Porta SMTP: `587`
   - Servidor IMAP: `imap.gmail.com`
5. Pronto. O agente pode `enviar_email` e `ler_emails`.

(Outlook: mesma ideia no conector "Outlook"; servidores já vêm preenchidos.)

---

## B) Google OAuth (Calendar + Drive + Gmail em um clique)

Cria-se **um** app OAuth que serve aos três.

1. Acesse **console.cloud.google.com** e crie/selecione um projeto.
2. **APIs e Serviços → Biblioteca**: ative as APIs que for usar:
   - Google Calendar API · Google Drive API · Gmail API.
3. **APIs e Serviços → Tela de consentimento OAuth**:
   - Tipo: Externo. Preencha nome do app e e-mail.
   - Em "Usuários de teste", **adicione seu próprio e-mail** (enquanto o app não
     for verificado, só usuários de teste conseguem autorizar).
4. **APIs e Serviços → Credenciais → Criar credenciais → ID do cliente OAuth**:
   - Tipo de aplicativo: **Aplicativo da Web**.
   - **URIs de redirecionamento autorizados**: `http://localhost:7777/api/oauth/callback`
   - Crie e copie o **Client ID** e o **Client Secret**.
5. No arquivo `.env` do YVAKOR, adicione:
   ```
   GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=xxxxxxxx
   ```
6. Reinicie o YVAKOR. Agora 🔌 Conectores mostra **"Entrar com Google"** (1 clique)
   em Calendar, Drive e Gmail. Clica → autoriza → volta conectado.

> Sem o `.env`, o botão fica como **"Configurar Google"** e abre o formulário
> pedindo Client ID/Secret (modo avançado, dá no mesmo).

---

## C) GitHub OAuth

1. **github.com/settings/developers → OAuth Apps → New OAuth App**.
2. Authorization callback URL: `http://localhost:7777/api/oauth/callback`
3. Crie e copie Client ID + gere um Client Secret.
4. No `.env`:
   ```
   GITHUB_CLIENT_ID=Iv1.xxxxxxxx
   GITHUB_CLIENT_SECRET=xxxxxxxx
   ```
5. Reinicie → "Entrar com GitHub" em um clique.

---

## D) Slack OAuth

1. **api.slack.com/apps → Create New App** (from scratch).
2. **OAuth & Permissions**:
   - Bot Token Scopes: `chat:write`, `channels:read`, `groups:read`.
   - Redirect URLs: `http://localhost:7777/api/oauth/callback`
     (o Slack costuma exigir https; se recusar, use um túnel como ngrok).
3. Em **Basic Information**, copie o Client ID e Client Secret.
4. No `.env`:
   ```
   SLACK_CLIENT_ID=xxxxxxxx.xxxxxxxx
   SLACK_CLIENT_SECRET=xxxxxxxx
   ```
5. Reinicie → "Entrar com Slack" em um clique.
