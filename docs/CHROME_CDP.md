# Chrome real via CDP

O YVAKOR usa o **Google Chrome instalado** com um perfil dedicado e
`--remote-debugging-port=9222`. O Playwright se conecta via **CDP**
(`connect_over_cdp`), sem as flags típicas de automação
(`--enable-automation`, `--disable-blink-features=AutomationControlled`).

## Por que reduz bloqueios

- É o Chrome real, não o Chromium de automação.
- `navigator.webdriver` permanece **false**.
- O perfil é persistente: cookies e login sobrevivem entre execuções.
- Sem `--headless`: o Google costuma tratar headless como suspeito.
- Sem automação de senha: o login é feito **uma vez, manualmente**, na janela
  do Chrome.

## Como usar

1. Abra o YVAKOR e peça algo como “abra o YouTube no Chrome”.
2. Se o Chrome dedicado ainda não estiver aberto, o YVAKOR o inicia em
   `http://127.0.0.1:9222` com o perfil
   `data/browser_profiles/chrome-cdp`.
3. Faça login manualmente na janela do Chrome (Google, sites etc.).
4. Depois disso, o agente reutiliza a sessão. O painel **TELA** mostra a página
   ao vivo dentro da conversa.

## Status

`GET /api/browser` mostra `modo: "cdp"`, `cdp_url` e `engine: "chrome (CDP)"`.
`GET /api/browser/screenshot` devolve o frame atual.

## Limites honestos

- CAPTCHA, 2FA e “verifique se é você” continuam exigindo ação humana; o
  agente deve pausar e pedir sua intervenção.
- Nenhuma técnica garante 100% de não bloqueio: o Google muda as regras.
- Use apenas em contas/sites que você tem direito de automatizar; respeite os
  termos de uso.
- O perfil em `data/browser_profiles/chrome-cdp` contém cookies: trate como
  credencial sensível.

## Configuração

Em `config/settings.yaml`:

```yaml
browser:
  motor_padrao: "chrome"
  engines:
    chrome:
      channel: "chrome"
      profile_dir: "data/browser_profiles/chrome-cdp"
      mode: "cdp"
      cdp_url: "http://127.0.0.1:9222"
```

Se o Chrome não estiver rodando, o YVAKOR o inicia automaticamente.
