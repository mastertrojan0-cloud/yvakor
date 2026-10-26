"""
YVAKOR — Ferramentas de rede para o agente

Leitura/descoberta é livre (o agente precisa enxergar o ambiente). Ações que
mudam algo — PTZ, gravar, tocar mídia, tecla na TV, ADB, MQTT, WoL — passam
pelo Confirmation Guard. Segredos (senha de câmera, token de TV) e comandos
que podem ser destrutivos (ADB shell) exigem confirmação SEMPRE.
"""
from __future__ import annotations

from yvakor.rede.facade import Rede


def _safe(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def _resumo_dev(d: dict) -> dict:
    return {
        "ip": d.get("ip"), "tipo": d.get("tipo"), "nome": d.get("nome"),
        "mac": d.get("mac"), "portas": (d.get("portas") or [])[:8],
        "servicos": (d.get("servicos") or [])[:4],
        "credenciais": d.get("credenciais"),
    }


def register_rede_tools(registry, rede: Rede) -> list[str]:
    reg = registry.register
    guard = registry.guard

    # ------------------------------------------------------------------ #
    # Descoberta e inventário
    # ------------------------------------------------------------------ #
    def escanear(profundo: bool = True) -> dict:
        devs = rede.descobridor.escanear(profundo=bool(profundo))
        meta = getattr(rede.descobridor, "ultimo", {})
        return {
            "ok": True,
            "total": len(devs),
            "duracao_s": meta.get("duracao_s"),
            "escopo": rede.escopo.descrever(),
            "dispositivos": [_resumo_dev(d) for d in devs],
            "resumo": rede.resumo(),
        }

    def dispositivos(tipo: str = "") -> dict:
        devs = rede.registro.listar(tipo=(tipo or None))
        if not devs:
            return {"ok": True, "total": 0,
                    "resumo": "nada registrado ainda — use rede_escanear"}
        return {"ok": True, "total": len(devs),
                "dispositivos": [_resumo_dev(d) for d in devs]}

    def escopo_info() -> dict:
        return {"ok": True, **rede.escopo.resumo()}

    def nomear(alvo: str, nome: str) -> dict:
        dev = rede.registro.renomear(alvo, nome)
        if not dev:
            return {"ok": False, "erro": f"dispositivo '{alvo}' não encontrado"}
        return {"ok": True, "dispositivo": _resumo_dev(dev)}

    # ------------------------------------------------------------------ #
    # Câmeras
    # ------------------------------------------------------------------ #
    def camera_listar() -> dict:
        cams = rede.cameras.listar()
        return {"ok": True, "total": len(cams),
                "cameras": [{"ip": c["ip"], "nome": c.get("nome"),
                             "fabricante": c.get("fabricante"),
                             "modelo": c.get("modelo"),
                             "credenciais": c.get("credenciais")}
                            for c in cams]}

    def camera_descobrir(segundos: float = 3) -> dict:
        achadas = rede.cameras.descobrir(float(segundos))
        return {"ok": True, "total": len(achadas),
                "cameras": [{"ip": c["ip"], "nome": c.get("nome"),
                             "xaddr": c.get("xaddr")} for c in achadas]}

    def camera_info(alvo: str) -> dict:
        return {"ok": True, "info": rede.cameras.info(alvo)}

    def camera_snapshot(alvo: str, perfil: str = "") -> dict:
        return rede.cameras.snapshot(alvo, perfil or None)

    def camera_credenciais(alvo: str, usuario: str, senha: str) -> dict:
        ip = rede.escopo.exigir(alvo)
        rede.registro.salvar_credenciais(ip, user=usuario, password=senha)
        return {"ok": True, "ip": ip,
                "obs": "credenciais salvas em data/rede.json (fora do git)"}

    def camera_ptz(alvo: str, x: float = 0, y: float = 0, zoom: float = 0,
                   segundos: float = 0.4) -> dict:
        return rede.cameras.ptz(alvo, x, y, zoom, segundos)

    def camera_janela(alvo: str) -> dict:
        dev = rede.cameras._dev(alvo)
        import subprocess
        try:
            saida = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Yoosee.exe"],
                capture_output=True, text=True, timeout=8).stdout
            if "Yoosee.exe" not in saida:
                subprocess.Popen([r"C:\Program Files (x86)\Yoosee\Yoosee.exe"])
        except Exception:
            pass
        url = f"http://127.0.0.1:7777/camera/{dev['ip']}"
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
        return {"ok": True, "url": url, "janela": "YVAKOR",
                "fonte": "espelho do app Yoosee (ao vivo)"}

    def camera_gravar(alvo: str, segundos: int = 10) -> dict:
        return rede.cameras.gravar(alvo, int(segundos))

    def camera_ao_vivo(alvo: str, segundos: int = 0) -> dict:
        r = rede.cameras.ao_vivo(alvo, int(segundos))
        if r.get("ok"):
            try:
                import webbrowser
                webbrowser.open(r["url"])
            except Exception:
                pass
        return r

    # ------------------------------------------------------------------ #
    # Chromecast / TV
    # ------------------------------------------------------------------ #
    def cast(acao: str = "status", alvo: str = "", valor: str = "") -> dict:
        a = (acao or "status").lower()
        if a == "status":
            if alvo:
                return rede.casts.status(alvo)
            return {"ok": True, "aparelhos": rede.casts.descobrir(8)}
        if a == "tocar":
            return rede.casts.tocar(alvo, valor)
        if a in ("pausar", "continuar", "parar"):
            return getattr(rede.casts, a)(alvo)
        if a == "volume":
            return rede.casts.volume(alvo, nivel=int(float(valor or 0)))
        if a == "mudo":
            return rede.casts.mudo(alvo, str(valor).lower() in ("1", "true", "sim"))
        return {"ok": False, "erro": f"ação de cast inválida: {acao}"}

    def tv(acao: str = "status", alvo: str = "", valor: str = "") -> dict:
        a = (acao or "status").lower()
        if a == "status":
            return {"ok": True, **(rede.tvs.status(alvo) or {})}
        if a == "ligar":
            return rede.tvs.ligar(alvo)
        if a in ("desligar", "off"):
            return rede.tvs.desligar(alvo)
        if a in ("tecla", "key"):
            return rede.tvs.tecla(alvo, valor or "ok")
        if a == "volume":
            return rede.tvs.volume(alvo, int(float(valor or 0)))
        if a in ("app", "abrir_app"):
            return rede.tvs.app(alvo, valor)
        return {"ok": False, "erro": f"ação de TV inválida: {acao}"}

    # ------------------------------------------------------------------ #
    # Celular (ADB)
    # ------------------------------------------------------------------ #
    def telefone_preparar() -> dict:
        return rede.telefones.preparar()

    def telefone_dispositivos() -> dict:
        devs = rede.telefones.dispositivos()
        return {"ok": True, "total": len(devs), "dispositivos": devs,
                "adb": rede.telefones.adb()}

    def telefone_conectar(ip: str, porta: int = 5555) -> dict:
        return rede.telefones.conectar(ip, int(porta))

    def telefone_tela(serial: str = "") -> dict:
        return rede.telefones.tela(serial)

    def telefone_acao(acao: str, serial: str = "", x: int = 0, y: int = 0,
                      x2: int = 0, y2: int = 0, texto: str = "",
                      valor: str = "") -> dict:
        a = (acao or "").lower()
        if a in ("tocar", "tap"):
            return rede.telefones.tocar(x, y, serial)
        if a in ("deslizar", "swipe"):
            return rede.telefones.deslizar(x, y, x2, y2, serial=serial)
        if a in ("texto", "digitar", "type"):
            return rede.telefones.texto(texto or valor, serial)
        if a in ("tecla", "key"):
            return rede.telefones.tecla(valor or texto or "KEYCODE_ENTER", serial)
        if a in ("abrir_app", "app"):
            return rede.telefones.abrir_app(valor or texto, serial)
        if a == "instalar":
            return rede.telefones.instalar(valor or texto, serial)
        if a == "shell":
            return rede.telefones.shell(valor or texto, serial)
        return {"ok": False, "erro": f"ação de celular inválida: {acao}"}

    # ------------------------------------------------------------------ #
    # IoT
    # ------------------------------------------------------------------ #
    def http_dispositivo(alvo: str, caminho: str = "/", metodo: str = "GET",
                         dados: str = "") -> dict:
        return rede.http.requisicao(alvo, caminho, metodo,
                                    dados if dados else None)

    def mqtt_ler(topico: str, segundos: float = 3) -> dict:
        return rede.mqtt.ler(topico, float(segundos))

    def mqtt_publicar(topico: str, payload: str, retain: bool = False) -> dict:
        return rede.mqtt.publicar(topico, payload, bool(retain))

    def wol(alvo: str) -> dict:
        dev = rede.registro.obter(alvo) or {}
        mac = dev.get("mac") or alvo
        from yvakor.rede.iot import wol as enviar
        return enviar(mac)

    # ------------------------------------------------------------------ #
    # Registro
    # ------------------------------------------------------------------ #
    reg("rede_escanear", escanear,
        "Varre a rede local autorizada e descobre câmeras, TVs, celulares, "
        "IoT e computadores (leva ~10s).", {"profundo": "bool?"})
    reg("rede_dispositivos", dispositivos,
        "Lista os dispositivos já conhecidos (filtro opcional por tipo: "
        "camera, tv, telefone, iot, roteador, computador).", {"tipo": "str?"})
    reg("rede_escopo", escopo_info,
        "Mostra o escopo de rede autorizado (sub-redes, gateway, limites).", {})
    reg("rede_nomear", nomear,
        "Dá um nome humano a um dispositivo (ex.: 'câmera da garagem').",
        {"alvo": "str", "nome": "str"})

    reg("rede_camera_listar", camera_listar,
        "Lista as câmeras registradas.", {})
    reg("rede_camera_descobrir", camera_descobrir,
        "Procura câmeras ONVIF na rede (WS-Discovery).", {"segundos": "float?"})
    reg("rede_camera_info", camera_info,
        "Fabricante, modelo, perfis e URL de snapshot de uma câmera.",
        {"alvo": "str"})
    reg("rede_camera_snapshot", camera_snapshot,
        "Tira uma foto da câmera e salva em data/rede_shots. Alvo = IP ou nome.",
        {"alvo": "str", "perfil": "str?"})
    reg("rede_camera_credenciais", camera_credenciais,
        "Salva usuário/senha de uma câmera (fica em data/rede.json).",
        {"alvo": "str", "usuario": "str", "senha": "str"})
    reg("rede_camera_ptz", camera_ptz,
        "Move a câmera (PTZ): x/y de -1 a 1, zoom de -1 a 1.",
        {"alvo": "str", "x": "float?", "y": "float?", "zoom": "float?",
         "segundos": "float?"})
    reg("rede_camera_gravar", camera_gravar,
        "Grava um clipe RTSP da câmera (segundos).",
        {"alvo": "str", "segundos": "int?"})
    reg("rede_camera_janela", camera_janela,
        "Abre a JANELA DE MONITOR do YVAKOR para a câmera (player das "
        "gravações + imagem mais recente), sem depender do EYE DELTA.",
        {"alvo": "str"})
    reg("rede_camera_ao_vivo", camera_ao_vivo,
        "Abre uma JANELA de vídeo ao vivo da câmera (ffplay/RTSP). "
        "segundos=0 deixa aberta.",
        {"alvo": "str", "segundos": "int?"})

    reg("rede_cast", cast,
        "Chromecast/Google TV. acao = status|tocar|pausar|continuar|parar|"
        "volume|mudo. valor = URL/arquivo, ou 0-100 no volume.",
        {"acao": "str", "alvo": "str?", "valor": "str?"})
    reg("rede_tv", tv,
        "TV Samsung/LG. acao = status|ligar|desligar|tecla|volume|app. "
        "valor = tecla (ok, voltar, volume+, mudo…) ou nome do app.",
        {"acao": "str", "alvo": "str?", "valor": "str?"})

    reg("rede_telefone_preparar", telefone_preparar,
        "Baixa o adb (platform-tools) se ainda não existir.", {})
    reg("rede_telefone_dispositivos", telefone_dispositivos,
        "Lista celulares Android conectados/autorizados.", {})
    reg("rede_telefone_conectar", telefone_conectar,
        "Conecta um celular por Wi-Fi (depuração sem fio): ip:5555.",
        {"ip": "str", "porta": "int?"})
    reg("rede_telefone_tela", telefone_tela,
        "Print da tela do celular (salva PNG em data/rede_shots).",
        {"serial": "str?"})
    reg("rede_telefone_acao", telefone_acao,
        "Controla o celular: acao = tocar|deslizar|texto|tecla|abrir_app|"
        "instalar|shell. Use x/y, texto/valor e serial.",
        {"acao": "str", "serial": "str?", "x": "int?", "y": "int?",
         "x2": "int?", "y2": "int?", "texto": "str?", "valor": "str?"})

    reg("rede_http_dispositivo", http_dispositivo,
        "Chama a API HTTP de um aparelho (Tasmota /cm?cmnd=..., Shelly /rpc/...).",
        {"alvo": "str", "caminho": "str?", "metodo": "str?", "dados": "str?"})
    reg("rede_mqtt_ler", mqtt_ler,
        "Escuta um tópico MQTT por N segundos e devolve as mensagens.",
        {"topico": "str", "segundos": "float?"})
    reg("rede_mqtt_publicar", mqtt_publicar,
        "Publica num tópico MQTT (liga/desliga aparelho, cena…).",
        {"topico": "str", "payload": "str", "retain": "bool?"})
    def monitor(acao: str = "status") -> dict:
        m = getattr(rede, "monitor", None)
        if m is None:
            return {"ok": False, "erro": "monitor de rede indisponível"}
        acao = (acao or "status").lower()
        if acao in ("iniciar", "ligar", "start", "ative"):
            return {"ok": True, **m.iniciar()}
        if acao in ("parar", "desligar", "stop", "pare"):
            return {"ok": True, **m.parar()}
        return {"ok": True, **m.status()}

    def dispositivo_detalhe(alvo: str) -> dict:
        dev = rede.registro.obter(alvo)
        if not dev:
            return {"ok": False, "erro": f"dispositivo '{alvo}' não encontrado"}
        from yvakor.ambiente import _probe
        testes = _probe(rede, dev)
        eventos = []
        try:
            import json
            from yvakor.rede.monitor import EVENTOS
            if EVENTOS.exists():
                for linha in EVENTOS.read_text(encoding="utf-8").splitlines()[-300:]:
                    e = json.loads(linha)
                    if e.get("ip") == dev.get("ip"):
                        eventos.append(e)
        except Exception:
            pass
        return {"ok": True, "dispositivo": dev, "testes": testes,
                "eventos": eventos[-20:]}

    def dispositivo_atualizar(alvo: str, nome: str = "", tipo: str = "",
                              grupo: str = "", notas: str = "",
                              favorito: bool | None = None) -> dict:
        campos = {}
        for chave, valor in (("nome", nome), ("tipo", tipo),
                             ("grupo", grupo), ("notas", notas)):
            if valor:
                campos[chave] = valor
        if favorito is not None:
            campos["favorito"] = favorito
        dev = rede.registro.atualizar(alvo, **campos)
        return ({"ok": True, "dispositivo": dev} if dev
                else {"ok": False, "erro": f"dispositivo '{alvo}' não encontrado"})

    def dispositivo_esquecer(alvo: str) -> dict:
        return ({"ok": True, "esquecido": alvo}
                if rede.registro.esquecer(alvo)
                else {"ok": False, "erro": "não encontrado"})

    def dispositivo_testar(alvo: str) -> dict:
        dev = rede.registro.obter(alvo)
        if not dev:
            return {"ok": False, "erro": "não encontrado"}
        from yvakor.ambiente import _probe
        return {"ok": True, "dispositivo": dev, "testes": _probe(rede, dev)}

    def dispositivos_grupos() -> dict:
        g = rede.registro.grupos()
        return {"ok": True, "grupos": g, "total": len(g)}

    def painel() -> dict:
        url = "http://127.0.0.1:7777/dispositivos"
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
        return {"ok": True, "url": url}

    def gerenciar() -> dict:
        from yvakor.rede.gerente import organizar
        return organizar(rede)

    def devolver_controle(alvo: str) -> dict:
        dev = rede.registro.atualizar(alvo, manual=False)
        return ({"ok": True, "dispositivo": dev} if dev
                else {"ok": False, "erro": "não encontrado"})

    reg("rede_gerenciar", gerenciar,
        "YVAKOR assume o comando: agrupa, testa e atualiza os dispositivos "
        "que não foram editados manualmente.", {})
    reg("rede_devolver_controle", devolver_controle,
        "Devolve um dispositivo ao controle automático do YVAKOR.",
        {"alvo": "str"})

    reg("rede_painel", painel,
        "Abre o painel visual de gerenciamento de dispositivos.", {})

    reg("rede_dispositivo_detalhe", dispositivo_detalhe,
        "Ficha completa de um dispositivo + testes + histórico.",
        {"alvo": "str"})
    reg("rede_dispositivo_atualizar", dispositivo_atualizar,
        "Edita nome/tipo/grupo/notas/favorito de um dispositivo.",
        {"alvo": "str", "nome": "str?", "tipo": "str?", "grupo": "str?",
         "notas": "str?", "favorito": "bool?"})
    reg("rede_dispositivo_esquecer", dispositivo_esquecer,
        "Remove um dispositivo do registro.", {"alvo": "str"})
    reg("rede_dispositivo_testar", dispositivo_testar,
        "Testa TCP/HTTP/snapshot e devolve o resultado.", {"alvo": "str"})
    reg("rede_dispositivos_grupos", dispositivos_grupos,
        "Lista os grupos de dispositivos e a quantidade.", {})

    reg("rede_monitor", monitor,
        "Monitoramento contínuo da rede: acao=status|iniciar|parar.",
        {"acao": "str?"})
    reg("rede_wol", wol,
        "Liga um aparelho por Wake-on-LAN (MAC ou nome registrado).",
        {"alvo": "str"})

    # ------------------------------------------------------------------ #
    # Política de confirmação
    # ------------------------------------------------------------------ #
    guard.guarded.update({
        "rede_camera_ao_vivo", "rede_camera_ptz", "rede_camera_gravar",
        "rede_camera_credenciais",
        "rede_cast", "rede_tv", "rede_telefone_preparar",
        "rede_telefone_conectar", "rede_telefone_acao",
        "rede_http_dispositivo", "rede_mqtt_publicar", "rede_wol",
    })
    # Nunca automáticas: segredo, shell de celular e comando em aparelho
    guard.always_confirm.update({
        "rede_camera_credenciais", "rede_telefone_acao",
        "rede_mqtt_publicar", "rede_http_dispositivo",
    })

    return [n for n in registry.tools if n.startswith("rede_")]
