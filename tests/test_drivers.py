"""Drivers: verificação e atualização (sistema simulado — nada toca no Windows)."""
import json

import pytest

from yvakor import drivers

PCI = r"PCI\X"
VIRTUAL = r"ROOT\SYNTH3DVSP\0000"
AUDIO = r"HDAUDIO\Y"


@pytest.fixture
def sistema(tmp_path, monkeypatch):
    monkeypatch.setattr(drivers, "DIR_TRABALHO", tmp_path)
    estado = {"pendentes": [], "problemas": [], "elevados": [], "uac": True}

    def ps(comando, timeout):
        if "Microsoft.Update.Session" in comando:
            return estado["pendentes"]
        if "Get-PnpDevice" in comando:
            return estado["problemas"]
        return []

    def elevado(script, nome, esperar_s):
        estado["elevados"].append((nome, script))
        saida = tmp_path / f"{nome}.json"
        if estado["uac"] and esperar_s:
            saida.write_text(json.dumps({"reparados": [{"id": PCI, "saida": "ok"}]}),
                             encoding="utf-8")
        return saida, None

    monkeypatch.setattr(drivers, "_ps", ps)
    monkeypatch.setattr(drivers, "_elevado", elevado)
    monkeypatch.setattr(drivers, "_vigiar", lambda saida: None)
    return estado


def test_auto_sem_nada_pendente_nao_pede_uac(sistema):
    sistema["problemas"] = [{"FriendlyName": "Microsoft RemoteFX Synth3D VSP Driver",
                             "Status": "Degraded", "InstanceId": VIRTUAL}]
    r = drivers.atualizar("auto")
    assert r["windows_update"] == "nenhuma atualização de driver pendente"
    assert "virtual" in r["virtuais_ignorados"][0]
    assert sistema["elevados"] == []


def test_auto_reinstala_aparelho_fisico_com_uac(sistema):
    sistema["problemas"] = [{"FriendlyName": "Placa de rede", "Status": "Error",
                             "InstanceId": PCI}]
    r = drivers.atualizar("auto")
    assert sistema["elevados"][0][0] == "reparar"
    assert f"'{PCI}'" in sistema["elevados"][0][1]
    assert r["reparar"]["reparados"][0]["id"] == PCI


def test_uac_recusado_vira_erro_claro(sistema):
    sistema["uac"] = False
    sistema["problemas"] = [{"FriendlyName": "Som", "Status": "Error", "InstanceId": AUDIO}]
    assert "UAC" in drivers.atualizar("reparar")["reparar"]["erro"]


def test_windows_update_pendente_instala_em_segundo_plano(sistema):
    sistema["pendentes"] = [{"Titulo": "Intel - Display - 10.18.10.5200", "Data": "2024-01-01"}]
    r = drivers.atualizar("windows_update")
    assert sistema["elevados"][0][0] == "windows_update"
    assert r["windows_update"]["iniciado"] == ["Intel - Display - 10.18.10.5200"]
    assert "status" in r["windows_update"]["acompanhar"]


def test_acao_invalida(sistema):
    assert drivers.atualizar("formatar")["ok"] is False


def test_nome_trocado_sistema_drivers_com_acao_atualiza(sistema):
    """Exame de 29/10: sistema_drivers(acao="atualizar") só verificava de novo."""
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry({"tools": {"guarded_actions": []}})
    drivers.register_drivers_tools(reg)
    r = reg.run("sistema_drivers", acao="atualizar")
    assert r.get("ok") and "windows_update" in str(r)
