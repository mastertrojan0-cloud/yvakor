/* Testa a lógica pura dos atalhos "/comando". Uso: node tests/extensao/atalhos.test.js */
const path = require("path");
const A = require(path.join(__dirname, "..", "..", "chrome-extension", "atalhos.js"));
const casos = [];
const ok = (nome, cond, det) => casos.push({ nome, ok: !!cond, det: det === undefined ? "" : String(det).slice(0, 140) });

const lista = A.juntar([]);
ok("há atalhos padrão úteis", ["resumir", "explicar", "pesquisar", "extrair", "formulario", "traduzir"].every((c) => lista.some((a) => a.comando === c)));

// sugestões
ok("'/' lista tudo (até o limite)", A.sugerir("/", lista).length === 6);
ok("'/re' sugere resumir", A.sugerir("/re", lista).map((a) => a.comando).join() === "resumir");
ok("sem sugestão depois do espaço (já está digitando argumentos)", A.sugerir("/pesquisar gatos", lista).length === 0);
ok("texto comum não sugere nada", A.sugerir("oi", lista).length === 0);

// expandir
let r = A.expandir("/resumir", lista, { url: "https://x.com", titulo: "X" });
ok("expande um atalho sem argumentos", r.ok && /Resuma esta página/.test(r.prompt), r.prompt);
r = A.expandir("/pesquisar gatos persas", lista, {});
ok("{args} é substituído", r.ok && r.prompt.includes("sobre: gatos persas."), r.prompt);
r = A.expandir("/pesquisar", lista, {});
ok("atalho que exige argumento, sem argumento → erro com uso", !r.ok && /Use: \/pesquisar/.test(r.erro), r.erro);
r = A.expandir("/explicar", lista, { selecao: "" });
ok("'explicar' sem seleção → pede para selecionar", !r.ok && /Selecione um texto/.test(r.erro), r.erro);
r = A.expandir("/explicar", lista, { selecao: "mitocôndria" });
ok("'explicar' usa o texto selecionado", r.ok && r.prompt.includes("mitocôndria"), r.prompt);
r = A.expandir("/resumir foco em preços", lista, {});
ok("dado extra num atalho sem {args} não se perde", r.ok && /Informação adicional: foco em preços/.test(r.prompt), r.prompt);
r = A.expandir("  /RESUMIR  ", lista, {});
ok("ignora espaços e maiúsculas", r.ok);

// o que NÃO é atalho
ok("texto comum não é atalho", A.expandir("como vai?", lista, {}).nao_atalho === true);
ok("caminho/URL com barra não é atalho nem erro", A.expandir("/usr/bin/python", lista, {}).nao_atalho === true && A.expandir("//exemplo.com", lista, {}).nao_atalho === true);
r = A.expandir("/naoexiste", lista, {});
ok("comando desconhecido → erro claro", !r.ok && /não existe/.test(r.erro) && !r.nao_atalho, r.erro);
ok("'/' sozinho não vira erro", A.expandir("/", lista, {}).nao_atalho === true);

// atalhos do usuário
const meus = A.juntar([
  { comando: "/Preco", nome: "Ver preço", prompt: "Qual o preço do produto desta página? {titulo}" },
  { comando: "resumir", nome: "Meu resumo", prompt: "Resuma em 1 frase." },
  { comando: "", prompt: "sem comando" }, { comando: "vazio", prompt: "   " },
]);
ok("atalho do usuário é normalizado e adicionado", meus.some((a) => a.comando === "preco"));
r = A.expandir("/preco", meus, { titulo: "Tênis X" });
ok("marcadores do usuário funcionam ({titulo})", r.ok && r.prompt.includes("Tênis X"), r.prompt);
ok("o do usuário vence o padrão de mesmo comando", A.expandir("/resumir", meus, {}).prompt === "Resuma em 1 frase.");
ok("entradas inválidas (sem comando / prompt vazio) são ignoradas", !meus.some((a) => a.comando === "vazio") && meus.length === lista.length + 1);
ok("{selecao} é limitado (não estoura o contexto)", A.expandir("/explicar", lista, { selecao: "x".repeat(9000) }).prompt.length < 4300);

// comandos do núcleo (GET /api/comandos) seguem intactos ao servidor
const comNucleo = A.juntar([], [{ comando: "skills", nome: "Skills" }, { comando: "relatorio-vendas" },
                                { comando: "meu-plugin:deploy" }, { comando: "resumir", nome: "não sobrescreve" }]);
r = A.expandir("/relatorio-vendas de março", comNucleo, {});
ok("skill do núcleo vai sem expandir", r.ok && r.prompt === "/relatorio-vendas de março", r.prompt);
ok("comando de plugin com ':' é reconhecido", A.expandir("/meu-plugin:deploy", comNucleo, {}).prompt === "/meu-plugin:deploy");
ok("atalho local vence o do núcleo", /Resuma esta página/.test(A.expandir("/resumir", comNucleo, {}).prompt));
ok("comando do núcleo aparece nas sugestões", A.sugerir("/sk", comNucleo).some((a) => a.comando === "skills"));

console.log(JSON.stringify({ casos }));
