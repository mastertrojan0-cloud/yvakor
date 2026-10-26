chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((e) => console.warn("sidePanel:", e));

const BASE = "http://127.0.0.1:7777";

function reportarErro() {
  try {
    fetch(BASE + "/api/ext/erro", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: "{}"
    }).catch(() => {});
  } catch (e) {}
}
globalThis.addEventListener("error", reportarErro);
globalThis.addEventListener("unhandledrejection", reportarErro);

async function pontePing() {
  try {
    await fetch(BASE + "/api/ext/ping", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: "{}"
    });
  } catch (e) { /* núcleo offline */ }
}

async function abaAtivaBG() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!t || !t.id) throw new Error("sem aba ativa");
  return t;
}

const CTRL_KEY = "yvakor_ctrl_tab";
async function ctrlIdBG() {
  try {
    const o = await chrome.storage.session.get(CTRL_KEY);
    return o[CTRL_KEY] || null;
  } catch (e) { return null; }
}
async function setCtrlIdBG(id) {
  try { await chrome.storage.session.set({ [CTRL_KEY]: id }); } catch (e) {}
}
async function ctrlOrActiveBG() {
  const id = await ctrlIdBG();
  if (id) {
    const t = await chrome.tabs.get(id).catch(() => null);
    if (t) return t;
  }
  return abaAtivaBG();
}

const dormirBG = (ms) => new Promise(r => setTimeout(r, ms));
async function aguardarCarregarBG(tabId, ms = 7000) {
  const fim = Date.now() + ms;
  while (Date.now() < fim) {
    const t = await chrome.tabs.get(tabId).catch(() => null);
    if (t && t.status === "complete" && t.url && !t.url.startsWith("about:")) {
      await dormirBG(500);
      return t;
    }
    await dormirBG(250);
  }
  return chrome.tabs.get(tabId).catch(() => null);
}

async function scriptBG(func, args = []) {
  const t = await ctrlOrActiveBG();
  const r = await chrome.scripting.executeScript({
    target: { tabId: t.id }, func, args
  });
  return { tab: t, resultado: r && r[0] ? r[0].result : null };
}

async function responderBG(c, ok, dados = {}, erro = "") {
  await fetch(BASE + "/api/ext/resultado", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: c.id, ok, erro, ...dados })
  });
}

async function injetarOverlayBG() {
  const t = await ctrlOrActiveBG();
  await chrome.scripting.executeScript({
    target: { tabId: t.id }, files: ["overlay.js"]
  });
}

