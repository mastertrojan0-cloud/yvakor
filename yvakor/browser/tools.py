"""
YVAKOR — Ferramentas de navegador (Edge + Chrome)

Cada ferramenta aceita `navegador` ("edge" ou "chrome"). Sem o parâmetro, usa o
motor do contexto atual (uma tarefa cowork pode fixar o seu) e, na falta dele,
o motor padrão do settings.

O isolamento é por aba: cada tarefa cowork recebe a própria aba no motor
escolhido, então duas tarefas não disputam a mesma página.
"""
from __future__ import annotations

from yvakor.browser import contexto
from yvakor.browser.manager import Navegadores


def _safe(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def _motor(nav: Navegadores, nome: str | None) -> str:
    return nav.motor(nome or contexto.motor_atual())


def _exec(nav: Navegadores, nome: str | None, acao):
    """Seleciona a aba do contexto e executa a ação de forma atômica."""
    sess = nav.sessao(_motor(nav, nome))
    with sess.trilho:
        sess.selecionar_aba(contexto.aba_atual())
        return acao(sess)


def register_browser_tools(registry, nav: Navegadores) -> list[str]:
    reg = registry.register

    # ------------------------------------------------------------------ #
    def abrir(url: str = "", navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.open(url)))

    def ir(url: str, navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.goto(url)))

    def ver(navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.snapshot()))

    def clicar(alvo: str, navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.click(alvo)))

    def preencher(alvo: str, valor: str, enviar: bool = False,
                  navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador,
                                   lambda s: s.fill(alvo, valor, enviar)))

    def pressionar(tecla: str, alvo: str = "", navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.press(tecla, alvo)))

    def rolar(direcao: str = "baixo", vezes: int = 1,
              navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.scroll(direcao, vezes)))

    def esperar(segundos: float = 2, seletor: str = "",
                navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.wait(segundos, seletor)))

    def extrair(seletor: str = "", max_chars: int = 6000,
                navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador,
                                   lambda s: s.extract(seletor, max_chars)))

    def captura(pagina_inteira: bool = False, navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador,
                                   lambda s: s.screenshot(pagina_inteira)))

    def pesquisar(termo: str, navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.search(termo)))

    def abas(navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.tabs()))

    def nova_aba(url: str = "", navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.new_tab(url)))

    def trocar_aba(indice: int = 0, navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.switch_tab(indice)))

    def fechar_aba(indice: int = -1, navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.close_tab(indice)))

    def fechar(navegador: str = "") -> dict:
        return _safe(lambda: _exec(nav, navegador, lambda s: s.close()))

    def grupos(acao: str = "listar", nome: str = "",
               navegador: str = "") -> dict:
        def acao_fn(s):
            grupo = nome or contexto.aba_atual()
            if acao == "fechar":
                return s.fechar_grupo(grupo)
            if acao == "focar":
                return s.focar_grupo(grupo)
            return s.grupos()
        return _safe(lambda: _exec(nav, navegador, acao_fn))

    def motores() -> dict:
        est = nav.status()
        return {"ok": True, "padrao": est["padrao"], "motores": est["motores"],
                "resumo": nav.resumo()}

    def conectar(navegador: str = "chrome", url_cdp: str = "") -> dict:
        return _safe(lambda: nav.conectar_cdp(navegador, url_cdp or None))

    # ------------------------------------------------------------------ #
    reg("navegador_abrir", abrir,
        "Abre o navegador (edge ou chrome) e navega; sem URL só abre.",
        {"url": "str?", "navegador": "str?"})
    reg("navegador_ir", ir,
        "Navega a aba atual para outra URL.",
        {"url": "str", "navegador": "str?"})
    reg("navegador_ver", ver,
        "Vê a página atual: URL, título, texto e elementos com refs (e1, e2…).",
        {"navegador": "str?"})
    reg("navegador_clicar", clicar,
        "Clica num elemento (ref do último navegador_ver, CSS ou texto).",
        {"alvo": "str", "navegador": "str?"})
    reg("navegador_preencher", preencher,
        "Preenche campo/checkbox/select; enviar=True pressiona Enter.",
        {"alvo": "str", "valor": "str", "enviar": "bool?", "navegador": "str?"})
    reg("navegador_pressionar", pressionar,
        "Pressiona uma tecla (Enter, Escape, Tab, Control+A…).",
        {"tecla": "str", "alvo": "str?", "navegador": "str?"})
    reg("navegador_rolar", rolar,
        "Rola a página: baixo|cima|topo|fim.",
        {"direcao": "str?", "vezes": "int?", "navegador": "str?"})
    reg("navegador_esperar", esperar,
        "Espera N segundos ou até um seletor aparecer.",
        {"segundos": "float?", "seletor": "str?", "navegador": "str?"})
    reg("navegador_extrair", extrair,
        "Extrai texto de um seletor (ou da página) + links.",
        {"seletor": "str?", "max_chars": "int?", "navegador": "str?"})
    reg("navegador_captura", captura,
        "Print da página em data/browser_shots.",
        {"pagina_inteira": "bool?", "navegador": "str?"})
    reg("navegador_pesquisar", pesquisar,
        "Pesquisa no DuckDuckGo pelo navegador.",
        {"termo": "str", "navegador": "str?"})
    reg("navegador_abas", abas,
        "Lista abas abertas (índice, URL, título, ativa).", {"navegador": "str?"})
    reg("navegador_nova_aba", nova_aba,
        "Abre nova aba (opcionalmente numa URL).",
        {"url": "str?", "navegador": "str?"})
    reg("navegador_trocar_aba", trocar_aba,
        "Passa o controle para a aba do índice.", {"indice": "int?",
                                                  "navegador": "str?"})
    reg("navegador_fechar_aba", fechar_aba,
        "Fecha uma aba (-1 = atual).", {"indice": "int?", "navegador": "str?"})
    reg("navegador_fechar", fechar,
        "Fecha o motor escolhido e libera memória.", {"navegador": "str?"})
    reg("navegador_grupo", grupos,
        "Grupo de abas da tarefa: acao=listar|focar|fechar (nome opcional; "
        "padrão = tarefa atual).",
        {"acao": "str?", "nome": "str?", "navegador": "str?"})
    reg("navegador_motores", motores,
        "Mostra Edge e Chrome: modo, perfil, se está aberto e em que URL.",
        {})
    reg("navegador_conectar", conectar,
        "Anexa a um navegador já aberto com --remote-debugging-port "
        "(ex.: chrome em http://127.0.0.1:9222).",
        {"navegador": "str?", "url_cdp": "str?"})

    def google_login(timeout: int = 240) -> dict:
        sess = nav.sessao(_motor(nav, None))
        return sess.login_google(int(timeout))

    def google_status() -> dict:
        sess = nav.sessao(_motor(nav, None))
        return sess.google_status()

    reg("navegador_google_login", google_login,
        "Abre o Google visível para login e salva a sessão (perfil + cookies).",
        {"timeout": "int?"})
    reg("navegador_google_status", google_status,
        "Mostra se a sessão Google está logada e onde foi salva.", {})

    return [n for n in registry.tools if n.startswith("navegador_")]
