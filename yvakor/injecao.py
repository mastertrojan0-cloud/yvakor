"""
YVAKOR — Detector de prompt-injection (texto que entra no system prompt)

Inspirado no Hermes Agent: tudo o que vai fixo para o prompt de sistema
(memória curada, arquivos de contexto do projeto, SOUL.md, skills escritas
pelo próprio agente) passa por aqui antes. Um AGENTS.md malicioso num
repositório clonado, ou uma "memória" gravada a partir de uma página web,
não pode virar instrução do agente.

Detecta:
  - ordens para ignorar/substituir as instruções do sistema;
  - HTML escondido (display:none, comentário com ordens, texto invisível);
  - exfiltração de credenciais (enviar .env, chaves, ~/.ssh para fora);
  - acesso a arquivos de segredo;
  - caracteres invisíveis/bidirecionais (texto que o usuário não vê).
"""
from __future__ import annotations

import re

_PADROES: tuple[tuple[str, re.Pattern], ...] = tuple(
    (motivo, re.compile(rx, re.I | re.S)) for motivo, rx in (
        ("ordem para ignorar instruções",
         r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|all|system|earlier)\b"
         r".{0,20}\b(instructions?|prompts?|rules?|messages?)\b"),
        ("ordem para ignorar instruções",
         r"\b(ignor[ea]|esque[çc]a|desconsider[ea])\b.{0,40}\b(as |todas as |suas )?"
         r"(instru[çc][õo]es|regras|ordens)\b.{0,20}\b(anteriores|acima|do sistema|originais)\b"),
        ("troca de papel do sistema",
         r"\b(you are now|from now on you are|act as the system|new system prompt)\b"),
        ("troca de papel do sistema",
         r"\b(a partir de agora voc[êe] [ée]|novo prompt de sistema|voc[êe] agora [ée] o sistema)\b"),
        ("marcador falso de mensagem do sistema",
         r"(<\|?(im_start|system)\|?>|\[/?SYSTEM\]|^\s*###\s*system\s*:)"),
        ("HTML escondido",
         r"<[a-z]+[^>]*style\s*=\s*[\"'][^\"']*(display\s*:\s*none|visibility\s*:\s*hidden|"
         r"font-size\s*:\s*0)[^\"']*[\"']"),
        ("comentário HTML com ordens",
         r"<!--(?:(?!-->).){0,400}\b(ignore|instru[çc]|execute|run|curl|send|envie|you must|voc[êe] deve)\b"
         r"(?:(?!-->).){0,400}-->"),
        ("exfiltração de credenciais",
         r"\b(curl|wget|invoke-webrequest|iwr|fetch|requests\.(post|get))\b.{0,120}"
         r"(\.env\b|api[_-]?key|token|senha|password|secret|id_rsa|credential)"),
        ("exfiltração de credenciais",
         r"\b(send|envie|mande|post|upload)\b.{0,60}\b(api[_-]?keys?|tokens?|senhas?|passwords?|"
         r"secrets?|credenciais|credentials)\b.{0,60}\b(to|para)\b.{0,40}(https?://|@|webhook)"),
        ("acesso a arquivo de segredo",
         r"(~|%userprofile%|\$home)[\\/]\.(ssh|aws|gnupg)\b|\bid_rsa\b|\b\.git-credentials\b"),
    ))

# zero-width, controles bidirecionais (Trojan Source), BOM no meio do texto
_INVISIVEIS = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")


def varrer(texto: str) -> list[str]:
    """Motivos de suspeita encontrados (lista vazia = limpo)."""
    t = texto or ""
    motivos: list[str] = []
    if _INVISIVEIS.search(t.lstrip("\ufeff")):
        motivos.append("caracteres invisíveis")
    for motivo, rx in _PADROES:
        if motivo not in motivos and rx.search(t):
            motivos.append(motivo)
    return motivos


def suspeito(texto: str) -> bool:
    return bool(varrer(texto))
