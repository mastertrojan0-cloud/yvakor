"""YVAKOR — respostas diretas de voz/texto (sem IA) para pedidos simples."""
from __future__ import annotations
from yvakor import proc as _ywproc

from datetime import datetime
import re

from yvakor.memory.db import normalizar

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]



def _expressao_da_conta(texto: str) -> str:
    """Só a conta: "quanto é 2+2? responda só o número" → "2+2".
    Pega o maior trecho feito de dígitos, operadores e parênteses depois do gatilho."""
    resto = re.sub(r"^.*?(?:quanto (?:e|é)|calcule|calcular|resultado de)\s*", "",
                   texto, flags=re.I).strip()
    pct = re.search(r"\d+(?:[.,]\d+)?\s*%\s*de\s*\d+(?:[.,]\d+)?", resto, re.I)
    if pct:                                   # "15% de 200"
        return pct.group(0)
    trechos = re.findall(r"[\d(][\d\s+\-*/%x×÷().,^]*", resto)
    trechos = [t.strip().rstrip("+-*/x×÷^,. ") for t in trechos]
    trechos = [t for t in trechos if re.search(r"\d", t) and re.search(r"[+\-*/%x×÷^]", t)]
    return max(trechos, key=len) if trechos else resto.rstrip("?").strip()


_VERBO_MERCADO = re.compile(
    r"\b(analis\w*|an[aá]lise|grafic\w*|gr[aá]fic\w*|tend[eê]ncia|cota[cç][aã]o|como (?:esta|est[aá])|"
    r"stocktwits|rsi|macd|suporte|resist[eê]ncia|sentimento|previs[aã]o|vale a pena)\b", re.I)
_ATIVO_MERCADO = re.compile(
    r"\b(btc|bitcoin|eth|ethereum|solana|bnb|xrp|ripple|cardano|doge|dogecoin|ltc|litecoin|"
    r"avax|matic|zec|zcash|trx|shib|pepe)\b|\$[A-Za-z]{1,6}\b", re.I)


def _intencao_mercado(texto: str):
    """'analise do btc com gráficos e análise stocktwits' → análise completa, sem LLM."""
    if not (_VERBO_MERCADO.search(texto) and _ATIVO_MERCADO.search(texto)):
        return None
    # pedido de CÓDIGO/arquivo sobre o ativo não é análise de mercado
    if re.search(r"\b(c[oó]digo|script|fun[cç][aã]o|arquivo|pasta|bug|erro de)\b", texto, re.I):
        return None
    m = re.search(r"\b(1w|semanal|4h|1h|15m|30m|1d|di[aá]rio|diario)\b", texto, re.I)
    iv = {"semanal": "1w", "diario": "1d", "diário": "1d"}.get((m.group(1).lower() if m else ""), (m.group(1).lower() if m else "1d"))
    return {"acao": "mercado", "ativo": texto, "intervalo": iv}


