/* navegador_rede (redeNaPagina), navegador_js (jsNaPagina) e a política do JS
 * (politicaJs) — código REAL do background.js com uma "página" simulada. Uso:
 *     node tests/extensao/rede_js_background.js   → imprime JSON {casos:[...]}
 */
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "..", "chrome-extension", "background.js"), "utf8");

function recorte(ini, fim) {
  const a = src.indexOf(ini), b = src.indexOf(fim, a);
  if (a < 0 || b < 0) throw new Error("recorte inválido: " + ini);
  return src.slice(a, b);
}
const HOST_SENSIVEL = /(bank|banco|gov\.br)/i;
function hostDe(url) { try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }
const hostCombina = (h, r) => !!h && !!r && (h === r || h.endsWith("." + r));

// "página" mínima: fetch que devolve JSON, XHR, performance e location
class Resp {
  constructor(corpo) { this._c = corpo; this.status = 200; this.headers = { get: () => "application/json" }; }
  clone() { return new Resp(this._c); }
  text() { return Promise.resolve(this._c); }
}
globalThis.location = { href: "https://loja.com/planos" };
globalThis.fetch = async (url) => new Resp(JSON.stringify({ plano: "500 Mega", preco: 99.9, url }));
class XHR { open() {} send() { this.status = 200; this.responseType = ""; this.responseText = '{"cep":"ok"}';
  setTimeout(() => (this._l || []).forEach((f) => f()), 0); }
  addEventListener(ev, f) { (this._l = this._l || []).push(f); } getResponseHeader() { return "application/json"; } }
globalThis.XMLHttpRequest = XHR;
globalThis.performance = { getEntriesByType: () => [
  { initiatorType: "fetch", name: "https://loja.com/api/inicio" },
  { initiatorType: "img", name: "https://loja.com/logo.png" }] };
globalThis.window = globalThis;
globalThis.Node = class {};

eval(recorte("const JS_SENSIVEL", "// Roda no MUNDO DA PÁGINA") +
     recorte("function redeNaPagina", "// Roda no mundo da página: avalia") +
     recorte("async function jsNaPagina", "// Se a ação iniciou uma navegação") +
     ";globalThis.T = { politicaJs, redeNaPagina, jsNaPagina };");

(async () => {
  const casos = [];
  const c = (nome, ok) => casos.push({ nome, ok: !!ok });
  const r1 = T.redeNaPagina({});
  c("1ª chamada liga a escuta e lista as APIs já chamadas (sem imagens)",
    r1.ok && r1.escutando_desde_agora && r1.capturadas.length === 0 &&
    r1.recursos_anteriores.join() === "https://loja.com/api/inicio" && /escuta/.test(r1.dica));
  await fetch("/api/planos?cep=69000000");
  const x = new XMLHttpRequest(); x.open("GET", "/api/cep"); x.send();
  await new Promise((r) => setTimeout(r, 10));
  const r2 = T.redeNaPagina({});
  c("depois da ação devolve as respostas de fetch e XHR com URL absoluta",
    r2.capturadas.length === 2 && !r2.escutando_desde_agora &&
    r2.capturadas[0].url === "https://loja.com/api/planos?cep=69000000" &&
    /500 Mega/.test(r2.capturadas[0].corpo) && r2.capturadas[1].url === "https://loja.com/api/cep");
  c("filtro casa pela URL ou pelo conteúdo", T.redeNaPagina({ filtro: "preco" }).capturadas.length === 1);
  c("limpar zera o que foi capturado", T.redeNaPagina({ limpar: true }).capturadas.length === 0);

  const tab = { url: "https://loja.com/x" };
  const AUTO = { modo: "autonomo", permitidos: [], bloqueados: [] };
  c("JS de leitura roda direto no modo autônomo",
    T.politicaJs(tab, "document.title", AUTO, false, false) === null);
  for (const cod of ["document.querySelector('b').click()", "document.cookie",
                     "fetch('https://x.com', {method:'POST'})", "el.value = '1'", "localStorage.token"]) {
    const v = T.politicaJs(tab, cod, AUTO, false, false);
    c("JS que age/sai/lê segredo pede confirmação: " + cod, v && v.precisa_confirmar.tipo === "acao");
  }
  c("confirmado_acao libera", T.politicaJs(tab, "document.cookie", AUTO, false, true) === null);
  c("site novo no modo perguntar pede o site",
    T.politicaJs(tab, "1+1", { modo: "perguntar" }, false, false).precisa_confirmar.tipo === "site");
  c("site bloqueado recusa", T.politicaJs(tab, "1", { bloqueados: ["loja.com"] }, false, false).bloqueado);

  c("jsNaPagina devolve o valor em JSON", (await T.jsNaPagina("[1,2].map(n=>n*2)")).resultado === "[2,4]");
  c("jsNaPagina espera promessa", (await T.jsNaPagina("Promise.resolve({a:1})")).resultado === '{"a":1}');
  const erro = await T.jsNaPagina("naoExiste.x");
  c("jsNaPagina devolve o erro", erro.ok === false && /naoExiste/.test(erro.erro));
  console.log(JSON.stringify({ casos }));
})();
