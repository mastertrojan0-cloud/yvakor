"""Motor de entorno: aprendizado incremental, anomalia, novidade e orçamento."""
import json
import time

from yvakor.entorno.motor import MotorEntorno, register_entorno_tools
from yvakor.entorno.perfil import Perfil
from yvakor.entorno import sensores
from yvakor.tools.registry import ToolRegistry


def _motor(tmp_path, **cfg):
    base = {"sensores": {"conexoes": False, "processos": False}, "notificar": False}
    base.update(cfg)
    return MotorEntorno({"entorno": base}, raiz=tmp_path)


def test_perfil_aprende_e_mede_desvio(tmp_path):
    p = Perfil(tmp_path / "e.db")
    for v in [10, 11, 9, 10, 12, 10, 9, 11, 10, 10]:
        p.observar("pc.cpu", v)
    media, desvio, n = p.esperado("pc.cpu")
    assert 9 < media < 12 and n >= 8
    assert abs(p.observar("pc.cpu", 10)) < 2
    assert p.observar("pc.cpu", 95) > 3.5


def test_perfil_persiste_no_flush(tmp_path):
    p = Perfil(tmp_path / "e.db")
    for _ in range(10):
        p.observar("rede.upload_kbs", 5)
    p.item("app", "code.exe", 30)
    p.fechar()
    q = Perfil(tmp_path / "e.db")
    assert q.esperado("rede.upload_kbs") is not None
    assert q.itens("app")[0]["nome"] == "code.exe"


def test_anomalia_so_depois_do_aquecimento(tmp_path):
    m = _motor(tmp_path, aquecimento_horas=24)
    for _ in range(20):
        m.aprender([("m", "pc.cpu", 10.0)])
    m.aprender([("m", "pc.cpu", 99.0)])
    assert m.perfil.eventos(tipo="anomalia") == []
    m.inicio = time.time() - 25 * 3600
    for _ in range(20):
        m.aprender([("m", "pc.cpu", 10.0)])
    m.aprender([("m", "pc.cpu", 99.0)])
    ev = m.perfil.eventos(tipo="anomalia")
    assert ev and ev[0]["chave"] == "pc.cpu"


def test_novidade_de_processo(tmp_path):
    m = _motor(tmp_path, aquecimento_horas=0)
    m.aprender([("i", "processo", "explorer.exe", 1.0, "")])   # 1º do tipo: base
    m.aprender([("i", "processo", "explorer.exe", 1.0, "")])
    assert m.perfil.eventos(tipo="novidade") == []
    m.aprender([("i", "processo", "estranho.exe", 1.0, "")])
    assert m.perfil.eventos(tipo="novidade")[0]["chave"] == "processo:estranho.exe"


def test_sensor_caro_tem_intervalo_dobrado(tmp_path):
    m = _motor(tmp_path, orcamento_ms=1)

    class Lento(sensores.Sensor):
        nome, intervalo, essencial = "lento", 10, True

        def ler(self):
            time.sleep(0.01)
            return []

    m.sensores = [Lento({})]
    m._estado = {"lento": {"proxima": 0.0, "fator": 1, "custo_ms": 0.0,
                           "execucoes": 0, "pulos": 0, "erro": ""}}
    m.ciclo(agora=1000.0)
    assert m._estado["lento"]["fator"] == 2
    assert m._estado["lento"]["proxima"] == 1020.0


def test_historico_nao_e_relido_ao_reiniciar(tmp_path):
    (tmp_path / "data").mkdir()
    linha = {"ts": "2026-10-28T17:57:08", "passos": [{"nome": "gerar_imagem", "ok": True}],
             "falhas": 0}
    (tmp_path / "data" / "rastros.jsonl").write_text(json.dumps(linha) + "\n",
                                                     encoding="utf-8")
    m = _motor(tmp_path)
    m.importar_historico()
    assert m.perfil.itens("ferramenta")[0]["contagem"] == 1
    m.perfil.fechar()
    m2 = _motor(tmp_path)
    m2.ciclo()
    assert m2.perfil.itens("ferramenta")[0]["contagem"] == 1


def test_bloco_prompt_so_quando_relevante(tmp_path):
    m = _motor(tmp_path)
    for _ in range(10):
        m.aprender([("m", "pc.cpu", 20.0), ("m", "uso.ativo", 1.0)])
    assert m.bloco_prompt("me conte uma piada") == ""
    bloco = m.bloco_prompt("qual a rotina do meu computador?")
    assert bloco.startswith("## ENTORNO") and len(bloco) <= 700


def test_ferramentas_registradas(tmp_path):
    reg = ToolRegistry({"tools": {"guarded_actions": []}})
    nomes = register_entorno_tools(reg, _motor(tmp_path))
    assert "entorno_resumo" in nomes
    assert reg.tools["entorno_resumo"]()["ok"]
    assert reg.tools["entorno_pausar"]("false")["pausado"] is False