def detectar(texto: str) -> dict | None:
    low = normalizar(texto or "")
    _mercado = _intencao_mercado(texto or "")
    if _mercado:
        return _mercado
    if low in ("nao funciona", "não funciona", "nao esta funcionando",
               "não está funcionando", "deu erro", "ta com erro",
               "está com erro", "nao sei o que fazer"):
        return {"acao": "ajuda_erro"}
    if any(p in low for p in ("para a musica", "pare a musica", "para o video",
                              "pare o video", "fecha o vlc", "fechar o vlc")):
        return {"acao": "midia_parar"}
    m_midia = re.match(
        r"^(?:toca|toque|reproduz|reproduza|abre no vlc|abra no vlc)\s+(.+)$",
        texto.strip(), re.I)
    if m_midia:
        return {"acao": "midia", "texto": m_midia.group(1).strip()}
    m_foto = re.match(
        r"^(?:busque|buscar|traga|trazer|encontre|encontrar|mostre|mostrar)\s+"
        r"(?:uma\s+|1\s+)?(?:foto|fotografia|imagem)\s+"
        r"(?:real\s+)?(?:de|do|da|sobre)\s+(.+)$",
        texto.strip(), re.I)
    if m_foto:
        termo = re.sub(r"\s*,?\s*(?:e|para)\s+(?:entregue|entregar|envie|"
                       r"mostre|mostrar).*$", "", m_foto.group(1).strip(),
                       flags=re.I)
        return {"acao": "foto", "texto": termo}
    m_rel = re.match(
        r"^(?:gere|gerar|faça|faca|crie|criar|entregue)\s+(?:um\s+)?"
        r"relat[oó]rio\s+(?:(pdf|html|docx|md)\s+)?"
        r"(?:(?:curto|simples|completo|executivo)\s+)?"
        r"(?:sobre|de)\s+(.+)$", texto.strip(), re.I)
    if m_rel:
        return {"acao": "relatorio", "formato": (m_rel.group(1) or "pdf").lower(),
                "texto": m_rel.group(2).strip()}
    m_imagem = re.match(
        r"^(?:gere|gerar|crie|criar|desenhe|desenhar|produza|produzir)\s+"
        r"(?:uma\s+|um\s+)?(?:foto|fotografia|imagem|ilustra[çc][aã]o)\s+"
        r"(?:realista\s+)?(?:de|do|da|sobre)\s+(.+)$",
        texto.strip(), re.I)
    if m_imagem:
        return {"acao": "imagem", "texto": m_imagem.group(1).strip()}
    m_grafico = re.match(
        r"^(?:gere|gerar|faça|faca|crie|criar)\s+(?:um\s+|o\s+)?gr[aá]fico\s+"
        r"(?:de\s+)?(?:(barra|barras|linha|pizza)\s+)?(?:com\s+)?"
        r"(?:os\s+)?(?:valores|dados)\s+(.+)$",
        texto.strip(), re.I)
    if m_grafico:
        return {"acao": "grafico", "tipo": (m_grafico.group(1) or "barra").lower(),
                "dados": m_grafico.group(2).strip()}
    m_pesquisa = re.match(
        r"^(?:pesquise|pesquisar|pesquisa profunda|faça uma pesquisa|"
        r"faca uma pesquisa)\s+(?:sobre\s+|por\s+)?(.+)$",
        texto.strip(), re.I)
    if m_pesquisa:
        return {"acao": "pesquisa", "texto": m_pesquisa.group(1).strip()}
    m_grande = re.match(
        r"^(?:grande tarefa|tarefa grande|processe em segundo plano)\s*[:\-]?\s*(.+)$",
        texto.strip(), re.I)
    if m_grande:
        return {"acao": "grande_tarefa", "texto": m_grande.group(1).strip()}
    if any(p in low for p in ("quais projetos", "liste os projetos",
                              "meus projetos", "projetos no computador",
                              "reconheca os projetos", "reconhecer projetos",
                              "escaneie os projetos", "projetos instalados")):
        return {"acao": "projetos",
                "escanear": ("reconhec" in low or "escane" in low)}
    m_proj = re.match(r"^(?:abra|abrir|abre)\s+(?:o\s+)?projeto\s+(.+)$",
                      texto.strip(), re.I)
    if m_proj:
        return {"acao": "projeto_abrir", "texto": m_proj.group(1).strip()}
    if re.search(r"(quanto (?:e|é)|calcule|calcular|resultado de)", low):
        expr = _expressao_da_conta(texto)
        if re.search(r"\d", expr) and re.search(r"[+\-*/%x×÷]", expr):
            return {"acao": "conta", "texto": texto}
    if (any(p in low for p in ("liste", "listar", "mostre", "o que tem"))
            and any(p in low for p in ("arquivo", "pasta", "conteudo",
                                       "conteúdo", "diretorio", "diretório"))
            and re.search(r"[A-Za-z]:\\|(?:^|\s)(?:\.{1,2}[\\/]|[/~])",
                          texto)):
        return {"acao": "listar_arquivos", "texto": texto}
    if (any(p in low for p in ("leia o arquivo", "ler o arquivo",
                               "mostre o arquivo", "abra o arquivo"))
            and re.search(r"[A-Za-z]:\\|(?:^|\s)(?:\.{1,2}[\\/]|[/~])",
                          texto)):
        return {"acao": "ler_arquivo", "texto": texto}
    if any(p in low for p in ("media de", "média de", "estatistica de",
                              "estatística de", "desvio padrao de")):
        if len(re.findall(r"-?\d+(?:[.,]\d+)?", texto)) >= 2:
            return {"acao": "estatistica", "texto": texto}
    if any(p in low for p in ("saude dos hds", "saude dos discos",
                              "status dos discos", "saude do hd",
                              "saude do ssd", "smart dos discos")):
        return {"acao": "discos"}
    if any(p in low for p in ("especificacoes", "especificações",
                              "configuracao do pc", "configuração do pc",
                              "hardware do computador", "quais as specs",
                              "config do computador")):
        return {"acao": "hardware"}
    if any(p in low for p in ("espaco em disco", "espaço em disco",
                              "espaco livre", "espaço livre", "disco cheio")):
        return {"acao": "espaco"}
    if any(p in low for p in ("que horas", "horas sao", "hora agora",
                              "horas agora", "me diga as horas")):
        return {"acao": "hora"}
    if any(p in low for p in ("que dia", "data de hoje", "dia de hoje",
                              "hoje e que dia", "qual a data")):
        return {"acao": "data"}
    if low in ("status", "status do sistema", "como voce esta",
               "como você está", "tudo bem", "voce esta online"):
        return {"acao": "status"}
    if any(p in low for p in ("repita", "repete", "o que voce disse",
                              "o que você disse")):
        return {"acao": "repetir"}
    if low in ("obrigado", "obrigada", "valeu", "muito obrigado",
               "muito obrigada"):
        return {"acao": "agradecer"}
    if any(p in low for p in ("o que voce faz", "o que você faz",
                              "suas funcoes", "suas funções",
                              "o que voce sabe fazer")):
        return {"acao": "capacidades"}
    return None


