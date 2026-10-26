/* YVAKOR — painel lateral simples do Chrome */
const BASE = "http://127.0.0.1:7777";
const CHAVE_SESSAO = "yvakor_session";

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const vazio = $("vazio");
const entrada = $("entrada");
const enviar = $("enviar");
const mic = $("mic");
const vozBtn = $("voz");
const statusEl = $("status");
const processo = $("processo");
const passosEl = $("passos");
const procStatus = $("proc-status");
const ctxTitulo = $("ctx-titulo");

let sessao = null;
let ocupado = false;
let timerProgresso = null;
let recVoz = null;
let contexto = null;
let contextoAba = null;
let vozAtiva = localStorage.getItem("yvakor_voz") === "1";

/* ------------------------------ API -------------------------------- */
async function api(path, opts = {}) {
  const cfg = { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } };
  if (cfg.body && typeof cfg.body !== "string") cfg.body = JSON.stringify(cfg.body);
  const ctrl = new AbortController();
  const limite = setTimeout(() => ctrl.abort(), cfg.timeout || 120000);
  cfg.signal = ctrl.signal;
  try {
    const r = await fetch(BASE + path, cfg);
    const txt = await r.text();
    let j = {};
    try { j = txt ? JSON.parse(txt) : {}; } catch (e) { j = { erro: txt }; }
    if (!r.ok) throw new Error(j.error || j.erro || ("HTTP " + r.status));
    return j;
  } finally { clearTimeout(limite); }
}

async function ping() {
  try {
    await api("/api/ping", { timeout: 2500 });
    statusEl.textContent = "online";
    statusEl.className = "pill ok";
  } catch (e) {
    statusEl.textContent = "offline";
    statusEl.className = "pill erro";
  }
}

async function carregarBuild() {
  try {
    const b = await fetch(chrome.runtime.getURL("build.json")).then(r => r.json());
    $("assinatura").textContent = `para Chrome · v${b.version}`;
  } catch (e) { /* opcional */ }
}

async function guardarSessao() {
  try { await chrome.storage.local.set({ [CHAVE_SESSAO]: sessao }); }
  catch (e) { localStorage.setItem(CHAVE_SESSAO, sessao || ""); }
}
async function lerSessao() {
  try { return (await chrome.storage.local.get(CHAVE_SESSAO))[CHAVE_SESSAO]; }
  catch (e) { return localStorage.getItem(CHAVE_SESSAO); }
}
async function novaSessao() {
  const j = await api("/api/sessions", { method: "POST", body: {} });
  sessao = j.active;
  await guardarSessao();
}

/* --------------------------- contexto ------------------------------ */
async function atualizarContexto() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      ctxTitulo.textContent = "Sem aba ativa";
      return;
    }
    contextoAba = tab;
    let resultado = null;
    if (!/^(chrome|edge|about|chrome-extension|devtools|view-source):/.test(tab.url || "")) {
      try {
        const exec = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: () => {
            const corpo = document.querySelector("main, article, [role='main']")
                       || document.body || document.documentElement;
            const texto = corpo ? (corpo.innerText || corpo.textContent || "") : "";
            const meta = document.querySelector("meta[name='description']");
            const secoes = Array.from(document.querySelectorAll("h1,h2,h3"))
              .slice(0, 24)
              .map(h => (h.innerText || "").replace(/\s+/g, " ").trim())
              .filter(Boolean);
            const selecao = (window.getSelection() ? window.getSelection().toString() : "")
              .replace(/\s+/g, " ").trim().slice(0, 3000);
            return {
              titulo: document.title,
              url: location.href,
              descricao: meta ? meta.content.slice(0, 600) : "",
              secoes: secoes.join(" · ").slice(0, 2500),
              selecao,
              texto: texto.replace(/\s+/g, " ").trim().slice(0, 20000)
            };
          }
        });
        resultado = exec && exec[0] ? exec[0].result : null;
      } catch (e) {
        resultado = { titulo: tab.title || "", url: tab.url || "",
                      texto: "", erro: e.message || "sem permissão" };
      }
    }
    contexto = resultado || { titulo: tab.title || tab.url, url: tab.url,
                              texto: "" };
    const n = (contexto.texto || "").length;
    const titulo = contexto.titulo || contexto.url || "Página atual";
    ctxTitulo.textContent = n
      ? `${titulo} · ${n} car.`
      : (contexto.erro ? "Sem acesso — ative Acesso ao site" : `${titulo} · sem texto`);
    ctxTitulo.title = `${contexto.url || ""}\n${n} caracteres de conteúdo`;
  } catch (e) {
    ctxTitulo.textContent = "Página atual indisponível";
  }
}
chrome.tabs.onActivated.addListener(() => setTimeout(atualizarContexto, 250));
chrome.tabs.onUpdated.addListener((id, info) => {
  if (info.status === "complete") setTimeout(atualizarContexto, 350);
});
setInterval(atualizarContexto, 10000);

