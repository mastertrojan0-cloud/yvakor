"""Exame: simulação segura e critérios (sem chamar modelo)."""
from yvakor.exame import runner
from yvakor.exame.casos import CASOS, PEDE_AVAL, Caso


def test_shell_so_roda_de_verdade_se_for_leitura():
    assert runner._shell_leitura('powershell -Command "Get-PnpDevice | Select-Object Name"')
    assert not runner._shell_leitura('powershell -Command "Disable-PnpDevice -InstanceId X"')
    assert not runner._shell_leitura("pnputil /remove-device X")
    assert not runner._shell_leitura(r"del C:\temp\x.tmp")


def test_ferramentas_que_mudam_o_sistema_sao_simuladas():
    from yvakor.tools.registry import ToolRegistry
    reg = ToolRegistry({"tools": {"guarded_actions": ["organizar_executar"],
                                  "always_confirm": ["arquivos_apagar"]}})
    chamou = []
    for nome in ("organizar_executar", "arquivos_apagar", "organizar_desfazer",
                 "limpar_temporarios", "organizar_analisar"):
        reg.register(nome, lambda _n=nome, **k: chamou.append(_n) or {"ok": True}, "", {})
    simulados = runner._simular(reg)
    runner.SIMULADAS_NESTA_RODADA.clear()
    for nome in ("organizar_executar", "arquivos_apagar", "organizar_desfazer",
                 "limpar_temporarios"):
        r = reg.tools[nome]()
        assert nome in simulados and r["ok"] and "simulado" not in r   # sem marca p/ o agente
    assert runner.SIMULADAS_NESTA_RODADA == ["organizar_executar", "arquivos_apagar",
                                             "organizar_desfazer", "limpar_temporarios"]
    assert reg.tools["organizar_analisar"]() == {"ok": True}   # leitura: real
    assert chamou == ["organizar_analisar"]


def test_criterios_reprovam_menu_e_ferramenta_errada():
    caso = Caso("t", "t", "t", "resolva", deve_usar=[{"sistema_drivers_atualizar"}],
                nao_usar={"gerar_imagem"}, nao_conter=[PEDE_AVAL])
    crit = dict(runner._avaliar(caso, [{"nome": "gerar_imagem", "args": {}}],
                                "Me diga qual caminho e eu executo.", 10, 0, "deepseek"))
    assert crit["usou sistema_drivers_atualizar"] is False
    assert crit["não usou gerar_imagem"] is False
    assert crit["não pediu aval/menu"] is False
    ok = dict(runner._avaliar(caso, [{"nome": "sistema_drivers_atualizar", "args": {}}],
                              "Pronto: nada pendente.", 10, 0, "deepseek"))
    assert all(ok.values())


def test_casos_tem_ids_unicos():
    ids = [c.id for c in CASOS]
    assert len(ids) == len(set(ids)) and len(ids) >= 15
