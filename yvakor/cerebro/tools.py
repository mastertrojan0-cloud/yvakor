"""
YVAKOR — Ferramentas do cérebro (vault markdown estilo Obsidian)

O agente consulta o índice FTS (rápido) e pode escrever notas novas, que
ficam legíveis e linkáveis no Obsidian.
"""
from __future__ import annotations

from yvakor.cerebro.vault import Cerebro


def _safe(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def register_cerebro_tools(registry, cerebro: Cerebro) -> list[str]:
    reg = registry.register

    def status() -> dict:
        return {"ok": True, **cerebro.status()}

    def sincronizar(exportar: bool = True) -> dict:
        return cerebro.sincronizar(exportar=bool(exportar))

    def buscar(termo: str, limite: int = 10) -> dict:
        resultados = cerebro.buscar(termo, int(limite))
        return {"ok": True, "termo": termo, "total": len(resultados),
                "resultados": resultados}

    def nota(nome: str) -> dict:
        n = cerebro.nota(nome)
        if not n:
            return {"ok": False, "erro": f"nota '{nome}' não encontrada no cérebro"}
        return {"ok": True, **n}

    def grafo(nome: str = "", profundidade: int = 1) -> dict:
        g = cerebro.grafo(nome, profundidade)
        return {"ok": True, "nos": len(g["nos"]), "arestas": len(g["arestas"]),
                "grafo": g}

    def escrever(titulo: str, corpo: str, tags: str = "",
                 tipo: str = "nota") -> dict:
        return cerebro.escrever(titulo, corpo, tags, tipo)

    def receitas(acao: str = "listar", nome: str = "", texto: str = "",
                 simular: bool = True) -> dict:
        acao = (acao or "listar").lower()
        if acao == "listar":
            return {"ok": True, "total": len(cerebro.receitas),
                    "receitas": [{"nome": r.nome, "aprovada": r.aprovada,
                                  "gatilhos": r.gatilhos,
                                  "passos": len(r.passos)} for r in cerebro.receitas]}
        alvo = next((r for r in cerebro.receitas if r.nome == nome), None)
        if alvo is None:
            return {"ok": False, "erro": f"receita '{nome}' não encontrada"}
        if acao == "validar":
            from yvakor.cerebro.receitas import ExecutorReceitas
            if cerebro.executor is None:
                return {"ok": False, "erro": "executor indisponível"}
            erros = ExecutorReceitas(cerebro.executor).validar(alvo)
            return {"ok": not erros, "nome": nome, "erros": erros}
        if acao == "executar":
            return cerebro.executar_receita(alvo, texto, bool(simular))
        return {"ok": False, "erro": f"ação inválida: {acao}"}

    def aprender(fonte: str = "", tema: str = "", texto: str = "") -> dict:
        """Aprende com uma URL, arquivo local ou texto e grava no vault."""
        import html
        import re
        import urllib.request
        from datetime import datetime
        from pathlib import Path

        fonte = (fonte or "").strip()
        corpo = (texto or "").strip()
        titulo = (tema or "Fonte").strip()[:80]
        origem = fonte
        try:
            if not corpo and fonte:
                if fonte.lower().startswith(("http://", "https://")):
                    req = urllib.request.Request(
                        fonte, headers={"User-Agent": "YVAKOR/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        bruto = r.read(3_000_000).decode("utf-8", errors="replace")
                    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", bruto)
                    if m:
                        titulo = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()[:80]
                    bruto = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>",
                                   " ", bruto)
                    corpo = re.sub(r"(?s)<[^>]+>", " ", bruto)
                    corpo = html.unescape(re.sub(r"\s+", " ", corpo)).strip()
                else:
                    p = Path(fonte).expanduser()
                    if not p.is_file():
                        return {"ok": False, "erro": f"fonte não encontrada: {fonte}"}
                    corpo = p.read_text(encoding="utf-8", errors="replace")
                    titulo = tema or p.stem
            if not corpo:
                return {"ok": False, "erro": "sem conteúdo para aprender"}
            corpo = corpo[:16000]
            data = datetime.now().strftime("%Y-%m-%d %H:%M")
            nota = (f"# {titulo}\n\n**Fonte:** {origem or 'texto direto'}\n"
                    f"**Aprendido em:** {data}\n\n---\n\n{corpo}\n")
            r = cerebro.escrever(titulo, nota, "aprendizado,fonte",
                                 tipo="fonte")
            try:
                syn = cerebro.sincronizar()
            except Exception:
                syn = {}
            return {"ok": True, "nota": r, "caracteres": len(corpo),
                    "fonte": origem, "sincronizado": bool(syn)}
        except Exception as exc:
            return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}

    reg("cerebro_aprender", aprender,
        "Aprende com uma URL, arquivo local ou texto e grava no cérebro/vault. "
        "Use quando o usuário pedir para estudar uma fonte.",
        {"fonte": "str?", "tema": "str?", "texto": "str?"})

    reg("cerebro_status", status,
        "Estado do cérebro: notas, links, tipos e arquivos do vault.", {})
    reg("cerebro_sincronizar", sincronizar,
        "Exporta memórias/skills/conversas para o vault markdown e reindexa. "
        "Use depois de aprender algo importante.", {"exportar": "bool?"})
    reg("cerebro_buscar", buscar,
        "Busca no cérebro (FTS, ranking bm25): memórias, skills, conversas.",
        {"termo": "str", "limite": "int?"})
    reg("cerebro_nota", nota,
        "Lê uma nota inteira do vault, com backlinks.",
        {"nome": "str"})
    reg("cerebro_grafo", grafo,
        "Grafo de ligações ([[wikilinks]]) de uma nota ou do vault inteiro.",
        {"nome": "str?", "profundidade": "int?"})
    reg("cerebro_escrever", escrever,
        "Cria/anexa uma nota no vault (título, corpo, tags, tipo: nota|memoria|"
        "skill|conversa).", {"titulo": "str", "corpo": "str",
                             "tags": "str?", "tipo": "str?"})
    reg("cerebro_receitas", receitas,
        "Receitas executáveis: acao=listar|validar|executar. simular=True só "
        "mostra o plano. Só roda receita aprovada.",
        {"acao": "str?", "nome": "str?", "texto": "str?", "simular": "bool?"})

    return [n for n in registry.tools if n.startswith("cerebro_")]