/* ----------------------------- chat -------------------------------- */
function esc(t) {
  return String(t || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function markdown(t) {
  let s = esc(t);
  const blocos = [];
  s = s.replace(/```([\s\S]*?)```/g, (_, c) => {
    blocos.push("<pre><code>" + c.trim() + "</code></pre>");
    return "\u0000" + (blocos.length - 1) + "\u0000";
  });
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, "");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  s = s.replace(/\n/g, "<br>");
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => blocos[Number(i)]);
  return s;
}
function rolar() { chat.scrollTop = chat.scrollHeight; }

function add(role, texto, artefatos = []) {
  if (vazio) vazio.style.display = "none";
  const d = document.createElement("div");
  d.className = "msg " + (role === "user" ? "voce" : "agente");
  const quem = document.createElement("span");
  quem.className = "quem";
  quem.textContent = role === "user" ? "VOCÊ" : "YVAKOR";
  const corpo = document.createElement("div");
  corpo.innerHTML = markdown(texto);
  d.append(quem, corpo);
  for (const a of artefatos || []) {
    if (!a || !a.url) continue;
    if (a.tipo === "imagem") {
      const img = document.createElement("img");
      img.src = BASE + a.url;
      img.loading = "lazy";
      img.alt = a.titulo || "resultado";
      d.appendChild(img);
      if (a.fonte || a.autor) {
        const cap = document.createElement("small");
        cap.textContent = `${a.titulo || "foto"} — ${a.autor || a.fonte}` +
          (a.licenca ? ` (${a.licenca})` : "");
        d.appendChild(cap);
      }
    } else {
      const link = document.createElement("a");
      link.className = "arquivo";
      link.href = BASE + a.url;
      link.target = "_blank";
      link.textContent = `⬇ ${a.titulo || a.nome || a.url}`;
      d.appendChild(link);
    }
  }
  chat.appendChild(d);
  rolar();
  return d;
}

/* --------------------------- progresso ----------------------------- */
function mostrarProcesso(v) { processo.classList.toggle("oculto", !v); }
function pintarPassos(steps, running) {
  passosEl.innerHTML = "";
  const ultimos = (steps || []).slice(-8);
  ultimos.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "passo" + (i === ultimos.length - 1 && running ? " atual" : "");
    d.textContent = (i === ultimos.length - 1 && running ? "▸ " : "· ") + s;
    passosEl.appendChild(d);
  });
  procStatus.textContent = running ? "executando" : "concluído";
  procStatus.style.color = running ? "var(--ouro)" : "var(--agua)";
}
async function acompanhar(sid) {
  clearInterval(timerProgresso);
  mostrarProcesso(true);
  passosEl.innerHTML = "";
  procStatus.textContent = "iniciando…";
  const tick = async () => {
    try {
      const p = await api("/api/progress?session=" + encodeURIComponent(sid),
                          { timeout: 4000 });
      pintarPassos(p.steps || [], !!p.running);
    } catch (e) { /* ignora */ }
  };
  await tick();
  timerProgresso = setInterval(tick, 900);
}

