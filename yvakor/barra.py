"""
YVAKOR — Comandos com barra no chat ("/nome …"), como no Claude e no Hermes

  /skills                      lista as skills (com ligada/desligada)
  /skills ligar|desligar NOME  liga/desliga uma skill
  /plugins                     lista os plugins da pasta plugins/
  /plugins ligar|desligar NOME liga/desliga um plugin
  /comandos                    lista tudo o que dá para chamar com "/"
  /<comando-de-plugin> resto   roda o prompt do comando (commands/*.md)
  /<skill> [/<skill>…] resto   carrega até 5 skills inteiras e usa o resto
                               como pedido (ex.: "/relatorio-vendas de março")

Primeira palavra com "/" que não é nada disso → mensagem normal (um caminho
como "/home/x" não vira comando). Sem IA: resolve antes do agente.
"""
from __future__ import annotations

MAX_SKILLS = 5
MAX_CHARS_SKILL = 12000


def _lista_skills(skills) -> str:
    itens = skills.listar(incluir_desligadas=True)["skills"]
    if not itens:
        return "Nenhuma skill ainda."
    linhas = [f"{'✅' if s['ligada'] else '⏸️'} /{s['nome']} — {s['descricao'][:110]}"
              for s in itens]
    return (f"Skills ({len(itens)}):\n" + "\n".join(linhas)
            + "\n\nUse /skills desligar <nome> ou /skills ligar <nome>.")


def _lista_plugins(plugins) -> str:
    if plugins is None:
        return "Plugins indisponíveis."
    dados = plugins.listar()
    if not dados["plugins"]:
        return (f"Nenhum plugin em {dados['pasta']}. Um plugin é uma pasta com "
                ".yvakor-plugin/plugin.json (ou .claude-plugin/plugin.json), "
                "skills/, commands/ e .mcp.json.")
    linhas = []
    for p in dados["plugins"]:
        partes = [f"{len(p['skills'])} skill(s)", f"{len(p['comandos'])} comando(s)"]
        if p["agentes"]:
            partes.append(f"{len(p['agentes'])} agente(s)")
        if p["hooks"]:
            partes.append(f"hooks: {', '.join(p['hooks'])}")
        if p["mcp"]:
            partes.append(f"MCP: {', '.join(p['mcp'])}")
        linha = (f"{'✅' if p['ligado'] else '⏸️'} {p['nome']}"
                 + (f" v{p['versao']}" if p["versao"] else "")
                 + f" — {p['descricao'][:100]} ({'; '.join(partes)})")
        if p["bloqueados"]:
            linha += f"\n   ⚠️ bloqueado por segurança: {'; '.join(p['bloqueados'])}"
        linhas.append(linha)
    return ("Plugins:\n" + "\n".join(linhas)
            + "\n\nUse /plugins ligar <nome> (leia o conteúdo antes: pode trazer "
              "servidores MCP que rodam no PC) ou /plugins desligar <nome>.")


def _lista_comandos(skills, plugins) -> str:
    linhas = ["/skills · /plugins · /comandos · /compactar"]
    if plugins is not None:
        linhas += [f"/{c}" for c in sorted(plugins.comandos())]
    linhas += [f"/{s['nome']}" for s in skills.listar()["skills"]]
    return "Comandos disponíveis:\n" + "\n".join(linhas)


def comandos_disponiveis(skills, plugins=None) -> list[dict]:
    """Para o autocompletar das interfaces (GET /api/comandos)."""
    itens = [{"comando": "skills", "nome": "Listar/ligar/desligar skills"},
             {"comando": "plugins", "nome": "Listar/ligar/desligar plugins"},
             {"comando": "comandos", "nome": "Tudo o que dá para chamar com /"},
             {"comando": "compactar", "nome": "Resumir os turnos antigos desta conversa"}]
    if plugins is not None:
        itens += [{"comando": c, "nome": f"Comando de plugin ({arq.stem})"}
                  for c, arq in sorted(plugins.comandos().items())]
    itens += [{"comando": s["nome"], "nome": s["descricao"][:60] or "Skill"}
              for s in skills.listar()["skills"]]
    return itens


def _ligar_desligar(args: list[str], definir) -> str | None:
    if len(args) >= 2 and args[0].lower() in ("ligar", "desligar", "on", "off"):
        r = definir(" ".join(args[1:]), args[0].lower() in ("ligar", "on"))
        return r.get("result") if r.get("ok") else f"❌ {r.get('error')}"
    return None


def interpretar(mensagem: str, skills, plugins=None) -> dict | None:
    """None = mensagem normal; {"tipo": "resposta", "texto"} = responder já;
    {"tipo": "expandir", "mensagem", "contexto", "rotulo"} = seguir ao agente."""
    texto = (mensagem or "").strip()
    if not texto.startswith("/") or texto.startswith("//"):
        return None
    tokens = texto.split()
    primeiro = tokens[0][1:].lower()
    args = tokens[1:]

    if primeiro == "skills":
        def definir(nome, ligada):
            alvo = skills.resolver(nome)
            return skills.definir(alvo, ligada) if alvo else \
                {"ok": False, "error": f"skill {nome!r} não existe"}
        return {"tipo": "resposta",
                "texto": _ligar_desligar(args, definir) or _lista_skills(skills)}
    if primeiro == "plugins":
        definir = plugins.definir if plugins is not None else \
            (lambda n, l: {"ok": False, "error": "plugins indisponíveis"})
        return {"tipo": "resposta",
                "texto": _ligar_desligar(args, definir) or _lista_plugins(plugins)}
    if primeiro in ("comandos", "ajuda", "help"):
        return {"tipo": "resposta", "texto": _lista_comandos(skills, plugins)}

    if plugins is not None:
        from yvakor.plugins import expandir_comando
        arq = plugins.comandos().get(primeiro)
        if arq is not None:
            resto = texto[len(tokens[0]):].strip()
            return {"tipo": "expandir",
                    "mensagem": resto or f"Execute o comando /{primeiro}.",
                    "contexto": (f"## COMANDO /{primeiro} (chamado pelo usuário — siga)\n"
                                 + expandir_comando(arq, resto)),
                    "rotulo": f"⌨️ comando /{primeiro}"}

    # empilha até 5 skills: "/a /b pedido"
    usadas: list[str] = []
    consumidos = 0
    for tok in tokens[:MAX_SKILLS]:
        nome = skills.resolver(tok[1:]) if tok.startswith("/") else None
        if not nome or not skills.ligada(nome):
            break
        consumidos += 1
        if nome not in usadas:
            usadas.append(nome)
    if not usadas:
        return None
    resto = " ".join(tokens[consumidos:]).strip()
    blocos = []
    for nome in usadas:
        vista = skills.ver(nome)
        if vista.get("ok"):
            apoio = vista.get("arquivos_de_apoio")
            blocos.append(f"### /{nome}\n{vista['conteudo'][:MAX_CHARS_SKILL]}"
                          + (f"\n(arquivos de apoio: {', '.join(apoio)} — leia com "
                             "skill_ver se o procedimento pedir)" if apoio else ""))
    return {"tipo": "expandir",
            "mensagem": resto or f"Execute a skill {', '.join(usadas)}.",
            "contexto": "## SKILLS CHAMADAS PELO USUÁRIO (siga estes procedimentos)\n"
                        + "\n\n".join(blocos),
            "rotulo": "📘 skill " + ", ".join(f"/{n}" for n in usadas)}
