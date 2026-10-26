"""YVAKOR — motor de contexto: seleciona o que importa da página."""
from __future__ import annotations

import re

STOP = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "para",
    "por", "com", "um", "uma", "que", "se", "no", "na", "nos", "nas", "ao",
    "aos", "é", "são", "foi", "ser", "como", "mais", "menos", "sobre", "qual",
    "quais", "quando", "onde", "porque", "tem", "ter", "aqui", "isso", "esse",
    "essa", "este", "esta", "eu", "você", "voce", "me", "minha", "meu",
}


def _termos(texto: str) -> set[str]:
    return {t for t in re.findall(r"[a-zà-ÿ0-9]{3,}", (texto or "").lower())
            if t not in STOP}


def _blocos(texto: str) -> list[str]:
    """Quebra em parágrafos, headings e itens, preservando estrutura."""
    t = re.sub(r"\r\n?", "\n", texto or "")
    partes = re.split(r"\n{2,}|(?=\n#{1,6}\s)|(?=\n[-*•]\s)", t)
    saida = []
    for p in partes:
        p = p.strip()
        if not p:
            continue
        if len(p) > 1400:
            for i in range(0, len(p), 1200):
                saida.append(p[i:i + 1200].strip())
        else:
            saida.append(p)
    return saida


def _extrair_cabecalho(pagina: str) -> tuple[dict, str]:
    """Reconhece o formato TÍTULO/URL/SELEÇÃO/CONTEÚDO vindo da extensão."""
    info = {"titulo": "", "url": "", "selecao": "", "descricao": "",
            "secoes": "", "conteudo": ""}
    linhas = (pagina or "").splitlines()
    corpo_inicio = 0
    for i, ln in enumerate(linhas):
        m = re.match(r"^\s*(TÍTULO|TITULO|URL|SELEÇÃO|SELECAO|DESCRIÇÃO|"
                     r"DESCRICAO|SEÇÕES|SECOES)\s*:\s*(.*)$", ln, re.I)
        if not m:
            if ln.strip():
                corpo_inicio = i
                break
            continue
        chave = m.group(1).lower().replace("í", "i").replace("ç", "c")
        mapa = {"titulo": "titulo", "url": "url", "selecao": "selecao",
                "descricao": "descricao", "secoes": "secoes"}
        info[mapa.get(chave, "conteudo")] = m.group(2).strip()
        corpo_inicio = i + 1
    corpo = "\n".join(linhas[corpo_inicio:]).strip()
    if not corpo:
        corpo = pagina or ""
    # Se veio um bloco "CONTEÚDO:" explícito, usa o restante.
    m = re.search(r"(?im)^\s*CONTEÚDO\s*:\s*", corpo)
    if m:
        corpo = corpo[m.end():].strip()
    info["conteudo"] = corpo
    return info, corpo


def preparar_contexto(pergunta: str, pagina: str | None,
                      anexos: str = "", max_chars: int = 9000) -> str:
    """Monta o contexto mais útil dentro do orçamento de caracteres.

    A página chega com até ~20 mil caracteres da extensão; aqui escolhemos
    parágrafos/seções por relevância para a pergunta, em vez de cortar cego.
    """
    pagina = (pagina or "").strip()
    if not pagina:
        return (("## ANEXOS\n" + anexos) if anexos else "")
    info, corpo = _extrair_cabecalho(pagina)
    termos = _termos(pergunta)
    blocos = _blocos(corpo)
    if not blocos:
        blocos = [corpo[:max_chars]]
    pontuados = []
    for i, b in enumerate(blocos):
        baixo = b.lower()
        pontos = sum(1 for t in termos if t in baixo) * 3
        if b.startswith("#"):
            pontos += 2
        if i < 2:
            pontos += 2
        if info.get("selecao") and b[:120] in info["selecao"]:
            pontos += 6
        pontuados.append((pontos, i, b))
    # Bases: primeiros blocos + os mais relevantes; depois ordem original.
    escolhidos = {0, 1, len(blocos) - 1} if len(blocos) > 1 else {0}
    for pontos, i, _ in sorted(pontuados, reverse=True):
        if pontos <= 0 and len(escolhidos) >= 4:
            break
        escolhidos.add(i)
        if len(escolhidos) >= 32:
            break
    selecionados = [blocos[i] for i in sorted(escolhidos)]

    cab = ["## PÁGINA ATUAL DO CHROME"]
    if info.get("titulo"):
        cab.append(f"TÍTULO: {info['titulo']}")
    if info.get("url"):
        cab.append(f"URL: {info['url']}")
    if info.get("descricao"):
        cab.append(f"DESCRIÇÃO: {info['descricao'][:500]}")
    if info.get("secoes"):
        cab.append(f"SEÇÕES: {info['secoes'][:1200]}")
    if info.get("selecao"):
        cab.append(f"SELEÇÃO DO USUÁRIO: {info['selecao'][:2500]}")
    cab.append("\nCONTEÚDO RELEVANTE:")
    orcamento = max_chars - len("\n".join(cab)) - 2
    corpo_final = []
    usado = 0
    for b in selecionados:
        if usado + len(b) > orcamento:
            if orcamento - usado > 200:
                corpo_final.append(b[:orcamento - usado])
            break
        corpo_final.append(b)
        usado += len(b) + 2
    out = "\n".join(cab) + "\n" + "\n\n".join(corpo_final)
    if anexos:
        out += "\n\n## ANEXOS\n" + anexos
    return out[:max_chars + len(anexos) + 200]


def limitar(texto: str, max_chars: int = 12000) -> str:
    t = (texto or "").strip()
    return t if len(t) <= max_chars else t[:max_chars].rstrip() + "\n[…]"