/* ---------------------------- envio -------------------------------- */
async function enviarMensagem() {
  if (ocupado) return;
  const texto = entrada.value.trim();
  if (!texto) return;
  if (!sessao) {
    try { await novaSessao(); }
    catch (e) { add("agente", "Núcleo indisponível: " + e.message); return; }
  }
  ocupado = true;
  enviar.disabled = true;
  entrada.value = "";
  ajustarAltura();
  add("user", texto);
  await acompanhar(sessao);
  try {
    const body = { message: texto, session: sessao };
    await atualizarContexto();
    if (contexto) {
      body.page_context = `TÍTULO: ${contexto.titulo || ""}\n`
        + `URL: ${contexto.url || ""}\n`
        + (contexto.descricao ? `DESCRIÇÃO: ${contexto.descricao}\n` : "")
        + (contexto.secoes ? `SEÇÕES: ${contexto.secoes}\n` : "")
        + (contexto.selecao ? `SELEÇÃO: ${contexto.selecao}\n` : "")
        + `\nCONTEÚDO:\n${contexto.texto
           || "(conteúdo textual não acessível; use o título e a URL acima)"}`;
    }
    // Captura automática só quando a página tem pouco texto (canvas/imagem).
    if (contextoAba && /^https?:/i.test(contextoAba.url || "")
        && (contexto.texto || "").length < 700) {
      try {
        body.page_image = await chrome.tabs.captureVisibleTab(
          contextoAba.windowId, { format: "jpeg", quality: 78 });
      } catch (e) { /* captura indisponível */ }
    }
    const j = await api("/api/chat", { method: "POST", body, timeout: 600000 });
    if (j.session) { sessao = j.session; await guardarSessao(); }
    const bolha = add("agente", j.answer || j.error || "(sem resposta)", j.artefatos || []);
    if (vozAtiva) falarTexto(j.answer || "", bolha);
  } catch (e) {
    add("agente", "Erro: " + e.message);
  } finally {
    ocupado = false;
    enviar.disabled = false;
    clearInterval(timerProgresso);
    procStatus.textContent = "concluído";
    entrada.focus();
    ping();
    atualizarContexto();
  }
}

async function limparConversa() {
  try {
    await novaSessao();
    chat.querySelectorAll(".msg").forEach(e => e.remove());
    if (vazio) vazio.style.display = "";
    mostrarProcesso(false);
    ping();
  } catch (e) { add("agente", "Não consegui criar conversa: " + e.message); }
}

/* ---------------------------- utilidades --------------------------- */
function ajustarAltura() {
  entrada.style.height = "auto";
  entrada.style.height = Math.min(100, entrada.scrollHeight) + "px";
}
entrada.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    enviarMensagem();
  }
});
entrada.addEventListener("input", ajustarAltura);
enviar.addEventListener("click", enviarMensagem);
$("nova").addEventListener("click", limparConversa);

