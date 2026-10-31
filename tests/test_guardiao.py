"""Guardião de rede e vírus: linha de base, alertas, sem alarme falso, não invasivo."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from yvakor import guardiao as gmod


@pytest.fixture
def g(tmp_path, monkeypatch):
    monkeypatch.setattr(gmod, "_ps_json", lambda *a, **k: None)
    gd = gmod.Guardiao({"guardiao": {"notificar": False}}, raiz=tmp_path)
    return gd


def test_codigo_do_guardiao_nao_e_invasivo():
    """Garantia: o guardião só observa. Nada de matar, apagar ou bloquear."""
    fonte = Path(gmod.__file__).read_text(encoding="utf-8")
    proibido = re.compile(r"(\.kill\(|\.terminate\(|\.unlink\(|rmtree|os\.remove|"
                          r"Remove-Item|Stop-Process|taskkill|netsh|New-NetFirewallRule|"
                          r"Set-MpPreference|Remove-MpThreat|winreg\.(SetValue|DeleteValue))",
                          re.I)
    assert not proibido.search(fonte), proibido.findall(fonte)


def test_primeira_rodada_vira_linha_de_base_e_depois_avisa_o_novo(g):
    assert g._novos("inicializacao", {"HKCU\\Run\\OneDrive": "onedrive.exe"}) == {}
    novos = g._novos("inicializacao", {"HKCU\\Run\\OneDrive": "onedrive.exe",
                                       "HKCU\\Run\\x": r"C:\Users\a\AppData\Local\Temp\x.exe"})
    assert list(novos) == ["HKCU\\Run\\x"]


def test_alerta_nao_repete_e_confiar_silencia(g):
    assert g._alerta("medio", "porta:7070:anydesk.exe", "Porta nova") is not None
    assert g._alerta("medio", "porta:7070:anydesk.exe", "Porta nova") is None
    g.confiar("porta:7070:anydesk.exe")
    g.estado["base"]["portas"] = {}
    assert g._novos("portas", {"7070:anydesk.exe": "AnyDesk.exe"}) == {}
    assert g.eventos(1)[0]["chave"] == "porta:7070:anydesk.exe"


def test_hosts_alterado_avisa_com_as_linhas_novas(g, tmp_path, monkeypatch):
    win = tmp_path / "win"
    hosts = win / "System32" / "drivers" / "etc" / "hosts"
    hosts.parent.mkdir(parents=True)
    hosts.write_text("# padrão\n127.0.0.1 localhost\n", encoding="utf-8")
    monkeypatch.setenv("WINDIR", str(win))
    assert g.hosts() == []
    hosts.write_text("127.0.0.1 localhost\n6.6.6.6 www.meubanco.com.br\n", encoding="utf-8")
    alerta = g.hosts()[0]
    assert alerta["nivel"] == "alto" and "meubanco" in alerta["detalhe"]


def test_roteador_trocando_de_mac_avisa(g, monkeypatch):
    if not gmod.sys.platform.startswith("win"):
        pytest.skip("só Windows")
    respostas = iter([{"ip": "192.168.15.1", "mac": "44-89-6D-F2-2A-10"},
                      {"ip": "192.168.15.1", "mac": "44-89-6D-F2-2A-10"},
                      {"ip": "192.168.15.1", "mac": "DE-AD-BE-EF-00-01"}])
    monkeypatch.setattr(gmod, "_ps_json", lambda *a, **k: next(respostas))
    assert g.gateway() == [] and g.gateway() == []
    alerta = g.gateway()[0]
    assert "ARP" in alerta["sugestao"] and "de-ad-be-ef-00-01" in alerta["detalhe"]


def _conexoes(lista):
    return SimpleNamespace(
        net_connections=lambda kind="inet": lista,
        Process=lambda pid: SimpleNamespace(name=lambda: {1: "tailscaled.exe", 2: "evil.exe",
                                                          3: "AnyDesk.exe"}[pid]),
        CONN_LISTEN="LISTEN", CONN_ESTABLISHED="ESTABLISHED", Error=Exception)


def _c(status, porta, pid, remota=None):
    return SimpleNamespace(status=status, pid=pid, laddr=SimpleNamespace(port=porta),
                           raddr=SimpleNamespace(ip="203.0.113.9", port=remota) if remota else None)


def test_portas_sem_alarme_falso_para_porta_sorteada(g, monkeypatch):
    monkeypatch.setattr(gmod, "psutil", _conexoes([_c("LISTEN", 41000, 1)]))
    assert g.portas() == []                                   # linha de base
    monkeypatch.setattr(gmod, "psutil", _conexoes([_c("LISTEN", 52333, 1),     # Tailscale sorteou outra
                                                   _c("LISTEN", 7070, 3)]))    # AnyDesk novo (risco)
    alertas = g.portas()
    assert [a["chave"] for a in alertas] == ["porta:7070:anydesk.exe"]


def test_conexao_para_porta_de_malware_avisa(g, monkeypatch):
    monkeypatch.setattr(gmod, "psutil", _conexoes([_c("ESTABLISHED", 50000, 2, 4444),
                                                   _c("ESTABLISHED", 50001, 1, 443)]))
    alertas = g.conexoes()
    assert len(alertas) == 1 and "evil.exe" in alertas[0]["titulo"]
    assert alertas[0]["nivel"] == "alto"


def test_ferramentas_e_escanear_protegido():
    from yvakor.config import load_settings
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry(load_settings())
    nomes = gmod.register_guardiao_tools(reg, gmod.Guardiao({}, raiz=Path(".")))
    assert {"guardiao_status", "guardiao_escanear"} <= set(nomes)
    assert reg.guard.requires_confirmation("guardiao_escanear")
    assert not reg.guard.requires_confirmation("guardiao_status")
