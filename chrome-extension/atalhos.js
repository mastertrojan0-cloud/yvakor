/* YVAKOR — atalhos "/comando" do painel (como os shortcuts/workflows do Claude no
 * Chrome). Lógica PURA, sem DOM nem chrome.*: carregada pelo painel e testada em
 * Node (tests/extensao/atalhos.test.js).
 *
 * Um atalho é {comando, nome, prompt, exige?}. O prompt aceita os marcadores
 * {args} (o que vem depois do comando), {selecao} (texto selecionado na página),
 * {url} e {titulo}. `exige` = "args" | "selecao": o atalho só roda com isso.
 */
(function (raiz) {
  "use strict";

  const PADRAO = [
    { comando: "resumir", nome: "Resumir a página",
      prompt: "Resuma esta página em até 6 tópicos curtos e destaque o ponto principal." },
    { comando: "explicar", nome: "Explicar a seleção", exige: "selecao",
      prompt: "Explique de forma simples o trecho que selecionei na página:\n\n{selecao}" },
    { comando: "pesquisar", nome: "Pesquisar na web", exige: "args",
      prompt: "Pesquise na web sobre: {args}. Traga as 3 melhores fontes, com um resumo de cada e o link." },
    { comando: "extrair", nome: "Extrair dados em tabela",
      prompt: "Extraia os dados principais desta página e apresente em uma tabela." },
    { comando: "formulario", nome: "Preencher formulário", exige: "args",
      prompt: "Veja os campos do formulário desta página e preencha o que for óbvio com estes dados: {args}. " +
              "Antes de enviar, me mostre o que preencheu e pergunte o que faltar." },
    { comando: "traduzir", nome: "Traduzir a página",
      prompt: "Traduza o conteúdo principal desta página para o português do Brasil." },
  ];

  const norm = (c) => String(c == null ? "" : c).toLowerCase().replace(/^\//, "").replace(/[^a-z0-9_-]/g, "");

  // Atalhos do usuário vencem os padrão de mesmo comando.
  function juntar(usuario) {
    const mapa = new Map(PADRAO.map((a) => [a.comando, Object.assign({ padrao: true }, a)]));
    for (const a of usuario || []) {
      const c = norm(a && a.comando);
      if (c && a.prompt && String(a.prompt).trim()) {
        mapa.set(c, { comando: c, nome: String(a.nome || c).slice(0, 60), prompt: String(a.prompt), exige: a.exige || undefined });
      }
    }
    return Array.from(mapa.values());
  }

  // Sugestões enquanto digita: só quando começa com "/" e ainda não há espaço.
  function sugerir(texto, lista, max = 6) {
    const t = String(texto || "");
    if (!t.startsWith("/") || /\s/.test(t)) return [];
    const p = norm(t);
    return lista.filter((a) => a.comando.startsWith(p)).slice(0, max);
  }

  // Devolve {ok:true, prompt, atalho} | {ok:false, nao_atalho:true} | {ok:false, erro}
  function expandir(texto, lista, ctx) {
    ctx = ctx || {};
    const t = String(texto || "").trim();
    if (!t.startsWith("/")) return { ok: false, nao_atalho: true };
    const m = t.match(/^\/([^\s]+)\s*([\s\S]*)$/);
    if (!m) return { ok: false, nao_atalho: true };
    const cmd = norm(m[1]);
    const args = (m[2] || "").trim();
    const atalho = lista.find((a) => a.comando === cmd);
    if (!atalho) {
      // "/usr/bin" ou uma URL não é atalho: só reclama se parece comando de verdade
      if (/^[a-z][a-z0-9_-]{1,19}$/i.test(m[1]) && !m[1].includes("/")) {
        return { ok: false, erro: "O atalho /" + cmd + " não existe. Digite / para ver os disponíveis." };
      }
      return { ok: false, nao_atalho: true };
    }
    if (atalho.exige === "selecao" && !String(ctx.selecao || "").trim()) {
      return { ok: false, erro: "Selecione um texto na página antes de usar /" + cmd + "." };
    }
    if (atalho.exige === "args" && !args) {
      return { ok: false, erro: "Use: /" + cmd + " <o que você quer>" };
    }
    const vals = { args, selecao: String(ctx.selecao || "").slice(0, 4000),
                   url: ctx.url || "", titulo: ctx.titulo || "" };
    let prompt = atalho.prompt.replace(/\{(args|selecao|url|titulo)\}/g, (_, k) => vals[k]);
    // dado extra num atalho que não usa {args}: não se perde
    if (args && !/\{args\}/.test(atalho.prompt)) prompt += "\n\nInformação adicional: " + args;
    return { ok: true, prompt, atalho };
  }

  const api = { PADRAO, juntar, sugerir, expandir, norm };
  raiz.YvakorAtalhos = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
