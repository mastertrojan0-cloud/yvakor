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
// O núcleo exige o header X-YVAKOR-Token em POST/DELETE (anti-CSRF). O token é
// buscado em GET /api/token (só origens confiáveis conseguem ler) e renovado
// se o núcleo reiniciar (403).
let TOKEN = "";
async function obterToken() {
  try {
    const r = await fetch(BASE + "/api/token", { cache: "no-store" });
    if (r.ok) TOKEN = (await r.json()).token || "";
  } catch (e) { /* núcleo offline */ }
  return TOKEN;
}
async function fetchNucleo(path, cfg) {
  const montar = () => ({
    ...cfg,
    headers: { ...(cfg.headers || {}), ...(TOKEN ? { "X-YVAKOR-Token": TOKEN } : {}) }
  });
  if (!TOKEN && cfg.method && cfg.method !== "GET") await obterToken();
  let r = await fetch(BASE + path, montar());
  if (r.status === 403) {
    await obterToken();
    r = await fetch(BASE + path, montar());
  }
  return r;
}

async function api(path, opts = {}) {
  const cfg = { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } };
  if (cfg.body && typeof cfg.body !== "string") cfg.body = JSON.stringify(cfg.body);
  const ctrl = new AbortController();
  const limite = setTimeout(() => ctrl.abort(), cfg.timeout || 120000);
  cfg.signal = ctrl.signal;
  try {
    const r = await fetchNucleo(path, cfg);
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
    if (!modeloCarregado) { carregarModelo(); carregarPolitica(); }   // voltou do offline
  } catch (e) {
    statusEl.textContent = "offline";
    statusEl.className = "pill erro";
    modeloCarregado = false;
  }
}

/* --------------------- permissões do agente (sites) ------------------ */
// "Pedir permissão por site" (padrão) ou "Agir sem pedir". Ações sensíveis e
// sites de banco/pagamento pedem confirmação nos dois modos.
const modoSel = $("modo-acao");
const sitesPainel = $("sites-painel");
function pintarSites(j) {
  const lista = $("sites-lista");
  lista.innerHTML = "";
  const permitidos = j.permitidos || [];
  if (!permitidos.length) {
    const v = document.createElement("div");
    v.className = "sites-vazio";
    v.textContent = "Nenhum site permitido ainda. O YVAKOR pergunta na primeira vez.";
    lista.appendChild(v);
  }
  for (const host of permitidos) {
    const linha = document.createElement("div");
    linha.className = "site";
    const nome = document.createElement("span");
    nome.textContent = host;
    const x = document.createElement("button");
    x.type = "button";
    x.textContent = "✕";
    x.title = "Revogar " + host;
    x.setAttribute("aria-label", "Revogar " + host);
    x.addEventListener("click", () => atualizarPolitica({ remover: host }));
    linha.append(nome, x);
    lista.appendChild(linha);
  }
}
async function carregarPolitica() {
  try {
    const j = await api("/api/extensao/politica", { timeout: 4000 });
    modoSel.innerHTML = "";
    for (const m of j.modos || []) {
      const o = document.createElement("option");
      o.value = m.id; o.textContent = m.rotulo; o.title = m.descricao;
      o.selected = m.id === j.modo;
      modoSel.appendChild(o);
    }
    pintarSites(j);
  } catch (e) { /* núcleo offline */ }
}
async function atualizarPolitica(corpo) {
  try {
    pintarSites(await api("/api/extensao/politica", { method: "POST", body: corpo, timeout: 5000 }));
  } catch (e) {
    add("agente", "Não consegui atualizar as permissões: " + e.message);
  }
  carregarPolitica();
}
modoSel.addEventListener("change", () => atualizarPolitica({ modo: modoSel.value }));
$("btn-sites").addEventListener("click", () => sitesPainel.classList.toggle("oculto"));
$("sites-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("sites-novo").value.trim();
  if (v) { atualizarPolitica({ permitir: v }); $("sites-novo").value = ""; }
});