async function executarBG(c) {
  const a = c.args || {};
  if (c.tipo === "open") {
    // Reaproveita a aba de controle em vez de abrir várias.
    const prev = await ctrlIdBG();
    let tab = prev ? await chrome.tabs.get(prev).catch(() => null) : null;
    if (tab) {
      await chrome.tabs.update(tab.id, { url: a.url || "about:blank", active: true });
      await chrome.windows.update(tab.windowId, { focused: true });
      tab = await aguardarCarregarBG(tab.id);
      return { tab_id: tab.id, titulo: a.url || tab.title || "",
               url: a.url || tab.url || "" };
    }
    tab = await chrome.tabs.create({ url: a.url || "about:blank", active: true });
    await setCtrlIdBG(tab.id);
    tab = await aguardarCarregarBG(tab.id);
    return { tab_id: tab.id, titulo: a.url || tab.title || "",
             url: a.url || tab.url || "" };
  }
  if (c.tipo === "newtab") {
    let tab = await chrome.tabs.create({ url: a.url || "about:blank",
                                         active: true });
    await setCtrlIdBG(tab.id);
    tab = await aguardarCarregarBG(tab.id);
    return { tab_id: tab.id, titulo: a.url || tab.title || "",
             url: a.url || tab.url || "" };
  }
  if (c.tipo === "goto") {
    const t = await ctrlOrActiveBG();
    await chrome.tabs.update(t.id, { url: a.url || "about:blank" });
    await aguardarCarregarBG(t.id);
    return { tab_id: t.id, url: a.url || "" };
  }
  if (c.tipo === "search") {
    const t = await ctrlOrActiveBG();
    const url = "https://www.google.com/search?q=" + encodeURIComponent(a.termo || "");
    await chrome.tabs.update(t.id, { url });
    await aguardarCarregarBG(t.id);
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
      const r = await scriptBG(coletaSnap);
      tab = r.tab; resultado = r.resultado;
      if (resultado && (resultado.title || resultado.text)) break;
      await dormirBG(700);
    }
    const elementos = (resultado && resultado.items) || [];
    const resumo = `URL: ${resultado ? resultado.url : ""}\nTÍTULO: ${resultado ? resultado.title : ""}\n\n` +
      `TEXTO:\n${((resultado && resultado.text) || "").slice(0, 1800)}\n\nELEMENTOS:\n` +
      elementos.slice(0, 60).map(e => `[${e.ref}] <${e.tag}> ${e.texto}`).join("\n");
    return { url: resultado ? resultado.url : "", titulo: resultado ? resultado.title : "",
             elementos_total: elementos.length, resumo, elementos, tab_id: tab ? tab.id : null };
  }
  if (c.tipo === "extract") {
    const { resultado } = await scriptBG((maxChars) => {
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
    await injetarOverlayBG();
    const { resultado } = await scriptBG(async (alvo) => {
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
    await injetarOverlayBG();
    const { resultado } = await scriptBG(async (alvo, valor, enviar) => {
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
        el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", bubbles: true }));
      }
      const corpo = document.body || document.documentElement;
      return { ok: true, url: location.href, titulo: document.title,
               texto: (corpo ? corpo.innerText : "").slice(0, 1200) };
    }, [a.alvo || "", String(a.valor || ""), !!a.enviar]);
    return resultado;
  }
  if (c.tipo === "press") {
    const { resultado } = await scriptBG((tecla) => {
      const alvo = document.activeElement || document.body;
      alvo.dispatchEvent(new KeyboardEvent("keydown", { key: tecla, bubbles: true }));
      alvo.dispatchEvent(new KeyboardEvent("keyup", { key: tecla, bubbles: true }));
      return { ok: true };
    }, [a.tecla || "Enter"]);
    return resultado;
  }
  if (c.tipo === "scroll") {
    const { resultado } = await scriptBG((dir, vezes) => {
      window.scrollBy(0, (dir === "cima" ? -1 : 1) * 600 * (vezes || 1));
      return { ok: true, y: window.scrollY };
    }, [a.direcao || "baixo", Number(a.vezes) || 1]);
    return resultado;
  }
  throw new Error("comando desconhecido: " + c.tipo);
}

async function ponteComandos() {
  try {
    const r = await fetch(BASE + "/api/ext/comandos", { cache: "no-store" });
    const j = await r.json();
    for (const c of (j.comandos || [])) {
      try {
        const dados = await executarBG(c);
        await responderBG(c, true, dados);
      } catch (e) {
        await responderBG(c, false, {}, e.message || "falha");
      }
    }
  } catch (e) { /* sem comando */ }
}

pontePing();
setInterval(pontePing, 10000);
setInterval(ponteComandos, 1200);
try {
  chrome.alarms.create("yvakor-bridge", { periodInMinutes: 0.5 });
} catch (e) { /* versões antigas exigem >=1 min */ }
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "yvakor-bridge") { pontePing(); ponteComandos(); }
});
chrome.tabs.onActivated.addListener(pontePing);
chrome.tabs.onUpdated.addListener((id, info) => {
  if (info.status === "complete") pontePing();
});
chrome.tabs.onRemoved.addListener((id) => {
  ctrlIdBG().then(c => { if (c === id) setCtrlIdBG(null); });
});

async function verificarBuild() {
  try {
    const local = await fetch(chrome.runtime.getURL("build.json")).then(r => r.json());
    const core = await fetch("http://127.0.0.1:7777/api/version", {
      cache: "no-store"
    }).then(r => r.json());
    if (String(core.build) !== String(local.build)) {
      await chrome.action.setBadgeBackgroundColor({ color: "#D9A441" });
      await chrome.action.setBadgeText({ text: "!" });
      await chrome.action.setTitle({
        title: `YVAKOR — atualização disponível (v${core.version})`
      });
    } else {
      await chrome.action.setBadgeText({ text: "" });
      await chrome.action.setTitle({ title: "Abrir YVAKOR" });
    }
  } catch (e) {
    /* núcleo offline: sem badge */
  }
}

chrome.runtime.onInstalled.addListener(verificarBuild);
chrome.runtime.onStartup.addListener(verificarBuild);
verificarBuild();
setInterval(verificarBuild, 60000);
