/* Roteiro de verificação do motor de ações (chrome-extension/pagina.js).
 *
 * Como rodar: sirva pagina_teste.html + pagina.js + este arquivo numa mesma
 * pasta (python -m http.server, APENAS a pasta de teste — nunca a raiz do
 * projeto, que tem o .env), abra no Chrome e execute rodarTestes() no console.
 * Devolve {total, falhas, todos}; falhas deve ser [].
 */
async function rodarTestes() {
  const A = window.__yvakorAcoes;
  const R = [];
  const $ = (id) => document.getElementById(id);
  const t = (nome, ok, det) => R.push({ nome, ok: !!ok, det: det === undefined ? "" : String(det).slice(0, 140) });

  // ---- ver ----
  let s = A.snapshot({ max: 80 });
  t("snapshot lista os campos e esconde o botão oculto",
    s.items.length >= 10 && !s.items.some((i) => i.id === "oculto"), s.items.length + " itens");
  t("snapshot NÃO vaza o valor do campo de senha", s.items.find((i) => i.id === "senha").valor === "");
  t("snapshot mostra as opções do <select>",
    (s.items.find((i) => i.id === "pais").opcoes || []).includes("Portugal"));
  const refBusca = s.items.find((i) => i.id === "q").ref;
  A.snapshot({ max: 80 });
  t("refs antigas são limpas (sem 'e1' duplicado)",
    document.querySelectorAll('[data-yvakor-ref="e1"]').length === 1);

  // ---- pesquisar / escrever / enviar ----
  let r = await A.escrever({ alvo: refBusca, texto: "gatos fofos", enviar: true });
  t("digita na busca e ENVIA o <form> (Enter sintético não envia)",
    r.ok && $("r-busca").textContent === "BUSCOU:gatos fofos", r.enviado_por + " | " + $("r-busca").textContent);
  r = await A.escrever({ alvo: "Seu nome", texto: "Antonio" });
  t("acha o campo pelo placeholder e o evento 'input' chega ao app",
    $("nome").value === "Antonio" && $("nome").dataset.modelo === "Antonio", $("nome").dataset.modelo);
  r = await A.escrever({ alvo: "E-mail", texto: "a@b.com" });
  t("acha o campo pelo <label>", $("email").value === "a@b.com", r.erro || "");
  await A.escrever({ alvo: "#nome", texto: " Cordero", limpar: false });
  t("limpar=false anexa ao texto existente", $("nome").value === "Antonio Cordero", $("nome").value);
  await A.escrever({ alvo: "#nome", texto: "Novo" });
  t("limpar=true (padrão) substitui", $("nome").value === "Novo", $("nome").value);
  await A.escrever({ alvo: "#msg", texto: "linha1\nlinha2" });
  t("textarea multilinha", $("msg").value === "linha1\nlinha2");
  $("rico").dataset.eventos = "0";
  r = await A.escrever({ alvo: "#rico", texto: "olá rico" });
  t("editor rico (contenteditable) via execCommand dispara 'input'",
    $("rico").innerText.trim() === "olá rico" && +$("rico").dataset.eventos >= 1,
    $("rico").innerText + " | eventos=" + $("rico").dataset.eventos);
  await A.escrever({ alvo: "#chat", texto: "oi chat", enviar: true });
  t("chat sem <form>: o Enter chega ao handler JS", $("enviadas").innerText.includes("oi chat"), $("enviadas").innerText);
  r = await A.escrever({ alvo: "dentro do shadow", texto: "sombra" });
  t("campo dentro de shadow DOM",
    document.getElementById("host").shadowRoot.getElementById("sh-in").value === "sombra", r.erro || "");
  $("q").value = ""; $("q").focus();
  r = await A.escrever({ texto: "sem alvo", enviar: true });
  t("sem alvo: usa o campo focado", $("r-busca").textContent === "BUSCOU:sem alvo", $("r-busca").textContent);
  r = await A.escrever({ alvo: "#senha", texto: "novaSenha" });
  t("não ecoa o conteúdo de campo de senha", r.escrito === "(senha)", r.escrito);
  r = await A.escrever({ alvo: "#naoexiste", texto: "x" });
  t("campo inexistente → erro claro", !r.ok && /não encontrado/.test(r.erro), r.erro);

  // ---- selecionar / marcar ----
  r = await A.selecionar({ alvo: "#pais", valor: "Portugal" });
  t("select por texto", $("pais").value === "pt", $("pais").value);
  r = await A.selecionar({ alvo: "#pais", valor: "ar" });
  t("select por value", $("pais").value === "ar", $("pais").value);
  r = await A.selecionar({ alvo: "#pais", valor: "Japão" });
  t("opção inexistente → erro com as opções disponíveis", !r.ok && (r.opcoes || []).length === 3, JSON.stringify(r.opcoes));
  await A.escrever({ alvo: "#ck", texto: "sim" });
  t("checkbox marca", $("ck").checked);
  await A.escrever({ alvo: "#ck", texto: "não" });
  t("checkbox desmarca", !$("ck").checked);

  // ---- clicar ----
  await A.clicar({ alvo: "Clique aqui" });
  await A.clicar({ alvo: "#btn" });
  t("clicar por texto e por seletor", $("cliques").textContent === "2", $("cliques").textContent);
  r = await A.clicar({ alvo: "botão que não existe" });
  t("clicar em algo inexistente → erro claro", !r.ok && /não encontrado/.test(r.erro), r.erro);

  // ---- teclas ----
  $("nome").value = "abc"; $("nome").focus();
  r = await A.pressionar({ tecla: "Control+A" });
  t("Ctrl+A seleciona tudo", $("nome").selectionStart === 0 && $("nome").selectionEnd === 3, r.efeito);
  await A.pressionar({ tecla: "Backspace" });
  t("Backspace apaga a seleção", $("nome").value === "", JSON.stringify($("nome").value));
  $("q").value = "x2";
  r = await A.pressionar({ tecla: "Enter", alvo: "#q" });
  t("Enter em campo de <form> envia", $("r-busca").textContent === "BUSCOU:x2", $("r-busca").textContent);
  $("nome").focus();
  await A.pressionar({ tecla: "Tab" });
  t("Tab move o foco", document.activeElement !== $("nome"), document.activeElement.id);
  $("nome").focus();
  r = await A.pressionar({ tecla: "z" });
  t("tecla de caractere digita no campo focado", $("nome").value === "z", $("nome").value);

  // ---- mouse / espera / rolagem ----
  await A.passar_mouse({ alvo: "#hov" });
  t("hover dispara mouseenter", $("hovr").textContent === "HOVER");
  setTimeout(() => {
    const d = document.createElement("div");
    d.id = "tardio"; d.textContent = "CHEGOU"; document.body.appendChild(d);
  }, 400);
  r = await A.esperar({ seletor: "#tardio", segundos: 3 });
  t("espera um elemento que aparece depois", r.ok && r.apareceu, JSON.stringify(r).slice(0, 80));
  r = await A.esperar({ texto: "texto-que-nao-existe-xyz", segundos: 0.5 });
  t("espera com tempo esgotado → erro claro", !r.ok && /esgotado/.test(r.erro), r.erro);
  scrollTo(0, 0);
  r = await A.rolar({ direcao: "baixo" });
  t("rola a página para baixo", scrollY > 0, "y=" + scrollY);
  r = await A.rolar({ direcao: "topo" });
  t("rola ao topo", scrollY === 0, "y=" + scrollY);
  r = await A.rolar({ direcao: "fim" });
  t("rola ao fim e informa", r.no_fim === true, JSON.stringify(r));

  // ---- extrair ----
  r = A.extrair({ max_chars: 500 });
  t("extrair devolve texto e links", r.ok && r.texto.length > 10 && r.links.some((l) => l.texto.includes("âncora")),
    r.links && r.links.length + " links");

  return { total: R.length, falhas: R.filter((x) => !x.ok), todos: R };
}