/* ------------------------- seletor de modelo ------------------------ */
// Local (padrão) / Automático / DeepSeek. A escolha é salva no núcleo.
const modeloSel = $("modelo");
let modeloCarregado = false;
async function carregarModelo() {
  try {
    const j = await api("/api/modelo", { timeout: 4000 });
    modeloSel.innerHTML = "";
    for (const m of j.modos || []) {
      const o = document.createElement("option");
      o.value = "modo:" + m.id;
      o.textContent = m.id === "local" && (j.local || {}).modelo
        ? `${m.rotulo} · ${j.local.modelo}` : m.rotulo;
      o.title = m.descricao;
      o.selected = m.id === j.modo;
      modeloSel.appendChild(o);
    }
    const locais = j.locais || [];
    if (locais.length > 1) {                    // só oferece se houver escolha
      const g = document.createElement("optgroup");
      g.label = "Modelo local";
      for (const n of locais) {
        const o = document.createElement("option");
        o.value = "local:" + n;
        o.textContent = n;
        g.appendChild(o);
      }
      modeloSel.appendChild(g);
    }
    modeloCarregado = true;
  } catch (e) { /* núcleo offline */ }
}
modeloSel.addEventListener("change", async () => {
  const [tipo, ...resto] = modeloSel.value.split(":");
  const valor = resto.join(":");
  try {
    const j = await api("/api/modelo", {
      method: "POST", body: tipo === "modo" ? { modo: valor } : { local: valor } });
    const rot = ((j.modos || []).find(m => m.id === j.modo) || {}).rotulo || j.modo;
    add("agente", `Modelo: **${rot}**` +
        ((j.local || {}).modelo ? ` · local: ${j.local.modelo}` : ""));
  } catch (e) {
    add("agente", "Não consegui trocar o modelo: " + e.message);
  }
  carregarModelo();
});

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
// completo=false: só atualiza a legenda (título/URL da aba) — NÃO injeta script
// na página. Antes isso rodava a cada 10s e a cada troca de página, lendo até
// 20 mil caracteres de TODA aba visitada só para escrever uma legenda.
// completo=true: extrai o conteúdo da página (usado ao enviar a mensagem).
async function atualizarContexto(completo = false) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      ctxTitulo.textContent = "Sem aba ativa";
      return;
    }
    contextoAba = tab;
    if (!completo) {
      ctxTitulo.textContent = tab.title || tab.url || "Página atual";
      ctxTitulo.title = tab.url || "";
      return;
    }
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
// Legenda atualiza só quando o painel está visível e com debounce.
let timerLegenda = null;
function agendarLegenda() {
  if (document.visibilityState !== "visible") return;
  clearTimeout(timerLegenda);
  timerLegenda = setTimeout(() => atualizarContexto(false), 300);
}
chrome.tabs.onActivated.addListener(agendarLegenda);
chrome.tabs.onUpdated.addListener((id, info) => {
  if (info.status === "complete" || info.title) agendarLegenda();
});
document.addEventListener("visibilitychange", agendarLegenda);

/* ----------------------------- chat -------------------------------- */
function esc(t) {
  return String(t || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
// Inline: o texto JÁ vem escapado (esc), então só nossas próprias tags existem.
function inline(s) {
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
  s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, "");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,
    '$1<a href="$2" target="_blank" rel="noreferrer">$2</a>');
  return s;
}

