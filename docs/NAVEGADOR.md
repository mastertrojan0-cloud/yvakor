# Navegador controlado — como funciona e como usar

O YVAKOR dirige um navegador real (Edge ou Chrome) através do Playwright.
Não é `requests` nem scraping de HTML: há JavaScript, cookies, login, abas e
cliques de verdade.

---

## 0. Dois motores: Edge e Chrome

Cada navegador tem **processo e perfil próprios** (`data/browser_profiles/edge`
e `.../chrome`), então logins não se misturam. Toda ferramenta aceita
`navegador`:

```
navegador_abrir("https://site.com", navegador="chrome")
navegador_ver(navegador="edge")
navegador_motores()          # estado dos dois
```

Sem o parâmetro, vale o motor da tarefa (se definido) ou `browser.motor_padrao`.

```yaml
browser:
  motor_padrao: "edge"
  engines:
    edge:   {channel: msedge, mode: launch, profile_dir: data/browser_profiles/edge}
    chrome: {channel: chrome, mode: launch, profile_dir: data/browser_profiles/chrome}
```

**Aba por tarefa:** cada tarefa cowork roda na própria aba; o chat usa
`principal`. Duas tarefas simultâneas não sobrescrevem a página uma da outra.

**Anexar a um navegador já aberto (CDP):**

```bash
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 --user-data-dir="%CD%\data\chrome-cdp"
```

Depois: *"conecte ao Chrome em http://127.0.0.1:9222"* →
`navegador_conectar("chrome", "http://127.0.0.1:9222")`. O YVAKOR não fecha
esse navegador ao terminar (só solta a conexão).

---

## 1. Como o agente "enxerga" a página

Modelos de texto não veem pixels. Então o YVAKOR usa um **snapshot de
acessibilidade**:

1. O agente chama `navegador_ver`.
2. A página é inspecionada e cada elemento interativo visível recebe um
   atributo temporário `data-yvk-ref="eN"`.
3. O agente recebe um resumo compacto:

```
URL: https://exemplo.com/login
TÍTULO: Entrar — Exemplo
ROLAGEM: 0px de 1240px

TEXTO VISÍVEL:
Bem-vindo de volta. Entre com sua conta para continuar.

ELEMENTOS INTERATIVOS (aja pela ref, ex.: "e3"):
[e1] campo:email "E-mail"
[e2] campo:password "Senha" valor="••••••"
[e3] button "Entrar"
[e4] link "Esqueci minha senha" → https://exemplo.com/reset
```

4. O agente age por ref: `navegador_clicar {"alvo":"e3"}`.
5. Depois de qualquer mudança de página, ele chama `navegador_ver` de novo —
   **as refs antigas expiram**.

Isso é o que torna o ciclo confiável com modelos de texto: nada de adivinhar
coordenadas de pixel.

---

## 2. Ferramentas disponíveis

| Ferramenta | Para que serve |
|---|---|
| `navegador_abrir(url)` | Abre o navegador e navega (se o texto não for URL, busca) |
| `navegador_ir(url)` | Navega a aba atual |
| `navegador_ver()` | Snapshot: texto + elementos com refs (**sempre antes de agir**) |
| `navegador_clicar(alvo)` | Clique real (ref, seletor CSS ou texto) |
| `navegador_preencher(alvo, valor, enviar?)` | Digita, marca checkbox/select; `enviar=true` dá Enter |
| `navegador_pressionar(tecla, alvo?)` | Enter, Tab, Escape, Control+A… |
| `navegador_rolar(direcao, vezes)` | baixo/cima/topo/fim |
| `navegador_esperar(segundos?, seletor?)` | Espera JS/requisição terminar |
| `navegador_extrair(seletor?, max_chars?)` | Texto limpo + links (sem poluir contexto) |
| `navegador_captura(pagina_inteira?)` | Print em `data/browser_shots/` |
| `navegador_pesquisar(termo)` | Busca no DuckDuckGo e devolve resultados com refs |
| `navegador_abas()` | Lista abas (índice, URL, título, ativa) |
| `navegador_nova_aba(url?)` | Abre e passa a usar nova aba |
| `navegador_trocar_aba(indice)` | Alterna aba |
| `navegador_fechar_aba(indice?)` | Fecha aba (-1 = atual) |
| `navegador_fechar()` | Fecha o navegador |

