/* YVAKOR — motor de ações na página (injetado pelo background.js).
 *
 * Único lugar que mexe no DOM: ver (snapshot), extrair, clicar, escrever,
 * pressionar, selecionar, passar o mouse, esperar e rolar. Fica em arquivo
 * próprio (e não em funções soltas dentro do background) para ser testado
 * numa página real. Idempotente: pode ser injetado a cada comando.
 *
 * Cada ação devolve um objeto simples {ok, ...}. Ações com efeito devolvem
 * também url/titulo/texto da página depois de agir.
 */
(function () {
  if (window.__yvakorAcoes) return;

  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => String(s == null ? "" : s)
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/\s+/g, " ").trim();
  const curto = (s, n) => String(s == null ? "" : s).replace(/\s+/g, " ").trim().slice(0, n);

  // ---- feedback visual (overlay.js) — opcional e nunca quebra a ação ----
  const V = () => window.__yvakorVisual || null;
  async function mostrar(msg, el) {
    try {
      const v = V();
      if (!v) return;
      v.show(msg);
      if (el && v.mover) await v.mover(el);
    } catch (e) { /* só estética */ }
  }
  function esconder() { try { const v = V(); if (v) v.hide(); } catch (e) {} }

  // ---- DOM: shadow roots, visibilidade, busca de elementos ----
  function* raizes(cont, orcamento = { n: 4000 }) {
    yield cont;
    const nos = cont.querySelectorAll ? cont.querySelectorAll("*") : [];
    for (const n of nos) {
      if (orcamento.n-- <= 0) return;
      if (n.shadowRoot) yield* raizes(n.shadowRoot, orcamento);
    }
  }
  function consultar(sel, cont = document) {
    const out = [];
    for (const r of raizes(cont)) {
      try { out.push(...r.querySelectorAll(sel)); } catch (e) { /* seletor inválido */ }
    }
    return out;
  }
  function visivel(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" &&
           parseFloat(cs.opacity || "1") > 0;
  }

  const SEL_INTERATIVO =
    "a,button,input,textarea,select,summary,label,[onclick],[tabindex]," +
    "[role='button'],[role='link'],[role='textbox'],[role='searchbox']," +
    "[role='combobox'],[role='checkbox'],[role='radio'],[role='tab']," +
    "[role='menuitem'],[role='option'],[contenteditable='']," +
    "[contenteditable='true']";

  function rotulo(el) {
    const rotulos = el.labels ? Array.from(el.labels).map((l) => l.innerText).join(" ") : "";
    return norm(el.innerText || el.value || el.getAttribute("aria-label") ||
                el.placeholder || el.name || el.title || el.id || rotulos || "") +
           " " + norm(rotulos) + " " + norm(el.getAttribute("aria-label"));
  }

  // Modelos escrevem seletores do Playwright/jQuery ("text=Consultar",
  // "button:has-text('Consultar')", ":contains(...)") e listas com vírgula —
  // CSS inválido, que antes virava "elemento não encontrado".
  function alternativas(alvo) {
    const saida = [];
    for (const parte of alvo.split(/,(?![^()]*\))/).map((s) => s.trim()).filter(Boolean)) {
      const m = parte.match(/^text\s*=\s*["']?(.+?)["']?$/i)
             || parte.match(/:(?:has-text|contains|text)\(\s*["']?(.+?)["']?\s*\)/i);
      if (m) {
        const base = parte.split(/:(?:has-text|contains|text)\(/i)[0].trim();
        saida.push({ texto: m[1], base: /^text\s*=/i.test(parte) ? "" : base });
      } else {
        saida.push({ css: parte });
      }
    }
    return saida;
  }

  // alvo = ref "e3" do último snapshot | seletor CSS | texto/rótulo do elemento
  function achar(alvo) {
    alvo = String(alvo == null ? "" : alvo).trim();
    if (!alvo) return null;
    const alts = alternativas(alvo);
    if (alts.length > 1 || alts.some((a) => a.texto)) {
      for (const a of alts) {
        if (a.css) {
          const el = acharSimples(a.css);
          if (el) return el;
          continue;
        }
        const q = norm(a.texto);
        let cand = consultar(a.base || SEL_INTERATIVO).filter(visivel);
        const el = cand.find((e) => norm(e.innerText || e.value || e.getAttribute("aria-label") || "") === q)
                || cand.find((e) => rotulo(e).includes(q));
        if (el) return el;
      }
      return null;
    }
    return acharSimples(alvo);
  }

  function acharSimples(alvo) {
    if (/^e\d+$/.test(alvo)) {
      const el = consultar('[data-yvakor-ref="' + alvo + '"]')[0];
      if (el) return el;
    }
    try { const el = document.querySelector(alvo); if (el) return el; } catch (e) { /* não é CSS */ }
    const q = norm(alvo);
    const cand = consultar(SEL_INTERATIVO).filter(visivel);
    const achado = cand.find((el) => norm(el.innerText || el.value || el.getAttribute("aria-label") || el.placeholder || "") === q)
        || cand.find((el) => rotulo(el).includes(q))
        || null;
    // Um <label> "E-mail" casa com o próprio texto; o que se quer é o CAMPO
    // que ele rotula (label.control cobre for="id" e o campo aninhado).
    if (achado && achado.tagName === "LABEL" && achado.control) return achado.control;
    return achado;
  }

  function editavel(el) {
    if (!el) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "textarea") return !el.disabled && !el.readOnly;
    if (tag === "input") {
      const t = (el.type || "text").toLowerCase();
      return !["button", "submit", "reset", "checkbox", "radio", "file", "image",
               "range", "color", "hidden"].includes(t) && !el.disabled && !el.readOnly;
    }
    return !!el.isContentEditable || ["textbox", "searchbox"].includes(el.getAttribute("role"));
  }

  // campo de texto "óbvio" quando o pedido não diz qual (ex.: "digite X e Enter")
  function campoPadrao() {
    const ativo = document.activeElement;
    if (editavel(ativo)) return ativo;
    const cand = consultar(
      "input[type='search'],input[name='q'],input[type='text'],input:not([type])," +
      "input[type='email'],textarea,[contenteditable='true'],[role='searchbox']," +
      "[role='textbox']").filter((e) => visivel(e) && editavel(e));
    return cand[0] || null;
  }

  function resumoPagina() {
    const corpo = document.body || document.documentElement;
    return { url: location.href, titulo: document.title,
             texto: curto(corpo ? corpo.innerText : "", 1200) };
  }
  const comPagina = (obj) => Object.assign({ ok: true }, obj, resumoPagina());

  // ---- ver ----
  function descrever(el, ref) {
    const tag = el.tagName.toLowerCase();
    const tipo = (el.getAttribute("type") || "").toLowerCase();
    const o = { ref, tag, tipo,
      texto: curto(el.innerText || el.getAttribute("aria-label") || el.title ||
                   el.value || el.placeholder || "", 120),
      id: el.id || "", aria: curto(el.getAttribute("aria-label"), 80),
      nome: el.name || "" };
    if (tag === "input" || tag === "textarea") {
      o.placeholder = curto(el.placeholder, 60);
      // nunca devolve o conteúdo de campo de senha
      o.valor = tipo === "password" ? "" : curto(el.value, 80);
    }
    if (tag === "input" && (tipo === "checkbox" || tipo === "radio")) o.marcado = !!el.checked;
    if (tag === "select") {
      o.opcoes = Array.from(el.options).slice(0, 30).map((x) => curto(x.text, 40));
      o.selecionado = el.options[el.selectedIndex] ? curto(el.options[el.selectedIndex].text, 40) : "";
    }
    if (el.isContentEditable) o.editavel = true;
    if (el.disabled) o.desabilitado = true;
    return o;
  }

  function textoProfundo(no, orc = { n: 60000 }) {
    if (!no || orc.n <= 0) return "";
    if (no.nodeType === 3) { orc.n -= no.textContent.length; return no.textContent + " "; }
    if (no.nodeType === 1) {
      const tag = (no.tagName || "").toLowerCase();
      if (["script", "style", "noscript", "template", "svg", "head", "iframe"].includes(tag)) return "";
      let s = "";
      if (no.shadowRoot) s += textoProfundo(no.shadowRoot, orc);
      for (const c of no.childNodes) s += textoProfundo(c, orc);
      return s;
    }
    if (no.nodeType === 11) {
      let s = "";
      for (const c of no.childNodes) s += textoProfundo(c, orc);
      return s;
    }
    return "";
  }

  function snapshot({ max = 80 } = {}) {
    // Limpa as refs ANTERIORES: sem isso, "e1" de um snapshot velho continuava
    // no DOM e podia ser achado no lugar do "e1" atual.
    consultar("[data-yvakor-ref]").forEach((e) => e.removeAttribute("data-yvakor-ref"));
    const itens = [];
    const vistos = new Set();
    for (const el of consultar(SEL_INTERATIVO)) {
      if (vistos.has(el)) continue;
      vistos.add(el);
      if (!visivel(el)) continue;
      if (itens.length >= max) break;
      const ref = "e" + (itens.length + 1);
      el.setAttribute("data-yvakor-ref", ref);
      itens.push(descrever(el, ref));
    }
    const texto = curto(textoProfundo(document.documentElement || document), 3000);
    const linhas = itens.map((e) => {
      let extra = "";
      if (e.tipo) extra += " type=" + e.tipo;
      if (e.placeholder) extra += ' placeholder="' + e.placeholder + '"';
      if (e.valor) extra += ' valor="' + e.valor + '"';
      if (e.marcado !== undefined) extra += e.marcado ? " [marcado]" : " [desmarcado]";
      if (e.opcoes) extra += " opcoes=[" + e.opcoes.slice(0, 8).join("|") + "]";
      if (e.editavel) extra += " [editavel]";
      if (e.desabilitado) extra += " [desabilitado]";
      return "[" + e.ref + "] <" + e.tag + extra + "> " + e.texto;
    });
    const cap = captchaEstado();
    const avisoCaptcha = !cap.presente ? "" : cap.resolvido
      ? "\n\nCAPTCHA: RESOLVIDO pelo usuário. NÃO recarregue a página nem preencha de novo " +
        "(isso invalida o captcha): clique direto no botão de envio."
      : "\n\nCAPTCHA: PENDENTE. Você NÃO resolve captcha. Preencha os campos e chame " +
        "navegador_aguardar_captcha para o usuário resolver; depois clique no botão de envio.";
    return {
      url: location.href, title: document.title, text: texto, items: itens,
      captcha: cap.presente ? cap : undefined,
      resumo: "URL: " + location.href + "\nTÍTULO: " + document.title +
              "\n\nTEXTO:\n" + texto.slice(0, 1800) + "\n\nELEMENTOS:\n" + linhas.join("\n") +
              avisoCaptcha
    };
  }

  function extrair({ max_chars = 6000, seletor = "" } = {}) {
    let raiz = document.documentElement || document;
    if (seletor) {
      const el = achar(seletor);
      if (!el) return { ok: false, erro: "seletor não encontrado: " + seletor };
      raiz = el;
    }
    const texto = curto(textoProfundo(raiz), max_chars);
    const links = [];
    const vistos = new Set();
    for (const a of consultar("a[href]", raiz.querySelectorAll ? raiz : document)) {
      if (vistos.has(a)) continue;
      vistos.add(a);
      if (links.length >= 60) break;
      const t = curto(a.innerText || a.getAttribute("aria-label"), 80);
      if (t) links.push({ texto: t, url: String(a.href).slice(0, 200) });
    }
    return { ok: true, texto, links, url: location.href, titulo: document.title };
  }

  // ---- clicar ----
  async function clicar({ alvo } = {}) {
    const el = achar(alvo);
    if (!el) return { ok: false, erro: "elemento não encontrado — use navegador_ver para ver as refs atuais" };
    if (el.disabled) return { ok: false, erro: "elemento desabilitado" };
    const cap = captchaEstado();
    const envia = !!(el.form && (el.type === "submit" || el.tagName === "BUTTON" && !el.type))
               || (el.tagName === "A" && el.href && !/^javascript:/i.test(el.getAttribute("href") || ""));
    const v = V();
    if (envia) {
      // Envio de formulário/link NAVEGA: a página é descarregada antes de este
      // script devolver o resultado, e a extensão ficava presa até o tempo limite
      // ("a extensão não respondeu"). Responde ANTES e clica logo em seguida.
      const resp = comPagina({ navegando: true, captcha: cap.presente ? cap : undefined });
      setTimeout(() => {
        if (v && v.click) v.click(el, "clicando").catch(() => el.click());
        else { el.scrollIntoView({ block: "center" }); el.click(); }
      }, 30);
      return resp;
    }
    if (v && v.click) await v.click(el, "clicando");
    else { el.scrollIntoView({ block: "center" }); el.click(); }
    await dormir(150);
    return comPagina({});
  }

  // ---- captcha (detectar e esperar o USUÁRIO resolver; nunca resolve sozinho) ----
  function captchaEstado() {
    const sinais = consultar(
      "iframe[src*='hcaptcha'],iframe[src*='recaptcha'],iframe[src*='turnstile']," +
      "iframe[src*='captcha'],.h-captcha,.g-recaptcha,.cf-turnstile,[data-sitekey]");
    const respostas = consultar(
      "textarea[name='h-captcha-response'],textarea[name='g-recaptcha-response']," +
      "input[name='cf-turnstile-response'],input[name='h-captcha-response']");
    const presente = sinais.length > 0 || respostas.length > 0;
    const resolvido = respostas.some((e) => (e.value || "").trim().length > 20);
    return { presente, resolvido };
  }
  function captcha() {
    const c = captchaEstado();
    if (c.presente && !c.resolvido) {
      const alvo = consultar(".h-captcha,.g-recaptcha,.cf-turnstile,[data-sitekey]," +
                             "iframe[src*='captcha']")[0];
      if (alvo) {
        alvo.scrollIntoView({ block: "center" });
        alvo.style.outline = "3px solid #d4a017";
        alvo.style.outlineOffset = "4px";
      }
    }
    return Object.assign({ ok: true }, c, { url: location.href, titulo: document.title });
  }

  // ---- escrever ----
  function setarValor(el, v) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const d = Object.getOwnPropertyDescriptor(proto, "value");
    if (d && d.set) d.set.call(el, v); else el.value = v;
  }
  function evInput(el, tipo, dados) {
    try {
      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: tipo, data: dados == null ? null : dados }));
    } catch (e) { el.dispatchEvent(new Event("input", { bubbles: true })); }
  }
  function evTecla(el, tipo, key, extra) {
    el.dispatchEvent(new KeyboardEvent(tipo, Object.assign(
      { key, bubbles: true, cancelable: true, composed: true }, extra || {})));
  }

  // Enter "de verdade": evento de teclado sintético NÃO envia formulário (só o
  // navegador faz isso para teclas reais). Então: dentro de <form> usa
  // requestSubmit(); fora, dispara os eventos para handlers JS (chats, SPAs).
  function enviarCampo(el) {
    if (el.form && typeof el.form.requestSubmit === "function") {
      el.form.requestSubmit();
      return "formulario";
    }
    const info = { code: "Enter", keyCode: 13, which: 13 };
    evTecla(el, "keydown", "Enter", info);
    evTecla(el, "keypress", "Enter", info);
    evTecla(el, "keyup", "Enter", info);
    return "enter";
  }

  async function escrever({ alvo = "", texto = "", limpar = true, enviar = false, humano = false } = {}) {
    texto = String(texto == null ? "" : texto);
    const el = alvo ? achar(alvo) : campoPadrao();
    if (!el) {
      return { ok: false, erro: alvo
        ? "campo não encontrado — use navegador_ver para ver as refs atuais"
        : "nenhum campo de texto visível na página" };
    }
    const tag = el.tagName.toLowerCase();
    const tipo = (el.type || "").toLowerCase();
    if (tag === "select") return selecionar({ alvo, valor: texto, _el: el });
    if (tag === "input" && (tipo === "checkbox" || tipo === "radio")) {
      const quer = /^(1|true|sim|on|marcar|marcado|yes|x)$/i.test(texto.trim());
      if (el.checked !== quer) el.click();
      return comPagina({ marcado: el.checked });
    }
    if (!editavel(el)) return { ok: false, erro: "o elemento não aceita texto (desabilitado, somente leitura ou não é um campo)" };

    el.scrollIntoView({ block: "center" });
    await mostrar("digitando", el);
    try {
      el.focus();
      const rico = !!el.isContentEditable;
      if (rico) {
        // Editores ricos (Gmail, Notion, chats) ignoram innerText/textContent;
        // execCommand dispara beforeinput/input reais que eles escutam.
        if (limpar) { document.execCommand("selectAll", false); document.execCommand("delete", false); }
        else { const s = getSelection(); s.selectAllChildren(el); s.collapseToEnd(); }
        if (humano) {
          for (const ch of texto) {
            document.execCommand("insertText", false, ch);
            await dormir(15 + Math.random() * 25);
          }
        } else if (texto && !document.execCommand("insertText", false, texto)) {
          el.textContent = (limpar ? "" : el.textContent) + texto;
          evInput(el, "insertText", texto);
        }
      } else {
        if (limpar) {
          try { el.select(); } catch (e) { /* tipos que não suportam select() */ }
          setarValor(el, "");
          evInput(el, "deleteContentBackward");
        }
        if (humano) {
          for (const ch of texto) {
            evTecla(el, "keydown", ch);
            setarValor(el, el.value + ch);
            evInput(el, "insertText", ch);
            evTecla(el, "keyup", ch);
            await dormir(15 + Math.random() * 25);
          }
        } else if (texto) {
          setarValor(el, (limpar ? "" : el.value) + texto);
          evInput(el, "insertText", texto);
        }
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
      let envio = null;
      if (enviar) { await dormir(120); envio = enviarCampo(el); }
      await dormir(120);
      const lido = el.isContentEditable ? el.innerText : el.value;
      const senha = tipo === "password";
      const confere = norm(lido).includes(norm(texto));
      const r = comPagina({ escrito: senha ? "(senha)" : curto(lido, 200), enviado_por: envio });
      if (!confere && texto) {
        r.aviso = "o campo não refletiu o texto digitado (a página pode ter rejeitado ou formatado) — confira com navegador_ver";
      }
      return r;
    } finally { esconder(); }
  }

  // ---- teclas ----
  const TECLAS = {
    enter: ["Enter", "Enter", 13], return: ["Enter", "Enter", 13],
    escape: ["Escape", "Escape", 27], esc: ["Escape", "Escape", 27],
    tab: ["Tab", "Tab", 9], backspace: ["Backspace", "Backspace", 8],
    delete: ["Delete", "Delete", 46], del: ["Delete", "Delete", 46],
    space: [" ", "Space", 32], espaco: [" ", "Space", 32],
    arrowdown: ["ArrowDown", "ArrowDown", 40], arrowup: ["ArrowUp", "ArrowUp", 38],
    arrowleft: ["ArrowLeft", "ArrowLeft", 37], arrowright: ["ArrowRight", "ArrowRight", 39],
    pagedown: ["PageDown", "PageDown", 34], pageup: ["PageUp", "PageUp", 33],
    home: ["Home", "Home", 36], end: ["End", "End", 35],
  };
  function lerTecla(txt) {
    const partes = String(txt || "Enter").split("+").map((p) => p.trim()).filter(Boolean);
    const mods = { ctrlKey: false, shiftKey: false, altKey: false, metaKey: false };
    let principal = partes.pop() || "Enter";
    for (const p of partes) {
      const k = p.toLowerCase();
      if (k === "ctrl" || k === "control") mods.ctrlKey = true;
      else if (k === "shift") mods.shiftKey = true;
      else if (k === "alt") mods.altKey = true;
      else if (k === "meta" || k === "cmd" || k === "win") mods.metaKey = true;
    }
    const def = TECLAS[principal.toLowerCase()];
    if (def) return Object.assign({ key: def[0], code: def[1], keyCode: def[2], which: def[2] }, mods);
    if (principal.length === 1) {
      const up = principal.toUpperCase();
      return Object.assign({
        key: mods.shiftKey ? up : principal.toLowerCase(),
        code: /[a-z]/i.test(principal) ? "Key" + up : (/\d/.test(principal) ? "Digit" + principal : ""),
        keyCode: up.charCodeAt(0), which: up.charCodeAt(0) }, mods);
    }
    return Object.assign({ key: principal, code: principal, keyCode: 0, which: 0 }, mods);
  }
  function proximoFoco(de, atras) {
    const foco = consultar("a[href],button,input,select,textarea,[tabindex]")
      .filter((e) => visivel(e) && !e.disabled && e.tabIndex >= 0);
    const i = foco.indexOf(de);
    return foco[(i + (atras ? -1 : 1) + foco.length) % foco.length] || null;
  }

  async function pressionar({ tecla = "Enter", alvo = "" } = {}) {
    const el = alvo ? achar(alvo) : (document.activeElement && document.activeElement !== document.body
                                      ? document.activeElement : (campoPadrao() || document.body));
    if (!el) return { ok: false, erro: "elemento não encontrado" };
    if (alvo && el.focus) el.focus();
    const t = lerTecla(tecla);
    const init = { key: t.key, code: t.code, keyCode: t.keyCode, which: t.which,
                   ctrlKey: t.ctrlKey, shiftKey: t.shiftKey, altKey: t.altKey, metaKey: t.metaKey };
    const alvoEv = el;
    const imprimivel = t.key.length === 1 && !t.ctrlKey && !t.altKey && !t.metaKey;
    const keydown = new KeyboardEvent("keydown", Object.assign({ bubbles: true, cancelable: true, composed: true }, init));
    alvoEv.dispatchEvent(keydown);
    if (imprimivel || t.key === "Enter") {
      alvoEv.dispatchEvent(new KeyboardEvent("keypress", Object.assign({ bubbles: true, cancelable: true, composed: true }, init)));
    }
    // Ações padrão que o navegador NÃO executa para eventos sintéticos:
    let efeito = null;
    if (!keydown.defaultPrevented) {
      const tag = el.tagName.toLowerCase();
      const ehCampo = tag === "input" || tag === "textarea" || el.isContentEditable;
      if (t.key === "Enter") {
        if (tag === "input" && el.form) { el.form.requestSubmit(); efeito = "formulario enviado"; }
        else if (tag === "textarea") { document.execCommand("insertText", false, "\n"); efeito = "quebra de linha"; }
        else if (el.isContentEditable) { document.execCommand("insertParagraph", false); efeito = "novo parágrafo"; }
        else if (["button", "a", "summary"].includes(tag) || el.getAttribute("role") === "button") { el.click(); efeito = "clique"; }
      } else if (t.key === "Tab") {
        const p = proximoFoco(el, t.shiftKey);
        if (p) { p.focus(); efeito = "foco movido"; }
      } else if (t.key === " " && !ehCampo && ["button", "summary"].includes(tag)) {
        el.click(); efeito = "clique";
      } else if (t.ctrlKey && t.key.toLowerCase() === "a" && ehCampo) {
        if (el.isContentEditable) document.execCommand("selectAll", false); else el.select();
        efeito = "tudo selecionado";
      } else if (t.key === "Backspace" && ehCampo) {
        document.execCommand("delete", false); efeito = "apagado";
      } else if (t.key === "Delete" && ehCampo) {
        document.execCommand("forwardDelete", false); efeito = "apagado";
      } else if (imprimivel && ehCampo) {
        if (el.isContentEditable || tag === "input" || tag === "textarea") {
          document.execCommand("insertText", false, t.key); efeito = "digitado";
        }
      }
    }
    alvoEv.dispatchEvent(new KeyboardEvent("keyup", Object.assign({ bubbles: true, cancelable: true, composed: true }, init)));
    await dormir(120);
    return comPagina({ tecla, efeito });
  }

  // ---- selecionar (<select>) ----
  async function selecionar({ alvo = "", valor = "", _el = null } = {}) {
    const el = _el || achar(alvo);
    if (!el) return { ok: false, erro: "campo não encontrado — use navegador_ver para ver as refs atuais" };
    if (el.tagName.toLowerCase() !== "select") {
      return { ok: false, erro: "não é uma lista <select>; para menus customizados clique no menu e depois na opção" };
    }
    const q = norm(valor);
    const ops = Array.from(el.options);
    const i = ops.findIndex((o) => norm(o.value) === q)
      >= 0 ? ops.findIndex((o) => norm(o.value) === q)
      : (ops.findIndex((o) => norm(o.text) === q) >= 0
          ? ops.findIndex((o) => norm(o.text) === q)
          : ops.findIndex((o) => norm(o.text).includes(q)));
    if (i < 0) {
      return { ok: false, erro: "opção não encontrada: " + valor,
               opcoes: ops.slice(0, 40).map((o) => curto(o.text, 40)) };
    }
    el.scrollIntoView({ block: "center" });
    await mostrar("selecionando", el);
    try {
      el.focus();
      if (el.multiple) ops[i].selected = true; else el.selectedIndex = i;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      await dormir(100);
      return comPagina({ selecionado: curto(ops[i].text, 60) });
    } finally { esconder(); }
  }

  // ---- enviar arquivo (<input type=file>) ----
  // Campos de arquivo costumam ficar ocultos atrás de um botão/área de soltar:
  // aceita a ref do input, um rótulo/botão ligado a ele, ou a única entrada da página.
  function acharArquivo(alvo) {
    const ehArq = (e) => e && e.tagName && e.tagName.toLowerCase() === "input" && (e.type || "").toLowerCase() === "file";
    const el = alvo ? achar(alvo) : null;
    if (ehArq(el)) return el;
    if (el) {
      const lig = el.control || el.querySelector && el.querySelector("input[type='file']")
        || (el.closest && el.closest("label,form,div") && el.closest("label,form,div").querySelector("input[type='file']"));
      if (ehArq(lig)) return lig;
    }
    const todos = consultar("input[type='file']");
    return todos.length === 1 ? todos[0] : null;
  }
  async function enviar_arquivo({ alvo = "", nome = "arquivo", mime = "", b64 = "" } = {}) {
    const el = acharArquivo(alvo);
    if (!el) return { ok: false, erro: "campo de arquivo não encontrado — use navegador_ver/navegador_procurar ('enviar arquivo') e passe a ref do campo" };
    if (!b64) return { ok: false, erro: "arquivo vazio" };
    let bytes;
    try {
      const bin = atob(b64);
      bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    } catch (e) { return { ok: false, erro: "conteúdo do arquivo inválido" }; }
    const arq = new File([bytes], nome, { type: mime || "application/octet-stream" });
    const dt = new DataTransfer();
    if (el.multiple) Array.from(el.files || []).forEach((f) => dt.items.add(f));
    dt.items.add(arq);
    el.scrollIntoView({ block: "center" });
    await mostrar("enviando arquivo", el);
    try {
      el.files = dt.files;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      await dormir(150);
      return comPagina({ anexado: nome, bytes: bytes.length,
                         total_no_campo: el.files ? el.files.length : 1 });
    } finally { esconder(); }
  }

  // ---- mouse / espera / rolagem ----
  async function passar_mouse({ alvo = "" } = {}) {
    const el = achar(alvo);
    if (!el) return { ok: false, erro: "elemento não encontrado — use navegador_ver para ver as refs atuais" };
    el.scrollIntoView({ block: "center" });
    await mostrar("passando o mouse", el);
    try {
      const r = el.getBoundingClientRect();
      const pos = { bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
      for (const tipo of ["pointerover", "mouseover", "pointerenter", "mouseenter", "pointermove", "mousemove"]) {
        const Ev = tipo.startsWith("pointer") && window.PointerEvent ? PointerEvent : MouseEvent;
        el.dispatchEvent(new Ev(tipo, pos));
      }
      await dormir(250);
      return comPagina({});
    } finally { esconder(); }
  }

  async function esperar({ texto = "", seletor = "", segundos = 10 } = {}) {
    const total = Math.max(0.2, Math.min(30, Number(segundos) || 10)) * 1000;
    if (!texto && !seletor) { await dormir(total); return comPagina({ esperou_s: total / 1000 }); }
    const fim = Date.now() + total;
    const q = norm(texto);
    while (Date.now() < fim) {
      let achou = false;
      if (seletor) { try { achou = !!consultar(seletor).filter(visivel)[0]; } catch (e) { achou = false; } }
      if (!achou && q) achou = norm((document.body && document.body.innerText) || "").includes(q);
      if (achou) return comPagina({ apareceu: true });
      await dormir(150);
    }
    return { ok: false, erro: "tempo esgotado esperando " + (seletor || ('o texto "' + texto + '"')), url: location.href };
  }

  function maiorRolavel() {
    let melhor = null, area = 0;
    for (const el of consultar("*")) {
      if (el.scrollHeight <= el.clientHeight + 20) continue;
      const oy = getComputedStyle(el).overflowY;
      if (oy !== "auto" && oy !== "scroll") continue;
      const a = el.clientWidth * el.clientHeight;
      if (a > area) { area = a; melhor = el; }
    }
    return melhor;
  }
  async function rolar({ direcao = "baixo", vezes = 1, alvo = "" } = {}) {
    if (alvo) {
      const el = achar(alvo);
      if (!el) return { ok: false, erro: "elemento não encontrado" };
      el.scrollIntoView({ block: "center", behavior: "instant" });
      await dormir(150);
      return comPagina({ y: Math.round(scrollY) });
    }
    const raiz = document.scrollingElement || document.documentElement;
    // Apps (Gmail, chats, dashboards) rolam um painel interno, não a janela.
    const alvoRolagem = raiz.scrollHeight > innerHeight + 5 ? null : maiorRolavel();
    const passo = (alvoRolagem ? alvoRolagem.clientHeight : innerHeight) * 0.8 * Math.max(1, Number(vezes) || 1);
    const d = norm(direcao);
    const aplicar = (dy, abs) => {
      if (alvoRolagem) { if (abs !== undefined) alvoRolagem.scrollTop = abs; else alvoRolagem.scrollTop += dy; }
      else if (abs !== undefined) window.scrollTo(0, abs); else window.scrollBy(0, dy);
    };
    if (d === "topo" || d === "top") aplicar(0, 0);
    else if (d === "fim" || d === "bottom") aplicar(0, (alvoRolagem || raiz).scrollHeight);
    else if (d === "cima" || d === "up") aplicar(-passo);
    else aplicar(passo);
    await dormir(200);
    const sc = alvoRolagem || raiz;
    const y = alvoRolagem ? sc.scrollTop : scrollY;
    const alt = sc.scrollHeight - sc.clientHeight;
    return { ok: true, y: Math.round(y), no_topo: y <= 2, no_fim: y >= alt - 2,
             painel_interno: !!alvoRolagem, url: location.href };
  }

  // ---- procurar: achar elementos por DESCRIÇÃO ("campo de busca") ----
  // Em vez de ler a página inteira, devolve só os melhores candidatos, já com
  // refs que as outras ações entendem. Pontuação por palavras + sinônimos de
  // papel (botão/campo/link/lista…): é heurística local, sem modelo de IA.
  const PARADAS = new Set(["de", "do", "da", "dos", "das", "o", "a", "os", "as", "um",
    "uma", "no", "na", "em", "para", "pra", "com", "que", "the", "of", "to", "in"]);
  const SINONIMOS = {
    botao: ["button", "submit", "btn"], botoes: ["button", "submit"],
    campo: ["input", "textarea", "textbox", "searchbox"], caixa: ["input", "textarea", "checkbox"],
    texto: ["input", "textarea", "textbox"], busca: ["search", "pesquis", "procur", "buscar"],
    pesquisa: ["search", "busca", "procur"], pesquisar: ["search", "busca"],
    link: ["a", "href"], lista: ["select", "listbox", "combobox"], menu: ["menu", "nav"],
    senha: ["password"], email: ["e-mail", "mail"], enviar: ["submit", "send", "enviar"],
    entrar: ["login", "sign in", "signin", "entrar"], login: ["entrar", "sign in"],
    marcar: ["checkbox"], opcao: ["radio", "option"], aba: ["tab"],
  };
  function procurar({ consulta = "", max = 20 } = {}) {
    const q = norm(consulta);
    const palavras = q.split(" ").filter((p) => p.length >= 2 && !PARADAS.has(p));
    if (!palavras.length) return { ok: false, erro: "descreva o que procurar (ex.: campo de busca)" };
    const melhor = new Map();                 // elemento -> maior pontuação
    for (const bruto of consultar(SEL_INTERATIVO)) {
      if (!visivel(bruto)) continue;
      // Um <label> "E-mail" casa com o texto; o que se quer é o CAMPO que ele
      // rotula (mesma regra do achar). Mantém a maior pontuação, sem duplicar.
      const el = bruto.tagName === "LABEL" && bruto.control ? bruto.control : bruto;
      const tag = el.tagName.toLowerCase();
      const feno = norm([rotulo(el), tag, el.type, el.getAttribute("role"), el.name, el.id,
                         el.placeholder, el.title, el.getAttribute("autocomplete"),
                         tag === "a" ? "link" : ""].join(" "));
      let pontos = 0;
      for (const p of palavras) {
        if (feno.includes(p)) pontos += 2;
        else if ((SINONIMOS[p] || []).some((s) => feno.includes(s))) pontos += 1;
      }
      if (q && feno.includes(q)) pontos += 3;               // a frase inteira
      if (pontos > 0) pontos += editavel(el) && /campo|caixa|texto|busca|pesquis|senha|email/.test(q) ? 0.5 : 0;
      if (pontos > 0 && pontos > (melhor.get(el) || 0)) melhor.set(el, pontos);
    }
    const pontuados = Array.from(melhor, ([el, pontos]) => ({ el, pontos }));
    pontuados.sort((a, b) => b.pontos - a.pontos);
    const top = pontuados.slice(0, Math.max(1, Math.min(20, Number(max) || 20)));
    // refs novas continuam a numeração, SEM apagar as do último snapshot
    let n = 0;
    for (const e of consultar("[data-yvakor-ref]")) {
      n = Math.max(n, parseInt((e.getAttribute("data-yvakor-ref") || "e0").slice(1), 10) || 0);
    }
    const itens = top.map(({ el, pontos }) => {
      let ref = el.getAttribute("data-yvakor-ref");
      if (!ref) { ref = "e" + (++n); el.setAttribute("data-yvakor-ref", ref); }
      return Object.assign(descrever(el, ref), { relevancia: pontos });
    });
    const resumo = itens.map((e) => "[" + e.ref + "] <" + e.tag + (e.tipo ? " type=" + e.tipo : "") +
      (e.placeholder ? ' placeholder="' + e.placeholder + '"' : "") + "> " + e.texto).join("\n");
    return { ok: true, consulta, total: pontuados.length, itens, resumo,
             aviso: itens.length ? "" : "nada encontrado — use navegador_ver para ver a página", url: location.href };
  }

  // ---- pré-visualização (SEM efeito): o que a ação faria e se é sensível ----
  // Alimenta o pedido de confirmação ("Clicar em «Comprar agora»") antes de agir.
  const SENSIVEL_TEXTO = new RegExp(
    "\\b(comprar|compra|pagar|pagamento|finalizar|confirmar (a )?(compra|pedido|" +
    "pagamento)|fechar pedido|enviar|publicar|postar|tuitar|excluir|apagar|" +
    "deletar|remover|cancelar (assinatura|pedido|conta)|assinar|contratar|" +
    "transferir|autorizar|aprovar|aceitar|buy|purchase|pay|checkout|place order|" +
    "submit|send|post|publish|delete|remove|subscribe|transfer|authorize)\\b", "i");
  const SENSIVEL_CAMPO = /(card|cart[aã]o|cvv|cvc|cpf|ssn|senha|password|passwd|otp|iban|pix)/i;

  // Nome que o USUÁRIO reconhece. Campos de formulário são nomeados por rótulo/
  // placeholder/nome — NUNCA pelo valor atual (viraria "Digitar X em «z»") nem
  // pelo texto interno (um <select> devolveria todas as opções juntas).
  function nomeDe(el) {
    const tag = el.tagName.toLowerCase();
    const tipo = (el.type || "").toLowerCase();
    const campo = tag === "textarea" || tag === "select" ||
      (tag === "input" && !["button", "submit", "reset", "image"].includes(tipo));
    if (campo) {
      const rot = el.labels && el.labels[0] ? el.labels[0].innerText : "";
      return curto(el.getAttribute("aria-label") || rot || el.placeholder ||
                   el.name || el.id || tag, 60);
    }
    return curto(el.innerText || el.getAttribute("aria-label") || el.title ||
                 el.value || el.placeholder || el.name || el.id || tag, 60);
  }

  function descrever_acao({ acao = "", alvo = "", texto = "", valor = "",
                            tecla = "Enter", enviar = false } = {}) {
    const val = texto || valor;
    let el;
    if (acao === "pressionar") {
      el = alvo ? achar(alvo)
        : (document.activeElement && document.activeElement !== document.body
            ? document.activeElement : campoPadrao());
    } else if (acao === "escrever") {
      el = alvo ? achar(alvo) : campoPadrao();
    } else if (acao === "enviar_arquivo") {
      el = acharArquivo(alvo);
    } else {
      el = achar(alvo);
    }
    if (!el) {
      return { ok: true, descricao: "(elemento não encontrado — a ação vai falhar)",
               sensivel: false, host: location.hostname };
    }
    const tag = el.tagName.toLowerCase();
    const tipo = (el.type || "").toLowerCase();
    const nome = nomeDe(el);
    const atrib = [el.name, el.id, el.getAttribute("autocomplete"),
                   el.getAttribute("aria-label"), el.placeholder].join(" ");
    const form = el.form || el.closest("form");
    const formTemSenha = !!(form && form.querySelector(
      "input[type='password'],input[autocomplete^='cc-']"));
    let descricao = "", sensivel = false, motivo = "";

    if (acao === "clicar") {
      descricao = "Clicar em «" + nome + "»";
      const ehEnvio = (tag === "button" && (tipo === "submit" || !tipo)) ||
                      (tag === "input" && tipo === "submit");
      if (SENSIVEL_TEXTO.test(nome)) { sensivel = true; motivo = "ação irreversível ou com custo"; }
      else if (ehEnvio && formTemSenha) { sensivel = true; motivo = "envia um formulário com senha/cartão"; }
    } else if (acao === "escrever") {
      const oculto = tipo === "password" || SENSIVEL_CAMPO.test(atrib);
      descricao = oculto ? "Digitar um valor (oculto) em «" + nome + "»"
                         : "Digitar «" + curto(val, 40) + "» em «" + nome + "»";
      if (oculto) { sensivel = true; motivo = "campo de senha, cartão ou documento"; }
      if (enviar) {
        descricao += " e enviar";
        if (formTemSenha && !sensivel) { sensivel = true; motivo = "envia um formulário com senha/cartão"; }
      }
    } else if (acao === "pressionar") {
      descricao = "Pressionar " + tecla + " em «" + nome + "»";
      if (/^enter$/i.test(tecla) && formTemSenha) { sensivel = true; motivo = "envia um formulário com senha/cartão"; }
    } else if (acao === "selecionar") {
      descricao = "Escolher «" + curto(val, 40) + "» em «" + nome + "»";
    } else if (acao === "enviar_arquivo") {
      // sempre pergunta: um arquivo do computador do usuário sairá para o site
      descricao = "Anexar o arquivo «" + curto(val || "arquivo", 60) + "» do seu computador em «" + nome + "»";
      sensivel = true; motivo = "envia um arquivo do seu computador para este site";
    } else {
      descricao = acao + " em «" + nome + "»";
    }
    return { ok: true, descricao, sensivel, motivo, host: location.hostname };
  }

  window.__yvakorAcoes = { snapshot, extrair, clicar, escrever, pressionar,
                           selecionar, enviar_arquivo, passar_mouse, esperar, rolar,
                           descrever_acao, procurar, captcha };
})();