def _ps(comando: str) -> str:
    import subprocess
    try:
        p = _ywproc.run(["powershell", "-NoProfile", "-Command", comando],
                           capture_output=True, text=True, timeout=15)
        return (p.stdout or p.stderr or "").strip()
    except Exception as exc:
        return f"falha: {exc}"


def executar(orchestrator, intent: dict, ultima: str = "") -> str:
    agora = datetime.now()
    acao = intent.get("acao")
    texto = intent.get("texto") or ""

    if acao == "ajuda_erro":
        return ("O que exatamente não está funcionando? Se for o navegador, "
                "diga “abre o YouTube no Chrome”; se for uma tarefa, diga o "
                "que você pediu e o que apareceu.")

    if acao == "imagem":
        from pathlib import Path
        from urllib.parse import quote
        try:
            r = orchestrator.tools.run(
                "cap_imagem", prompt=intent.get("texto") or "imagem")
        except Exception as exc:
            return f"Geração de imagem falhou: {exc}"
        if not r.get("ok") or not r.get("arquivo"):
            return f"Geração de imagem falhou: {r.get('erro')}"
        p = Path(r["arquivo"]).resolve()
        foto_alt = None
        # Se o gerador caiu no SVG, tenta uma foto real antes de desistir.
        if p.suffix.lower() == ".svg":
            try:
                alt = orchestrator.tools.run(
                    "buscar_foto", termo=intent.get("texto") or "", quantidade=1)
                if alt.get("ok") and alt.get("fotos"):
                    foto_alt = alt["fotos"][0]
                    p = Path(foto_alt["arquivo"]).resolve()
                    intent["texto"] = foto_alt.get("titulo") or intent.get("texto")
            except Exception:
                pass
        try:
            rel = p.relative_to(Path("data/imagens").resolve())
            url = "/midia/imagens/" + quote(rel.as_posix())
        except Exception:
            try:
                rel = p.relative_to(Path("data/artefatos").resolve())
                url = "/artefatos/" + quote(rel.as_posix())
            except Exception:
                url = ""
        orchestrator.ultimos_artefatos.append({
            "tipo": "imagem", "url": url, "caminho": str(p),
            "titulo": intent.get("texto") or "imagem gerada",
            "autor": (foto_alt or {}).get("autor") or "YVAKOR",
            "licenca": (foto_alt or {}).get("licenca") or "imagem gerada",
            "fonte": (foto_alt or {}).get("fonte") or "IA"})
        return (f"Imagem gerada: **{intent.get('texto')}**\n\n"
                f"![imagem]({url})")

    if acao == "relatorio":
        from pathlib import Path
        from urllib.parse import quote
        assunto = intent.get("texto") or "relatório"
        assunto = re.sub(r",?\s*com\s+\d+\s+se[çc][oõ]es.*$", "", assunto,
                         flags=re.I).strip(" .")
        formato = intent.get("formato") or "pdf"
        try:
            conteudo = orchestrator.router.complete_messages(
                "analise_complexa",
                [{"role": "system", "content":
                  "Você é um analista sênior. Escreva em português, com 3 a 5 "
                  "seções curtas, dados verificáveis, riscos e conclusão. Não "
                  "invente números; quando não souber, diga a limitação."},
                 {"role": "user", "content":
                  f"Escreva um relatório sobre: {assunto}"}]) or ""
        except Exception as exc:
            return f"Não consegui redigir o relatório: {exc}"
        if not conteudo.strip():
            return "Não consegui redigir o conteúdo do relatório."
        try:
            r = orchestrator.tools.run("entregar_relatorio",
                                       titulo=f"Relatório — {assunto[:60]}",
                                       conteudo=conteudo, formato=formato)
        except Exception as exc:
            return f"Relatório falhou: {exc}"
        if not r.get("ok"):
            return f"Relatório falhou: {r.get('erro')}"
        p = Path(r["arquivo"]).resolve()
        try:
            rel = p.relative_to(Path("data/artefatos").resolve())
            url = "/artefatos/" + quote(rel.as_posix())
        except Exception:
            url = ""
        orchestrator.ultimos_artefatos.append({
            "tipo": r.get("tipo") or "pdf", "url": url, "caminho": str(p),
            "titulo": p.name, "nome": p.name})
        return (f"Relatório **{assunto}** gerado em {formato.upper()}.\n\n"
                f"[Abrir {p.name}]({url})")

    if acao == "grafico":
        from pathlib import Path
        from urllib.parse import quote
        vals = re.findall(r"-?\d+(?:[.,]\d+)?", intent.get("dados") or "")
        if len(vals) < 2:
            return "Preciso de pelo menos dois números para gerar o gráfico."
        tipo = intent.get("tipo") or "barra"
        tipo = {"barras": "barra", "bar": "barra", "line": "linha",
                "pie": "pizza"}.get(tipo, tipo)
        try:
            r = orchestrator.tools.run("cap_grafico", tipo=tipo,
                                       dados=", ".join(vals),
                                       titulo="Gráfico YVAKOR")
        except Exception as exc:
            return f"Gráfico falhou: {exc}"
        if not r.get("ok"):
            return f"Gráfico falhou: {r.get('erro')}"
        p = Path(r["arquivo"]).resolve()
        try:
            rel = p.relative_to(Path("data/graficos").resolve())
            url = "/midia/graficos/" + quote(rel.as_posix())
        except Exception:
            url = ""
        orchestrator.ultimos_artefatos.append({
            "tipo": "imagem", "url": url, "caminho": str(p),
            "titulo": p.name})
        return (f"Gráfico de {tipo} gerado com {len(vals)} valores: "
                f"{', '.join(vals)}.\n\n![gráfico]({url})")

    if acao == "foto":
        from pathlib import Path
        from urllib.parse import quote
        try:
            r = orchestrator.tools.run("buscar_foto",
                                       termo=intent.get("texto") or "",
                                       quantidade=1)
        except Exception as exc:
            return f"Busca de foto falhou: {exc}"
        if not r.get("ok") or not r.get("fotos"):
            return f"Não encontrei foto: {r.get('erro') or 'sem resultados'}"
        f = r["fotos"][0]
        try:
            p = Path(f["arquivo"]).resolve()
            try:
                rel = p.relative_to(Path("data/artefatos").resolve())
                url = "/artefatos/" + quote(rel.as_posix())
            except ValueError:
                rel = p.relative_to(Path("data/imagens").resolve())
                url = "/midia/imagens/" + quote(rel.name)
        except Exception:
            url = ""
        orchestrator.ultimos_artefatos.append({
            "tipo": "imagem", "url": url, "caminho": f.get("arquivo"),
            "titulo": f.get("titulo"), "fonte": f.get("fonte"),
            "autor": f.get("autor"), "licenca": f.get("licenca"),
            "url_origem": f.get("url_origem")})
        return (f"Foto encontrada: **{f.get('titulo') or intent.get('texto')}**\n"
                f"Autor: {f.get('autor') or 'desconhecido'} · "
                f"Licença: {f.get('licenca') or 'ver fonte'} · "
                f"Fonte: {f.get('fonte')}\n\n"
                f"![foto]({url})")

    if acao == "pesquisa":
        try:
            r = orchestrator.tools.run("pesquisa_profunda",
                                       pergunta=intent.get("texto") or "",
                                       max_fontes=3)
        except Exception as exc:
            return f"Pesquisa falhou: {exc}"
        if not r.get("ok"):
            return f"Pesquisa falhou: {r.get('erro')}"
        return r.get("resultado") or r.get("resposta") or "Sem resultado."

    if acao == "midia":
        alvo = intent.get("texto") or ""
        p = getattr(orchestrator, "midia", None)
        if p is None:
            return "Player de mídia indisponível."
        r = p.tocar(alvo)
        return (f"Tocando {r.get('titulo') or alvo} no VLC."
                if r.get("ok") else f"Não consegui tocar: {r.get('erro')}")

    if acao == "midia_parar":
        p = getattr(orchestrator, "midia", None)
        if p:
            p.parar()
        return "VLC parado."

    if acao == "grande_tarefa":
        try:
            t = orchestrator.cowork.submit(intent.get("texto") or "")
            return (f"Grande tarefa {t.get('id')} criada e em execução. "
                    "Acompanhe o plano e o resultado no chat.")
        except Exception as exc:
            return f"Não consegui criar a tarefa: {exc}"

    if acao == "projetos":
        g = getattr(orchestrator, "projetos", None)
        if g is None:
            return "Gerenciador de projetos indisponível."
        if intent.get("escanear") or not g.itens:
            g.escanear()
        projs = g.listar()
        if not projs:
            return "Nenhum projeto reconhecido ainda."
        linhas = [f"{p['nome']} — {p['caminho']} ({', '.join(p['tipos'])})"
                  for p in projs[:25]]
        return (f"{len(projs)} projeto(s) reconhecido(s):\n"
                + "\n".join(linhas))

    if acao == "projeto_abrir":
        g = getattr(orchestrator, "projetos", None)
        r = g.abrir(intent.get("texto", "")) if g else {"ok": False,
                                                        "erro": "indisponível"}
        return (f"Abri o projeto {r.get('nome')} em {r.get('caminho')}."
                if r.get("ok") else f"Não encontrei: {r.get('erro')}")

    if acao == "mercado":
        from pathlib import Path
        from urllib.parse import quote
        from yvakor import mercado
        try:
            r = mercado.analisar(intent.get("ativo") or "BTC", intent.get("intervalo") or "1d")
        except Exception as exc:
            return f"A análise de mercado falhou: {exc}"
        if not r.get("ok"):
            return f"Não consegui analisar o ativo: {r.get('erro')}"
        for a in r.get("arquivos", []):
            p = Path(a["arquivo"]).resolve()
            orchestrator.ultimos_artefatos.append({
                "tipo": "imagem", "url": "/midia/graficos/" + quote(p.name),
                "caminho": str(p), "titulo": a.get("titulo") or p.name, "nome": p.name})
        return r["resumo"]

    if acao == "conta":
        from yvakor.capacidades import calcular
        expr = _expressao_da_conta(texto)
        r = calcular(expr)
        return (f"{expr} = {r.get('resultado')}" if r.get("ok")
                else f"Não consegui calcular: {r.get('erro')}")

    if acao == "listar_arquivos":
        from pathlib import Path
        m = re.search(r"(?:de|em|da|do)\s+(.+)$", texto, re.I)
        caminho = (m.group(1).strip().strip('"') if m else ".")
        try:
            p = Path(caminho).expanduser()
            itens = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            linhas = [f"{'📁' if i.is_dir() else '📄'} {i.name}" for i in itens[:25]]
            return (f"{p} — {len(itens)} item(ns):\n" + "\n".join(linhas))
        except Exception as exc:
            return f"Não consegui listar {caminho}: {exc}"

    if acao == "ler_arquivo":
        from pathlib import Path
        m = re.search(r"(?:arquivo)\s+(.+)$", texto, re.I)
        caminho = (m.group(1).strip().strip('"') if m else "")
        try:
            return Path(caminho).expanduser().read_text(
                encoding="utf-8", errors="replace")[:1500]
        except Exception as exc:
            return f"Não consegui ler {caminho}: {exc}"

    if acao == "estatistica":
        from yvakor.capacidades import estatisticas
        nums = re.findall(r"-?\d+(?:[.,]\d+)?", texto)
        r = estatisticas(nums)
        if not r.get("ok"):
            return r.get("erro") or "Sem números."
        return (f"n={r['n']} · média {r['media']} · mediana {r['mediana']} · "
                f"desvio {r['desvio_padrao']} · mín {r['min']} · máx {r['max']}")
    if acao == "discos":
        saida = _ps("Get-PhysicalDisk | ForEach-Object { "
                    "\"$($_.FriendlyName): $($_.MediaType), $($_.HealthStatus), "
                    "$([math]::Round($_.Size/1GB)) GB\" }")
        return saida or "Não encontrei discos."
    if acao == "hardware":
        return _ps("$c=Get-CimInstance Win32_ComputerSystem; "
                   "$p=Get-CimInstance Win32_Processor; "
                   "$o=Get-CimInstance Win32_OperatingSystem; "
                   "\"$($c.Manufacturer) $($c.Model). CPU: $($p.Name). "
                   "RAM: $([math]::Round($c.TotalPhysicalMemory/1GB)) GB. "
                   "SO: $($o.Caption).\"") or "Não consegui ler o hardware."
    if acao == "espaco":
        saida = _ps("Get-PSDrive -PSProvider FileSystem | ForEach-Object { "
                    "\"$($_.Name): $([math]::Round($_.Free/1GB,1)) GB livres "
                    "de $([math]::Round(($_.Used+$_.Free)/1GB,1)) GB\" }")
        return saida or "Não consegui ler os discos."
    if acao == "hora":
        return f"São {agora.hour} horas e {agora.minute} minutos."
    if acao == "data":
        return (f"Hoje é {DIAS[agora.weekday()]}, {agora.day} de "
                f"{MESES[agora.month - 1]} de {agora.year}.")
    if acao == "status":
        total = 0
        try:
            total = len(orchestrator.rede.registro.listar())
        except Exception:
            pass
        return (f"Estou online. Conheço {total} dispositivo(s) na rede e "
                "posso ouvir, ver a câmera, pesquisar e executar tarefas.")
    if acao == "repetir":
        return ultima or "Ainda não tenho uma resposta anterior para repetir."
    if acao == "agradecer":
        return "De nada. Estou aqui se precisar."
    if acao == "capacidades":
        return ("Posso redigir e corrigir textos, calcular e fazer estatística, "
                "gerar gráficos e imagens, programar e abrir aplicativos, "
                "controlar câmeras/TV/rede e consultar a memória.")
    return ""
