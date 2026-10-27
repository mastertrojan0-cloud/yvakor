chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((e) => console.warn("sidePanel:", e));

const BASE = "http://127.0.0.1:7777";

// Token exigido pelo núcleo em rotas de efeito (POST). Buscado no GET
// /api/token (o CORS só deixa a extensão ler essa resposta) e reenviado no
// header X-YVAKOR-Token. Em 403, renova e tenta de novo.
let TOKEN = "";
async function obterToken() {
  try {
    const r = await fetch(BASE + "/api/token", { cache: "no-store" });
    if (r.ok) { TOKEN = (await r.json()).token || ""; }
  } catch (e) { /* núcleo offline */ }
  return TOKEN;
}
function cabNucleo() {
  const h = { "Content-Type": "application/json" };
  if (TOKEN) h["X-YVAKOR-Token"] = TOKEN;
  return h;
}
async function postNucleo(path, obj) {
  if (!TOKEN) await obterToken();
  const corpo = JSON.stringify(obj || {});
  let r = await fetch(BASE + path, { method: "POST", headers: cabNucleo(), body: corpo });
  if (r.status === 403) {
    await obterToken();
    r = await fetch(BASE + path, { method: "POST", headers: cabNucleo(), body: corpo });
  }
  return r;
}
obterToken();

function reportarErro() {
  try {
    postNucleo("/api/ext/erro", {}).catch(() => {});
  } catch (e) {}
}
globalThis.addEventListener("error", reportarErro);
globalThis.addEventListener("unhandledrejection", reportarErro);

