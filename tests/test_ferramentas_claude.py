"""Ferramentas no estilo do Claude: pensar, tarefas_checklist, arquivos_grep,
web_ler (yvakor/ferramentas_claude.py)."""
import http.server
import threading

from yvakor import ferramentas_claude as fc


def test_pensar_nao_age_e_exige_texto():
    assert fc.pensar("o campo CPF é e3; preencher antes da data")["ok"]
    assert not fc.pensar("")["ok"]


def test_checklist_aceita_json_lista_repr_e_linhas():
    r = fc.tarefas_checklist('[{"texto":"pesquisar","estado":"done"},'
                             '{"texto":"comparar","status":"in_progress"},'
                             '{"texto":"salvar"}]')
    assert r["ok"] and r["progresso"] == "1/3"
    assert [i["estado"] for i in fc.checklist_atual()] == ["feito", "fazendo", "pendente"]
    # modo nativo: o registry converte a lista em str(lista) (repr Python)
    r = fc.tarefas_checklist(str([{"texto": "a", "estado": "feito"}]))
    assert r["progresso"] == "1/1"
    r = fc.tarefas_checklist("[x] abrir site\n- extrair preço")
    assert r["progresso"] == "1/2"
    assert fc.resumo_checklist('[{"texto":"ler","estado":"fazendo"}]') == "☑ Checklist 0/1: ler"
    assert not fc.tarefas_checklist("")["ok"]
    fc.limpar_checklist()
    assert fc.checklist_atual() == []


def test_grep_acha_conteudo_com_linha_e_filtro(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ndef alvo():\n    return 2\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("Alvo no texto\n", encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\0\0alvo")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "c.py").write_text("def alvo(): pass", encoding="utf-8")
    r = fc.arquivos_grep("alvo", str(tmp_path), arquivos="*.py", contexto=1)
    assert r["ok"] and len(r["ocorrencias"]) == 1
    oc = r["ocorrencias"][0]
    assert oc["linha"] == 2 and oc["arquivo"].endswith("a.py") and "x = 1" in oc["contexto"]
    r = fc.arquivos_grep("alvo", str(tmp_path), ignorar_maiusculas=True)
    assert r["arquivos_com_ocorrencia"] == 2          # a.py e b.md; binário e node_modules fora
    # o modelo real escreveu caminho= em vez de raiz=
    assert fc.arquivos_grep("alvo", caminho=str(tmp_path / "a.py"))["arquivos_com_ocorrencia"] == 1
    assert not fc.arquivos_grep("(", str(tmp_path))["ok"]
    assert not fc.arquivos_grep("", str(tmp_path))["ok"]


_PAGINA = """<html><head><title>Docs YVAKOR</title><style>.x{}</style>
<script>var lixo = 1;</script></head><body><nav>menu menu</nav>
<h1>Instalação</h1><p>Rode o <b>instalador</b> e depois
o app.</p><ul><li>Passo um</li><li>Passo dois</li></ul>
<a href="/guia">Guia completo</a><table><tr><td>A</td><td>B</td></tr></table>
<footer>rodapé</footer></body></html>"""


def _servidor():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            corpo = _PAGINA.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_web_ler_devolve_markdown_limpo_e_pagina():
    srv = _servidor()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/docs"
        r = fc.web_ler(url)
        assert r["ok"] and r["titulo"] == "Docs YVAKOR"
        t = r["texto"]
        assert "# Instalação" in t and "Rode o instalador e depois o app." in t
        assert "- Passo um" in t and "- Passo dois" in t
        assert "lixo" not in t and "menu" not in t and "rodapé" not in t
        assert any(l.endswith("/guia") and l.startswith("Guia completo") for l in r["links"])
        r2 = fc.web_ler(url, inicio=10, max_chars=500)
        assert r2["texto"] == t[10:510]
    finally:
        srv.shutdown()
    assert not fc.web_ler("ftp://x")["ok"]


def test_web_ler_prefere_o_conteudo_principal():
    """Wikipédia: lista de idiomas e menus vêm antes do artigo, fora de <nav>."""
    idiomas = "".join(f"<li><a href='/{i}'>Idioma {i}</a></li>" for i in range(80))
    artigo = "<p>" + "Manaus é a capital do Amazonas. " * 20 + "</p>"
    html = (f"<html><body><div class='menu'><ul>{idiomas}</ul></div>"
            f"<div id='mw-content-text'><div><h2>História</h2>{artigo}</div></div>"
            "</body></html>")
    leitor = fc._Leitor("https://x/")
    leitor.feed(html)
    texto = leitor.markdown()
    assert texto.startswith("## História") and "Idioma" not in texto
    # <main> que contém idiomas E o artigo: vence a região mais específica
    leitor = fc._Leitor("https://x/")
    leitor.feed(f"<main id='content'><ul>{idiomas}</ul>"
                f"<div id='mw-content-text'>{artigo}</div></main>")
    assert "Idioma" not in leitor.markdown()


def test_chamada_repetida_na_mesma_resposta_roda_uma_vez():
    """O DeepSeek escreveu o mesmo JSON duas vezes: a ação rodava em dobro."""
    from yvakor.agent import _parse_acoes
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry(load_settings())
    fc.register_ferramentas_claude(reg)
    um = '{"acao":"usar_ferramenta","ferramenta":"arquivos_grep","args":{"padrao":"x"}}'
    outro = '{"acao":"usar_ferramenta","ferramenta":"arquivos_grep","args":{"padrao":"y"}}'
    assert len(_parse_acoes(um + "\n\n" + um, reg)) == 1
    assert len(_parse_acoes(um + "\n" + outro, reg)) == 2


def test_registro_e_roteador():
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    from yvakor.tools.router import selecionar
    reg = ToolRegistry(load_settings())
    assert fc.register_ferramentas_claude(reg) == [
        "pensar", "perguntar_usuario", "tarefas_checklist", "arquivos_grep",
        "web_ler"]
    reg.register("arquivos_ler", lambda **k: {}, "Lê.", {"caminho": "str"})
    sel = selecionar(reg, "procure a função main no código do projeto")
    assert "arquivos_grep" in sel and "pensar" in sel
    assert "web_ler" in selecionar(reg, "leia a documentação em https://docs.python.org")


def test_checklist_pendente_entra_na_conferencia_final():
    from yvakor import raciocinio
    fc.tarefas_checklist('[{"texto":"salvar planilha","estado":"pendente"}]')
    try:
        texto = raciocinio.pedido_verificacao(None)
        assert "⬜ salvar planilha" in texto and "não concluídos" in texto
    finally:
        fc.limpar_checklist()
