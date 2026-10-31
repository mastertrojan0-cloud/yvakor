// YVAKOR para VS Code — o editor integrado ao YVAKOR (não uma ferramenta solta).
//
// - A pasta aberta vira workspace do YVAKOR; cada pasta tem sua conversa.
// - Manda ao núcleo o contexto do editor: arquivo, seleção, cursor, problemas,
//   abas (o agente entende "este arquivo", "esta função").
// - Painel de conversa (barra lateral) que fala com o MESMO núcleo do app.
// - Executa o que o YVAKOR pede: abrir arquivo na linha, mostrar diff.
// - Confirmações do agente aparecem aqui também (Permitir / Negar).
"use strict";
const vscode = require("vscode");
const path = require("path");

let token = "";
let saida;                    // OutputChannel
let barra;                    // StatusBarItem
let provedor;                 // painel de conversa
let ativo = true;
let workspaceId = "";
let pendenteVisto = "";

function base() {
  return vscode.workspace.getConfiguration("yvakor").get("url") || "http://127.0.0.1:7777";
}

function pastaAtual() {
  const f = vscode.workspace.workspaceFolders;
  return f && f.length ? f[0].uri.fsPath : "";
}

async function obterToken() {
  const r = await fetch(base() + "/api/token", { signal: AbortSignal.timeout(4000) });
  token = (await r.json()).token || "";
}

async function api(rota, corpo, espera = 15000) {
  if (!token) await obterToken();
  const pedir = () => fetch(base() + rota, {
    method: corpo === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-YVAKOR-Token": token },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
    signal: AbortSignal.timeout(espera),
  });
  let r = await pedir();
  if (r.status === 403) { await obterToken(); r = await pedir(); }
  return r.json();
}

function estado(texto, ok) {
  if (!barra) return;
  barra.text = (ok ? "$(hubot) " : "$(debug-disconnect) ") + texto;
  barra.tooltip = ok ? "YVAKOR conectado — clique para conversar" : "Núcleo do YVAKOR offline (abra o app)";
}

// ------------------------------------------------------------------ workspace
async function registrarWorkspace() {
  const pasta = pastaAtual();
  if (!pasta) return "";
  try {
    const r = await api("/api/workspaces/adicionar", { caminho: pasta, ativar: false });
    workspaceId = (r.workspace && r.workspace.id) || "";
    estado("YVAKOR · " + path.basename(pasta), true);
  } catch (e) {
    estado("YVAKOR offline", false);
  }
  return workspaceId;
}

async function sessaoDoWorkspace(ctx, nova = false) {
  const chave = "yvakor.sessao." + (pastaAtual() || "geral").toLowerCase();
  let sid = nova ? "" : ctx.globalState.get(chave, "");
  if (sid) {
    try {
      const j = await api("/api/sessions");
      if (!(j.sessions || []).some((s) => s.id === sid)) sid = "";
    } catch (e) { /* offline: tenta depois */ }
  }
  if (!sid) {
    if (!workspaceId) await registrarWorkspace();
    const j = await api("/api/sessions", {
      title: "VS Code · " + (path.basename(pastaAtual()) || "geral"),
      workspace: workspaceId,
    });
    sid = j.active || "";
    await ctx.globalState.update(chave, sid);
  }
  return sid;
}

// --------------------------------------------------------- contexto do editor
let timerContexto;
function agendarContexto() {
  clearTimeout(timerContexto);
  timerContexto = setTimeout(enviarContexto, 700);
}

async function enviarContexto() {
  const ed = vscode.window.activeTextEditor;
  const pasta = pastaAtual();
  if (!pasta) return;
  const dados = { workspace: pasta, abertos: [] };
  try {
    for (const g of vscode.window.tabGroups.all) {
      for (const t of g.tabs) {
        if (t.input && t.input.uri && t.input.uri.scheme === "file") dados.abertos.push(t.input.uri.fsPath);
      }
    }
  } catch (e) { /* API de abas indisponível */ }
  if (ed && ed.document.uri.scheme === "file") {
    const sel = ed.selection;
    dados.arquivo = ed.document.uri.fsPath;
    dados.linguagem = ed.document.languageId;
    dados.linha = sel.active.line + 1;
    if (!sel.isEmpty) {
      dados.selecao = ed.document.getText(sel).slice(0, 6000);
      dados.linha_inicio = sel.start.line + 1;
      dados.linha_fim = sel.end.line + 1;
    }
    dados.problemas = vscode.languages.getDiagnostics(ed.document.uri)
      .filter((d) => d.severity <= vscode.DiagnosticSeverity.Warning)
      .slice(0, 15)
      .map((d) => `linha ${d.range.start.line + 1}: ${d.message}`);
  }
  try { await api("/api/vscode/contexto", dados, 5000); } catch (e) { /* offline */ }
}

