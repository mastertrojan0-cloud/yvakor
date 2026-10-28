"""YVAKOR — central de configurações (o "Ajustes" do Claude.ai, para o YVAKOR).

Concentra num só lugar o que o usuário configura, com a regra de que SEGREDO NUNCA SAI:
  • chaves de API (.env): só se lê "definida? + máscara"; gravar/remover/testar por endpoint;
  • preferências (data/ajustes.json): perfil e instruções pessoais, tema, voz, memória, consumo;
  • integrações MCP (config/mcp.json): servidores por comando, com `env` mascarado;
  • conectores: continuam no ConnectorManager (a interface só os mostra).

Tudo que muda vale NA HORA (sem reiniciar) sempre que possível: `aplicar_vivo` atualiza o
agente em execução, e `aplicar_ao_settings` reaplica as preferências no próximo boot.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from yvakor import seguro

ROOT = Path(__file__).resolve().parent.parent
ARQ_AJUSTES = ROOT / "data" / "ajustes.json"
ARQ_ENV = ROOT / ".env"
ARQ_MCP = ROOT / "config" / "mcp.json"

# --------------------------------------------------------------------------- #
# Chaves de API (.env)
# --------------------------------------------------------------------------- #
CHAVES = {
    "DEEPSEEK_API_KEY": {"rotulo": "DeepSeek", "grupo": "Modelos",
                         "ajuda": "Modelo de nuvem para tarefas profundas (modo Automático/DeepSeek).",
                         "link": "https://platform.deepseek.com/api_keys", "testavel": True},
    "GEMINI_API_KEY": {"rotulo": "Gemini (Google AI Studio)", "grupo": "Modelos",
                       "ajuda": "Nuvem de reserva do DeepSeek, ou a principal no modo Gemini.",
                       "link": "https://aistudio.google.com/apikey", "testavel": True},
    "OPENAI_API_KEY": {"rotulo": "OpenAI", "grupo": "Modelos",
                       "ajuda": "Opcional: visão/imagens compatíveis com a API da OpenAI.",
                       "link": "https://platform.openai.com/api-keys", "testavel": False},
    "BRAVE_API_KEY": {"rotulo": "Brave Search", "grupo": "Pesquisa",
                      "ajuda": "Busca oficial por API (plano grátis ~2.000/mês): resultados bem melhores na web.",
                      "link": "https://api-dashboard.search.brave.com/", "testavel": True},
    "PEXELS_API_KEY": {"rotulo": "Pexels", "grupo": "Mídia",
                       "ajuda": "Fotos reais para a ferramenta buscar_foto.",
                       "link": "https://www.pexels.com/api/", "testavel": False},
    "IMAGE_API_KEY": {"rotulo": "Geração de imagens", "grupo": "Mídia",
                      "ajuda": "Chave do serviço de imagens configurado (cap_imagem).", "link": "", "testavel": False},
    "GOOGLE_CLIENT_ID": {"rotulo": "Google · Client ID", "grupo": "Login (OAuth)", "ajuda": "Calendar/Drive/Gmail em um clique.",
                         "link": "https://console.cloud.google.com/apis/credentials", "testavel": False, "publica": True},
    "GOOGLE_CLIENT_SECRET": {"rotulo": "Google · Client Secret", "grupo": "Login (OAuth)", "ajuda": "", "link": "", "testavel": False},
    "GITHUB_CLIENT_ID": {"rotulo": "GitHub · Client ID", "grupo": "Login (OAuth)", "ajuda": "Entrar com GitHub.",
                         "link": "https://github.com/settings/developers", "testavel": False, "publica": True},
    "GITHUB_CLIENT_SECRET": {"rotulo": "GitHub · Client Secret", "grupo": "Login (OAuth)", "ajuda": "", "link": "", "testavel": False},
    "SLACK_CLIENT_ID": {"rotulo": "Slack · Client ID", "grupo": "Login (OAuth)", "ajuda": "Entrar com Slack.",
                        "link": "https://api.slack.com/apps", "testavel": False, "publica": True},
    "SLACK_CLIENT_SECRET": {"rotulo": "Slack · Client Secret", "grupo": "Login (OAuth)", "ajuda": "", "link": "", "testavel": False},
}
# chave de ambiente -> (provedor do roteador que a usa)
_PROVEDOR_DA_CHAVE = {"DEEPSEEK_API_KEY": "deepseek", "GEMINI_API_KEY": "gemini"}


def mascarar(valor: str, publica: bool = False) -> str:
    v = str(valor or "")
    if not v:
        return ""
    if publica and len(v) <= 80:
        return v[:6] + "…" + v[-4:] if len(v) > 14 else v
    return (v[:3] + "…" + v[-4:]) if len(v) > 10 else "•" * len(v)


def _ler_env(arq: Path | None = None) -> dict[str, str]:
    arq = arq or ARQ_ENV
    out: dict[str, str] = {}
    try:
        for linha in arq.read_text(encoding="utf-8").splitlines():
            l = linha.strip()
            if l and not l.startswith("#") and "=" in l:
                k, v = l.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _gravar_env(nome: str, valor: str | None, arq: Path | None = None) -> None:
    """Troca/insere/remove UMA variável no .env, preservando comentários e as outras linhas."""
    arq = arq or ARQ_ENV
    try:
        linhas = arq.read_text(encoding="utf-8").splitlines()
    except OSError:
        linhas = []
    novas, achou = [], False
    for l in linhas:
        k = l.split("=", 1)[0].strip().lstrip("#").strip() if "=" in l else ""
        ativa = not l.strip().startswith("#")
        if k == nome and (ativa or valor is not None) and not achou:
            achou = True
            if valor is not None:
                novas.append(f"{nome}={valor}")
            continue                                   # valor None: remove a linha
        novas.append(l)
    if valor is not None and not achou:
        novas.append(f"{nome}={valor}")
    seguro.gravar_texto(arq, "\n".join(novas).rstrip("\n") + "\n")


def estado_chaves(arq: Path | None = None) -> list[dict]:
    arq = arq or ARQ_ENV
    env = _ler_env(arq)
    out = []
    for nome, meta in CHAVES.items():
        valor = os.environ.get(nome) or env.get(nome, "")
        out.append({"nome": nome, "rotulo": meta["rotulo"], "grupo": meta["grupo"], "ajuda": meta["ajuda"],
                    "link": meta["link"], "testavel": meta["testavel"], "definida": bool(valor),
                    "mascara": mascarar(valor, bool(meta.get("publica"))),
                    "origem": ("ambiente" if os.environ.get(nome) and nome not in env else ".env") if valor else ""})
    return out


def _valida_valor(valor: str) -> str:
    v = str(valor or "").strip()
    if not v or len(v) > 500 or re.search(r"[\r\n\x00]", v):
        raise ValueError("valor inválido (vazio, com quebra de linha ou grande demais)")
    return v


def definir_chave(nome: str, valor: str, arq: Path | None = None) -> dict:
    arq = arq or ARQ_ENV
    if nome not in CHAVES:
        raise ValueError(f"chave desconhecida: {nome}")
    v = _valida_valor(valor)
    _gravar_env(nome, v, arq)
    os.environ[nome] = v
    return {"nome": nome, "mascara": mascarar(v, bool(CHAVES[nome].get("publica")))}


def remover_chave(nome: str, arq: Path | None = None) -> dict:
    arq = arq or ARQ_ENV
    if nome not in CHAVES:
        raise ValueError(f"chave desconhecida: {nome}")
    _gravar_env(nome, None, arq)
    os.environ.pop(nome, None)
    return {"nome": nome, "removida": True}


def recarregar_provedores(agente) -> None:
    """Passa as chaves novas para os provedores já criados e dá nova chance à nuvem."""
    r = getattr(agente, "router", None)
    if r is None:
        return
    for nome, cfg in (agente.settings.get("llm", {}).get("providers") or {}).items():
        env = cfg.get("api_key_env")
        if env and nome in r.providers:
            r.providers[nome].api_key = os.environ.get(env) or None
    try:
        r.definir_modo(r.modo)                           # zera breaker/probe: tenta a nuvem de novo
    except Exception:
        pass


def _modelo_configurado(provedor: str) -> str:
    try:
        from yvakor.config import load_settings
        return str(load_settings()["llm"]["providers"][provedor]["model"])
    except Exception:
        return ""


def testar_chave(nome: str, valor: str | None = None) -> dict:
    """Verifica a chave na própria API (sem gastar tokens). Se `valor` vier, testa ele; senão a salva."""
    if nome not in CHAVES:
        return {"ok": False, "erro": f"chave desconhecida: {nome}"}
    chave = (valor or os.environ.get(nome) or _ler_env().get(nome, "")).strip()
    if not chave:
        return {"ok": False, "erro": "chave não definida"}
    try:
        if nome == "DEEPSEEK_API_KEY":
            req = urllib.request.Request("https://api.deepseek.com/user/balance",
                                         headers={"Authorization": f"Bearer {chave}", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            infos = d.get("balance_infos") or []
            saldo = ", ".join(f"{i.get('total_balance')} {i.get('currency')}" for i in infos) or "—"
            if d.get("is_available") is False:
                return {"ok": False, "erro": f"chave válida, mas sem saldo ({saldo}) — recarregue em platform.deepseek.com",
                        "saldo": saldo}
            return {"ok": True, "detalhe": f"chave válida · saldo {saldo}", "saldo": saldo}
        if nome == "GEMINI_API_KEY":
            # Lista os modelos (não gasta tokens) e confere o configurado.
            req = urllib.request.Request(
                "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                headers={"x-goog-api-key": chave, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            nomes = [str(m.get("name", "")).split("/", 1)[-1] for m in d.get("models") or []]
            alvo = _modelo_configurado("gemini")
            if alvo and nomes and alvo not in nomes and not alvo.endswith("-latest"):
                flash = [n for n in nomes if "flash" in n][:4]
                return {"ok": False, "erro": f"chave válida, mas o modelo '{alvo}' não está "
                        f"disponível; troque em config/settings.yaml (ex.: {', '.join(flash) or nomes[0]})"}
            return {"ok": True, "detalhe": f"chave válida · modelo {alvo or '?'} · {len(nomes)} modelos"}
        if nome == "BRAVE_API_KEY":
            req = urllib.request.Request("https://api.search.brave.com/res/v1/web/search?q=teste&count=1",
                                         headers={"X-Subscription-Token": chave, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read(2000)
            return {"ok": True, "detalhe": "chave válida"}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return {"ok": False, "erro": "chave recusada pela API (inválida ou sem permissão)"}
        if exc.code == 402:
            return {"ok": False, "erro": "sem saldo/crédito nesta conta"}
        if exc.code == 429:
            return {"ok": True, "detalhe": "chave válida (limite de uso atingido agora)"}
        return {"ok": False, "erro": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "erro": f"não consegui testar: {str(exc)[:80]}"}
    return {"ok": False, "erro": "esta chave não tem teste automático"}


# --------------------------------------------------------------------------- #
# Preferências (data/ajustes.json)
# --------------------------------------------------------------------------- #
VOZES_EDGE = ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural",
              "pt-PT-DuarteNeural", "pt-PT-RaquelNeural", "en-US-AndrewMultilingualNeural",
              "es-ES-AlvaroNeural"]


def _bool(v):
    if isinstance(v, bool):
        return v
    if str(v).lower() in ("1", "true", "sim", "on"):
        return True
    if str(v).lower() in ("0", "false", "nao", "não", "off"):
        return False
    raise ValueError("esperado verdadeiro/falso")


def _texto(maximo):
    return lambda v: str(v or "").strip()[:maximo]


def _escolha(*opcoes):
    def f(v):
        if v not in opcoes:
            raise ValueError("opção inválida: " + str(v))
        return v
    return f


def _padrao(regex, ex):
    def f(v):
        v = str(v).strip()
        if not re.fullmatch(regex, v):
            raise ValueError(f"formato inválido (ex.: {ex})")
        return v
    return f


def _numero(minimo, maximo, inteiro=False):
    def f(v):
        n = float(v)
        if not (minimo <= n <= maximo):
            raise ValueError(f"fora do intervalo {minimo}–{maximo}")
        return int(n) if inteiro else round(n, 4)
    return f


SECOES = {
    "perfil": {"nome": (_texto(60), ""), "preferencias": (_texto(2000), "")},
    "aparencia": {"tema": (_escolha("auto", "claro", "escuro"), "auto")},
    "voz": {"habilitado": (_bool, True), "narrar": (_bool, True),
            "tts": (_escolha("auto", "edge", "sapi"), "auto"),
            "voz_edge": (_escolha(*VOZES_EDGE), "pt-BR-AntonioNeural"),
            "tom": (_padrao(r"[+-]\d{1,2}Hz", "-12Hz"), "-12Hz"),
            "taxa": (_padrao(r"[+-]\d{1,2}%", "-5%"), "-5%"),
            "efeito": (_escolha("assinatura", "nenhum"), "assinatura")},
    "memoria": {"aprender_local": (_bool, False), "reter_operacionais_dias": (_numero(1, 365, True), 30)},
    "consumo": {"diario_usd": (_numero(0, 10000), 0.5), "mensal_usd": (_numero(0, 100000), 8.0),
                "diario_tokens": (_numero(0, 1e9, True), 0)},
}


def padroes() -> dict:
    return {sec: {k: d for k, (_, d) in campos.items()} for sec, campos in SECOES.items()}


def obter(arq: Path | None = None) -> dict:
    arq = arq or ARQ_AJUSTES
    base = padroes()
    salvo = seguro.ler_json(arq, {}) or {}
    for sec, campos in base.items():
        if isinstance(salvo.get(sec), dict):
            for k in campos:
                if k in salvo[sec]:
                    campos[k] = salvo[sec][k]
    return base


def salvar_secao(secao: str, valores: dict, arq: Path | None = None) -> dict:
    arq = arq or ARQ_AJUSTES
    if secao not in SECOES:
        raise ValueError(f"seção desconhecida: {secao}")
    campos = SECOES[secao]
    erros, novos = {}, {}
    for k, v in (valores or {}).items():
        if k not in campos:
            erros[k] = "campo desconhecido"
            continue
        try:
            novos[k] = campos[k][0](v)
        except (ValueError, TypeError) as exc:
            erros[k] = str(exc)
    if erros:
        raise ValueError(json.dumps(erros, ensure_ascii=False))
    todo = seguro.ler_json(arq, {}) or {}
    todo.setdefault(secao, {}).update(novos)
    seguro.gravar_json(arq, todo)
    return obter(arq)[secao]


def aplicar_ao_settings(settings: dict, arq: Path | None = None) -> dict:
    """No boot: as preferências salvas valem por cima do settings.yaml."""
    arq = arq or ARQ_AJUSTES
    try:
        aj = seguro.ler_json(arq, {}) or {}
    except Exception:
        return settings
    voz = aj.get("voz") or {}
    sv = settings.setdefault("voz", {})
    for k in ("habilitado", "narrar", "tts", "voz_edge", "tom", "taxa", "efeito"):
        if k in voz:
            sv[k] = voz[k]
    if "voz_edge" in voz:
        sv.setdefault("vozes", {})["pt-BR"] = voz["voz_edge"]
    mem = aj.get("memoria") or {}
    if "aprender_local" in mem:
        settings.setdefault("agent", {})["aprender_local"] = mem["aprender_local"]
    if "reter_operacionais_dias" in mem:
        settings.setdefault("maintenance", {})["reter_operacionais_dias"] = mem["reter_operacionais_dias"]
    con = aj.get("consumo") or {}
    if con:
        settings.setdefault("llm", {}).setdefault("otimizacao", {}).setdefault("orcamento", {}).update(con)
    return settings


def aplicar_vivo(agente, secao: str, valores: dict) -> None:
    """Efeito imediato no agente em execução."""
    s = agente.settings
    if secao == "voz":
        sv = s.setdefault("voz", {})
        sv.update({k: v for k, v in valores.items()})
        if "voz_edge" in valores:
            sv.setdefault("vozes", {})["pt-BR"] = valores["voz_edge"]
        tts = getattr(getattr(agente, "voz", None), "tts", None)
        if tts is not None:
            if "tts" in valores:
                tts.motor_pref = valores["tts"]
            if "voz_edge" in valores:
                tts.voz_edge = valores["voz_edge"]
                tts.vozes_idioma["pt-BR"] = valores["voz_edge"]
            for k in ("tom", "taxa", "efeito"):
                if k in valores:
                    setattr(tts, k, valores[k])
    elif secao == "memoria":
        if "aprender_local" in valores:
            s.setdefault("agent", {})["aprender_local"] = valores["aprender_local"]
        if "reter_operacionais_dias" in valores:
            s.setdefault("maintenance", {})["reter_operacionais_dias"] = valores["reter_operacionais_dias"]
    elif secao == "consumo":
        o = getattr(getattr(agente, "router", None), "otim", None)
        if o is not None:
            o.definir_orcamento(**valores)
    elif secao == "aparencia" and "tema" in valores:
        # o app nativo lê "tema" de data/preferencias.json
        p = ROOT / "data" / "preferencias.json"
        d = seguro.ler_json(p, {}) or {}
        d["tema"] = valores["tema"]
        seguro.gravar_json(p, d)


_cache_perfil = {"mtime": None, "texto": ""}


def bloco_perfil(arq: Path | None = None) -> str:
    """Texto das 'preferências pessoais' para o prompt do sistema (como no Claude.ai)."""
    arq = arq or ARQ_AJUSTES
    try:
        m = arq.stat().st_mtime
    except OSError:
        return ""
    if _cache_perfil["mtime"] != m:
        p = obter(arq)["perfil"]
        partes = []
        if p.get("nome"):
            partes.append(f"O usuário se chama {p['nome']}.")
        if p.get("preferencias"):
            partes.append(p["preferencias"])
        _cache_perfil.update(mtime=m, texto=("## PREFERÊNCIAS DO USUÁRIO (siga sempre)\n" + "\n".join(partes)) if partes else "")
    return _cache_perfil["texto"]


# --------------------------------------------------------------------------- #
# Integrações MCP (config/mcp.json)
# --------------------------------------------------------------------------- #
def _mcp_ler(arq: Path | None = None) -> dict:
    arq = arq or ARQ_MCP
    d = seguro.ler_json(arq, None)
    return d if isinstance(d, dict) else {"servers": {}}


def mcp_listar(arq: Path | None = None) -> list[dict]:
    arq = arq or ARQ_MCP
    out = []
    for nome, cfg in (_mcp_ler(arq).get("servers") or {}).items():
        if isinstance(cfg, dict):
            out.append({"nome": nome, "enabled": bool(cfg.get("enabled")), "command": cfg.get("command", ""),
                        "args": cfg.get("args") or [], "cwd": cfg.get("cwd", ""),
                        "env": {k: mascarar(str(v)) for k, v in (cfg.get("env") or {}).items()}})
    return out


def mcp_salvar(nome: str, cfg: dict, arq: Path | None = None) -> dict:
    arq = arq or ARQ_MCP
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", str(nome or "")):
        raise ValueError("nome: use letras minúsculas, números, - e _ (até 32)")
    cmd = str(cfg.get("command") or "").strip()
    if not cmd or re.search(r"[\r\n\x00]", cmd):
        raise ValueError("informe o comando (ex.: npx)")
    args = cfg.get("args") or []
    if isinstance(args, str):
        import shlex
        args = shlex.split(args, posix=False)
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        raise ValueError("args deve ser uma lista de textos")
    dados = _mcp_ler(arq)
    antigo = (dados.get("servers") or {}).get(nome) or {}
    env = {}
    for k, v in (cfg.get("env") or {}).items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,60}", str(k)):
            raise ValueError(f"nome de variável inválido: {k}")
        v = str(v)
        env[k] = (antigo.get("env") or {}).get(k, "") if v == mascarar(str((antigo.get("env") or {}).get(k, ""))) and v else v
    entrada = {"enabled": bool(cfg.get("enabled", True)), "command": cmd, "args": args}
    if str(cfg.get("cwd") or "").strip():
        entrada["cwd"] = str(cfg["cwd"]).strip()
    if env:
        entrada["env"] = env
    dados.setdefault("servers", {})[nome] = entrada
    seguro.gravar_json(arq, dados)
    return {"nome": nome}


def mcp_remover(nome: str, arq: Path | None = None) -> dict:
    arq = arq or ARQ_MCP
    dados = _mcp_ler(arq)
    existia = nome in (dados.get("servers") or {})
    (dados.get("servers") or {}).pop(nome, None)
    seguro.gravar_json(arq, dados)
    return {"nome": nome, "removido": existia}
