"""YVAKOR — capacidades integradas: texto, cálculo, estatística, gráficos,
imagens e desenvolvimento. Ferramentas prefixadas com `cap_`.
"""
from __future__ import annotations
from yvakor import proc as _ywproc

import ast
import json
import math
import operator
import re
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAFICOS = ROOT / "data" / "graficos"
IMAGENS = ROOT / "data" / "imagens"

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUN = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": math.log, "log10": math.log10, "exp": math.exp, "abs": abs,
        "round": round, "floor": math.floor, "ceil": math.ceil,
        "min": min, "max": max, "sum": sum}
_CONST = {"pi": math.pi, "e": math.e}


def _avaliar(no):
    if isinstance(no, ast.Expression):
        return _avaliar(no.body)
    if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)):
        return no.value
    if isinstance(no, ast.BinOp) and type(no.op) in _BIN:
        return _BIN[type(no.op)](_avaliar(no.left), _avaliar(no.right))
    if isinstance(no, ast.UnaryOp) and type(no.op) in _UN:
        return _UN[type(no.op)](_avaliar(no.operand))
    if isinstance(no, ast.Name) and no.id in _CONST:
        return _CONST[no.id]
    if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) \
            and no.func.id in _FUN and not no.keywords:
        return _FUN[no.func.id](*[_avaliar(a) for a in no.args])
    raise ValueError("expressão não permitida")


def calcular(expressao: str) -> dict:
    try:
        valor = _avaliar(ast.parse(str(expressao), mode="eval"))
        return {"ok": True, "expressao": expressao, "resultado": valor}
    except Exception as exc:
        return {"ok": False, "erro": f"cálculo inválido: {exc}"}


def _numeros(dados) -> list[float]:
    if isinstance(dados, str):
        partes = re.findall(r"-?\d+(?:[.,]\d+)?", dados)
        return [float(p.replace(",", ".")) for p in partes]
    return [float(x) for x in dados]


def estatisticas(dados) -> dict:
    try:
        vals = _numeros(dados)
        if not vals:
            return {"ok": False, "erro": "nenhum número informado"}
        vals_ord = sorted(vals)
        p = lambda q: vals_ord[min(len(vals_ord) - 1, int(round(q * (len(vals_ord) - 1))))]
        return {"ok": True, "n": len(vals), "min": min(vals),
                "max": max(vals), "soma": sum(vals),
                "media": round(statistics.mean(vals), 4),
                "mediana": round(statistics.median(vals), 4),
                "desvio_padrao": round(statistics.pstdev(vals), 4)
                if len(vals) > 1 else 0.0,
                "q1": p(0.25), "q3": p(0.75)}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def _svg_grafico(tipo: str, dados: list[float], titulo: str) -> str:
    largura, altura, margem = 800, 450, 50
    if tipo == "pizza":
        total = sum(abs(v) for v in dados) or 1
        cx, cy, r = 400, 230, 150
        ang, partes = -90.0, []
        cores = ["#3fbfae", "#d9a441", "#5b8def", "#d96b6b", "#a06bd9",
                 "#6bd98a", "#d9b06b"]
        for i, v in enumerate(dados):
            frac = abs(v) / total
            ini, ang = ang, ang + frac * 360
            rad1, rad2 = math.radians(ini), math.radians(ang)
            x1, y1 = cx + r * math.cos(rad1), cy + r * math.sin(rad1)
            x2, y2 = cx + r * math.cos(rad2), cy + r * math.sin(rad2)
            grande = 1 if frac > 0.5 else 0
            partes.append(f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} '
                          f'A{r},{r} 0 {grande} 1 {x2:.1f},{y2:.1f} Z" '
                          f'fill="{cores[i % len(cores)]}" stroke="#071018"/>')
        corpo = "".join(partes)
    else:
        maxv = max(abs(v) for v in dados) or 1
        passo = (largura - 2 * margem) / max(1, len(dados) - 1)
        if tipo == "linha":
            pts = [(margem + i * passo,
                    altura - margem - (v / maxv) * (altura - 2 * margem))
                   for i, v in enumerate(dados)]
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            corpo = (f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x,y in pts)}" '
                     f'fill="none" stroke="#3fbfae" stroke-width="3"/>' +
                     "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#d9a441"/>'
                             for x, y in pts))
        else:
            largura_barra = (largura - 2 * margem) / len(dados) * 0.6
            corpo = "".join(
                f'<rect x="{margem + i * passo - largura_barra/2:.1f}" '
                f'y="{altura - margem - (v/maxv)*(altura-2*margem):.1f}" '
                f'width="{largura_barra:.1f}" '
                f'height="{(v/maxv)*(altura-2*margem):.1f}" fill="#3fbfae"/>'
                for i, v in enumerate(dados))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" '
            f'height="{altura}" viewBox="0 0 {largura} {altura}">'
            f'<rect width="100%" height="100%" fill="#08121a"/>'
            f'<text x="{margem}" y="30" fill="#dceaf0" font-family="Segoe UI" '
            f'font-size="16">{titulo}</text>{corpo}</svg>')