// ------------------------------------------- comandos que o YVAKOR pede ao editor
async function lacoComandos() {
  while (ativo) {
    try {
      const j = await api("/api/vscode/comandos?espera=25", undefined, 32000);
      estado("YVAKOR · " + (path.basename(pastaAtual()) || "geral"), true);
      for (const c of j.comandos || []) await executar(c);
    } catch (e) {
      estado("YVAKOR offline", false);
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}

async function executar(c) {
  try {
    const uri = vscode.Uri.file(c.arquivo);
    if (c.tipo === "abrir") {
      const linha = Math.max(0, (c.linha || 1) - 1);
      const doc = await vscode.workspace.openTextDocument(uri);
      const ed = await vscode.window.showTextDocument(doc, { preview: false });
      const pos = new vscode.Position(linha, 0);
      ed.selection = new vscode.Selection(pos, pos);
      ed.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
    } else if (c.tipo === "diff") {
      try { await vscode.commands.executeCommand("git.openChange", uri); }
      catch (e) { await vscode.window.showTextDocument(uri); }
    }
  } catch (e) {
    saida.appendLine("comando falhou: " + JSON.stringify(c) + " — " + e);
  }
}

// --------------------------------------------------------- painel de conversa
class Painel {
  constructor(ctx) { this.ctx = ctx; this.view = undefined; this.sid = ""; this.ocupado = false; }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.html = html();
    view.webview.onDidReceiveMessage((m) => this.mensagem(m));
    this.carregar();
  }

  postar(m) { if (this.view) this.view.webview.postMessage(m); }

  async carregar(nova = false) {
    try {
      this.sid = await sessaoDoWorkspace(this.ctx, nova);
      const j = await api("/api/sessions/" + this.sid + "/messages");
      this.postar({ tipo: "historico", mensagens: j.messages || [],
                    workspace: path.basename(pastaAtual()) || "sem pasta aberta" });
    } catch (e) {
      this.postar({ tipo: "status", texto: "Núcleo do YVAKOR offline — abra o app YVAKOR." });
    }
  }

  async mensagem(m) {
    if (m.tipo === "nova") return this.carregar(true);
    if (m.tipo !== "enviar" || !m.texto || this.ocupado) return;
    this.ocupado = true;
    this.postar({ tipo: "usuario", texto: m.texto });
    await enviarContexto();
    const inicio = Date.now();
    const vigia = setInterval(async () => {
      try {
        const p = await api("/api/progress?session=" + encodeURIComponent(this.sid), undefined, 4000);
        const passos = p.steps || [];
        const ultimo = passos.length ? String(passos[passos.length - 1].texto || passos[passos.length - 1]) : "";
        const seg = Math.round((Date.now() - inicio) / 1000);
        this.postar({ tipo: "status", texto: `⏳ ${seg}s` + (ultimo ? " · " + ultimo.slice(0, 90) : "") });
        await confirmar(p.pending, this.sid);
      } catch (e) { /* segue */ }
    }, 1500);
    try {
      const j = await api("/api/chat", { message: m.texto, session: this.sid }, 900000);
      const passos = (j.passos || []).length;
      this.postar({ tipo: "yvakor", texto: j.answer || j.error || "(sem resposta)" });
      const seg = Math.round((Date.now() - inicio) / 1000);
      this.postar({ tipo: "status", texto: `pronto · ${passos} passo(s) em ${seg}s` });
    } catch (e) {
      this.postar({ tipo: "status", texto: "Falha ao falar com o núcleo: " + e });
    } finally {
      clearInterval(vigia);
      this.ocupado = false;
    }
  }
}

async function confirmar(pend, sid) {
  if (!pend || pend.id === pendenteVisto) return;
  pendenteVisto = pend.id;
  const opcoes = pend.opcoes && pend.opcoes.length ? pend.opcoes : ["Permitir", "Negar"];
  const titulo = "YVAKOR: " + (pend.action || pend.titulo || "confirmação") +
    (pend.detail ? " — " + String(pend.detail).slice(0, 160) : "");
  const escolha = await vscode.window.showWarningMessage(titulo, { modal: false }, ...opcoes);
  const allow = !!escolha && escolha !== "Negar" && escolha !== "Cancelar";
  try { await api("/api/confirm", { session: pend.session || sid, allow, resposta: escolha || "" }); }
  catch (e) { /* expira no núcleo */ }
}

function html() {
  const n = String(Math.random()).slice(2);
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${n}';">
<style>
  body{font-family:var(--vscode-font-family);font-size:var(--vscode-font-size);color:var(--vscode-foreground);margin:0;display:flex;flex-direction:column;height:100vh}
  #topo{padding:6px 10px;font-size:11px;opacity:.8;display:flex;justify-content:space-between;border-bottom:1px solid var(--vscode-panel-border)}
  #topo a{cursor:pointer;color:var(--vscode-textLink-foreground)}
  #msgs{flex:1;overflow-y:auto;padding:8px 10px}
  .m{margin:8px 0;line-height:1.45;word-wrap:break-word;white-space:normal}
  .u{background:var(--vscode-input-background);padding:6px 9px;border-radius:6px}
  .y pre{background:var(--vscode-textCodeBlock-background);padding:8px;overflow-x:auto;border-radius:4px;white-space:pre}
  .y code{font-family:var(--vscode-editor-font-family);background:var(--vscode-textCodeBlock-background);padding:0 3px;border-radius:3px}
  #status{font-size:11px;opacity:.75;padding:3px 10px;min-height:16px;border-top:1px solid var(--vscode-panel-border)}
  #entrada{display:flex;gap:6px;padding:8px 10px}
  textarea{flex:1;resize:none;height:54px;font-family:inherit;font-size:inherit;color:var(--vscode-input-foreground);background:var(--vscode-input-background);border:1px solid var(--vscode-input-border,transparent);padding:6px;border-radius:4px}
  button{background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:0;padding:0 12px;border-radius:4px;cursor:pointer}
</style></head><body>
<div id="topo"><span id="ws">YVAKOR</span><a id="nova">+ nova conversa</a></div>
<div id="msgs"></div>
<div id="status"></div>
<div id="entrada"><textarea id="txt" placeholder="Peça ao YVAKOR (Enter envia, Shift+Enter quebra linha)"></textarea><button id="env">Enviar</button></div>
<script nonce="${n}">
const vs = acquireVsCodeApi();
const msgs = document.getElementById("msgs"), txt = document.getElementById("txt");
function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
function md(s){
  const partes = String(s||"").split(/\`\`\`/);
  return partes.map((p,i)=> i%2 ? "<pre>"+esc(p.replace(/^[a-zA-Z0-9]*\\n/,""))+"</pre>"
    : esc(p).replace(/\\*\\*(.+?)\\*\\*/g,"<b>$1</b>").replace(/\`([^\`]+)\`/g,"<code>$1</code>").replace(/\\n/g,"<br>")).join("");
}
function add(tipo, texto){
  const d=document.createElement("div"); d.className="m "+(tipo==="usuario"?"u":"y");
  d.innerHTML = tipo==="usuario" ? esc(texto).replace(/\\n/g,"<br>") : md(texto);
  msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight;
}
function enviar(){ const t=txt.value.trim(); if(!t) return; txt.value=""; vs.postMessage({tipo:"enviar", texto:t}); }
document.getElementById("env").onclick = enviar;
document.getElementById("nova").onclick = ()=>{ msgs.innerHTML=""; vs.postMessage({tipo:"nova"}); };
txt.addEventListener("keydown", e=>{ if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); enviar(); }});
window.addEventListener("message", ev=>{
  const m = ev.data;
  if(m.tipo==="historico"){ msgs.innerHTML=""; document.getElementById("ws").textContent="📁 "+m.workspace;
    for(const x of m.mensagens){ add(x.role==="user"?"usuario":"yvakor", x.content); } }
  else if(m.tipo==="usuario"||m.tipo==="yvakor"){ add(m.tipo, m.texto); }
  else if(m.tipo==="status"){ document.getElementById("status").textContent = m.texto; }
  else if(m.tipo==="preencher"){ txt.value = m.texto; txt.focus(); }
});
</script></body></html>`;
}

// ------------------------------------------------------------------ ativação
function activate(ctx) {
  saida = vscode.window.createOutputChannel("YVAKOR");
  barra = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  barra.command = "yvakor.focar";
  estado("YVAKOR", true);
  barra.show();
  provedor = new Painel(ctx);
  ctx.subscriptions.push(
    saida, barra,
    vscode.window.registerWebviewViewProvider("yvakor.chat", provedor,
      { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.commands.registerCommand("yvakor.focar", () =>
      vscode.commands.executeCommand("yvakor.chat.focus")),
    vscode.commands.registerCommand("yvakor.novaConversa", async () => {
      await vscode.commands.executeCommand("yvakor.chat.focus");
      provedor.carregar(true);
    }),
    vscode.commands.registerCommand("yvakor.perguntarSelecao", async () => {
      const ed = vscode.window.activeTextEditor;
      if (!ed) return;
      const s = ed.selection;
      await enviarContexto();
      await vscode.commands.executeCommand("yvakor.chat.focus");
      provedor.postar({ tipo: "preencher",
        texto: `Sobre ${path.basename(ed.document.fileName)} (linhas ${s.start.line + 1}–${s.end.line + 1}): ` });
    }),
    vscode.window.onDidChangeActiveTextEditor(agendarContexto),
    vscode.window.onDidChangeTextEditorSelection(agendarContexto),
    vscode.languages.onDidChangeDiagnostics(agendarContexto),
    vscode.workspace.onDidSaveTextDocument(agendarContexto),
    vscode.workspace.onDidChangeWorkspaceFolders(async () => { await registrarWorkspace(); provedor.carregar(); }),
  );
  registrarWorkspace().then(enviarContexto);
  lacoComandos();
}

function deactivate() { ativo = false; }

module.exports = { activate, deactivate };
