(function () {
  if (window.__yvakorVisual) return;

  const style = document.createElement("style");
  style.textContent = `
  #yvk-cursor{position:fixed;z-index:2147483647;width:26px;height:26px;
    pointer-events:none;transition:left .32s cubic-bezier(.2,.8,.2,1),
    top .32s cubic-bezier(.2,.8,.2,1);filter:drop-shadow(0 2px 3px #0006)}
  #yvk-cursor:before{content:"";position:absolute;left:2px;top:2px;
    border-left:12px solid #111;border-top:7px solid transparent;
    border-bottom:7px solid transparent;transform:rotate(-25deg)}
  #yvk-cursor:after{content:"";position:absolute;left:0;top:0;width:22px;
    height:22px;border:2px solid #e0a83c;border-radius:50%;
    animation:yvk-pulse .7s ease-out infinite}
  #yvk-ripple{position:fixed;z-index:2147483646;width:14px;height:14px;
    margin:-7px 0 0 -7px;border:2px solid #e0a83c;border-radius:50%;
    pointer-events:none;animation:yvk-ripple .55s ease-out forwards}
  #yvk-status{position:fixed;left:14px;bottom:14px;z-index:2147483647;
    background:#171d21;color:#f4efe4;font:600 12px/1.4 'Segoe UI',sans-serif;
    padding:8px 12px;border:1px solid #e0a83c;border-radius:8px;
    box-shadow:0 4px 18px #0008;pointer-events:none;opacity:0;
    transition:opacity .2s;max-width:340px}
  #yvk-status.on{opacity:1}
  @keyframes yvk-pulse{from{transform:scale(.5);opacity:.9}
    to{transform:scale(1.6);opacity:0}}
  @keyframes yvk-ripple{from{transform:scale(.4);opacity:1}
    to{transform:scale(3);opacity:0}}`;
  document.documentElement.appendChild(style);

  const cursor = document.createElement("div");
  cursor.id = "yvk-cursor";
  cursor.style.left = "-40px";
  cursor.style.top = "-40px";
  const status = document.createElement("div");
  status.id = "yvk-status";
  document.documentElement.append(cursor, status);

  // Aba em segundo plano: o Chrome limita timers a 1/s, então cada passo da
  // animação levava ~1s. Sem ninguém olhando, pula as esperas visuais.
  const sleep = (ms) => document.hidden ? Promise.resolve()
    : new Promise(r => setTimeout(r, ms));
  function show(msg) {
    status.textContent = "YVAKOR · " + msg;
    status.classList.add("on");
  }
  function hide() { status.classList.remove("on"); }

  async function moveTo(el) {
    const r = el.getBoundingClientRect();
    cursor.style.left = (r.left + r.width / 2) + "px";
    cursor.style.top = (r.top + r.height / 2) + "px";
    await sleep(360);
  }

  async function click(el, label) {
    try {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      await sleep(280);
      show(label || "clicando");
      await moveTo(el);
      const r = el.getBoundingClientRect();
      const ripple = document.createElement("div");
      ripple.id = "yvk-ripple";
      ripple.style.left = (r.left + r.width / 2) + "px";
      ripple.style.top = (r.top + r.height / 2) + "px";
      document.documentElement.appendChild(ripple);
      await sleep(90);
      el.click();
      await sleep(450);
      ripple.remove();
    } finally { hide(); }
  }

  // A digitação saiu daqui: o motor único está em pagina.js (editores
  // ricos, <select>, envio de formulário…). O overlay só dá o feedback visual.
  window.__yvakorVisual = { click, mover: moveTo, show, hide, sleep };
})();
