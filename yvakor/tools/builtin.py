"""
YVAKOR — Ferramentas nativas (capacidades reais do agente).

Cada ferramenta é uma função simples que devolve um valor serializável.
São registradas no ToolRegistry; ações com efeito colateral passam pelo
Confirmation Guard antes de rodar (ver tools/guard.py).

Dependências: apenas stdlib (roda em qualquer máquina). Ferramentas que
precisem de libs extras degradam com mensagem clara em vez de quebrar.
"""
from __future__ import annotations
import re
import json
import subprocess
from yvakor import proc as _ywproc
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SANDBOX = ROOT / "data" / "sandbox"

# Caminho do Higgsfield CLI (npm global no Windows)
_HIGGSFIELD = None


def _find_higgsfield() -> str | None:
    global _HIGGSFIELD
    if _HIGGSFIELD:
        return _HIGGSFIELD
    import shutil
    _HIGGSFIELD = shutil.which("higgsfield") or shutil.which("higgsfield.cmd") \
        or shutil.which("higgsfield.ps1")
    if not _HIGGSFIELD:
        # Fallback: caminho padrao do npm global no Windows
        padrao = Path.home() / "AppData" / "Roaming" / "npm" / "higgsfield.cmd"
        if padrao.exists():
            _HIGGSFIELD = str(padrao)
    return _HIGGSFIELD


# ----------------------------------------------------------------------- #
# Documentos brasileiros (CPF / CNPJ) — lógica pura, sem rede
# ----------------------------------------------------------------------- #
def _digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def validar_documento(doc: str) -> dict:
    """Valida e formata CPF (11) ou CNPJ (14). Retorna validade, tipo, formatado."""
    n = _digitos(doc)
    if len(n) == 11:
        return _validar_cpf(n)
    if len(n) == 14:
        return _validar_cnpj(n)
    return {"valido": False, "tipo": None, "formatado": None,
            "erro": "comprimento inválido (esperado 11=CPF ou 14=CNPJ)"}


def _validar_cpf(n: str) -> dict:
    def dv(parte: str) -> int:
        s = sum(int(d) * w for d, w in zip(parte, range(len(parte) + 1, 1, -1)))
        r = (s * 10) % 11
        return 0 if r == 10 else r
    ok = (len(set(n)) > 1 and dv(n[:9]) == int(n[9]) and dv(n[:10]) == int(n[10]))
    fmt = f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"
    return {"valido": ok, "tipo": "pf", "formatado": fmt}


def _validar_cnpj(n: str) -> dict:
    def dv(parte: str, pesos: list[int]) -> int:
        s = sum(int(d) * p for d, p in zip(parte, pesos))
        r = s % 11
        return 0 if r < 2 else 11 - r
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6] + p1
    ok = (len(set(n)) > 1 and dv(n[:12], p1) == int(n[12])
          and dv(n[:13], p2) == int(n[13]))
    fmt = f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"
    return {"valido": ok, "tipo": "pj", "formatado": fmt}


# ----------------------------------------------------------------------- #
# Web — GET de leitura (pesquisa, enriquecimento de lead)
# ----------------------------------------------------------------------- #
_DOMINIO = re.compile(r"^(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(:\d+)?([/?#].*)?$", re.I)


def normalizar_url(url) -> str | None:
    """"sefaz.am.gov.br/x" → "https://sefaz.am.gov.br/x". None se não parece
    um endereço web (o modelo às vezes manda o nome do site ou nada)."""
    u = str(url or "").strip().strip("<>\"'")
    if u.lower().startswith(("http://", "https://")):
        return u
    if u.startswith("//"):
        u = u[2:]
    return "https://" + u if _DOMINIO.match(u) else None