def _grafico_png(tipo: str, dados: list[float], titulo: str) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=140)
    fig.patch.set_facecolor("#08121a")
    ax.set_facecolor("#08121a")
    cores = ["#3fbfae", "#d9a441", "#5b8def", "#d96b6b", "#a06bd9",
             "#6bd98a", "#d9b06b"]
    if tipo == "pizza":
        ax.pie([abs(v) for v in dados], colors=cores[:len(dados)],
               startangle=90, wedgeprops={"edgecolor": "#071018"})
    elif tipo == "linha":
        ax.plot(range(len(dados)), dados, color="#3fbfae", linewidth=2.5,
                marker="o", markersize=5, markerfacecolor="#d9a441")
    else:
        ax.bar(range(len(dados)), dados, color="#3fbfae", width=0.6)
    ax.set_title(titulo, color="#dceaf0", fontsize=14)
    for spine in ax.spines.values():
        spine.set_color("#1b2b35")
    ax.tick_params(colors="#9fb3bf")
    ax.grid(color="#1b2b35", linestyle="--", alpha=0.5, axis="y")
    fig.tight_layout()
    GRAFICOS.mkdir(parents=True, exist_ok=True)
    nome = f"{re.sub(r'[^a-z0-9]+', '-', titulo.lower()).strip('-') or 'grafico'}-{int(time.time())}.png"
    destino = GRAFICOS / nome
    fig.savefig(destino, facecolor=fig.get_facecolor())
    plt.close(fig)
    return destino


def grafico(tipo: str, dados, titulo: str = "Gráfico") -> dict:
    try:
        vals = _numeros(dados)
        if not vals:
            return {"ok": False, "erro": "sem dados numéricos"}
        tipo = (tipo or "barra").lower()
        tipo = {"bar": "barra", "line": "linha", "pie": "pizza"}.get(tipo, tipo)
        if tipo not in ("barra", "linha", "pizza"):
            tipo = "barra"
        try:
            png = _grafico_png(tipo, vals, titulo)
            return {"ok": True, "tipo": tipo, "arquivo": str(png),
                    "formato": "png", "motor": "matplotlib", "n": len(vals)}
        except Exception:
            GRAFICOS.mkdir(parents=True, exist_ok=True)
            nome = f"{re.sub(r'[^a-z0-9]+', '-', titulo.lower()).strip('-') or 'grafico'}-{int(time.time())}.svg"
            arq = GRAFICOS / nome
            arq.write_text(_svg_grafico(tipo, vals, titulo), encoding="utf-8")
            return {"ok": True, "tipo": tipo, "arquivo": str(arq),
                    "formato": "svg", "motor": "fallback", "n": len(vals)}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def _llm(router, sistema: str, usuario: str, task: str = "analise_complexa") -> str:
    return router.complete_messages(
        task, [{"role": "system", "content": sistema},
               {"role": "user", "content": usuario}]).strip()