`alvo` aceita três formas:

- **ref** do último snapshot: `"e7"` ← preferido
- **seletor CSS**: `"#login"`, `"form input[type=email]"`
- **texto visível**: `"Entrar"`, `"Digite seu nome"` (usa placeholder/label)

---

## 3. Configuração (`config/settings.yaml`)

```yaml
browser:
  enabled: true
  headless: true              # false = janela visível (acompanhar ao vivo)
  channel: "msedge"           # msedge | chrome | "" (Chromium do Playwright)
  viewport: {width: 1280, height: 800}
  timeout_ms: 15000           # espera por elemento em cada ação
  nav_timeout_ms: 45000       # espera por navegação
  snapshot_text_chars: 3000   # quanto texto vai para o modelo
  max_elements: 120           # elementos por snapshot
  profile_dir: "data/browser_profile"
```

- **Quer ver o agente navegando?** `headless: false` (ou botão *Mostrar janela*
  no painel 🖥). Os dois modos usam o mesmo perfil.
- **Contexto apertado?** Diminua `snapshot_text_chars` e use
  `navegador_extrair` para páginas longas.
- **Site lento?** Aumente `nav_timeout_ms` e use `navegador_esperar`.

---

## 4. Receitas

### Pesquisar e resumir
> "Pesquise 'preço do café arábica hoje' e me diga a variação."

O agente faz `navegador_pesquisar`, abre o melhor resultado com
`navegador_clicar("e12")` e lê o conteúdo com `navegador_extrair`.

### Preencher um formulário
> "Abra o site X, preencha nome/e-mail e envie."

`navegador_abrir` → `navegador_ver` (descobre as refs) →
`navegador_preencher` em cada campo → `navegador_clicar` no botão.
Envio externo continua exigindo aprovação quando passa por conectores.

### Login (uma vez)
1. Peça: "abra https://site.com e me diga quando a tela de login estiver aberta".
2. Entre manualmente na janela visível (o perfil é o do YVAKOR).
3. Nas próximas execuções ele já está logado — o agente não precisa da senha.

> Nunca peça ao agente para "descobrir" sua senha. Se ele precisar de
> credencial, ele deve parar e pedir a você.

### Extrair tabela
> "Abra a página de cotações e extraia a tabela em CSV em data/cowork."

Depois de `navegador_ver`, use `navegador_extrair("table")` e
`executar_python` para converter em CSV (com confirmação).

---

## 5. Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| "nenhum navegador disponível" | Sem Edge/Chrome e sem Chromium | `python -m playwright install chromium` |
| "perfil em uso" | Outra instância do YVAKOR com o navegador aberto | Feche a outra instância ou `navegador_fechar` |
| "a ref X não existe mais" | Página mudou/carregou | Chame `navegador_ver` e use a ref nova |
| Clique não faz nada | Elemento coberto/carregando | `navegador_esperar`, role a página, tente pelo texto |
| Conteúdo não aparece | Está dentro de `iframe` | O snapshot avisa; abra a URL do iframe em nova aba |
| CAPTCHA / 2FA | Proteção anti-bot | Intervenção humana — o agente deve parar e avisar |
| Página em branco | JS ainda carregando | `navegador_esperar(3)` e `navegador_ver` |

---

## 6. Segurança e privacidade

- O perfil fica em `data/browser_profile/` (fora do git) e é **separado** do seu
  navegador pessoal.
- Senhas digitadas ficam no perfil local, como em qualquer navegador; não vão
  para logs nem para o modelo (o snapshot mascara `type=password`).
- O agente não tenta burlar CAPTCHA/anti-bot. Se a página bloquear, ele para.
- Downloads e prints ficam em `data/` (ignorado pelo git).
