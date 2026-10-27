/* Verifica o controle de abas do background.js (id explícito, grupo YVAKOR,
 * trocar/fechar com segurança) rodando o arquivo REAL num Chrome simulado em
 * memória. Uso:  node tests/extensao/abas_background.js  → JSON {casos:[...]}
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
// BG_SRC permite rodar o MESMO roteiro contra outra versão do arquivo (ex.: a
// anterior, do git) para provar que os testes pegam os bugs antigos.
const src = fs.readFileSync(process.env.BG_SRC || path.join(__dirname, "..", "..", "chrome-extension", "background.js"), "utf8");

function novoChrome({ semGrupos = false } = {}) {
  let proximoId = 100, proximoGrupo = 1;
  const tabs = [
    { id: 1, windowId: 1, index: 0, url: "https://usuario-a.com/", title: "Aba A do usuário", active: true, groupId: -1, status: "complete" },
    { id: 2, windowId: 1, index: 1, url: "https://usuario-b.com/", title: "Aba B do usuário", active: false, groupId: -1, status: "complete" },
    { id: 3, windowId: 2, index: 0, url: "https://outra-janela.com/", title: "Outra janela", active: true, groupId: -1, status: "complete" },
  ];
  const grupos = [];
  const chamadas = { update: [], remove: [], group: [] };
  const mem = {};
  const store = { get: async (k) => (k in mem ? { [k]: mem[k] } : {}), set: async (o) => { Object.assign(mem, o); } };
  const ev = { addListener() {} };
  const chrome = {
    sidePanel: { setPanelBehavior: () => Promise.resolve() },
    storage: { session: store, local: store },
    runtime: { getPlatformInfo() {}, onMessage: ev, onInstalled: ev, onStartup: ev, getURL: (p) => p },
    alarms: { create() {}, onAlarm: ev },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {}, setTitle: async () => {} },
    scripting: { executeScript: async () => [] },
    tabs: {
      onActivated: ev, onUpdated: ev, onRemoved: ev,
      query: async (q) => (q && q.currentWindow ? tabs.filter((t) => t.windowId === 1) : tabs.slice()),
      get: async (id) => { const t = tabs.find((x) => x.id === id); if (!t) throw new Error("No tab with id " + id); return t; },
      create: async (o) => {
        const t = { id: ++proximoId, windowId: 1, index: tabs.length, url: o.url || "about:blank",
                    title: o.url || "", active: o.active !== false, groupId: -1, status: "complete" };
        tabs.push(t); return t;
      },
      update: async (id, props) => { chamadas.update.push([id, props]); const t = tabs.find((x) => x.id === id); if (t) Object.assign(t, props); return t; },
      remove: async (id) => { chamadas.remove.push(id); const i = tabs.findIndex((x) => x.id === id); if (i >= 0) tabs.splice(i, 1); },
      group: async (o) => {
        if (semGrupos) throw new Error("tabGroups indisponível");
        chamadas.group.push(o);
        let gid = o.groupId;
        if (gid == null) { gid = proximoGrupo++; grupos.push({ id: gid, title: "", color: "", windowId: tabs.find((t) => t.id === o.tabIds[0]).windowId }); }
        for (const id of o.tabIds) tabs.find((t) => t.id === id).groupId = gid;
        return gid;
      },
      goBack: async () => {}, goForward: async () => {}, reload: async () => {},
    },
    tabGroups: {
      query: async (q) => grupos.filter((g) => (q.windowId == null || g.windowId === q.windowId) && (q.title == null || g.title === q.title)),
      get: async (id) => { const g = grupos.find((x) => x.id === id); if (!g) throw new Error("no group"); return g; },
      update: async (id, props) => { Object.assign(grupos.find((g) => g.id === id), props); },
    },
  };
  return { chrome, tabs, grupos, chamadas };
}

function carregar(opcoes) {
  const m = novoChrome(opcoes);
  const ctx = vm.createContext({
    chrome: m.chrome, console, setTimeout, clearTimeout, AbortSignal, URL, Promise,
    setInterval: () => 0, addEventListener() {},
    fetch: () => new Promise(() => {}),            // o laço da ponte fica ocioso
  });
  vm.runInContext(src + "\n;globalThis.__exp = { executarBG, ctrlIdBG };", ctx);
  return Object.assign(m, { exp: ctx.__exp });
}

const casos = [];
// `cond` pode ser função: uma exceção (ex.: versão antiga sem o campo) vira FALHA do
// caso em vez de abortar o roteiro inteiro.
const ok = (nome, cond, det) => {
  let v;
  try { v = typeof cond === "function" ? cond() : cond; } catch (e) { v = false; det = "exceção: " + e.message; }
  casos.push({ nome, ok: !!v, det: det === undefined ? "" : String(det).slice(0, 160) });
};
async function falha(fn) { try { await fn(); return null; } catch (e) { return e.message; } }

(async () => {
  // 1) nova aba entra no grupo YVAKOR; o grupo é criado UMA vez e reaproveitado
  let m = carregar();
  // executa um comando; uma exceção vira resultado de erro (não aborta o roteiro)
  async function run(c) {
    try { return await m.exp.executarBG(c); }
    catch (e) { return { ok: false, erro: "exceção: " + e.message, _excecao: true }; }
  }
  const A = await run({ tipo: "newtab", args: { url: "https://agente-1.com/" } });
  const B = await run({ tipo: "newtab", args: { url: "https://agente-2.com/" } });
  ok("nova aba entra num grupo chamado YVAKOR (amarelo)", m.grupos.length === 1 && m.grupos[0].title === "YVAKOR" && m.grupos[0].color === "yellow", JSON.stringify(m.grupos));
  ok("o grupo é reaproveitado pela 2ª aba (não cria outro)", () => m.grupos.length === 1 && m.tabs.filter((t) => t.groupId === m.grupos[0].id).length === 2);
  ok("a aba nova vira a controlada", (await m.exp.ctrlIdBG()) === B.tab_id);

  // 2) tabs: todas as janelas, com flags
  const lista = (await run({ tipo: "tabs", args: {} })).abas;
  const porId = Object.fromEntries(lista.map((t) => [t.id, t]));
  ok("tabs lista as abas de TODAS as janelas", () => lista.length === 5 && !!porId[3], lista.length);
  ok("tabs marca a controlada e as do YVAKOR", () => porId[B.tab_id].controlada && porId[A.tab_id].do_yvakor && porId[B.tab_id].do_yvakor);
  ok("aba do usuário NÃO aparece como do YVAKOR", () => porId[1].do_yvakor === false && porId[2].do_yvakor === false && porId[1].controlada === false);

  // 3) trocar de aba passa a CONTROLAR a escolhida (bug: só ativava)
  const sw = await run({ tipo: "switch_tab", args: { aba: 2 } });
  ok("switch_tab por id passa a controlar essa aba", (await m.exp.ctrlIdBG()) === 2 && sw.controlada === true);
  ok("a aba adotada entra no grupo YVAKOR", () => m.tabs.find((t) => t.id === 2).groupId === m.grupos[0].id);
  m.chamadas.update.length = 0;
  await run({ tipo: "goto", args: { url: "https://novo.com/" } });
  ok("as ações seguintes valem na aba nova (antes iam para a antiga)", m.chamadas.update.some(([id, p]) => id === 2 && p.url === "https://novo.com/"), JSON.stringify(m.chamadas.update));

  // 4) `aba` explícita age noutra aba sem mudar a controlada
  m.chamadas.update.length = 0;
  await run({ tipo: "goto", args: { url: "https://so-nessa.com/", aba: A.tab_id } });
  ok("comando com `aba` age naquela aba", m.chamadas.update.some(([id, p]) => id === A.tab_id && p.url === "https://so-nessa.com/"));
  ok("…e não muda a aba controlada", (await m.exp.ctrlIdBG()) === 2);
  m.chamadas.update.length = 0;
  const e1 = await run({ tipo: "goto", args: { url: "https://x.com", aba: 9999 } });
  ok("`aba` inventada (modelo pequeno) NÃO trava: age na aba atual e avisa", e1.ok !== false && /não existe/.test(e1.aviso || "") &&
     m.chamadas.update.some(([id, p]) => id === 2 && p.url === "https://x.com"), JSON.stringify(e1));
  const e2 = await falha(() => m.exp.executarBG({ tipo: "switch_tab", args: { aba: 9999 } }));
  ok("trocar para aba inexistente continua sendo erro claro", e2 && /não encontrada|não existe/.test(e2), e2);
  ok("o alvo do comando não vaza para o comando seguinte", await (async () => {
    m.chamadas.update.length = 0;
    await run({ tipo: "goto", args: { url: "https://seguinte.com/" } });
    return m.chamadas.update.some(([id]) => id === 2);
  })());

  // 5) fechar com segurança
  m = carregar();
  const antes = m.tabs.length;
  const r0 = await run({ tipo: "close_tab", args: {} });
  ok("fechar sem alvo e sem aba do agente NÃO fecha aba do usuário (bug: fechava o índice 0)",
    r0.ok === false && m.tabs.length === antes && !!m.tabs.find((t) => t.id === 1), JSON.stringify(r0));
  const r1 = await run({ tipo: "close_tab", args: { aba: 2 } });
  ok("fechar a aba do usuário por id também é recusado", r1.ok === false && !!m.tabs.find((t) => t.id === 2), r1.erro);
  ok("a recusa explica o motivo", /aba sua/.test(r1.erro || ""));
  const N = await run({ tipo: "newtab", args: { url: "https://minha.com/" } });
  const r2 = await run({ tipo: "close_tab", args: {} });
  ok("sem alvo fecha a aba CONTROLADA, se for do agente", () => r2.ok === true && !m.tabs.find((t) => t.id === N.tab_id));
  const N2 = await run({ tipo: "newtab", args: { url: "https://outra-minha.com/" } });
  await run({ tipo: "switch_tab", args: { aba: 1 } });          // adota a aba A do usuário
  const r3 = await run({ tipo: "close_tab", args: { aba: N2.tab_id } });
  ok("fecha uma aba do agente por id", () => r3.ok === true && !m.tabs.find((t) => t.id === N2.tab_id));
  const r4 = await run({ tipo: "close_tab", args: { aba: 2, forcar: true } });
  ok("`forcar` existe só para uso explícito do núcleo", r4.ok === true);

  // 6) a API de grupos falhando não pode quebrar o comando nem a segurança
  m = carregar({ semGrupos: true });
  const S = await run({ tipo: "newtab", args: { url: "https://sem-grupos.com/" } });
  ok("sem a API de grupos a aba abre normalmente", () => !!S.tab_id && !!m.tabs.find((t) => t.id === S.tab_id));
  const r5 = await run({ tipo: "close_tab", args: { aba: S.tab_id } });
  ok("…e continua contando como aba do agente (pode fechar)", r5.ok === true);
  const r6 = await run({ tipo: "close_tab", args: { aba: 2 } });
  ok("…e a aba do usuário continua protegida", r6.ok === false);

  console.log(JSON.stringify({ casos }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ erro: String(e && e.stack || e) })); process.exit(1); });