def http_get(url: str, max_chars: int = 8000) -> dict:
    """GET simples; devolve texto truncado. Apenas leitura (sem POST)."""
    url = normalizar_url(url)
    if not url:
        return {"ok": False, "erro": "url inválida: passe o endereço completo, "
                                     "ex.: https://site.com.br/pagina"}
    req = urllib.request.Request(url, headers={"User-Agent": "YVAKOR/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(max_chars * 4).decode("utf-8", errors="replace")
    return {"ok": True, "url": url, "texto": raw[:max_chars]}


# ----------------------------------------------------------------------- #
# Arquivos — confinados ao sandbox (data/sandbox)
# ----------------------------------------------------------------------- #
def _resolver_sandbox(nome: str) -> Path:
    SANDBOX.mkdir(parents=True, exist_ok=True)
    # Evita aninhar quando o modelo já passa "data/sandbox/..." no nome.
    n = str(nome).replace("\\", "/").lstrip("/")
    for pref in ("data/sandbox/", "sandbox/"):
        if n.lower().startswith(pref):
            n = n[len(pref):]
    alvo = (SANDBOX / n).resolve()
    if SANDBOX.resolve() not in alvo.parents and alvo != SANDBOX.resolve():
        raise ValueError("caminho fora do sandbox não é permitido")
    return alvo


def ler_arquivo(nome: str) -> dict:
    alvo = _resolver_sandbox(nome)
    if not alvo.exists():
        return {"ok": False, "erro": "arquivo não existe no sandbox"}
    return {"ok": True, "conteudo": alvo.read_text(encoding="utf-8", errors="replace")}


def escrever_arquivo(nome: str, conteudo: str) -> dict:
    """GUARDED (delete_file/escrita): registra arquivo no sandbox."""
    alvo = _resolver_sandbox(nome)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(conteudo, encoding="utf-8")
    return {"ok": True, "caminho": str(alvo.relative_to(ROOT))}


# ----------------------------------------------------------------------- #
# Execução de Python no sandbox (timeout) — GUARDED
# ----------------------------------------------------------------------- #
def executar_python(codigo: str, timeout: int = 15) -> dict:
    """Roda código Python isolado em data/sandbox com timeout. GUARDED."""
    SANDBOX.mkdir(parents=True, exist_ok=True)
    script = SANDBOX / "_run.py"
    script.write_text(codigo, encoding="utf-8")
    try:
        p = _ywproc.run([sys.executable, str(script)], cwd=str(SANDBOX),
                           capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "stdout": p.stdout[-6000:],
                "stderr": p.stderr[-3000:], "returncode": p.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "erro": f"timeout após {timeout}s"}


# ----------------------------------------------------------------------- #
# Acesso REAL ao computador (estilo Claude Code) — leitura livre, escrita
# e shell passam pelo Confirmation Guard.
# ----------------------------------------------------------------------- #
def listar_diretorio(caminho: str = ".") -> dict:
    p = Path(caminho).expanduser()
    if not p.exists():
        return {"ok": False, "erro": "caminho não existe"}
    if p.is_file():
        return {"ok": True, "tipo": "arquivo", "itens": [p.name]}
    itens = []
    for f in sorted(p.iterdir()):
        itens.append(("[dir] " if f.is_dir() else "") + f.name)
    return {"ok": True, "tipo": "diretorio", "caminho": str(p), "itens": itens[:500]}


def ler_arquivo_local(caminho: str, max_chars: int = 20000) -> dict:
    """Lê qualquer arquivo do PC (somente leitura)."""
    p = Path(caminho).expanduser()
    if not p.exists() or not p.is_file():
        return {"ok": False, "erro": "arquivo não encontrado"}
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "erro": str(e)}
    return {"ok": True, "caminho": str(p), "conteudo": txt[:max_chars],
            "truncado": len(txt) > max_chars}


def escrever_arquivo_local(caminho: str, conteudo: str) -> dict:
    """Cria/sobrescreve arquivo no PC. GUARDED."""
    p = Path(caminho).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(conteudo, encoding="utf-8")
    return {"ok": True, "caminho": str(p), "bytes": len(conteudo.encode())}


def editar_arquivo_local(caminho: str, busca: str, troca: str) -> dict:
    """Substitui a 1ª ocorrência de `busca` por `troca` no arquivo. GUARDED."""
    p = Path(caminho).expanduser()
    if not p.exists():
        return {"ok": False, "erro": "arquivo não existe"}
    texto = p.read_text(encoding="utf-8", errors="replace")
    if busca not in texto:
        return {"ok": False, "erro": "texto de busca não encontrado"}
    p.write_text(texto.replace(busca, troca, 1), encoding="utf-8")
    return {"ok": True, "caminho": str(p)}


def executar_shell(comando: str, timeout: int = 25, cwd: str | None = None) -> dict:
    """Executa um comando no shell do sistema com timeout. GUARDED."""
    try:
        import re
        from yvakor.extensao_bridge import PONTE
        if (not getattr(PONTE, "permitir_outro", False)
                and re.search(r"\b(msedge|chrome|firefox|brave)\b", comando or "",
                              re.I)):
            return {"ok": False, "error":
                    "Não abra navegador pelo shell. Use navegador_abrir para "
                    "abrir na janela da extensão."}
    except Exception:
        pass
    try:
        p = _ywproc.run(comando, shell=True, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
        return {"ok": p.returncode == 0, "stdout": p.stdout[-8000:],
                "stderr": p.stderr[-4000:], "returncode": p.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "erro": f"timeout após {timeout}s"}


# ----------------------------------------------------------------------- #
# Geração de imagens — Perchance.org + suporte a Higgsfield
# ----------------------------------------------------------------------- #
def gerar_imagem(prompt: str, resolucao: str = "512x768",
                 guidance: int = 7, seed: str = "") -> dict:
    """Gera imagem: tenta Higgsfield primeiro, depois Perchance no navegador.
       Sempre retorna o caminho absoluto do arquivo gerado."""
    import webbrowser

    # Prioridade 1: Higgsfield (programatico, rapido, baixa automatico)
    hf = _find_higgsfield()
    hf_ok = False
    if hf:
        try:
            p = _ywproc.run([hf, "account", "status"],
                               capture_output=True, text=True, timeout=8)
            if p.returncode == 0:
                hf_ok = True
        except Exception:
            pass

    if hf_ok:
        aspecto = "9:16" if "768" in resolucao.split("x")[1] else "1:1"
        cmd = [hf, "generate", "create", "gpt_image_2",
               "--prompt", prompt, "--aspect_ratio", aspecto,
               "--resolution", "2k", "--wait", "--wait-timeout", "5m"]
        try:
            p = _ywproc.run(cmd, capture_output=True, text=True, timeout=360)
            url_line = ""
            for line in (p.stdout + p.stderr).splitlines():
                line = line.strip()
                if line.startswith("http"):
                    url_line = line
                    break
            if url_line:
                dl = _baixar_url(url_line, prefix="higgsfield_")
                if dl.get("ok"):
                    return {"ok": True, "provedor": "higgsfield",
                            "prompt": prompt,
                            "caminho_absoluto": dl["caminho_absoluto"],
                            "url": url_line,
                            "tamanho_bytes": dl["tamanho_bytes"]}
            return {"ok": False, "erro": "URL nao encontrada na saida do Higgsfield",
                    "stdout": p.stdout[-300:]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "erro": "Higgsfield timeout (5min)"}
        except Exception as e:
            pass  # fallback para Perchance

    # Prioridade 2: Perchance (abre navegador, gratuito e sem login)
    params = json.dumps({
        "prompt": prompt, "resolution": resolucao,
        "guidanceScale": guidance, "seed": seed or None,
        "hideGalleryButtons": True})
    enc = urllib.parse.quote(params)
    url = f"https://ai-text-to-image-generator.perchance.org/embed#{enc}"
    webbrowser.open(url)
    return {"ok": True, "provedor": "perchance",
            "prompt": prompt,
            "status": "aberto no navegador. A imagem aparece na pagina.",
            "dica": "clique com botao direito na imagem > Salvar imagem como..."}


def gerar_imagem_higgsfield(prompt: str, estilo: str = "foto",
                            proporcao: str = "1:1") -> dict:
    """Gera imagem via Higgsfield CLI e faz download automatico para o PC.
       Requer 'higgsfield auth login' previo.
       Retorna o caminho absoluto do arquivo baixado."""
    hf = _find_higgsfield()
    if not hf:
        return {"ok": False, "erro": "Higgsfield CLI nao encontrado. Rode: npm i -g @higgsfield/cli"}
    try:
        p = _ywproc.run([hf, "account", "status"],
                           capture_output=True, text=True, timeout=10)
        if p.returncode != 0:
            return {"ok": False, "erro": "Higgsfield nao autenticado. Rode: higgsfield auth login"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}

    try:
        cmd = [hf, "generate", "create", "gpt_image_2",
               "--prompt", prompt, "--aspect_ratio", proporcao,
               "--resolution", "2k", "--wait", "--wait-timeout", "5m"]
        p = _ywproc.run(cmd, capture_output=True, text=True, timeout=360)
        url_line = ""
        for line in (p.stdout + p.stderr).splitlines():
            line = line.strip()
            if line.startswith("http"):
                url_line = line
                break
        if not url_line:
            return {"ok": False, "erro": "URL nao encontrada na saida",
                    "stdout": p.stdout[-500:]}
        dl = _baixar_url(url_line, prefix="higgsfield_")
        return {"ok": True, "provedor": "higgsfield", "prompt": prompt,
                "url": url_line, "arquivo": dl.get("arquivo"),
                "caminho_absoluto": dl.get("caminho_absoluto")}
    except subprocess.TimeoutExpired:
        return {"ok": False, "erro": "timeout (5min)"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def _baixar_url(url: str, prefix: str = "download_",
                destino: str | None = None) -> dict:
    """Baixa arquivo de uma URL para disco. Retorna caminho."""
    ext = ".png"
    url_lower = url.lower()
    for e in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".pdf", ".html"]:
        if e in url_lower:
            ext = e
            break
    ts = time.strftime("%Y%m%d_%H%M%S")
    nome = f"{prefix}{ts}{ext}"
    if destino:
        alvo = Path(destino).expanduser()
    else:
        caminho = ROOT / "data" / "downloads"
        caminho.mkdir(parents=True, exist_ok=True)
        alvo = caminho / nome
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "YVAKOR/2.0",
            "Accept": "image/*,*/*;q=0.8"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            alvo.write_bytes(resp.read())
        return {"ok": True, "arquivo": str(alvo),
                "caminho_absoluto": str(alvo.resolve()),
                "tamanho_bytes": alvo.stat().st_size}
    except Exception as e:
        return {"ok": False, "erro": str(e), "url": url}


def baixar_arquivo(url: str, nome: str = "") -> dict:
    """Baixa qualquer arquivo da internet e salva no PC.
       Se nome vazio, gera automatico. Retorna caminho absoluto."""
    prefix = nome.rsplit(".", 1)[0] if nome and "." in nome else "download_"
    if nome and "." not in nome:
        # Nome sem extensao: prefixo customizado
        prefix = nome
    dl = _baixar_url(url, prefix=prefix)
    if dl.get("ok"):
        return {"ok": True, "caminho_absoluto": dl["caminho_absoluto"],
                "tamanho_bytes": dl["tamanho_bytes"]}
    return dl


# ----------------------------------------------------------------------- #
# Ferramentas do blueprint (geradas pelo autoaprendizado)
# ----------------------------------------------------------------------- #
def gerar_proposta_html(cliente: str, servicos: str, valores: str,
                        prazo: str = "", observacoes: str = "") -> dict:
    """Gera proposta comercial em HTML (imprimível como PDF) no sandbox."""
    SANDBOX.mkdir(parents=True, exist_ok=True)
    html = f"""<!doctype html><html lang=pt-BR><meta charset=utf-8>
<title>Proposta — {cliente}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:48px;color:#1a1a1a}}
h1{{color:#C0272D}}table{{border-collapse:collapse;width:100%;margin:16px 0}}
td,th{{border:1px solid #ccc;padding:8px;text-align:left}}
.rod{{margin-top:40px;font-size:12px;color:#666}}</style>
<h1>Proposta Comercial — ACM Digital</h1>
<p><b>Cliente:</b> {cliente}</p>
<h3>Escopo</h3><p>{servicos}</p>
<table><tr><th>Item</th><th>Valor</th></tr><tr><td>{servicos}</td><td>{valores}</td></tr></table>
<p><b>Prazo:</b> {prazo or 'a combinar'}</p>
<p><b>Observações:</b> {observacoes or '—'}</p>
<div class=rod>ACM Digital · Antonio Cordero · Manaus-AM</div></html>"""
    alvo = SANDBOX / f"proposta_{re.sub(r'[^a-z0-9]+', '_', cliente.lower())}.html"
    alvo.write_text(html, encoding="utf-8")
    return {"ok": True, "arquivo": str(alvo.relative_to(ROOT)),
            "dica": "abra no navegador e use Ctrl+P → Salvar como PDF"}


def extrair_log_docker(container: str, filtro: str = "", linhas: int = 200) -> dict:
    """Extrai logs de um container Docker, com filtro opcional por palavra."""
    try:
        p = _ywproc.run(["docker", "logs", "--tail", str(linhas), container],
                           capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return {"ok": False, "erro": "docker não está instalado/no PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "erro": "timeout ao ler logs"}
    saida = (p.stdout + p.stderr).splitlines()
    if filtro:
        saida = [l for l in saida if filtro.lower() in l.lower()]
    return {"ok": p.returncode == 0, "linhas": saida[-linhas:]}


def converter_xlsx_para_json(caminho: str, aba: str | None = None) -> dict:
    """Converte uma planilha .xlsx em JSON (1ª linha = cabeçalho)."""
    try:
        import openpyxl
    except ImportError:
        return {"ok": False, "erro": "openpyxl não instalado (pip install openpyxl)"}
    p = Path(caminho).expanduser()
    if not p.exists():
        return {"ok": False, "erro": "arquivo não encontrado"}
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ws = wb[aba] if aba else wb.active
    linhas = list(ws.iter_rows(values_only=True))
    if not linhas:
        return {"ok": True, "dados": []}
    cab = [str(c) if c is not None else f"col{i}" for i, c in enumerate(linhas[0])]
    dados = [dict(zip(cab, linha)) for linha in linhas[1:]]
    return {"ok": True, "aba": ws.title, "dados": dados[:1000], "total": len(dados)}


# ----------------------------------------------------------------------- #
# Registro no ToolRegistry (com specs para o agente)
# ----------------------------------------------------------------------- #
def register_builtins(registry) -> list[str]:
    """Registra as ferramentas nativas com suas especificações."""
    reg = registry.register
    # leitura / utilidades (sem guarda)
    reg("validar_documento", validar_documento,
        "Valida e formata CPF ou CNPJ.", {"doc": "str"})
    reg("http_get", http_get,
        "Baixa o conteúdo (texto) de uma URL via GET.", {"url": "str"})
    reg("listar_diretorio", listar_diretorio,
        "Lista arquivos/pastas de um diretório do PC.", {"caminho": "str"})
    reg("ler_arquivo_local", ler_arquivo_local,
        "Lê o conteúdo de um arquivo do PC.", {"caminho": "str"})
    reg("ler_arquivo", ler_arquivo,
        "Lê um arquivo do sandbox.", {"nome": "str"})
    reg("converter_xlsx_para_json", converter_xlsx_para_json,
        "Converte planilha .xlsx em JSON.", {"caminho": "str", "aba": "str?"})
    reg("extrair_log_docker", extrair_log_docker,
        "Lê logs de um container Docker, com filtro.", {"container": "str", "filtro": "str?"})
    reg("gerar_proposta_html", gerar_proposta_html,
        "Gera proposta comercial em HTML (imprimível como PDF).",
        {"cliente": "str", "servicos": "str", "valores": "str", "prazo": "str?"})
    # escrita / execução (GUARDED)
    reg("escrever_arquivo", escrever_arquivo,
        "Escreve arquivo no sandbox.", {"nome": "str", "conteudo": "str"})
    reg("escrever_arquivo_local", escrever_arquivo_local,
        "Cria/sobrescreve arquivo no PC.", {"caminho": "str", "conteudo": "str"})
    reg("editar_arquivo_local", editar_arquivo_local,
        "Substitui um trecho dentro de um arquivo do PC.",
        {"caminho": "str", "busca": "str", "troca": "str"})
    reg("executar_python", executar_python,
        "Executa código Python no sandbox (timeout).", {"codigo": "str"})
    reg("executar_shell", executar_shell,
        "Executa um comando no shell do sistema (timeout).", {"comando": "str"})
    reg("gerar_imagem", gerar_imagem,
        "Gera imagem: Higgsfield (programatico, baixa automatico) ou "
        "Perchance (abre no navegador, gratuito, sem login). "
        "Retorna caminho absoluto se baixado.",
        {"prompt": "str", "resolucao": "str?", "guidance": "int?", "seed": "str?"})
    reg("gerar_imagem_higgsfield", gerar_imagem_higgsfield,
        "Gera imagem via Higgsfield CLI (requer autenticacao previa). Baixa e retorna caminho.",
        {"prompt": "str", "estilo": "str?", "proporcao": "str?"})
    reg("baixar_arquivo", baixar_arquivo,
        "Baixa qualquer arquivo da internet e salva no PC. Retorna caminho absoluto.",
        {"url": "str", "nome": "str?"})
    return list(registry.tools.keys())