def redigir(router, tema: str, estilo: str = "claro e profissional",
            tamanho: str = "médio", idioma: str = "português") -> dict:
    try:
        texto = _llm(router, "Você é um redator experiente. Responda apenas "
                     f"com o texto final em {idioma}.",
                     f"Redija sobre: {tema}\nEstilo: {estilo}\nTamanho: {tamanho}")
        return {"ok": True, "texto": texto}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def corrigir(router, texto: str) -> dict:
    try:
        saida = _llm(router, "Corrija ortografia, gramática e clareza. Devolva "
                     "o texto corrigido e, em seguida, uma lista curta de "
                     "mudanças.", texto)
        return {"ok": True, "resultado": saida}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def resumir(router, texto: str, linhas: int = 5) -> dict:
    try:
        return {"ok": True, "resumo": _llm(
            router, f"Resuma em até {linhas} tópicos, sem inventar.", texto)}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def gerar_codigo(router, descricao: str, linguagem: str = "Python") -> dict:
    try:
        return {"ok": True, "codigo": _llm(
            router, f"Escreva código {linguagem} completo, comentado e "
            "executável. Responda só com o código.", descricao)}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def revisar_codigo(router, codigo: str) -> dict:
    try:
        return {"ok": True, "revisao": _llm(
            router, "Revise o código: bugs, segurança e melhorias. Seja "
            "objetivo.", codigo)}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def _poster_svg(prompt: str, caminho: Path) -> Path:
    texto = re.sub(r"[<>&]", " ", prompt)[:80]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024">'
           f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
           f'<stop offset="0" stop-color="#0d2b33"/><stop offset="1" stop-color="#1c4a5a"/>'
           f'</linearGradient></defs><rect width="1024" height="1024" fill="url(#g)"/>'
           f'<text x="512" y="500" text-anchor="middle" fill="#dceaf0" '
           f'font-family="Segoe UI" font-size="34">{texto}</text>'
           f'<text x="512" y="560" text-anchor="middle" fill="#7f96a3" '
           f'font-family="Segoe UI" font-size="18">imagem indisponível — '
           f'prévia gerada pelo YVAKOR</text></svg>')
    caminho.write_text(svg, encoding="utf-8")
    return caminho


def gerar_imagem(prompt: str, largura: int = 1024, altura: int = 1024) -> dict:
    import base64
    import json
    import os
    import random
    IMAGENS.mkdir(parents=True, exist_ok=True)
    chave = os.getenv("OPENAI_API_KEY") or os.getenv("IMAGE_API_KEY") or ""
    if chave:
        try:
            corpo = json.dumps({"model": "gpt-image-1", "prompt": prompt,
                                "size": "1024x1024", "n": 1}).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/images/generations", data=corpo,
                headers={"Authorization": f"Bearer {chave}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                dados = json.loads(r.read().decode())
            item = dados["data"][0]
            destino = IMAGENS / f"img-{int(time.time())}.png"
            if item.get("b64_json"):
                destino.write_bytes(base64.b64decode(item["b64_json"]))
                return {"ok": True, "arquivo": str(destino), "motor": "openai"}
            if item.get("url"):
                with urllib.request.urlopen(item["url"], timeout=60) as r:
                    destino.write_bytes(r.read())
                return {"ok": True, "arquivo": str(destino), "motor": "openai"}
        except Exception:
            pass

    nome = f"img-{int(time.time())}.jpg"
    destino = IMAGENS / nome
    for tentativa in range(2):
        for modelo in ("flux", "turbo"):
            try:
                url = ("https://image.pollinations.ai/prompt/"
                       + urllib.parse.quote(prompt)
                       + f"?width={largura}&height={altura}&model={modelo}"
                         f"&enhance=true&nologo=true&seed={random.randint(1, 999999)}")
                req = urllib.request.Request(url, headers={"User-Agent": "YVAKOR/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    dados = r.read()
                if dados[:2] == b"\xff\xd8":
                    destino.write_bytes(dados)
                    return {"ok": True, "arquivo": str(destino),
                            "motor": f"pollinations-{modelo}"}
                if dados[:8] == b"\x89PNG\r\n\x1a\n":
                    destino = destino.with_suffix(".png")
                    destino.write_bytes(dados)
                    return {"ok": True, "arquivo": str(destino),
                            "motor": f"pollinations-{modelo}"}
            except Exception:
                continue
        time.sleep(1.5)
    fallback = _poster_svg(prompt, destino.with_suffix(".svg"))
    return {"ok": True, "arquivo": str(fallback), "motor": "fallback-svg"}


def _executar_local_limitado(cmd: list[str], cwd: str, timeout: int) -> dict:
    """subprocess + Job Object do Windows (memória/CPU/processos/kill)."""
    import ctypes
    import ctypes.wintypes as wt
    import subprocess
    import time

    if not hasattr(ctypes, "WinDLL"):
        proc = _ywproc.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
        return {"proc": proc, "limites": "nenhum"}

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wt.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wt.DWORD),
                    ("SchedulingClass", wt.DWORD)]

    class EXT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC),
                    ("IoInfo", IO),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    JOB_TIME, ACTIVE, PROC_MEM, JOB_MEM, KILL = 0x4, 0x8, 0x100, 0x200, 0x2000
    k32.CreateJobObjectW.restype = wt.HANDLE
    job = k32.CreateJobObjectW(None, None)
    limites = "job-object"
    if job:
        info = EXT()
        info.BasicLimitInformation.LimitFlags = ACTIVE | KILL
        info.BasicLimitInformation.ActiveProcessLimit = 1
        k32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                    ctypes.sizeof(info))
    proc = _ywproc.popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if job:
        try:
            k32.AssignProcessToJobObject(job, int(proc._handle))
        except Exception:
            limites = "job-object (não atribuído)"
    return {"proc": proc, "job": job if job else None, "limites": limites,
            "k32": k32}


