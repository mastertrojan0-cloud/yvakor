"""App e extensão abrem numa conversa nova; as anteriores ficam no histórico,
com busca pelo conteúdo para retomar."""
from __future__ import annotations

from pathlib import Path

from yvakor.memory.episodic import EpisodicMemory

RAIZ = Path(__file__).resolve().parent.parent
EXT = RAIZ / "chrome-extension"


def test_abrir_cria_conversa_nova_e_reaproveita_a_vazia(tmp_path):
    m = EpisodicMemory(tmp_path / "m.db")
    antiga = m.active_id
    m.log("conversa", "consulta de eleicoes", "Resultado do TSE…", session_id=antiga)

    nova = m.conversa_nova_ao_abrir()
    assert nova != antiga and m.active_id == nova
    # abrir de novo (ex.: painel fechado e reaberto) sem escrever nada: mesma conversa
    assert m.conversa_nova_ao_abrir() == nova
    assert len(m.listar_conversas()) == 2
    # a antiga continua no histórico, intacta
    assert [x["content"] for x in m.mensagens_da_conversa(antiga)][0] == "consulta de eleicoes"


def test_busca_acha_conversa_pelo_conteudo_e_mostra_o_trecho(tmp_path):
    m = EpisodicMemory(tmp_path / "m.db")
    a = m.active_id
    m.log("conversa", "procura passagens manaus boa vista", "Azul R$ 1.013 direto", session_id=a)
    b = m.conversa_nova_ao_abrir()
    m.log("conversa", "analise do btc", "Veredito levemente baixista", session_id=b)

    achadas = m.buscar_conversas("boa vista")
    assert [s["id"] for s in achadas] == [a]
    assert "boa vista" in achadas[0]["trecho"]
    assert [s["id"] for s in m.buscar_conversas("baixista")] == [b]   # na resposta
    assert m.buscar_conversas("xyz-nada") == []
    assert len(m.buscar_conversas("")) == 2


def test_titulo_automatico_vai_para_a_conversa_da_mensagem(tmp_path):
    """App e extensão em conversas diferentes: um não renomeia a do outro."""
    m = EpisodicMemory(tmp_path / "m.db")
    do_app = m.active_id
    m.log("conversa", "segunda via do cpf", "ok", session_id=do_app)
    da_ext = m.conversa_nova_ao_abrir()           # extensão abriu (virou a ativa)
    assert da_ext != do_app
    m.maybe_autotitle("segunda via do cpf", session_id=do_app)
    titulos = {s["id"]: s["title"] for s in m.listar_conversas()}
    assert titulos[do_app] == "segunda via do cpf"
    assert titulos[da_ext] != "segunda via do cpf"


def test_rotas_do_servidor_e_interfaces_ligadas():
    srv = (RAIZ / "yvakor" / "server.py").read_text(encoding="utf-8")
    assert '"/api/sessions/buscar"' in srv and 'data.get("ao_abrir")' in srv
    desk = (RAIZ / "yvakor" / "desktop.py").read_text(encoding="utf-8")
    assert 'nova="--retomar" not in sys.argv' in desk
    assert "nova_conversa(ao_abrir=True)" in desk and "/api/sessions/buscar?q=" in desk
    js = (EXT / "sidepanel.js").read_text(encoding="utf-8")
    assert "novaSessao(true)" in js and "retomarConversa" in js
    assert "/api/sessions/buscar?q=" in js
    html = (EXT / "sidepanel.html").read_text(encoding="utf-8")
    assert 'id="historico"' in html and 'id="hist-busca"' in html