/* ------------------------------ voz -------------------------------- */
function limparFala(t) {
  return String(t || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[#*_`>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 900);
}
function botaoOuvir(alvo, audio, url) {
  if (!alvo || alvo.querySelector(".ouvir")) return;
  const b = document.createElement("button");
  b.className = "ouvir";
  b.textContent = "🔊 ouvir";
  b.onclick = () => {
    if (audio.paused) {
      audio.play().catch(() => {});
      b.textContent = "⏸ pausar";
    } else {
      audio.pause();
      b.textContent = "🔊 ouvir";
    }
  };
  alvo.appendChild(b);
}

function falarTexto(texto, alvo) {
  const fala = limparFala(texto);
  if (!fala) return;
  // Voz neural do núcleo (Antonio) no painel; Web Speech só como fallback.
  fetch(BASE + "/api/voz/audio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texto: fala })
  }).then(r => {
    if (!r.ok) throw new Error("sem áudio");
    return r.blob();
  }).then(blob => {
    if (!vozAtiva) return;
    if (window._yvAudio) {
      try { window._yvAudio.pause(); } catch (e) {}
      try { URL.revokeObjectURL(window._yvAudio.src); } catch (e) {}
    }
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    window._yvAudio = audio;
    audio.onended = () => { try { URL.revokeObjectURL(url); } catch (e) {} };
    audio.play().then(() => {
      if (alvo) {
        const b = document.createElement("button");
        b.className = "ouvir";
        b.textContent = "⏸ pausar";
        b.onclick = () => {
          if (audio.paused) { audio.play(); b.textContent = "⏸ pausar"; }
          else { audio.pause(); b.textContent = "🔊 ouvir"; }
        };
        alvo.appendChild(b);
      }
    }).catch(() => botaoOuvir(alvo, audio, url));
  }).catch(() => {
    if (!vozAtiva) return;
    if (!("speechSynthesis" in window)) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(fala);
    const pt = speechSynthesis.getVoices().filter(
      v => (v.lang || "").toLowerCase().startsWith("pt-br"));
    const masculina = pt.find(v => /antonio|daniel|male|masc/i.test(v.name));
    if (masculina) u.voice = masculina;
    else if (pt.length) u.voice = pt[0];
    u.lang = "pt-BR";
    u.pitch = 1.0;
    u.rate = 1.0;
    speechSynthesis.speak(u);
  });
}
function pintarVoz() {
  vozBtn.textContent = vozAtiva ? "🔊" : "🔇";
  vozBtn.classList.toggle("on", vozAtiva);
  vozBtn.title = vozAtiva ? "Desativar voz" : "Ativar voz";
}
vozBtn.addEventListener("click", () => {
  vozAtiva = !vozAtiva;
  localStorage.setItem("yvakor_voz", vozAtiva ? "1" : "0");
  pintarVoz();
  if (vozAtiva) falarTexto("Voz ativada.");
  else {
    try { if (window._yvAudio) window._yvAudio.pause(); } catch (e) {}
    try { speechSynthesis.cancel(); } catch (e) {}
  }
});

function alternarMicrofone() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { add("agente", "Este Chrome não expõe reconhecimento de voz."); return; }
  if (recVoz) { try { recVoz.stop(); } catch (e) {} return; }
  recVoz = new SR();
  recVoz.lang = "pt-BR";
  recVoz.interimResults = true;
  recVoz.continuous = false;
  recVoz.onresult = (e) => {
    let t = "";
    for (let i = e.resultIndex; i < e.results.length; i++) t += e.results[i][0].transcript;
    entrada.value = t;
    ajustarAltura();
  };
  recVoz.onend = () => { recVoz = null; mic.classList.remove("on"); };
  recVoz.onerror = () => { recVoz = null; mic.classList.remove("on"); };
  entrada.value = "";
  try { recVoz.start(); mic.classList.add("on"); }
  catch (e) { add("agente", "Microfone indisponível: " + e.message); }
}
mic.addEventListener("click", alternarMicrofone);

/* ---------------- ponte: operar o Chrome onde a extensão está -------- */
let ponteOcupada = false;

async function pontePing() {
  try {
    await api("/api/ext/ping", { method: "POST", body: {}, timeout: 3000 });
  } catch (e) { /* núcleo offline */ }
}

async function abaAtiva() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!t || !t.id) throw new Error("sem aba ativa");
  return t;
}

const CTRL_KEY = "yvakor_ctrl_tab";
async function ctrlId() {
  try {
    const o = await chrome.storage.session.get(CTRL_KEY);
    return o[CTRL_KEY] || null;
  } catch (e) { return null; }
}
async function setCtrlId(id) {
  try { await chrome.storage.session.set({ [CTRL_KEY]: id }); } catch (e) {}
}
async function ctrlOrActive() {
  const id = await ctrlId();
  if (id) {
    const t = await chrome.tabs.get(id).catch(() => null);
    if (t) return t;
  }
  return abaAtiva();
}

const dormir = (ms) => new Promise(r => setTimeout(r, ms));
async function aguardarCarregar(tabId, ms = 7000) {
  const fim = Date.now() + ms;
  while (Date.now() < fim) {
    const t = await chrome.tabs.get(tabId).catch(() => null);
    if (t && t.status === "complete" && t.url && !t.url.startsWith("about:")) {
      await dormir(500);
      return t;
    }
    await dormir(250);
  }
  return chrome.tabs.get(tabId).catch(() => null);
}

async function script(func, args = []) {
  const t = await ctrlOrActive();
  const r = await chrome.scripting.executeScript({
    target: { tabId: t.id }, func, args
  });
  return { tab: t, resultado: r && r[0] ? r[0].result : null };
}

async function responder(c, ok, dados = {}, erro = "") {
  await api("/api/ext/resultado", {
    method: "POST",
    body: { id: c.id, ok, erro, ...dados },
    timeout: 5000
  });
}

async function injetarOverlay() {
  const t = await ctrlOrActive();
  await chrome.scripting.executeScript({
    target: { tabId: t.id }, files: ["overlay.js"]
  });
}

