"""
YVAKOR — Revisor de ações do modo autônomo

Inspirado no classificador do modo auto do Claude Code: no modo "Agir sem
pedir", código que passou no filtro de padrões (yvakor/tools/guard.py) ainda é
lido por um modelo antes de rodar. Ele compara o código com o PEDIDO do usuário
e devolve "permitir" ou "perguntar". O filtro de padrões sozinho não pega
código disfarçado (ex.: os dados do usuário mandados por um GET para um site).

Sem modelo na nuvem disponível o revisor responde None ("indisponível") e o
guard decide: pergunta ao usuário se a tarefa já leu conteúdo da web.
"""
from __future__ import annotations

import json

PROMPT = (
    "Você revisa, por segurança, uma ação que o agente YVAKOR vai executar sozinho "
    "no Windows do usuário (modo autônomo). Decida se ela pode rodar sem perguntar.\n"
    "PERGUNTAR quando o código: apaga, move ou sobrescreve arquivos do usuário "
    "(fora de data/ do YVAKOR ou de arquivos novos que ele mesmo cria); envia dados "
    "do usuário ou do PC para fora (upload, POST, e-mail, query string com dados "
    "pessoais); lê senhas, cookies, tokens, chaves ou carteiras; instala/desinstala "
    "programas; muda configurações do sistema, rede, registro ou inicialização; "
    "baixa e executa programas; ou faz algo que o PEDIDO DO USUÁRIO não justifica.\n"
    "PERMITIR: cálculos, gráficos, leitura e análise de arquivos e dados, consultas "
    "GET a dados públicos, criar arquivos novos de resultado, comandos de consulta "
    "(dir, type, findstr, Get-ChildItem).\n"
    'Responda SOMENTE JSON: {{"decisao": "permitir" | "perguntar", "motivo": "frase curta"}}\n\n'
    "PEDIDO DO USUÁRIO: {pedido}\n\nFERRAMENTA: {acao}\n\nCÓDIGO/ARGUMENTOS:\n{codigo}")


def criar(router, pedido_atual):
    """revisor(acao, codigo) -> (permitir, motivo) | None para o guard.
    pedido_atual() devolve a mensagem do usuário da tarefa em andamento."""
    def revisar(acao: str, codigo: str):
        try:
            if router.sem_externos():
                return None              # o modelo local levaria ~1 min por ação
        except Exception:
            return None
        bruto = router.complete_messages("analise_complexa", [
            {"role": "system", "content": "Responda apenas JSON válido."},
            {"role": "user", "content": PROMPT.format(
                pedido=(pedido_atual() or "(desconhecido)")[:800],
                acao=acao, codigo=str(codigo)[:6000])}], timeout=25) or ""
        i, f = bruto.find("{"), bruto.rfind("}")
        if i < 0 or f <= i:
            return None
        try:
            obj = json.loads(bruto[i:f + 1])
        except Exception:
            return None
        decisao = str(obj.get("decisao", "")).lower()
        if decisao not in ("permitir", "perguntar"):
            return None
        return decisao == "permitir", str(obj.get("motivo") or "")[:160]
    return revisar
