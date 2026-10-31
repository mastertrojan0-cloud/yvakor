"""Organizador de pastas: plano, execução em lote, duplicados, proteções e desfazer."""
import os
import time
from pathlib import Path

import pytest

from yvakor import organizador


def _liberar_tmp(tmp_path, monkeypatch):
    """tmp_path fica em AppData (recusada de verdade); libera só ela."""
    original = organizador._proibida
    monkeypatch.setattr(organizador, "_proibida",
                        lambda p: "" if str(p).startswith(str(tmp_path)) else original(p))
    monkeypatch.setattr(organizador, "DIR_PLANOS", tmp_path / "planos")


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    _liberar_tmp(tmp_path, monkeypatch)
    d = tmp_path / "Downloads"
    d.mkdir()
    antigo = time.time() - 3600
    arquivos = {"relatorio.pdf": b"pdf", "foto.jpg": b"jpg1", "foto_copia.jpg": b"jpg1",
                "setup.exe": b"exe", "dados.csv": b"a,b", "misterio.xyz": b"?",
                "atalho.lnk": b"lnk", "baixando.crdownload": b"..."}
    for nome, conteudo in arquivos.items():
        f = d / nome
        f.write_bytes(conteudo)
        os.utime(f, (antigo, antigo))
    (d / "agora.txt").write_text("recente")          # mexido agora: não toca
    (d / "MinhaPasta").mkdir()                        # pasta do usuário: não toca
    return d


def test_plano_nao_mexe_e_executar_organiza_em_lote(pasta):
    p = organizador.plano(str(pasta))
    assert p["ok"] and p["movimentos"] == 6
    assert (pasta / "relatorio.pdf").exists()        # plano não move nada
    r = organizador.executar(p["plano"])
    assert r["movidos"] == 6 and not r["falhas"]
    assert (pasta / "Documentos" / "relatorio.pdf").exists()
    assert (pasta / "Documentos" / "dados.csv").exists()
    assert (pasta / "Instaladores" / "setup.exe").exists()
    assert (pasta / "Imagens" / "foto.jpg").exists()
    assert (pasta / "_Duplicados" / "foto_copia.jpg").exists()
    assert (pasta / "Outros" / "misterio.xyz").exists()
    for intocado in ("atalho.lnk", "baixando.crdownload", "agora.txt", "MinhaPasta"):
        assert (pasta / intocado).exists()


def test_desfazer_devolve_tudo(pasta):
    antes = sorted(x.name for x in pasta.iterdir())
    pid = organizador.plano(str(pasta))["plano"]
    organizador.executar(pid)
    r = organizador.desfazer(pid)
    assert r["voltaram"] == 6
    assert sorted(x.name for x in pasta.iterdir()) == antes


def test_nao_executa_duas_vezes_nem_arquivo_alterado(pasta):
    pid = organizador.plano(str(pasta))["plano"]
    (pasta / "dados.csv").write_text("conteudo novo maior")
    r = organizador.executar(pid)
    assert any(f["arquivo"] == "dados.csv" for f in r["falhas"])
    assert organizador.executar(pid)["ok"] is False


def test_nome_repetido_no_destino_nao_sobrescreve(pasta):
    (pasta / "Documentos").mkdir()
    (pasta / "Documentos" / "relatorio.pdf").write_bytes(b"outro")
    organizador.executar(organizador.plano(str(pasta))["plano"])
    assert (pasta / "Documentos" / "relatorio (2).pdf").read_bytes() == b"pdf"
    assert (pasta / "Documentos" / "relatorio.pdf").read_bytes() == b"outro"


def test_recusa_pastas_de_sistema_e_raiz_do_perfil():
    for alvo in (os.environ.get("WINDIR", r"C:\Windows"), str(Path.home()),
                 str(Path.home() / "AppData" / "Local")):
        r = organizador.plano(alvo)
        assert r["movimentos"] == 0 and r["recusadas"]


def test_analisar_aponta_duplicados(pasta):
    r = organizador.analisar(str(pasta))
    info = r["pastas"][0]
    assert info["duplicados"]["copias"] == 1
    assert "Documentos" in info["por_tipo"]


def test_modo_data_em_pasta_de_fotos(tmp_path, monkeypatch):
    _liberar_tmp(tmp_path, monkeypatch)
    fotos = tmp_path / "Pictures"
    fotos.mkdir()
    f = fotos / "praia.jpg"
    f.write_bytes(b"x")
    t = time.mktime((2024, 5, 1, 12, 0, 0, 0, 0, -1))
    os.utime(f, (t, t))
    organizador.executar(organizador.plano(str(fotos))["plano"])
    assert (fotos / "2024" / "praia.jpg").exists()


def test_limpar_temporarios_apaga_antigos_com_progresso(tmp_path, monkeypatch):
    temp = tmp_path / "Temp"
    (temp / "pasta_velha").mkdir(parents=True)
    velho = time.time() - 5 * 86400
    for f in (temp / "a.tmp", temp / "pasta_velha" / "b.log"):
        f.write_bytes(b"x" * 1000)
        os.utime(f, (velho, velho))
    os.utime(temp / "pasta_velha", (velho, velho))
    (temp / "novo.tmp").write_bytes(b"recente")
    monkeypatch.setenv("TEMP", str(temp))
    passos = []
    organizador.definir_progresso(passos.append)
    try:
        r = organizador.limpar_temporarios(dias=2)
    finally:
        organizador.definir_progresso(None)
    assert r["arquivos_apagados"] == 2 and r["itens_restantes"] == 0
    assert not (temp / "a.tmp").exists() and not (temp / "pasta_velha").exists()
    assert (temp / "novo.tmp").exists()
    assert passos and "liberados" in passos[-1]


def test_limpar_temporarios_respeita_limite_de_tempo(tmp_path, monkeypatch):
    temp = tmp_path / "Temp"
    temp.mkdir()
    velho = time.time() - 5 * 86400
    for i in range(5):
        f = temp / f"{i}.tmp"
        f.write_bytes(b"x")
        os.utime(f, (velho, velho))
    monkeypatch.setenv("TEMP", str(temp))
    r = organizador.limpar_temporarios(dias=2, limite_s=0)
    assert r["itens_restantes"] == 5 and "de novo" in r["obs"]