async function resumoCurto() {
  try {
    const { resultado } = await script(() => {
      const corpo = document.body || document.documentElement;
      return { url: location.href, titulo: document.title,
               texto: (corpo ? corpo.innerText : "").slice(0, 1200) };
    });
    return resultado;
  } catch (e) { return {}; }
}

async function executarComando(c) {
  const a = c.args || {};
  if (c.tipo === "open") {
    // Reaproveita a aba de controle em vez de abrir várias.
    const prev = await ctrlId();
    let tab = prev ? await chrome.tabs.get(prev).catch(() => null) : null;
    if (tab) {
      await chrome.tabs.update(tab.id, { url: a.url || "about:blank", active: true });
      await chrome.windows.update(tab.windowId, { focused: true });
      tab = await aguardarCarregar(tab.id);
      return { tab_id: tab.id, titulo: a.url || tab.title || "",
               url: a.url || tab.url || "" };
    }
    tab = await chrome.tabs.create({ url: a.url || "about:blank", active: true });
    await setCtrlId(tab.id);
    tab = await aguardarCarregar(tab.id);
    return { tab_id: tab.id, titulo: a.url || tab.title || "",
             url: a.url || tab.url || "" };
  }
  if (c.tipo === "newtab") {
    let tab = await chrome.tabs.create({ url: a.url || "about:blank",
                                         active: true });
    await setCtrlId(tab.id);
    tab = await aguardarCarregar(tab.id);
    return { tab_id: tab.id, titulo: a.url || tab.title || "",
             url: a.url || tab.url || "" };
  }
  if (c.tipo === "goto") {
    const t = await ctrlOrActive();
    await chrome.tabs.update(t.id, { url: a.url || "about:blank" });
    await aguardarCarregar(t.id);
    return { tab_id: t.id, url: a.url || "" };
  }
  if (c.tipo === "search") {
    const t = await ctrlOrActive();
    const url = "https://www.google.com/search?q=" +
      encodeURIComponent(a.termo || "");
    await chrome.tabs.update(t.id, { url });
    await aguardarCarregar(t.id);
    return { tab_id: t.id, url };
  }
  if (c.tipo === "tabs") {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    return { abas: tabs.map(t => ({ indice: t.index, id: t.id,
                                    url: t.url || "", titulo: t.title || "",
                                    ativa: !!t.active })) };
  }
  if (c.tipo === "switch_tab") {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    const i = Math.max(0, Math.min(tabs.length - 1, Number(a.indice) || 0));
    await chrome.tabs.update(tabs[i].id, { active: true });
    return { tab_id: tabs[i].id, url: tabs[i].url || "" };
  }
  if (c.tipo === "close_tab") {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    let i = Number(a.indice);
    if (i === -1 || i === undefined) i = tabs.findIndex(t => t.active);
    i = Math.max(0, Math.min(tabs.length - 1, i || 0));
    await chrome.tabs.remove(tabs[i].id);
    return { tab_id: tabs[i].id };
  }
  if (c.tipo === "snapshot") {
    const coletaSnap = () => {
      const SEL = "a,button,input,textarea,select,[role='button'],[role='link']," +
                  "[onclick],ytd-video-renderer,ytd-rich-item-renderer," +
                  "[data-testid],[aria-label]";
      function deepText(node) {
        if (!node) return "";
        if (node.nodeType === 3) return node.textContent + " ";
        if (node.nodeType === 1) {
          const tag = (node.tagName || "").toLowerCase();
          if (["script", "style", "noscript", "template", "svg", "head",
               "iframe"].includes(tag)) return "";
          let s = "";
          if (node.shadowRoot) s += deepText(node.shadowRoot);
          for (const c of node.childNodes) s += deepText(c);
          return s;
        }
        if (node.nodeType === 11) {
          let s = "";
          for (const c of node.childNodes) s += deepText(c);
          return s;
        }
        return "";
      }
      const vistos = new Set();
      const items = [];
      function collect(cont) {
        if (!cont || !cont.querySelectorAll) return;
        for (const el of Array.from(cont.querySelectorAll(SEL))) {
          if (vistos.has(el)) continue;
          vistos.add(el);
          if (items.length >= 60) return;
          const ref = "e" + (items.length + 1);
          el.setAttribute("data-yvakor-ref", ref);
          const txt = (el.innerText || el.textContent ||
                       el.getAttribute("aria-label") || el.title ||
                       el.value || el.placeholder || "")
            .replace(/\s+/g, " ").trim().slice(0, 120);
          items.push({ ref, tag: el.tagName.toLowerCase(),
                       tipo: (el.getAttribute("type") || "").toLowerCase(),
                       texto: txt, id: el.id || "",
                       aria: (el.getAttribute("aria-label") || "").slice(0, 80) });
        }
        if (vistos.size >= 2500) return;
        for (const el of Array.from(cont.querySelectorAll("*"))) {
          if (el.shadowRoot) collect(el.shadowRoot);
          if (vistos.size >= 2500) break;
        }
      }
      collect(document.documentElement || document);
      const texto = deepText(document.documentElement || document)
        .replace(/\s+/g, " ").trim().slice(0, 3000);
      return { url: location.href, title: document.title, text: texto, items };
    };
    let tab = null, resultado = null;
    for (let i = 0; i < 5; i++) {
      const r = await script(coletaSnap);
      tab = r.tab; resultado = r.resultado;
      if (resultado && (resultado.title || resultado.text)) break;
      await dormir(700);
    }
    const elementos = (resultado && resultado.items) || [];
    const resumo = `URL: ${resultado ? resultado.url : ""}\nTÍTULO: ${resultado ? resultado.title : ""}\n\n` +
      `TEXTO:\n${((resultado && resultado.text) || "").slice(0, 1800)}\n\nELEMENTOS:\n` +
      elementos.slice(0, 60).map(e => `[${e.ref}] <${e.tag}> ${e.texto}`).join("\n");
    return { url: resultado ? resultado.url : "", titulo: resultado ? resultado.title : "",
             elementos_total: elementos.length, resumo,
             elementos, tab_id: tab ? tab.id : null };
  }
  if (c.tipo === "extract") {
    const { resultado } = await script((maxChars) => {
      function deepText(node) {
        if (!node) return "";
        if (node.nodeType === 3) return node.textContent + " ";
        if (node.nodeType === 1) {
          const tag = (node.tagName || "").toLowerCase();
          if (["script", "style", "noscript", "template", "svg", "head",
               "iframe"].includes(tag)) return "";
          let s = "";
          if (node.shadowRoot) s += deepText(node.shadowRoot);
          for (const c of node.childNodes) s += deepText(c);
          return s;
        }
        if (node.nodeType === 11) {
          let s = "";
          for (const c of node.childNodes) s += deepText(c);
          return s;
        }
        return "";
      }
      const texto = deepText(document.documentElement || document)
        .replace(/\s+/g, " ").trim().slice(0, maxChars || 6000);
      const links = [];
      const vistos = new Set();
      function collectLinks(cont) {
        if (!cont || !cont.querySelectorAll) return;
        for (const a of Array.from(cont.querySelectorAll("a[href]"))) {
          if (vistos.has(a)) continue;
          vistos.add(a);
          if (links.length >= 60) return;
          links.push({
            texto: (a.innerText || a.textContent ||
                    a.getAttribute("aria-label") || "")
              .replace(/\s+/g, " ").trim().slice(0, 80),
            url: String(a.href).slice(0, 200)
          });
        }
        if (vistos.size >= 5000) return;
        for (const el of Array.from(cont.querySelectorAll("*"))) {
          if (el.shadowRoot) collectLinks(el.shadowRoot);
          if (vistos.size >= 5000) break;
        }
      }
      collectLinks(document.documentElement || document);
      return { texto, links: links.filter(l => l.texto),
               url: location.href, titulo: document.title };
    }, [Number(a.max_chars) || 6000]);
    return { texto: resultado.texto, links: resultado.links,
             url: resultado.url, titulo: resultado.titulo };
  }
  if (c.tipo === "click") {
    await injetarOverlay();
    const { resultado } = await script(async (alvo) => {
      function findByRef(ref) {
        function find(cont) {
          if (!cont || !cont.querySelectorAll) return null;
          const el = cont.querySelector(`[data-yvakor-ref="${ref}"]`);
          if (el) return el;
          for (const node of Array.from(cont.querySelectorAll("*"))) {
            if (node.shadowRoot) {
              const r = find(node.shadowRoot);
              if (r) return r;
            }
          }
          return null;
        }
        return find(document.documentElement || document);
      }
      let el = /^e\d+$/.test(alvo) ? findByRef(alvo) : null;
      if (!el) {
        try { el = document.querySelector(alvo); } catch (e) {}
      }
      if (!el) {
        const txt = (alvo || "").toLowerCase();
        el = Array.from(document.querySelectorAll("a,button,[role='button']"))
          .find(x => (x.innerText || "").toLowerCase().includes(txt));
      }
      if (!el) return { ok: false, erro: "elemento não encontrado" };
      await window.__yvakorVisual.click(el, "clicando");
      const corpo = document.body || document.documentElement;
      return { ok: true, url: location.href, titulo: document.title,
               texto: (corpo ? corpo.innerText : "").slice(0, 1200) };
    }, [a.alvo || ""]);
    return resultado;
  }
  if (c.tipo === "fill") {
    await injetarOverlay();
    const { resultado } = await script(async (alvo, valor, enviar) => {
      function findByRef(ref) {
        function find(cont) {
          if (!cont || !cont.querySelectorAll) return null;
          const el = cont.querySelector(`[data-yvakor-ref="${ref}"]`);
          if (el) return el;
          for (const node of Array.from(cont.querySelectorAll("*"))) {
            if (node.shadowRoot) {
              const r = find(node.shadowRoot);
              if (r) return r;
            }
          }
          return null;
        }
        return find(document.documentElement || document);
      }
      let el = /^e\d+$/.test(alvo) ? findByRef(alvo) : null;
      if (!el) { try { el = document.querySelector(alvo); } catch (e) {} }
      if (!el) return { ok: false, erro: "campo não encontrado" };
      await window.__yvakorVisual.type(el, valor, "digitando");
      if (enviar) {
        el.dispatchEvent(new KeyboardEvent("keydown",
          { key: "Enter", bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keyup",
          { key: "Enter", bubbles: true }));
      }
      const corpo = document.body || document.documentElement;
      return { ok: true, url: location.href, titulo: document.title,
               texto: (corpo ? corpo.innerText : "").slice(0, 1200) };
    }, [a.alvo || "", String(a.valor || ""), !!a.enviar]);
    return resultado;
  }
  if (c.tipo === "press") {
    const { resultado } = await script((tecla) => {
      const alvo = document.activeElement || document.body;
      alvo.dispatchEvent(new KeyboardEvent("keydown",
        { key: tecla, bubbles: true }));
      alvo.dispatchEvent(new KeyboardEvent("keyup",
        { key: tecla, bubbles: true }));
      return { ok: true };
    }, [a.tecla || "Enter"]);
    return resultado;
  }
  if (c.tipo === "scroll") {
    const { resultado } = await script((dir, vezes) => {
      const passo = (dir === "cima" ? -1 : 1) * 600 * (vezes || 1);
      window.scrollBy(0, passo);
      return { ok: true, y: window.scrollY };
    }, [a.direcao || "baixo", Number(a.vezes) || 1]);
    return resultado;
  }
  throw new Error("comando desconhecido: " + c.tipo);
}

async function ponteComandos() {
  if (ponteOcupada) return;
  ponteOcupada = true;
  try {
    const j = await api("/api/ext/comandos", { timeout: 4000 });
    for (const c of j.comandos || []) {
      try {
        const dados = await executarComando(c);
        await responder(c, true, dados);
      } catch (e) {
        await responder(c, false, {}, e.message || "falha");
      }
    }
  } catch (e) { /* sem comando */ }
  finally { ponteOcupada = false; }
}

pontePing();
setInterval(pontePing, 5000);
setInterval(ponteComandos, 1500);

/* ----------------------------- iniciar ----------------------------- */
(async function iniciar() {
  ajustarAltura();
  pintarVoz();
  await carregarBuild();
  await ping();
  setInterval(ping, 5000);
  const salva = await lerSessao();
  if (salva) sessao = salva;
  try {
    const lista = await api("/api/sessions", { timeout: 5000 });
    if (!sessao || !(lista.sessions || []).some(s => s.id === sessao)) {
      await novaSessao();
    }
  } catch (e) { await ping(); }
  await atualizarContexto();
  entrada.focus();
})();