async function pontePing() {
  try {
    await postNucleo("/api/ext/ping", {});
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
// Aba pedida no comando atual (`aba`). Os comandos rodam UM por vez (a trava
// ponteOcupada), então uma variável de módulo é segura.
let abaAlvo = null;
let abaEstrita = false;     // close_tab/switch_tab: id inexistente é ERRO; nos demais comandos cai na aba atual
let avisoAba = "";
const ABAS_CHAVE = "yvakor_abas_do_agente";
const GRUPO_TITULO = "YVAKOR";

async function ctrlOrActiveBG() {
  if (abaAlvo != null) {
    const t = await chrome.tabs.get(abaAlvo).catch(() => null);
    if (t) return t;
    if (abaEstrita) throw new Error("a aba " + abaAlvo + " não existe mais (use navegador_abas para ver as atuais)");
    // Modelos pequenos inventam ids de aba (aba=0, aba=2…). Em vez de travar o agente num laço de
    // erro, age na aba atual e avisa no resultado.
    avisoAba = "a aba " + abaAlvo + " não existe; usei a aba atual (só passe `aba` com ids de navegador_abas)";
  }
  const id = await ctrlIdBG();
  if (id) {
    const t = await chrome.tabs.get(id).catch(() => null);
    if (t) return t;
  }
  return abaAtivaBG();
}

// ---- grupo de abas "YVAKOR" (como o grupo do Claude no Chrome) ----
// As abas que o agente abre ou passa a controlar entram num grupo amarelo, para
// o usuário ver quais são. O agente só FECHA abas desse conjunto.
async function lembrarAbaDoAgente(id) {
  try {
    const o = await chrome.storage.session.get(ABAS_CHAVE);
    const s = new Set(o[ABAS_CHAVE] || []);
    s.add(id);
    await chrome.storage.session.set({ [ABAS_CHAVE]: [...s] });
  } catch (e) { /* sem storage.session */ }
}

async function agruparBG(tabId) {
  await lembrarAbaDoAgente(tabId);
  try {                     // agrupar é cosmético: nunca quebra o comando
    if (!chrome.tabGroups || !chrome.tabs.group) return;
    const tab = await chrome.tabs.get(tabId);
    const existentes = await chrome.tabGroups.query({ windowId: tab.windowId, title: GRUPO_TITULO });
    if (existentes.length && tab.groupId === existentes[0].id) return;
    const gid = await chrome.tabs.group(existentes.length
      ? { tabIds: [tabId], groupId: existentes[0].id } : { tabIds: [tabId] });
    if (!existentes.length) await chrome.tabGroups.update(gid, { title: GRUPO_TITULO, color: "yellow" });
  } catch (e) { /* ignora */ }
}

async function abaDoAgente(tab) {
  try {
    const o = await chrome.storage.session.get(ABAS_CHAVE);
    if ((o[ABAS_CHAVE] || []).includes(tab.id)) return true;
    if (chrome.tabGroups && tab.groupId != null && tab.groupId >= 0) {
      const g = await chrome.tabGroups.get(tab.groupId).catch(() => null);
      return !!g && g.title === GRUPO_TITULO;
    }
  } catch (e) { /* ignora */ }
  return false;
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

async function responderBG(c, ok, dados = {}, erro = "") {
  await postNucleo("/api/ext/resultado", { id: c.id, ok, erro, ...dados });
}

// ---------------------------------------------------------------------------
// Ações na página: o motor está em pagina.js (injetado aqui). Antes cada ação
// era uma função solta embutida neste arquivo — difícil de testar e frágil
// (digitação em editores ricos, envio de formulário, <select>…).
// ---------------------------------------------------------------------------
const PAGINA_PROTEGIDA = /^(chrome|edge|about|chrome-extension|devtools|view-source|chrome-search):/;

async function acaoPagina(nome, args = {}) {
  const t = await ctrlOrActiveBG();
  if (PAGINA_PROTEGIDA.test(t.url || "")) {
    throw new Error("esta página do navegador (" + String(t.url).split(":")[0] +
                    ":) não aceita automação; abra um site normal");
  }
  // A política (modo, sites permitidos/bloqueados) vem do núcleo em cada comando
  // de ação. Quem decide é ESTE ponto, que conhece o host exato no momento.
  const { politica, confirmado_site, confirmado_acao, ...limpo } = args;
  if (ACOES_COM_EFEITO.has(nome)) {
    const veto = await verificarPolitica(t, nome, limpo, politica || {},
                                         !!confirmado_site, !!confirmado_acao);
    if (veto) return { tab: t, resultado: veto };
  }
  return { tab: t, resultado: await executarNaPagina(t, nome, limpo) };
}

async function executarNaPagina(t, nome, args) {
  await indicadorLigar(t.id);
  await chrome.scripting.executeScript({
    target: { tabId: t.id }, files: ["overlay.js", "pagina.js"] });
  const r = await chrome.scripting.executeScript({
    target: { tabId: t.id },
    func: async (n, a) => {
      try { return await window.__yvakorAcoes[n](a); }
      catch (e) { return { ok: false, erro: String((e && e.message) || e) }; }
    },
    args: [nome, args]
  });
  const resultado = r && r[0] && r[0].result;
  return resultado || { ok: false, erro: "a página não respondeu" };
}

// ---- permissões (inspirado no Claude no Chrome) ----
const ACOES_COM_EFEITO = new Set(["clicar", "escrever", "pressionar", "selecionar", "enviar_arquivo"]);
const HOST_SENSIVEL = /(bank|banco|bradesco|itau|santander|caixa\.gov|nubank|inter\.co|c6bank|sicredi|sicoob|bancodobrasil|paypal|mercadopago|pagseguro|pagbank|picpay|stripe|wise\.com|binance|coinbase|mercadobitcoin|gov\.br|receita\.fazenda)/i;

function hostDe(url) {
  try { return new URL(url).hostname.replace(/^www\./, "").toLowerCase(); } catch (e) { return ""; }
}
const hostCombina = (host, regra) => !!host && !!regra && (host === regra || host.endsWith("." + regra));

// Devolve null (pode agir) ou um resultado que NÃO executou nada: um bloqueio,
// ou {precisa_confirmar} para o núcleo perguntar ao usuário e reenviar o comando
// com confirmado_site / confirmado_acao.
async function verificarPolitica(t, nome, args, pol, okSite, okAcao) {
  const host = hostDe(t.url);
  const modo = pol.modo === "autonomo" ? "autonomo" : "perguntar";
  if ((pol.bloqueados || []).some((r) => hostCombina(host, r))) {
    return { ok: false, bloqueado: true, host,
             erro: "O usuário bloqueou o YVAKOR em " + host + "." };
  }
  const permitido = (pol.permitidos || []).some((r) => hostCombina(host, r));
  const hostSensivel = HOST_SENSIVEL.test(host);
  if (!okSite && !permitido && (modo === "perguntar" || hostSensivel)) {
    return { ok: false, host, precisa_confirmar: { tipo: "site", host, host_sensivel: hostSensivel } };
  }
  if (!okAcao) {
    const d = await executarNaPagina(t, "descrever_acao", Object.assign({ acao: nome }, args));
    // ação sensível pede confirmação nos DOIS modos
    if (d && d.sensivel) {
      return { ok: false, host, precisa_confirmar: {
        tipo: "acao", host, descricao: d.descricao || nome, sensivel: true, motivo: d.motivo || "" } };
    }
  }
  return null;
}

// Se a ação iniciou uma navegação (clicar num link, enviar um formulário),
// espera a página nova carregar antes de devolver o controle ao agente.
async function aposAcaoBG(tab) {
  await dormirBG(300);
  const t = await chrome.tabs.get(tab.id).catch(() => null);
  if (t && t.status === "loading") await aguardarCarregarBG(tab.id, 8000);
}

const BUSCADORES = {
  google: "https://www.google.com/search?q=",
  duckduckgo: "https://duckduckgo.com/?q=",
  bing: "https://www.bing.com/search?q=",
  youtube: "https://www.youtube.com/results?search_query="
};

// ---------------------------------------------------------------------------
// Indicador "YVAKOR está controlando esta aba" + botão Parar (como o Claude no
// Chrome): borda dourada e um pílula com Parar enquanto o agente trabalha.
// O Parar da página manda {tipo:"parar"} para cá, que cancela a execução no
// núcleo e remove o indicador de todas as abas.
// ---------------------------------------------------------------------------
const IND_CHAVE = "yvakor_abas_indicadas";
let ultimaAcao = 0;

// Roda DENTRO da página (serializada pelo executeScript): sem variáveis externas.
function bannerNaPagina(ligar) {
  const ID = "yvk-banner", BORDA = "yvk-borda";
  const velho = document.getElementById(ID), borda = document.getElementById(BORDA);
  if (!ligar) {
    if (velho) velho.remove();
    if (borda) borda.remove();
    return true;
  }
  if (velho) return true;                       // idempotente
  const b = document.createElement("div");
  b.id = BORDA;
  b.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483645;" +
    "box-shadow:inset 0 0 0 3px #e0a83c,inset 0 0 28px #e0a83c66;";
  const el = document.createElement("div");
  el.id = ID;
  el.setAttribute("role", "status");
  el.style.cssText = "position:fixed;top:10px;left:50%;transform:translateX(-50%);" +
    "z-index:2147483647;display:flex;gap:10px;align-items:center;background:#171d21;" +
    "color:#f4efe4;font:600 12px/1.2 'Segoe UI',sans-serif;padding:7px 8px 7px 14px;" +
    "border:1px solid #e0a83c;border-radius:999px;box-shadow:0 4px 18px #0009;";
  const ponto = document.createElement("span");
  ponto.textContent = "●";
  ponto.style.color = "#e0a83c";
  const txt = document.createElement("span");
  txt.textContent = "YVAKOR está controlando esta aba";
  const parar = document.createElement("button");
  parar.type = "button";
  parar.textContent = "Parar";
  parar.style.cssText = "all:unset;cursor:pointer;background:#b3382e;color:#fff;" +
    "padding:5px 12px;border-radius:999px;font:700 11px 'Segoe UI',sans-serif;";
  parar.addEventListener("click", () => {
    parar.textContent = "Parando…";
    try { chrome.runtime.sendMessage({ tipo: "parar" }); } catch (e) { /* sem runtime */ }
  });
  el.append(ponto, txt, parar);
  document.documentElement.append(b, el);
  return true;
}

async function indicadorLigar(tabId) {
  ultimaAcao = Date.now();
  // sempre injeta (é idempotente): uma navegação apaga o banner da página
  await chrome.scripting.executeScript({
    target: { tabId }, func: bannerNaPagina, args: [true] }).catch(() => {});
  try {
    const o = await chrome.storage.session.get(IND_CHAVE);
    const ids = new Set(o[IND_CHAVE] || []);
    if (!ids.has(tabId)) {
      ids.add(tabId);
      await chrome.storage.session.set({ [IND_CHAVE]: [...ids] });
    }
  } catch (e) { /* storage.session indisponível */ }
}

async function indicadorDesligar() {
  ultimaAcao = 0;
  let ids = [];
  try { ids = (await chrome.storage.session.get(IND_CHAVE))[IND_CHAVE] || []; } catch (e) {}
  for (const id of ids) {
    await chrome.scripting.executeScript({
      target: { tabId: id }, func: bannerNaPagina, args: [false] }).catch(() => {});
  }
  try { await chrome.storage.session.set({ [IND_CHAVE]: [] }); } catch (e) {}
}

chrome.runtime.onMessage.addListener((msg, _remetente, responder) => {
  if (!msg) return;
  if (msg.tipo === "parar") {
    (async () => {
      try { await postNucleo("/api/chat/cancelar", {}); } catch (e) { /* núcleo fora */ }
      await indicadorDesligar();
      responder({ ok: true });
    })();
    return true;                                 // resposta assíncrona
  }
  if (msg.tipo === "fim_tarefa") {
    indicadorDesligar().then(() => responder({ ok: true }));
    return true;
  }
});

// Campos de política que o núcleo anexa a cada comando de ação.
const politicaDe = (a) => ({ politica: a.politica, confirmado_site: a.confirmado_site,
                             confirmado_acao: a.confirmado_acao });

async function executarBG(c) {
  const a = (c && c.args) || {};
  abaAlvo = (a.aba != null && a.aba !== "") ? Number(a.aba) : null;
  abaEstrita = !!c && (c.tipo === "close_tab" || c.tipo === "switch_tab");
  avisoAba = "";
  try {
    const r = await executarBGInterno(c);
    return (avisoAba && r && typeof r === "object") ? Object.assign({ aviso: avisoAba }, r) : r;
  } finally { abaAlvo = null; abaEstrita = false; avisoAba = ""; }
}

async function executarBGInterno(c) {
  const a = c.args || {};
  if (c.tipo === "open") {
    // Reaproveita a aba de controle em vez de abrir várias.
    // `ativo` vem do núcleo: tarefas em segundo plano mandam ativo=false e NÃO
    // trocam a aba que o usuário está vendo. Nunca damos foco à JANELA (isso
    // puxava o Chrome para frente de qualquer app em uso) salvo `foco=true`.
    const ativo = a.ativo !== false;
    const prev = await ctrlIdBG();
    let tab = prev ? await chrome.tabs.get(prev).catch(() => null) : null;
    if (tab) {
      await chrome.tabs.update(tab.id, { url: a.url || "about:blank", active: ativo });
      if (ativo && a.foco === true) {
        await chrome.windows.update(tab.windowId, { focused: true });
      }
      tab = await aguardarCarregarBG(tab.id);
      return { tab_id: tab.id, titulo: a.url || tab.title || "",
               url: a.url || tab.url || "" };
    }
    tab = await chrome.tabs.create({ url: a.url || "about:blank", active: ativo });
    await setCtrlIdBG(tab.id);
    await agruparBG(tab.id);
    tab = await aguardarCarregarBG(tab.id);
    return { tab_id: tab.id, titulo: a.url || tab.title || "",
             url: a.url || tab.url || "" };
  }
  if (c.tipo === "newtab") {
    let tab = await chrome.tabs.create({ url: a.url || "about:blank",
                                         active: a.ativo !== false });
    await setCtrlIdBG(tab.id);
    await agruparBG(tab.id);
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
    const base = BUSCADORES[String(a.buscador || "google").toLowerCase()] || BUSCADORES.google;
    const url = base + encodeURIComponent(a.termo || "");
    await chrome.tabs.update(t.id, { url });
    const n = await aguardarCarregarBG(t.id);
    return { ok: true, tab_id: t.id, url, titulo: (n && n.title) || "" };
  }
  if (c.tipo === "tabs") {
    // TODAS as janelas (antes só a atual), com id, quem é a controlada e quais
    // pertencem ao grupo YVAKOR.
    const todas = await chrome.tabs.query({});
    const ctrl = await ctrlIdBG();
    const lista = [];
    for (const t of todas.slice(0, 60)) {
      lista.push({ indice: t.index, id: t.id, janela: t.windowId, url: t.url || "",
                   titulo: t.title || "", ativa: !!t.active, controlada: t.id === ctrl,
                   do_yvakor: await abaDoAgente(t) });
    }
    return { abas: lista };
  }
  if (c.tipo === "switch_tab") {
    let alvo = null;
    if (a.aba != null && a.aba !== "") {
      alvo = await chrome.tabs.get(Number(a.aba)).catch(() => null);
    } else {
      const tabs = await chrome.tabs.query({ currentWindow: true });
      alvo = tabs[Math.max(0, Math.min(tabs.length - 1, Number(a.indice) || 0))] || null;
    }
    if (!alvo) throw new Error("aba não encontrada (use navegador_abas para ver os ids)");
    await chrome.tabs.update(alvo.id, { active: a.ativo !== false });
    // Antes só ativava a aba: as ações seguintes continuavam indo para a ANTIGA.
    await setCtrlIdBG(alvo.id);
    await agruparBG(alvo.id);
    return { tab_id: alvo.id, url: alvo.url || "", titulo: alvo.title || "", controlada: true };
  }
  if (c.tipo === "close_tab") {
    let alvo = null;
    if (a.aba != null && a.aba !== "") {
      alvo = await chrome.tabs.get(Number(a.aba)).catch(() => null);
    } else if (a.indice != null && Number(a.indice) >= 0) {
      const tabs = await chrome.tabs.query({ currentWindow: true });
      alvo = tabs[Math.min(tabs.length - 1, Number(a.indice))] || null;
    } else {
      // Sem alvo: a aba CONTROLADA. Antes `Number(undefined)` virava NaN → índice 0,
      // que fechava a primeira aba do usuário.
      alvo = await ctrlOrActiveBG();
    }
    if (!alvo) throw new Error("aba não encontrada");
    // Só fecha o que o agente abriu ou passou a controlar (como o Claude no Chrome).
    if (a.forcar !== true && !(await abaDoAgente(alvo))) {
      return { ok: false, tab_id: alvo.id,
               erro: "só fecho abas do grupo YVAKOR (as que abri ou passei a controlar); esta é uma aba sua" };
    }
    await chrome.tabs.remove(alvo.id);
    return { ok: true, tab_id: alvo.id };
  }
  if (c.tipo === "snapshot") {
    let r = null;
    for (let i = 0; i < 5; i++) {
      r = await acaoPagina("snapshot", { max: 80 });
      const s = r.resultado || {};
      if (s.title || s.text || (s.items || []).length) break;
      await dormirBG(700);
    }
    const s = r.resultado || {};
    return { url: s.url || "", titulo: s.title || "",
             elementos_total: (s.items || []).length, resumo: s.resumo || "",
             elementos: s.items || [], tab_id: r.tab.id };
  }
  if (c.tipo === "find") {
    const { tab, resultado } = await acaoPagina("procurar", {
      consulta: a.consulta || "", max: Number(a.max) || 20 });
    return Object.assign({ tab_id: tab.id }, resultado);
  }
  if (c.tipo === "extract") {
    const { tab, resultado } = await acaoPagina("extrair", {
      max_chars: Number(a.max_chars) || 6000, seletor: a.seletor || a.selector || "" });
    return Object.assign({ tab_id: tab.id }, resultado);
  }
  if (c.tipo === "click") {
    const { tab, resultado } = await acaoPagina("clicar", Object.assign({ alvo: a.alvo || "" }, politicaDe(a)));
    await aposAcaoBG(tab);
    return resultado;
  }
  // fill = preenche (substitui, a menos que limpar=false); type = digita
  // acrescentando ao que já existe (a menos que limpar=true).
  if (c.tipo === "fill" || c.tipo === "type") {
    const limpar = c.tipo === "type" ? a.limpar === true : a.limpar !== false;
    const { tab, resultado } = await acaoPagina("escrever", Object.assign({
      alvo: a.alvo || "", texto: String(a.valor != null ? a.valor : (a.texto || "")),
      enviar: !!a.enviar, limpar, humano: !!a.humano }, politicaDe(a)));
    if (a.enviar) await aposAcaoBG(tab);
    return resultado;
  }
  if (c.tipo === "press") {
    const { tab, resultado } = await acaoPagina("pressionar", Object.assign({
      tecla: a.tecla || "Enter", alvo: a.alvo || "" }, politicaDe(a)));
    await aposAcaoBG(tab);
    return resultado;
  }
  if (c.tipo === "select") {
    const { resultado } = await acaoPagina("selecionar", Object.assign({ alvo: a.alvo || "", valor: String(a.valor || "") }, politicaDe(a)));
    return resultado;
  }
  if (c.tipo === "upload") {
    const { tab, resultado } = await acaoPagina("enviar_arquivo", Object.assign({
      alvo: a.alvo || "", nome: String(a.nome || "arquivo"), valor: String(a.nome || "arquivo"),
      mime: String(a.mime || ""), b64: String(a.b64 || "") }, politicaDe(a)));
    return Object.assign({ tab_id: tab.id }, resultado);
  }
  if (c.tipo === "hover") {
    const { resultado } = await acaoPagina("passar_mouse", { alvo: a.alvo || "" });
    return resultado;
  }
  if (c.tipo === "wait") {
    const { resultado } = await acaoPagina("esperar", {
      texto: a.texto || "", seletor: a.seletor || "", segundos: Number(a.segundos) || 10 });
    return resultado;
  }
  if (c.tipo === "scroll") {
    const { resultado } = await acaoPagina("rolar", {
      direcao: a.direcao || "baixo", vezes: Number(a.vezes) || 1, alvo: a.alvo || "" });
    return resultado;
  }
  if (c.tipo === "history") {
    const t = await ctrlOrActiveBG();
    const acao = String(a.acao || "voltar").toLowerCase();
    if (acao === "voltar") await chrome.tabs.goBack(t.id);
    else if (acao === "avancar" || acao === "avançar") await chrome.tabs.goForward(t.id);
    else await chrome.tabs.reload(t.id);
    await aguardarCarregarBG(t.id, 8000);
    const n = await chrome.tabs.get(t.id);
    return { tab_id: t.id, url: n.url || "", titulo: n.title || "" };
  }
  if (c.tipo === "screenshot") {
    // captureVisibleTab só captura a aba VISÍVEL da janela: ativa a de controle.
    const t = await ctrlOrActiveBG();
    await chrome.tabs.update(t.id, { active: true });
    await dormirBG(250);
    const dataUrl = await chrome.tabs.captureVisibleTab(t.windowId, { format: "jpeg", quality: 72 });
    return { imagem_b64: dataUrl.split(",")[1], mime: "image/jpeg",
             url: t.url || "", titulo: t.title || "", tab_id: t.id };
  }
  throw new Error("comando desconhecido: " + c.tipo);
}

let ponteOcupada = false;

// Busca (e executa) comandos. espera > 0 = long-poll: o núcleo segura a
// requisição até aparecer um comando — entrega quase instantânea, em vez de
// esperar em média meio ciclo de um polling de 1,2s. Devolve quantos comandos
// tratou (o laço usa isso para não girar à toa).
async function ponteComandos(espera = 0) {
  // Sem reentrância: o laço e o alarme podem coincidir; sem a trava, o mesmo
  // comando podia ser pego duas vezes.
  if (ponteOcupada) return -1;
  ponteOcupada = true;
  let tratados = 0;
  try {
    // Chamar uma API de extensão reinicia o timer de ociosidade (~30s) do
    // service worker do MV3 — mantém a ponte viva sem depender do painel.
    try { chrome.runtime.getPlatformInfo(() => {}); } catch (e) {}
    if (!TOKEN) await obterToken();
    const r = await fetch(BASE + "/api/ext/comandos?espera=" + espera, {
      cache: "no-store", headers: TOKEN ? { "X-YVAKOR-Token": TOKEN } : {},
      signal: AbortSignal.timeout((espera + 10) * 1000) });
    if (r.status === 403) { await obterToken(); return 0; }
    const j = await r.json();
    for (const c of (j.comandos || [])) {
      tratados++;
      try {
        const dados = await executarBG(c);
        await responderBG(c, true, dados);
      } catch (e) {
        await responderBG(c, false, {}, e.message || "falha");
      }
    }
  } catch (e) { /* núcleo fora ou sem comando */ }
  finally { ponteOcupada = false; }
  return tratados;
}

// Laço contínuo de long-poll (substitui o setInterval de 1,2s). Cada volta dura
// até 20s (< 30s de ociosidade do service worker). Se o núcleo está fora ou é
// uma versão antiga que ignora `espera` (volta na hora, vazio), descansa antes
// de repetir — nunca gira a 100%.
let lacoAtivo = false;
async function iniciarLacoPonte() {
  if (lacoAtivo) return;
  lacoAtivo = true;
  try {
    for (;;) {
      const t0 = Date.now();
      const n = await ponteComandos(20);
      if (n === -1) await dormirBG(300);                    // outra volta em curso
      else if (n === 0 && Date.now() - t0 < 1500) await dormirBG(1200);
    }
  } finally { lacoAtivo = false; }
}

pontePing();
setInterval(pontePing, 10000);
iniciarLacoPonte();
try {
  chrome.alarms.create("yvakor-bridge", { periodInMinutes: 0.5 });
} catch (e) { /* versões antigas exigem >=1 min */ }
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "yvakor-bridge") {
    pontePing();
    iniciarLacoPonte();          // vigia: se o service worker reiniciou, retoma o laço
    if (ultimaAcao && Date.now() - ultimaAcao > 120000) indicadorDesligar();
  }
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

/* Menu de contexto e atalho de teclado → painel. sidePanel.open exige gesto do
 * usuário: é chamado ANTES de qualquer await. O pedido vai pelo storage de sessão. */
function pedirAoPainel(pedido, tab) {
  try {
    if (tab && tab.windowId != null) chrome.sidePanel.open({ windowId: tab.windowId }).catch(() => {});
  } catch (e) { /* painel já aberto ou API indisponível */ }
  chrome.storage.session.set({ pedido_painel: Object.assign({ t: Date.now() }, pedido) }).catch(() => {});
}
try {
  if (chrome.contextMenus) {
    const criarMenu = () => {
      chrome.contextMenus.removeAll(() => {
        chrome.contextMenus.create({
          id: "yvakor-selecao", title: "Perguntar ao YVAKOR sobre a seleção",
          contexts: ["selection"],
        });
      });
    };
    chrome.runtime.onInstalled.addListener(criarMenu);
    chrome.contextMenus.onClicked.addListener((info, tab) => {
      if (info.menuItemId === "yvakor-selecao" && info.selectionText) {
        pedirAoPainel({ tipo: "selecao", texto: String(info.selectionText).slice(0, 4000) }, tab);
      }
    });
  }
  if (chrome.commands && chrome.commands.onCommand) {
    chrome.commands.onCommand.addListener((cmd, tab) => {
      if (cmd === "abrir-yvakor") pedirAoPainel({ tipo: "foco" }, tab);
    });
  }
} catch (e) { console.warn("menu/atalho:", e); }
