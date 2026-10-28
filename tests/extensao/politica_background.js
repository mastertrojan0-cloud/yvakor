/* Verifica a DECISÃO de permissões do background.js (acaoPagina → verificarPolitica)
 * com a API do Chrome simulada. Roda o código REAL do arquivo. Uso:
 *     node tests/extensao/politica_background.js     → imprime JSON {casos:[...]}
 */
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "..", "chrome-extension", "background.js"), "utf8");

const ini = src.indexOf("async function acaoPagina");
const fim = src.indexOf("// Se a ação iniciou uma navegação");
if (ini < 0 || fim < 0 || ini > fim) throw new Error("recorte inválido do background.js");
const trecho = src.slice(ini, fim);

let urlAba = "https://loja.com/produto";
let sensivel = false;
const acoesExecutadas = [];
const PAGINA_PROTEGIDA = /^(chrome|edge|about|chrome-extension|devtools|view-source|chrome-search):/;
const ctrlOrActiveBG = async () => ({ id: 7, url: urlAba });
const indicadorLigar = async () => {};
const dormirBG = (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5)));
const aguardarCarregarBG = async () => null;
const chrome = { scripting: { executeScript: async (o) => {
  if (o.files) return [];
  const [nome] = o.args;
  if (nome === "descrever_acao") {
    return [{ result: { ok: true, descricao: "Clicar em «Comprar agora»", sensivel, motivo: sensivel ? "ação irreversível ou com custo" : "" } }];
  }
  acoesExecutadas.push(nome);
  return [{ result: { ok: true, executou: nome } }];
} } };

eval(trecho + ";globalThis.acaoPagina = acaoPagina;");

async function caso(nome, url, pol, args, esp) {
  urlAba = url; sensivel = !!args._sensivel; delete args._sensivel;
  acoesExecutadas.length = 0;
  const r = (await globalThis.acaoPagina("clicar", Object.assign({ alvo: "e1", politica: pol }, args))).resultado;
  return { nome, esperado: esp, ok: esp(r), agiu: acoesExecutadas.length > 0, tipo: (r.precisa_confirmar || {}).tipo || null };
}

(async () => {
  const PERG = { modo: "perguntar", permitidos: [], bloqueados: [] };
  const AUTO = { modo: "autonomo", permitidos: [], bloqueados: [] };
  const casos = [];
  casos.push(await caso("site novo no modo perguntar pede permissão do site e NÃO age",
    "https://loja.com/x", PERG, {}, (r) => r.precisa_confirmar && r.precisa_confirmar.tipo === "site"));
  casos.push(await caso("site já permitido (e subdomínio) age direto",
    "https://pay.loja.com/x", { modo: "perguntar", permitidos: ["loja.com"], bloqueados: [] }, {}, (r) => r.ok && r.executou === "clicar"));
  casos.push(await caso("outro domínio parecido NÃO herda a permissão",
    "https://lojax.com/x", { modo: "perguntar", permitidos: ["loja.com"], bloqueados: [] }, {}, (r) => r.precisa_confirmar && r.precisa_confirmar.tipo === "site"));
  casos.push(await caso("site bloqueado recusa sem perguntar",
    "https://spam.com/x", { modo: "perguntar", permitidos: [], bloqueados: ["spam.com"] }, {}, (r) => r.bloqueado === true && !r.precisa_confirmar));
  casos.push(await caso("modo autônomo: site comum age sem pedir permissão",
    "https://blog.com/x", AUTO, {}, (r) => r.ok && r.executou === "clicar"));
  casos.push(await caso("modo autônomo: site de BANCO ainda pede permissão",
    "https://www.nubank.com.br/x", AUTO, {}, (r) => r.precisa_confirmar && r.precisa_confirmar.tipo === "site" && r.precisa_confirmar.host_sensivel));
  casos.push(await caso("ação SENSÍVEL pede confirmação mesmo com o site permitido",
    "https://loja.com/x", { modo: "perguntar", permitidos: ["loja.com"], bloqueados: [] }, { _sensivel: true },
    (r) => r.precisa_confirmar && r.precisa_confirmar.tipo === "acao" && /Comprar/.test(r.precisa_confirmar.descricao)));
  casos.push(await caso("ação SENSÍVEL pede confirmação também no modo autônomo",
    "https://blog.com/x", AUTO, { _sensivel: true }, (r) => r.precisa_confirmar && r.precisa_confirmar.tipo === "acao"));
  casos.push(await caso("confirmado_site pula só a pergunta do site",
    "https://loja.com/x", PERG, { confirmado_site: true }, (r) => r.ok && r.executou === "clicar"));
  casos.push(await caso("confirmado_acao libera a ação sensível",
    "https://blog.com/x", AUTO, { _sensivel: true, confirmado_acao: true }, (r) => r.ok && r.executou === "clicar"));
  // Seguro por padrão: sem política (núcleo antigo/ausente) a extensão PERGUNTA,
  // nunca age livre num site desconhecido.
  casos.push(await caso("sem política: o padrão é perguntar pelo site (seguro por padrão)",
    "https://qualquer.com/x", undefined, {}, (r) => !r.ok && r.precisa_confirmar && r.precisa_confirmar.tipo === "site"));
  // ação sem efeito (extrair) nunca passa pela política
  urlAba = "https://loja.com/x"; acoesExecutadas.length = 0;
  const r = (await globalThis.acaoPagina("extrair", { politica: PERG })).resultado;
  casos.push({ nome: "ações só de leitura não pedem permissão", ok: r.ok && r.executou === "extrair", agiu: true, tipo: null });
  // páginas internas do navegador continuam proibidas
  urlAba = "chrome://settings/";
  let msg = "";
  try { await globalThis.acaoPagina("clicar", { alvo: "x", politica: PERG }); } catch (e) { msg = e.message; }
  casos.push({ nome: "páginas chrome:// seguem proibidas", ok: /não aceita automação/.test(msg), agiu: false, tipo: null });

  console.log(JSON.stringify({ casos: casos.map((c) => ({ nome: c.nome, ok: !!c.ok, agiu: c.agiu, tipo: c.tipo })) }));
})();
