"""
YVAKOR — Sessão de navegador controlada (Playwright).

Por que uma thread dedicada?
  A API síncrona do Playwright é presa à thread que a criou. O YVAKOR executa
  ferramentas em threads diferentes (HTTP, cowork, CLI), então TODAS as
  operações do navegador são despachadas para uma única thread dona. Isso dá
  um navegador estável, compartilhado por chat e tarefas de segundo plano.

Por que perfil persistente?
  O agente precisa continuar logado entre execuções (Claude Cowork-like). O
  perfil fica em data/browser_profile/ (fora do git), separado do seu Edge/
  Chrome pessoal — sem risco de mexer no seu navegador do dia a dia.

Como o agente "enxerga" a página sem visão computacional?
  Cada `snapshot()` marca os elementos interativos com data-yvk-ref="eN" e
  devolve um resumo textual (título, texto visível, lista de elementos com
  ref). O modelo age por ref: {alvo: "e12"}. Depois de qualquer navegação ele
  pede um novo snapshot (as refs antigas expiram).
"""
from __future__ import annotations

import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path
import logging

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent

# Marcador dos elementos no DOM (não confundir com atributos do site).
MARK = "data-yvk-ref"


class BrowserUnavailable(RuntimeError):
    """Playwright ausente ou nenhum navegador instalado."""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BrowserSession:
    """Navegador real (Chromium/Edge/Chrome) com perfil persistente."""

    def sessao(self, nome: str | None = None) -> "BrowserSession":
        """Compatibilidade: a sessão também atende como gerenciador."""
        return self

    def motor(self, nome: str | None = None) -> str:
        return (nome or getattr(self, "engine", None)
                or getattr(self, "_engine", None) or "edge")

    @property
    def padrao(self) -> str:
        return self.motor()

    def __init__(self, settings: dict, engine: str | None = None,
                 mode: str | None = None, profile_dir: str | None = None,
                 cdp_url: str | None = None, rotulo: str = ""):
        cfg = (settings or {}).get("browser", {}) or {}
        self.cfg = cfg
        self.headless: bool = bool(cfg.get("headless", True))
        self.channel: str = (engine or cfg.get("channel") or "msedge").strip()
        self.rotulo = rotulo or self.channel
        self.mode = (mode or cfg.get("mode") or "launch").lower()
        self.cdp_url = (cdp_url or cfg.get("cdp_url") or "").strip()
        self.viewport = cfg.get("viewport") or {"width": 1280, "height": 800}
        self.timeout_ms: int = int(cfg.get("timeout_ms", 15000))
        self.nav_timeout_ms: int = int(cfg.get("nav_timeout_ms", 45000))
        self.snapshot_chars: int = int(cfg.get("snapshot_text_chars", 3000))
        self.max_elements: int = int(cfg.get("max_elements", 120))
        self.shot_dir = ROOT / "data" / "browser_shots"
        self.profile_dir = ROOT / (profile_dir or cfg.get("profile_dir")
                                   or "data/browser_profile")
        self.realismo = bool(cfg.get("realismo", True))
        self.digitar_ms = int(cfg.get("digitar_ms", 35))
        # Isolamento por tarefa: uma aba por contexto, todas no mesmo motor.
        self._abas: dict[str, object] = {}
        self._aba_atual = "principal"
        self._aba_nome = "principal"
        # Grupos de abas: cada tarefa acumula suas abas num grupo próprio.
        self._grupos: dict[str, list[str]] = {}
        self._aba_grupo: dict[str, str] = {}
        self._grupo_atual = "principal"
        self._seq_aba = 0
        self.trilho = threading.RLock()
        self._browser_cdp = None

        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()

        # Estado do navegador (tocado apenas na thread dona)
        self._pw = None
        self._ctx = None
        self._page = None
        self._engine = ""

        # Estado compartilhado (leitura para status/UI)
        self._state_lock = threading.Lock()
        self._url = ""
        self._title = ""
        self._last_error = ""
        self._last_action = ""
        self._last_seen = ""
        self._ops = 0

    # ================================================================== #
    # Infra: thread dona + fila de comandos
    # ================================================================== #
    def _ensure_thread(self) -> None:
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker, daemon=True, name="yvakor-browser")
            self._thread.start()

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, args, kwargs, box = item
            try:
                box["value"] = fn(*args, **kwargs)
            except Exception as exc:                      # devolve ao chamador
                box["error"] = exc
            finally:
                box["done"].set()
        # Encerramento limpo
        try:
            if self._ctx is not None and self.mode != "cdp":
                self._ctx.close()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

    def _call(self, fn, *args, timeout: float = 90, **kwargs):
        self._ensure_thread()
        box = {"done": threading.Event(), "value": None, "error": None}
        self._q.put((fn, args, kwargs, box))
        if not box["done"].wait(timeout):
            raise TimeoutError(f"operação do navegador excedeu {timeout:.0f}s")
        if box["error"] is not None:
            raise box["error"]
        return box["value"]

    # ================================================================== #
    # Ciclo de vida (executa na thread dona)
    # ================================================================== #
    def _ensure_browser(self):
        # Modo CDP: fala com um navegador JÁ ABERTO (remote debugging).
        if self.mode == "cdp":
            if self._pw is None:
                try:
                    from playwright.sync_api import sync_playwright
                except ImportError as exc:
                    raise BrowserUnavailable(
                        "Playwright não instalado. Rode: pip install playwright") from exc
                self._pw = sync_playwright().start()
            if self._browser_cdp is None:
                if not self.cdp_url:
                    raise BrowserUnavailable(
                        "modo CDP sem endereço: informe http://127.0.0.1:9222 "
                        "(Chrome) ou :9223 (Edge) com --remote-debugging-port")
                self._browser_cdp = self._conectar_cdp(self.cdp_url)
                contextos = self._browser_cdp.contexts
                self._ctx = contextos[0] if contextos else self._browser_cdp.new_context()
                paginas = self._ctx.pages
                self._page = paginas[0] if paginas else self._ctx.new_page()
                self._engine = f"{self.channel} (CDP)"
                # Timeouts default para nenhuma operação pendurar o worker
                # (um worker único serve a fila; op infinita congelava tudo).
                try:
                    self._ctx.set_default_timeout(self.timeout_ms)
                    self._ctx.set_default_navigation_timeout(self.nav_timeout_ms)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            if self._page is None or self._page.is_closed():
                paginas = self._ctx.pages if self._ctx else []
                self._page = paginas[0] if paginas else self._ctx.new_page()
            return self._ctx

        if self._ctx is not None:
            try:
                _ = self._ctx.pages          # detecta contexto morto
                if self._page is None or self._page.is_closed():
                    pages = self._ctx.pages
                    self._page = pages[0] if pages else self._ctx.new_page()
                return self._ctx
            except Exception:
                self._ctx, self._page = None, None

        if self._pw is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:      # pragma: no cover - ambiente
                raise BrowserUnavailable(
                    "Playwright não instalado. Rode: pip install playwright") from exc
            try:
                self._pw = sync_playwright().start()
            except Exception as exc:        # pragma: no cover - ambiente
                raise BrowserUnavailable(
                    f"não foi possível iniciar o Playwright: {exc}") from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        erros = []
        # 1ª tentativa: canal pedido (Edge/Chrome do sistema, zero download)
        # 2ª: Chromium embutido do Playwright (se baixado).
        for channel in self._channels_to_try():
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    channel=channel or None,
                    headless=self.headless,
                    viewport=self.viewport,
                    locale="pt-BR",
                    accept_downloads=True,
                    args=[
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-features=msEdgeFirstRunExperience,Translate",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                self._engine = channel or "chromium"
                pages = self._ctx.pages
                self._page = pages[0] if pages else self._ctx.new_page()
                try:
                    self._ctx.set_default_timeout(self.timeout_ms)
                    self._ctx.set_default_navigation_timeout(self.nav_timeout_ms)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
                return self._ctx
            except Exception as exc:
                erros.append(f"{channel or 'chromium'}: {str(exc)[:160]}")
                self._ctx = None

        raise BrowserUnavailable(
            "nenhum navegador disponível para o Playwright. Instale o Google "
            "Chrome/Edge ou rode: python -m playwright install chromium. "
            f"Detalhes: {' | '.join(erros)}")

    def _conectar_cdp(self, endereco: str):
        """Conecta ao CDP; no Chrome, abre o navegador real se necessário."""
        try:
            return self._pw.chromium.connect_over_cdp(endereco)
        except Exception as exc:
            if self.channel != "chrome":
                raise BrowserUnavailable(
                    f"CDP indisponível em {endereco}: {exc}. Abra o navegador "
                    "com --remote-debugging-port.") from exc
            from yvakor.browser.chrome_cdp import garantir_para_url
            info = garantir_para_url(endereco, perfil=self.profile_dir)
            if not info.get("ok"):
                raise BrowserUnavailable(
                    f"Chrome CDP: {info.get('erro')}") from exc
            return self._pw.chromium.connect_over_cdp(endereco)

    def _channels_to_try(self) -> list[str]:
        prefs = [self.channel, "msedge", "chrome"]
        out: list[str] = []
        for p in prefs:
            if p and p not in out:
                out.append(p)
        out.append("")          # "" → chromium embutido
        return out

    def _ensure_browser_headed(self):
        """Reabre o navegador no modo visível (para o usuário acompanhar)."""
        self.headless = False
        self._close_browser()
        self._ensure_browser()
        return self._ctx

    def _close_browser(self):
        if self.mode == "cdp":
            # Nunca fecha o navegador do usuário: apenas solta a conexão.
            self._browser_cdp = None
            self._ctx, self._page = None, None
            self._abas.clear()
            return
        try:
            if self._ctx is not None:
                self._ctx.close()
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        self._ctx, self._page = None, None
        self._abas.clear()

    # ------------------------------------------------------------------ #
    # Abas isoladas por contexto (chat, tarefa cowork, interface)
    # ------------------------------------------------------------------ #
    # ================================================================== #
    # Atuação visível: ponteiro, destaque de alvo, clique com ripple,
    # digitação letra por letra (para o usuário acompanhar a tarefa).
    # ================================================================== #
    _VISUAL_JS = r"""
    () => {
      if (window.__yvakorVisual) return;
      window.__yvakorVisual = true;
      const css = document.createElement('style');
      css.textContent = `
        #yvakor-cursor{position:fixed;z-index:2147483647;width:20px;height:20px;
          margin:-10px 0 0 -10px;border-radius:50%;pointer-events:none;
          border:2px solid #3FBFAE;background:rgba(63,191,174,.28);
          box-shadow:0 0 12px rgba(63,191,174,.65);left:0;top:0}
        #yvakor-ripple{position:fixed;z-index:2147483646;width:12px;height:12px;
          margin:-6px 0 0 -6px;border-radius:50%;pointer-events:none;
          border:2px solid #D9A441;opacity:0;left:0;top:0}
        #yvakor-foco{position:fixed;z-index:2147483645;pointer-events:none;
          border:2px solid #D9A441;border-radius:4px;opacity:0;
          transition:opacity .15s;left:0;top:0}
      `;
      document.documentElement.appendChild(css);
      const c = document.createElement('div'); c.id = 'yvakor-cursor';
      const r = document.createElement('div'); r.id = 'yvakor-ripple';
      const f = document.createElement('div'); f.id = 'yvakor-foco';
      document.documentElement.append(c, r, f);
    }
    """

    def _preparar_visual(self, page) -> None:
        if not getattr(self, "realismo", True):
            return
        try:
            page.evaluate(self._VISUAL_JS)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

    def _mover_visual(self, page, x: float, y: float) -> None:
        if not getattr(self, "realismo", True):
            return
        try:
            page.mouse.move(x, y, steps=14)
            page.evaluate(
                "([x,y]) => { const c=document.getElementById('yvakor-cursor');"
                " if(c) c.style.transform=`translate(${x}px,${y}px)`; }", [x, y])
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

    def _clique_visual(self, loc, timeout: int) -> None:
        page = self._page
        try:
            caixa = loc.bounding_box()
        except Exception:
            caixa = None
        if caixa and getattr(self, "realismo", True):
            x = caixa["x"] + caixa["width"] / 2
            y = caixa["y"] + caixa["height"] / 2
            try:
                page.evaluate(
                    """([x,y,w,h]) => {
                        const f=document.getElementById('yvakor-foco');
                        if(!f) return;
                        Object.assign(f.style,{left:x+'px',top:y+'px',
                          width:w+'px',height:h+'px',opacity:'1'});
                        setTimeout(()=>f.style.opacity='0', 700);
                    }""",
                    [caixa["x"], caixa["y"], caixa["width"], caixa["height"]])
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            self._mover_visual(page, x, y)
            try:
                page.evaluate(
                    """([x,y]) => {
                        const r=document.getElementById('yvakor-ripple');
                        if(!r) return;
                        r.style.left=x+'px'; r.style.top=y+'px';
                        r.style.transition='none'; r.style.opacity='1';
                        r.style.transform='scale(1)';
                        requestAnimationFrame(()=>{
                          r.style.transition='transform .45s ease-out, opacity .45s';
                          r.style.transform='scale(4.5)'; r.style.opacity='0';
                        });
                    }""", [x, y])
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            page.wait_for_timeout(120)
        loc.click(timeout=timeout)

    def _preenchimento_visual(self, loc, valor: str) -> None:
        if not getattr(self, "realismo", True):
            loc.fill(str(valor))
            return
        page = self._page
        try:
            caixa = loc.bounding_box()
            if caixa:
                self._mover_visual(page, caixa["x"] + caixa["width"] / 2,
                                   caixa["y"] + caixa["height"] / 2)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        loc.click()
        loc.fill("")
        atraso = int(getattr(self, "digitar_ms", 35))
        for caractere in str(valor):
            page.keyboard.type(caractere, delay=atraso)

    def _preparar_aba(self, chave: str) -> None:
        self._ensure_browser()
        if self._page is not None:
            self._preparar_visual(self._page)
        # registra a página atual sob o nome atual (cobre troca explícita de aba)
        if self._page is not None and not self._page.is_closed():
            self._abas[self._aba_atual] = self._page
            self._aba_grupo.setdefault(self._aba_atual, self._grupo_atual)
            lista_atual = self._grupos.setdefault(
                self._aba_grupo[self._aba_atual], [])
            if self._aba_atual not in lista_atual:
                lista_atual.append(self._aba_atual)
        if chave == self._aba_atual and self._page is not None \
                and not self._page.is_closed():
            return
        pagina = self._abas.get(chave)
        if pagina is None or pagina.is_closed():
            pagina = self._ctx.new_page()
            self._abas[chave] = pagina
        self._page = pagina
        self._aba_atual = chave
        self._aba_nome = chave
        self._aba_grupo.setdefault(chave, self._grupo_atual)
        lista = self._grupos.setdefault(self._aba_grupo[chave], [])
        if chave not in lista:
            lista.append(chave)

    def selecionar_aba(self, aba: str | None = None,
                       grupo: str | None = None) -> dict:
        """Prepara a aba (e o grupo) desta tarefa. Use dentro de `trilho`."""
        chave = aba or "principal"
        def run():
            self._grupo_atual = grupo or self._aba_grupo.get(chave, chave)
            self._preparar_aba(chave)
        self._call(run, timeout=60)
        return {"ok": True, "aba": chave}

    def grupos(self) -> dict:
        # Chamado a cada atualização de status (GUI/web fazem polling). Com o navegador
        # FECHADO não pode abri-lo: antes, `_ensure_browser()` aqui lançava o Chrome
        # real (CDP) poucos segundos depois de o núcleo subir.
        with self._state_lock:
            if self._ctx is None:
                return {"ok": True, "grupos": {}}

        def run():
            self._ensure_browser()
            saida = {}
            for grupo, chaves in list(self._grupos.items()):
                itens = []
                for chave in chaves:
                    pg = self._abas.get(chave)
                    if pg is None or pg.is_closed():
                        continue
                    try:
                        titulo = (pg.title() or "")[:80]
                    except Exception:
                        titulo = ""
                    itens.append({"aba": chave, "url": pg.url, "titulo": titulo,
                                  "ativa": chave == self._aba_atual})
                if itens:
                    saida[grupo] = itens
            return {"ok": True, "grupos": saida}
        return self._call(run, timeout=60)

    def focar_grupo(self, grupo: str) -> dict:
        alvo = str(grupo or self._grupo_atual)
        def run():
            self._ensure_browser()
            chaves = [c for c in self._grupos.get(alvo, [])
                      if self._abas.get(c) and not self._abas[c].is_closed()]
            if not chaves:
                raise ValueError(f"grupo '{alvo}' não tem abas abertas")
            self._grupo_atual = alvo
            self._preparar_aba(chaves[0])
            return {"ok": True, "grupo": alvo, "aba": chaves[0],
                    "url": self._page.url}
        return self._call(run, timeout=60)

    def fechar_grupo(self, grupo: str, manter_uma: bool = True) -> dict:
        alvo = str(grupo or self._grupo_atual)
        def run():
            self._ensure_browser()
            chaves = list(self._grupos.pop(alvo, []))
            fechadas = 0
            for chave in chaves:
                pg = self._abas.pop(chave, None)
                self._aba_grupo.pop(chave, None)
                try:
                    if pg and not pg.is_closed() and len(self._ctx.pages) > 1:
                        pg.close()
                        fechadas += 1
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            if self._aba_atual not in self._abas:
                self._aba_atual = "principal"
                self._abas["principal"] = (self._ctx.pages[0]
                                           if self._ctx.pages
                                           else self._ctx.new_page())
                self._aba_grupo["principal"] = "principal"
                self._grupos.setdefault("principal", ["principal"])
            self._page = self._abas[self._aba_atual]
            return {"ok": True, "grupo": alvo, "fechadas": fechadas}
        return self._call(run, timeout=60)

    def abas_internas(self) -> dict:
        return {"atual": self._aba_nome,
                "abertas": list(self._abas.keys())}

    def conectar_cdp(self, url: str | None = None) -> dict:
        """Anexa a um navegador já aberto com --remote-debugging-port."""
        endereco = (url or self.cdp_url or "").strip()
        if not endereco:
            raise ValueError("informe a URL do CDP (ex.: http://127.0.0.1:9222)")

        def run():
            self._close_browser()
            if self._pw is None:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
            self._browser_cdp = self._conectar_cdp(endereco)
            contextos = self._browser_cdp.contexts
            self._ctx = contextos[0] if contextos else self._browser_cdp.new_context()
            paginas = self._ctx.pages
            self._page = paginas[0] if paginas else self._ctx.new_page()
            self.mode = "cdp"
            self.cdp_url = endereco
            self._engine = f"{self.channel} (CDP)"
            self._aba_atual = self._aba_nome = "principal"
            self._abas = {"principal": self._page}
            dados = self._snapshot_raw(self._page)
            return {"ok": True, "modo": "cdp", "url": dados["url"],
                    "abas_abertas": len(paginas), "cdp": endereco,
                    "resumo": self._render_snapshot(dados, self.snapshot_chars)}
        return self._call(run, timeout=90)

    # ================================================================== #
    # Utilitários internos
    # ================================================================== #
    @staticmethod
    def _looks_like_url(target: str) -> bool:
        t = target.strip()
        # Qualquer esquema explícito: http, https, file, about, data…
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", t):
            return True
        # Domínio puro ("exemplo.com", "localhost:3000")
        if re.match(r"^localhost(:\d+)?(/.*)?$", t, re.I):
            return True
        return bool(re.match(r"^[\w-]+(\.[\w-]+)+(/.*)?$", t)) and " " not in t

    def _goto(self, page, url: str) -> str:
        url = url.strip()
        if not self._looks_like_url(url):
            url = "https://duckduckgo.com/?q=" + url.replace(" ", "+")
        elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
            url = "https://" + url
        resp = page.goto(url, wait_until="domcontentloaded",
                         timeout=self.nav_timeout_ms)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        if resp is not None and resp.status >= 400:
            self._last_error = f"HTTP {resp.status} em {url}"
        self._sync_state(page)
        return page.url

    def _sync_state(self, page) -> None:
        with self._state_lock:
            try:
                self._url = page.url
            except Exception:
                self._url = ""
            try:
                self._title = page.title()
            except Exception:
                self._title = ""
            self._last_seen = _now()

    def _locator(self, page, target: str):
        """Resolve `alvo` → locator. Aceita ref (e12), CSS ou texto literal."""
        t = str(target or "").strip()
        if not t:
            raise ValueError("alvo vazio: informe a ref (ex.: e12) do último "
                             "navegador_ver")
        if re.fullmatch(r"e\d+", t):
            loc = page.locator(f'[{MARK}="{t}"]')
            if loc.count() == 0:
                raise ValueError(
                    f"a ref '{t}' não existe mais nesta página. A página mudou "
                    "ou navegou: chame navegador_ver para ver as refs atuais.")
            return loc.first
        # Seletor explícito do Playwright (css=, text=, role=, xpath=…)
        if re.match(r"^(css|text|role|xpath|id|data-testid)=", t):
            return page.locator(t).first
        # CSS que claramente é CSS
        if re.match(r"^[#.\[]|^[a-zA-Z][\w-]*[#.\[]|^\w+\s*>", t):
            loc = page.locator(t)
            if loc.count() > 0:
                return loc.first
        # Texto acessível / placeholder / label / atributos (fallback amigável)
        seguro = t.replace('"', '\\"')
        tentativas = (
            lambda: page.get_by_text(t, exact=False),
            lambda: page.get_by_placeholder(t, exact=False),
            lambda: page.get_by_label(t, exact=False),
            lambda: page.get_by_role("button", name=t, exact=False),
            lambda: page.locator(f'[aria-label*="{seguro}" i]'),
            lambda: page.locator(f'[placeholder*="{seguro}" i]'),
            lambda: page.locator(f'[name="{seguro}" i]'),
        )
        for tentar in tentativas:
            try:
                loc = tentar()
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue
        raise ValueError(
            f"nada encontrado para '{t}'. Use a ref (ex.: e12) do último "
            "navegador_ver, ou um seletor CSS/text=.")

    # ================================================================== #
    # Snapshot (o "olho" do agente)
    # ================================================================== #
    _SNAPSHOT_JS = r"""
    (maxEl) => {
      const MARK = 'data-yvk-ref';
      document.querySelectorAll('[' + MARK + ']')
              .forEach(e => e.removeAttribute(MARK));

      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 2 && r.height > 2 &&
               s.visibility !== 'hidden' && s.display !== 'none' &&
               parseFloat(s.opacity || '1') > 0.05;
      };
      const nameOf = (el) => {
        const cand = el.getAttribute('aria-label') ||
          (el.labels && el.labels[0] && el.labels[0].innerText) ||
          el.getAttribute('placeholder') || el.getAttribute('title') ||
          el.innerText || el.value || el.getAttribute('alt') ||
          el.getAttribute('name') || '';
        return String(cand).replace(/\s+/g, ' ').trim().slice(0, 90);
      };
      const sel = 'a[href], button, input, textarea, select, summary, ' +
        'label[for], [role=button], [role=link], [role=tab], [role=menuitem], ' +
        '[role=checkbox], [role=radio], [role=combobox], [role=switch], ' +
        '[contenteditable=""], [contenteditable=true], ' +
        '[onclick], [tabindex]:not([tabindex="-1"])';

      const out = [];
      let i = 0;
      for (const el of document.querySelectorAll(sel)) {
        if (out.length >= maxEl) break;
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();
        if (tag === 'input' && type === 'hidden') continue;
        if (!visible(el)) continue;
        i += 1;
        const ref = 'e' + i;
        el.setAttribute(MARK, ref);

        const item = { ref: ref, tag: tag };
        if (tag === 'input') item.type = type || 'text';
        if (tag === 'a') {
          item.href = String(el.href || '').slice(0, 180);
        }
        const nm = nameOf(el);
        if (nm) item.name = nm;
        if (tag === 'input' || tag === 'textarea' || tag === 'select') {
          let v = el.value || '';
          if (type === 'password') v = '••••••';
          if (v) item.value = String(v).slice(0, 60);
          if (el.checked) item.checked = true;
          if (el.disabled) item.disabled = true;
        }
        if (el.getAttribute('aria-checked') === 'true') item.checked = true;
        out.push(item);
      }

      const body = document.body ? document.body.innerText : '';
      const text = body.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
      return {
        url: location.href,
        title: document.title,
        text: text,
        elements: out,
        total: out.length,
        iframes: document.querySelectorAll('iframe').length,
        scrollY: Math.round(window.scrollY),
        docHeight: Math.round(document.body ? document.body.scrollHeight : 0)
      };
    }
    """

    def _snapshot_raw(self, page) -> dict:
        self._preparar_visual(page)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)
        data = page.evaluate(self._SNAPSHOT_JS, self.max_elements)
        self._sync_state(page)
        return data

    @staticmethod
    def _render_snapshot(data: dict, text_chars: int) -> str:
        linhas = [
            f"URL: {data.get('url','')}",
            f"TÍTULO: {data.get('title','')}",
        ]
        scroll = data.get("scrollY", 0)
        doc = data.get("docHeight", 0)
        if doc:
            linhas.append(f"ROLAGEM: {scroll}px de {doc}px")
        if data.get("iframes"):
            linhas.append(f"AVISO: {data['iframes']} iframe(s) na página "
                          "(conteúdo interno pode não aparecer aqui)")

        texto = (data.get("text") or "").strip()
        if texto:
            corte = texto[:text_chars]
            linhas.append("\nTEXTO VISÍVEL:\n" + corte)
            if len(texto) > text_chars:
                linhas.append(f"… (+{len(texto) - text_chars} caracteres. "
                              "Use navegador_extrair ou role a página.)")

        els = data.get("elements") or []
        if els:
            linhas.append("\nELEMENTOS INTERATIVOS (aja pela ref, ex.: \"e3\"):")
            for e in els:
                partes = [f"[{e['ref']}]"]
                if e.get("tag") == "a":
                    partes.append("link")
                elif e.get("tag") == "input":
                    partes.append(f"campo:{e.get('type','text')}")
                elif e.get("tag") == "textarea":
                    partes.append("campo:texto")
                elif e.get("tag") == "select":
                    partes.append("select")
                else:
                    partes.append(e.get("tag", "?"))
                if e.get("name"):
                    partes.append(f"\"{e['name']}\"")
                if e.get("value"):
                    partes.append(f"valor=\"{e['value']}\"")
                if e.get("checked"):
                    partes.append("(marcado)")
                if e.get("disabled"):
                    partes.append("(desabilitado)")
                if e.get("href"):
                    partes.append(f"→ {e['href']}")
                linhas.append(" ".join(partes))
        else:
            linhas.append("\nNenhum elemento interativo visível.")
        return "\n".join(linhas)

    # ================================================================== #
    # API pública — todas as chamadas são seguras entre threads
    # ================================================================== #
    def open(self, url: str = "", headless: bool | None = None) -> dict:
        """Abre o navegador (se preciso) e navega para `url`."""
        if headless is not None:
            self.headless = bool(headless)

        def run():
            self._ensure_browser()
            self._last_error = ""
            if url:
                self._goto(self._page, url)
            else:
                self._sync_state(self._page)
            data = self._snapshot_raw(self._page)
            return {
                "ok": True,
                "url": data["url"],
                "titulo": data["title"],
                "engine": self._engine,
                "visivel": not self.headless,
                "resumo": self._render_snapshot(data, self.snapshot_chars),
            }
        return self._call(run, timeout=120)

    def login_google(self, timeout_s: int = 240) -> dict:
        """Abre o Google visível e espera o login; salva cookies + perfil."""
        timeout_s = max(30, min(int(timeout_s), 600))
        self.google_em = time.time()
        self.google_logado = False

        def run():
            self.headless = False
            self._ensure_browser()
            self._goto(self._page, "https://accounts.google.com")
            inicio = time.time()
            while time.time() - inicio < timeout_s:
                time.sleep(2)
                try:
                    url = self._page.url or ""
                    cookies = {c.get("name") for c in self._ctx.cookies()}
                except Exception:
                    break
                if ("accounts.google.com" not in url
                        and ({"SID", "HSID", "SSID"} & cookies)):
                    self.google_logado = True
                    break
            pasta = ROOT / "data" / "browser_state"
            pasta.mkdir(parents=True, exist_ok=True)
            destino = pasta / "google.json"
            try:
                self._ctx.storage_state(path=str(destino))
                salvo = str(destino)
            except Exception:
                salvo = ""
            if not self.google_logado:
                return {"ok": False, "erro": "login não concluído no tempo",
                        "url": self._page.url, "visivel": True}
            return {"ok": True, "url": self._page.url, "visivel": True,
                    "perfil": str(self.profile_dir), "estado": salvo,
                    "cookies": len(self._ctx.cookies())}
        return self._call(run, timeout=timeout_s + 20)

    def google_status(self) -> dict:
        pasta = ROOT / "data" / "browser_state"
        estado = pasta / "google.json"
        return {"logado": bool(getattr(self, "google_logado", False)),
                "desde": getattr(self, "google_em", 0),
                "perfil": str(getattr(self, "profile_dir", "")),
                "estado_salvo": estado.exists(),
                "estado_kb": round(estado.stat().st_size / 1024, 1)
                if estado.exists() else 0}

    def goto(self, url: str) -> dict:
        def run():
            self._ensure_browser()
            self._last_error = ""
            self._goto(self._page, url)
            self._capture_shot_async()
            data = self._snapshot_raw(self._page)
            return {
                "ok": True,
                "url": data["url"],
                "titulo": data["title"],
                "resumo": self._render_snapshot(data, self.snapshot_chars),
            }
        return self._call(run, timeout=120)

    def snapshot(self) -> dict:
        def run():
            self._ensure_browser()
            data = self._snapshot_raw(self._page)
            return {
                "ok": True,
                "url": data["url"],
                "titulo": data["title"],
                "elementos_total": data["total"],
                "resumo": self._render_snapshot(data, self.snapshot_chars),
            }
        return self._call(run, timeout=90)

    def click(self, target: str, timeout_ms: int | None = None) -> dict:
        timeout = int(timeout_ms or self.timeout_ms)

        def run():
            self._ensure_browser()
            self._last_error = ""
            loc = self._locator(self._page, target)
            try:
                loc.scroll_into_view_if_needed(timeout=timeout)
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            self._clique_visual(loc, timeout)
            try:
                self._page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            data = self._snapshot_raw(self._page)
            return {
                "ok": True,
                "clicou": str(target),
                "url": data["url"],
                "titulo": data["title"],
                "resumo": self._render_snapshot(data, self.snapshot_chars),
            }
        return self._call(run, timeout=120)

    def fill(self, target: str, value: str, submit: bool = False) -> dict:
        def run():
            self._ensure_browser()
            self._last_error = ""
            loc = self._locator(self._page, target)
            info = loc.evaluate(
                "el => ({tag: el.tagName.toLowerCase(), "
                "type: (el.getAttribute('type')||'').toLowerCase()})")
            tag, tipo = info.get("tag", ""), info.get("type", "")
            if tag == "select":
                loc.select_option(value=value)
            elif tipo in ("checkbox", "radio"):
                marcado = str(value).strip().lower() in ("1", "true", "sim", "on",
                                                         "yes", "marcar")
                loc.set_checked(marcado)
            else:
                self._preenchimento_visual(loc, str(value))
            if submit:
                try:
                    loc.press("Enter")
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
                try:
                    self._page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            data = self._snapshot_raw(self._page)
            return {
                "ok": True,
                "preencheu": str(target),
                "url": data["url"],
                "resumo": self._render_snapshot(data, self.snapshot_chars),
            }
        return self._call(run, timeout=120)

    def press(self, key: str, target: str = "") -> dict:
        def run():
            self._ensure_browser()
            if target:
                self._locator(self._page, target).focus()
            self._page.keyboard.press(key)
            try:
                self._page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            data = self._snapshot_raw(self._page)
            return {"ok": True, "tecla": key, "url": data["url"],
                    "resumo": self._render_snapshot(data, self.snapshot_chars)}
        return self._call(run, timeout=120)

    def scroll(self, direction: str = "baixo", times: int = 1) -> dict:
        dy = {"baixo": 650, "cima": -650, "topo": -100000, "fim": 100000}
        passo = dy.get(str(direction or "baixo").lower(), 650)
        vezes = max(1, min(int(times or 1), 10))

        def run():
            self._ensure_browser()
            for _ in range(vezes):
                self._page.mouse.wheel(0, passo)
                self._page.wait_for_timeout(180)
            data = self._snapshot_raw(self._page)
            return {"ok": True, "direcao": direction, "vezes": vezes,
                    "url": data["url"],
                    "resumo": self._render_snapshot(data, self.snapshot_chars)}
        return self._call(run, timeout=90)

    def wait(self, seconds: float = 2, selector: str = "") -> dict:
        secs = max(0.0, min(float(seconds or 0), 60.0))

        def run():
            self._ensure_browser()
            if selector:
                self._page.wait_for_selector(selector, timeout=int(secs * 1000)
                                             or self.timeout_ms)
            else:
                self._page.wait_for_timeout(int(secs * 1000))
            data = self._snapshot_raw(self._page)
            return {"ok": True, "esperou": secs, "url": data["url"],
                    "resumo": self._render_snapshot(data, self.snapshot_chars)}
        return self._call(run, timeout=max(60, secs + 30))

    def extract(self, selector: str = "", max_chars: int = 6000) -> dict:
        limite = max(500, min(int(max_chars or 6000), 30000))

        def run():
            self._ensure_browser()
            page = self._page
            if selector:
                loc = page.locator(selector).first
                texto = loc.inner_text(timeout=self.timeout_ms)
            else:
                texto = page.evaluate(
                    "() => document.body ? document.body.innerText : ''")
            texto = re.sub(r"[ \t]+\n", "\n", texto or "").strip()
            links = page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                     .slice(0, 60)
                     .map(a => ({texto: (a.innerText||'').replace(/\\s+/g,' ').trim().slice(0,80),
                                 url: String(a.href).slice(0,200)}))
                     .filter(l => l.texto)""")
            return {"ok": True, "url": page.url, "texto": texto[:limite],
                    "truncado": len(texto) > limite, "links": links[:40]}
        return self._call(run, timeout=90)

    def screenshot(self, full_page: bool = False, path: str | None = None) -> dict:
        def run():
            self._ensure_browser()
            self.shot_dir.mkdir(parents=True, exist_ok=True)
            alvo = Path(path) if path else (
                self.shot_dir / f"navegador_{time.strftime('%Y%m%d_%H%M%S')}.png")
            alvo.parent.mkdir(parents=True, exist_ok=True)
            self._page.screenshot(path=str(alvo), full_page=bool(full_page))
            self._sync_state(self._page)
            return {"ok": True, "arquivo": str(alvo.resolve()),
                    "url": self._url, "titulo": self._title,
                    "bytes": alvo.stat().st_size}
        return self._call(run, timeout=90)

    def live_frame(self) -> bytes:
        """Frame JPEG leve para o painel ao vivo da interface."""
        def run():
            self._ensure_browser()
            return self._page.screenshot(type="jpeg", quality=55,
                                         timeout=self.timeout_ms)
        return self._call(run, timeout=60)

    def tabs(self) -> dict:
        def run():
            self._ensure_browser()
            itens = []
            for idx, p in enumerate(self._ctx.pages):
                itens.append({"indice": idx,
                              "url": p.url,
                              "titulo": (p.title() if not p.is_closed() else ""),
                              "ativa": p is self._page})
            return {"ok": True, "abas": itens}
        return self._call(run, timeout=60)

    def switch_tab(self, index: int = 0) -> dict:
        def run():
            self._ensure_browser()
            pages = self._ctx.pages
            idx = int(index)
            if idx < 0 or idx >= len(pages):
                raise ValueError(f"aba {idx} não existe (há {len(pages)})")
            self._page = pages[idx]
            try:
                self._page.bring_to_front()
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            data = self._snapshot_raw(self._page)
            return {"ok": True, "aba": idx, "url": data["url"],
                    "resumo": self._render_snapshot(data, self.snapshot_chars)}
        return self._call(run, timeout=90)

    def new_tab(self, url: str = "") -> dict:
        def run():
            self._ensure_browser()
            self._page = self._ctx.new_page()
            if url:
                self._goto(self._page, url)
            # nova aba entra no grupo da tarefa atual
            self._seq_aba += 1
            chave = f"{self._aba_atual}#{self._seq_aba}"
            self._abas[chave] = self._page
            self._aba_grupo[chave] = self._grupo_atual
            self._grupos.setdefault(self._grupo_atual, []).append(chave)
            self._aba_atual = self._aba_nome = chave
            data = self._snapshot_raw(self._page)
            return {"ok": True, "aba": chave, "grupo": self._grupo_atual,
                    "url": data["url"],
                    "resumo": self._render_snapshot(data, self.snapshot_chars)}
        return self._call(run, timeout=120)

    def close_tab(self, index: int = -1) -> dict:
        def run():
            self._ensure_browser()
            pages = self._ctx.pages
            idx = int(index)
            if idx < 0:
                idx = len(pages) + idx
            if idx < 0 or idx >= len(pages):
                raise ValueError(f"aba {index} não existe (há {len(pages)})")
            pages[idx].close()
            pages = self._ctx.pages
            self._page = pages[-1] if pages else self._ctx.new_page()
            return {"ok": True, "abas_restantes": len(self._ctx.pages)}
        return self._call(run, timeout=60)

    def search(self, term: str) -> dict:
        term = (term or "").strip()
        if not term:
            raise ValueError("termo de busca vazio")
        def run():
            self._ensure_browser()
            self._goto(self._page,
                       "https://lite.duckduckgo.com/lite/?q="
                       + term.replace(" ", "+"))
            data = self._snapshot_raw(self._page)
            return {"ok": True, "termo": term, "url": data["url"],
                    "resumo": self._render_snapshot(data, self.snapshot_chars)}
        return self._call(run, timeout=120)

    def close(self) -> dict:
        def run():
            self._close_browser()
            with self._state_lock:
                self._url = self._title = ""
            return {"ok": True, "fechado": True}
        return self._call(run, timeout=60)

    def set_mode(self, headless: bool) -> dict:
        """Troca entre janela visível e invisível (reinicia o navegador)."""
        def run():
            self.headless = bool(headless)
            self._close_browser()
            self._ensure_browser()
            data = self._snapshot_raw(self._page)
            return {"ok": True, "visivel": not self.headless,
                    "engine": self._engine, "url": data["url"],
                    "titulo": data["title"]}
        return self._call(run, timeout=120)

    def shutdown(self) -> None:
        """Encerra a thread e o navegador (usado ao sair do servidor)."""
        try:
            if self._thread and self._thread.is_alive():
                self._q.put(None)
                self._thread.join(timeout=8)
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

    # ================================================================== #
    # Estado para a interface
    # ================================================================== #
    def status(self) -> dict:
        with self._state_lock:
            aberto = self._ctx is not None
            return {
                "aberto": aberto,
                "url": self._url,
                "titulo": self._title,
                "engine": self._engine or self.channel,
                "motor": self.rotulo,
                "modo": self.mode,
                "aba": self._aba_nome,
                "visivel": not self.headless,
                "perfil": str(self.profile_dir),
                "ultimo_erro": self._last_error,
                "ultima_acao": self._last_seen,
            }

    def is_open(self) -> bool:
        with self._state_lock:
            return self._ctx is not None

    def describe(self) -> str:
        st = self.status()
        if not st["aberto"]:
            return "navegador fechado"
        return f"navegador aberto em {st['url'] or '(vazio)'}"

    # Mantido por compatibilidade com chamadas antigas.
    def _capture_shot_async(self) -> None:
        pass