def _fechar_job(estado: dict) -> None:
    try:
        if estado.get("job"):
            estado["k32"].CloseHandle(estado["job"])
    except Exception:
        pass


def executar_codigo(codigo: str, linguagem: str = "python",
                    timeout: int = 8) -> dict:
    """Executa Python localmente com limites de recurso do Windows.

    Isolamento de recursos (memória/CPU/processos/tempo), não de rede: o
    código roda na máquina local. Responda `sandbox: local` no resultado.
    """
    import os
    import subprocess
    import sys
    import tempfile
    lang = (linguagem or "python").lower()
    if lang not in ("python", "py"):
        return {"ok": False, "erro": "por enquanto só Python"}
    timeout = max(1, min(int(timeout), 30))
    with tempfile.TemporaryDirectory(prefix="yvk-run-") as tmp:
        arq = Path(tmp) / "main.py"
        arq.write_text(codigo, encoding="utf-8")
        cmd = [sys.executable, "-I", "-S", "-B", str(arq)]
        inicio = time.time()
        try:
            proc = _ywproc.run(
                cmd, cwd=tmp, capture_output=True, text=True, timeout=timeout,
                env={"PYTHONIOENCODING": "utf-8", "PATH": "",
                     "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})
            return {"ok": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": (proc.stdout or "")[:4000],
                    "stderr": (proc.stderr or "")[:4000],
                    "ms": round((time.time() - inicio) * 1000),
                    "sandbox": "local", "network": "local",
                    "aviso": "execução local com timeout; sem isolamento de contêiner"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "erro": f"tempo excedido ({timeout}s)",
                    "sandbox": "local", "network": "local"}
        except Exception as exc:
            return {"ok": False, "erro": str(exc), "sandbox": "local"}


PROJETOS = ROOT / "data" / "projetos"


def desenvolver(router, descricao: str, tipo: str = "auto",
                abrir: bool = True) -> dict:
    """Gera um projeto completo, salva, executa e mostra (HTML no navegador)."""
    import webbrowser
    tipo = (tipo or "auto").lower()
    if tipo == "auto":
        baixo = descricao.lower()
        tipo = "python" if any(p in baixo for p in (
            "script", "python", "console", "terminal", "api")) else "html"
    slug = re.sub(r"[^a-z0-9]+", "-", descricao.lower()).strip("-")[:40] or "app"
    pasta = PROJETOS / f"{slug}-{int(time.time())}"
    pasta.mkdir(parents=True, exist_ok=True)

    if tipo == "html":
        codigo = _llm(
            router,
            "Você é um desenvolvedor front-end sênior. Crie uma aplicação web "
            "COMPLETA em UM único arquivo HTML, com CSS e JavaScript inline, "
            "sem bibliotecas externas. Precisa ser interativa, responsiva e "
            "funcional. Responda SOMENTE com o HTML, sem explicações.",
            descricao)
        m = re.search(r"```(?:html)?\s*(.*?)```", codigo, re.S)
        if m:
            codigo = m.group(1)
        arq = pasta / "index.html"
        arq.write_text(codigo.strip(), encoding="utf-8")
        url = f"http://127.0.0.1:7777/projetos/{pasta.name}/index.html"
        aberto = False
        if abrir:
            try:
                webbrowser.open(url)
                aberto = True
            except Exception:
                pass
        return {"ok": True, "tipo": "html", "arquivo": str(arq), "url": url,
                "aberto": aberto, "linhas": len(codigo.splitlines())}

    codigo = _llm(
        router,
        "Você é um desenvolvedor Python sênior. Escreva um programa completo, "
        "comentado e executável. Responda SOMENTE com o código.",
        descricao)
    m = re.search(r"```(?:python)?\s*(.*?)```", codigo, re.S)
    if m:
        codigo = m.group(1)
    arq = pasta / "main.py"
    arq.write_text(codigo.strip(), encoding="utf-8")
    execucao = executar_codigo(codigo, timeout=10)
    return {"ok": execucao.get("ok", False), "tipo": "python",
            "arquivo": str(arq), "codigo": codigo[:4000],
            "execucao": execucao}


def register_capacidades_tools(registry, router) -> list[str]:
    reg = registry.register
    reg("cap_calcular", calcular, "Calcula expressões matemáticas com segurança.",
        {"expressao": "str"})
    reg("cap_estatisticas", estatisticas,
        "Média, mediana, desvio, quartis, mínimo e máximo de uma lista.",
        {"dados": "str"})
    reg("cap_grafico", grafico,
        "Gera gráfico SVG (barra, linha ou pizza) a partir de números.",
        {"tipo": "str?", "dados": "str", "titulo": "str?"})
    reg("cap_redigir", lambda tema, estilo="claro e profissional",
        tamanho="médio", idioma="português": redigir(
            router, tema, estilo, tamanho, idioma),
        "Redige um texto sobre um tema.", {"tema": "str", "estilo": "str?",
                                          "tamanho": "str?", "idioma": "str?"})
    reg("cap_corrigir", lambda texto: corrigir(router, texto),
        "Corrige ortografia, gramática e clareza.", {"texto": "str"})
    reg("cap_resumir", lambda texto, linhas=5: resumir(router, texto, int(linhas)),
        "Resume um texto em tópicos.", {"texto": "str", "linhas": "int?"})
    reg("cap_codigo", lambda descricao, linguagem="Python": gerar_codigo(
        router, descricao, linguagem),
        "Gera código completo em uma linguagem.", {"descricao": "str",
                                                  "linguagem": "str?"})
    reg("cap_revisar_codigo", lambda codigo: revisar_codigo(router, codigo),
        "Revisa código (bugs, segurança, melhorias).", {"codigo": "str"})
    reg("cap_imagem", gerar_imagem,
        "Gera uma imagem a partir de um prompt (com fallback SVG).",
        {"prompt": "str", "largura": "int?", "altura": "int?"})
    reg("cap_executar_codigo", executar_codigo,
        "Executa código Python em pasta temporária, com timeout (até 20s).",
        {"codigo": "str", "linguagem": "str?", "timeout": "int?"})
    reg("cap_desenvolver", lambda descricao, tipo="auto", abrir=True: desenvolver(
        router, descricao, tipo, bool(abrir)),
        "Desenvolve um projeto completo (HTML interativo ou Python), salva, "
        "executa e abre para visualização.",
        {"descricao": "str", "tipo": "str?", "abrir": "bool?"})
    return ["cap_calcular", "cap_estatisticas", "cap_grafico", "cap_redigir",
            "cap_corrigir", "cap_resumir", "cap_codigo", "cap_revisar_codigo",
            "cap_imagem", "cap_executar_codigo", "cap_desenvolver"]