// Markdown em blocos: parágrafos, títulos, listas (-, *, 1.), tabelas, código.
// Antes só havia negrito/código/link e \n → <br>: listas e títulos apareciam crus.
function markdown(t) {
  const codigos = [];
  const bruto = String(t || "").replace(/```[^\n]*\n?([\s\S]*?)```/g, (_, c) => {
    codigos.push("<pre><code>" + esc(c.replace(/\n$/, "")) + "</code></pre>");
    return "\n\u0000" + (codigos.length - 1) + "\u0000\n";
  });
  const linhas = bruto.split("\n");
  const out = [];
  let lista = null, para = [];
  const fecharPara = () => {
    if (para.length) { out.push("<p>" + inline(esc(para.join("\n"))).replace(/\n/g, "<br>") + "</p>"); para = []; }
  };
  const fecharLista = () => { if (lista) { out.push("</" + lista + ">"); lista = null; } };
  const celulas = (l) => l.trim().replace(/^\||\|$/g, "").split("|")
    .map(c => inline(esc(c.trim())));

  for (let i = 0; i < linhas.length; i++) {
    const l = linhas[i];
    let m;
    if (!l.trim()) { fecharPara(); fecharLista(); continue; }
    if ((m = l.trim().match(/^\u0000(\d+)\u0000$/))) {
      fecharPara(); fecharLista(); out.push(codigos[Number(m[1])]); continue;
    }
    // tabela: linha com | seguida de separador |---|
    if (/\|/.test(l) && i + 1 < linhas.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(linhas[i + 1])) {
      fecharPara(); fecharLista();
      const cab = celulas(l);
      i += 2;
      const corpo = [];
      while (i < linhas.length && linhas[i].trim() && /\|/.test(linhas[i])) { corpo.push(celulas(linhas[i])); i++; }
      i--;
      out.push("<div class=\"tabela\"><table><thead><tr>" +
        cab.map(c => "<th>" + c + "</th>").join("") + "</tr></thead><tbody>" +
        corpo.map(r => "<tr>" + r.map(c => "<td>" + c + "</td>").join("") + "</tr>").join("") +
        "</tbody></table></div>");
      continue;
    }
    if ((m = l.match(/^\s{0,3}(#{1,4})\s+(.*)$/))) {
      fecharPara(); fecharLista();
      out.push("<p class=\"titulo\">" + inline(esc(m[2])) + "</p>");
      continue;
    }
    if ((m = l.match(/^\s*[-*•]\s+(.*)$/))) {
      fecharPara();
      if (lista !== "ul") { fecharLista(); out.push("<ul>"); lista = "ul"; }
      out.push("<li>" + inline(esc(m[1])) + "</li>");
      continue;
    }
    if ((m = l.match(/^\s*(\d+)[.)]\s+(.*)$/))) {
      fecharPara();
      if (lista !== "ol") { fecharLista(); out.push("<ol>"); lista = "ol"; }
      out.push("<li>" + inline(esc(m[2])) + "</li>");
      continue;
    }
    fecharLista();
    para.push(l);
  }
  fecharPara(); fecharLista();
  return out.join("");
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
  corpo.className = "corpo";
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
// Painel de processo discreto: mostra só o passo atual (uma linha) e o total;
// clique no cabeçalho para ver os últimos passos. Só repinta quando algo muda
// (antes refazia o DOM a cada 900ms, piscando) e se recolhe sozinho ao concluir.
let assinaturaPassos = "";
let processoAberto = false;
let timerOcultar = null;
function mostrarProcesso(v) { processo.classList.toggle("oculto", !v); }
function pintarPassos(steps, running) {
  const lista = steps || [];
  const assinatura = lista.length + "|" + (lista[lista.length - 1] || "") +
    "|" + running + "|" + processoAberto;
  if (assinatura === assinaturaPassos) return;
  assinaturaPassos = assinatura;
  passosEl.innerHTML = "";
  const visiveis = processoAberto ? lista.slice(-12) : lista.slice(-1);
  visiveis.forEach((s, i) => {
    const d = document.createElement("div");
    const ultimo = i === visiveis.length - 1;
    d.className = "passo" + (ultimo && running ? " atual" : "");
    d.textContent = (ultimo && running ? "▸ " : "· ") + s;
    passosEl.appendChild(d);
  });
  const n = lista.length;
  procStatus.textContent = (running ? "executando" : "concluído") +
    (n ? ` · ${n} passo${n > 1 ? "s" : ""}` : "") + (processoAberto ? " ▾" : " ▸");
  procStatus.style.color = running ? "var(--ouro)" : "var(--agua)";
  clearTimeout(timerOcultar);
  if (!running && !processoAberto) {
    timerOcultar = setTimeout(() => mostrarProcesso(false), 5000);
  }
}
document.querySelector(".proc-topo").addEventListener("click", () => {
  processoAberto = !processoAberto;
  clearTimeout(timerOcultar);
  assinaturaPassos = "";
  if (ocupado) tickProgresso();
});
let sidProgresso = null;
async function tickProgresso() {
  if (!sidProgresso) return;
  try {
    const p = await api("/api/progress?session=" + encodeURIComponent(sidProgresso),
                        { timeout: 4000 });
    pintarPassos(p.steps || [], !!p.running);
    tratarPendencia(p.pending);
  } catch (e) { /* ignora */ }
}

// Confirmação de ação protegida (shell, apagar/escrever arquivo, rede…).
// O núcleo PARA a conversa esperando esta resposta; a extensão não mostrava
// nada, então a tarefa ficava minutos travada até o prazo e era negada.
let pendenciaId = null;
function tratarPendencia(pend) {
  const cartao = $("confirmacao");
  if (!pend) {
    pendenciaId = null;
    cartao.classList.add("oculto");
    return;
  }
  if (pend.id === pendenciaId) return;           // já exibida
  pendenciaId = pend.id;
  $("conf-acao").textContent = pend.action || "ação protegida";
  $("conf-detalhe").textContent = pend.detail || "";
  $("conf-detalhe").classList.toggle("oculto", !pend.detail);
  $("conf-prazo").textContent =
    `Sem resposta em ${pend.timeout || 90}s a ação é negada.`;
  cartao.classList.remove("oculto");
  $("conf-permitir").focus();
  rolar();
}
async function responderConfirmacao(permitir) {
  $("confirmacao").classList.add("oculto");
  try {
    await api("/api/confirm", {
      method: "POST", timeout: 5000,
      body: { session: sidProgresso, allow: !!permitir } });
  } catch (e) {
    add("agente", "Não consegui enviar sua resposta ao núcleo: " + e.message);
  }
}
$("conf-permitir").addEventListener("click", () => responderConfirmacao(true));
$("conf-negar").addEventListener("click", () => responderConfirmacao(false));
$("confirmacao").addEventListener("keydown", (e) => {
  if (e.key === "Escape") responderConfirmacao(false);
});
async function acompanhar(sid) {
  clearInterval(timerProgresso);
  clearTimeout(timerOcultar);
  sidProgresso = sid;
  assinaturaPassos = "";
  mostrarProcesso(true);
  passosEl.innerHTML = "";
  procStatus.textContent = "iniciando…";
  await tickProgresso();
  // 1,2s enquanto a tarefa roda; o intervalo é cancelado ao concluir.
  timerProgresso = setInterval(tickProgresso, 1200);
}

/* ---------------------------- envio -------------------------------- */
async function enviarMensagem() {
  if (ocupado) return;
  const texto = entrada.value.trim();
  if (!texto) return;
  let mensagem = texto;
  if (texto.startsWith("/")) {
    await atualizarContexto(true);
    const ex = YvakorAtalhos.expandir(texto, listaAtalhos, {
      selecao: contexto && contexto.selecao, url: contexto && contexto.url,
      titulo: contexto && contexto.titulo });
    if (ex.erro) { add("agente", ex.erro); return; }
    if (ex.ok) mensagem = ex.prompt;
  }
  if (!sessao) {
    try { await novaSessao(); }
    catch (e) { add("agente", "Núcleo indisponível: " + e.message); return; }
  }
  ocupado = true;
  // Enquanto roda, o botão vira PARAR (nunca fica desabilitado).
  enviar.textContent = "■"; enviar.title = "Parar (Esc)";
  enviar.classList.add("parar");
  entrada.value = "";
  ajustarAltura();
  add("user", texto);
  await acompanhar(sessao);
  try {
    const body = { message: mensagem, session: sessao };
    await atualizarContexto(true);
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
    enviar.textContent = "↑"; enviar.title = "Enviar (Enter)";
    enviar.classList.remove("parar");
    enviar.disabled = false;
    try { chrome.runtime.sendMessage({ tipo: "fim_tarefa" }); } catch (e) {}
    clearInterval(timerProgresso);
    tickProgresso();   // leitura final: pinta "concluído · N passos" e recolhe sozinho
    tratarPendencia(null);   // a requisição acabou: nenhuma confirmação fica aberta
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
/* --------------------- atalhos "/comando" -------------------------- */
let listaAtalhos = YvakorAtalhos.juntar([]);
let atalhoSel = 0;
let sugestoes = [];
async function carregarAtalhos() {
  try {
    const r = await chrome.storage.local.get("atalhos_usuario");
    listaAtalhos = YvakorAtalhos.juntar(r.atalhos_usuario || []);
  } catch (e) { /* usa só os padrão */ }
  montarChips();
}
// Sugestões da tela inicial (como as do Claude): os atalhos mais úteis em um clique.
function montarChips() {
  const box = $("chips");
  if (!box) return;
  box.innerHTML = "";
  ["resumir", "pesquisar", "extrair", "traduzir"].forEach((c) => {
    const a = listaAtalhos.find((x) => x.comando === c);
    if (!a) return;
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = a.nome;
    b.addEventListener("click", () => {
      entrada.value = "/" + a.comando + (a.exige ? " " : "");
      entrada.focus();
      if (!a.exige) enviarMensagem();
    });
    box.appendChild(b);
  });
}
carregarAtalhos();
function fecharMenuAtalhos() { sugestoes = []; $("atalhos-menu").classList.add("oculto"); }
function atualizarMenuAtalhos() {
  sugestoes = YvakorAtalhos.sugerir(entrada.value, listaAtalhos, 8);
  const menu = $("atalhos-menu");
  if (!sugestoes.length) { fecharMenuAtalhos(); return; }
  atalhoSel = Math.min(atalhoSel, sugestoes.length - 1);
  menu.innerHTML = "";
  sugestoes.forEach((a, i) => {
    const it = document.createElement("div");
    it.className = "item" + (i === atalhoSel ? " sel" : "");
    const b = document.createElement("b"); b.textContent = "/" + a.comando;
    const s = document.createElement("span"); s.textContent = a.nome;
    it.append(b, s);
    it.addEventListener("mousedown", (ev) => { ev.preventDefault(); escolherAtalho(a); });
    menu.appendChild(it);
  });
  menu.classList.remove("oculto");
}
function escolherAtalho(a) {
  entrada.value = "/" + a.comando + " ";
  fecharMenuAtalhos();
  ajustarAltura();
  entrada.focus();
}
entrada.addEventListener("keydown", (e) => {
  if (sugestoes.length) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      atalhoSel = (atalhoSel + (e.key === "ArrowDown" ? 1 : sugestoes.length - 1)) % sugestoes.length;
      atualizarMenuAtalhos(); return;
    }
    if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
      e.preventDefault(); escolherAtalho(sugestoes[atalhoSel]); return;
    }
    if (e.key === "Escape") { e.stopPropagation(); fecharMenuAtalhos(); return; }
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    enviarMensagem();
  }
});
entrada.addEventListener("input", () => { atalhoSel = 0; atualizarMenuAtalhos(); ajustarAltura(); });
entrada.addEventListener("blur", () => setTimeout(fecharMenuAtalhos, 120));

// Pedidos vindos do menu de contexto / atalho de teclado (gravados pelo background).
async function consumirPedidoExterno() {
  try {
    const r = await chrome.storage.session.get("pedido_painel");
    const p = r.pedido_painel;
    if (!p) return;
    await chrome.storage.session.remove("pedido_painel");
    if (p.tipo === "selecao" && p.texto) {
      entrada.value = "/explicar";
      await atualizarContexto(true);
      if (!contexto || !contexto.selecao) contexto = Object.assign({}, contexto, { selecao: p.texto });
      enviarMensagem();
    } else if (p.tipo === "foco") {
      entrada.focus();
    }
  } catch (e) { /* sem acesso ao storage de sessão */ }
}
try {
  chrome.storage.onChanged.addListener((mud, area) => {
    if (area === "session" && mud.pedido_painel && mud.pedido_painel.newValue) consumirPedidoExterno();
    if (area === "local" && mud.atalhos_usuario) carregarAtalhos();
  });
} catch (e) {}
consumirPedidoExterno();
// Parar: cancela a execução no núcleo (o agente confere entre os passos; uma
// confirmação pendente é negada e um comando esperando o navegador aborta).
async function pararTarefa() {
  enviar.textContent = "…";
  procStatus.textContent = "parando…";
  try {
    await api("/api/chat/cancelar", { method: "POST", body: { session: sessao }, timeout: 5000 });
  } catch (e) {
    add("agente", "Não consegui parar a tarefa: " + e.message);
  }
  try { chrome.runtime.sendMessage({ tipo: "fim_tarefa" }); } catch (e) {}
}
enviar.addEventListener("click", () => (ocupado ? pararTarefa() : enviarMensagem()));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && ocupado && $("confirmacao").classList.contains("oculto")) pararTarefa();
});
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
  fetchNucleo("/api/voz/audio", {
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

/* A ponte de comandos (abrir/clicar/preencher/snapshot…) roda SOMENTE no
   background.js. Antes havia uma cópia completa aqui, e os dois faziam
   polling em /api/ext/comandos: com o painel aberto, dois executores
   competiam pelo mesmo comando (abas duplicadas, ações repetidas). */

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
