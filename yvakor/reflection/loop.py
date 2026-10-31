"""Loop de reflexão — o motor de aprendizado do YVAKOR.

Após cada tarefa relevante, o agente se pergunta:
  1. Deu certo?
  2. Há um padrão repetível aqui?
  3. Vale criar/atualizar uma skill?

Skills nascem 'novas' e viram 'estáveis' após N usos com sucesso
(config: skills.stable_threshold). Skills estáveis são candidatas a
rodar no modelo LOCAL — é assim que a dependência externa diminui.
"""
from __future__ import annotations
from datetime import datetime
import logging

_log = logging.getLogger(__name__)

RELEVANT_TYPES = {"codigo", "prospeccao", "analise_complexa", "pesquisa_sintese"}


class ReflectionLoop:
    def __init__(self, router, skills, episodic):
        self.router = router
        self.skills = skills
        self.episodic = episodic

    def after_task(self, user_msg: str, answer: str, task_type: str):
        if task_type not in RELEVANT_TYPES:
            return
        prompt = (
            "Avalie a interação abaixo de um agente pessoal. Responda APENAS em "
            "JSON: {\"padrao_repetivel\": true/false, \"nome_skill\": \"...\", "
            "\"motivo\": \"...\"}.\n\n"
            f"USUÁRIO: {user_msg[:1500]}\n\nRESPOSTA DO AGENTE: {answer[:1500]}"
        )
        try:
            raw = self.router.complete(task_type="classificacao",
                                       system="Você responde apenas json válido.",
                                       user=prompt)
            import json
            verdict = json.loads(raw.strip().strip("`").replace("json", "", 1)
                                 if raw.strip().startswith("`") else raw)
            if verdict.get("padrao_repetivel"):
                self.episodic.log(
                    "reflexao", user_msg[:500],
                    f"Padrão detectado: {verdict.get('nome_skill')} — "
                    f"{verdict.get('motivo')}. Use [skill] para salvar.")
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)  # reflexão nunca pode quebrar o fluxo principal

    def create_skill_from_context(self, instruction: str, recent: list[str]) -> str:
        context = "\n".join(recent[-20:])
        prompt = (
            "Crie uma skill em markdown a partir do contexto recente, seguindo "
            "EXATAMENTE este formato:\n\n"
            "<!-- skill: nome-curto | tags: t1, t2 | status: nova -->\n"
            "# Título\n## Quando usar\n## Procedimento\n1. ...\n## Erros conhecidos\n\n"
            f"PEDIDO DO USUÁRIO: {instruction}\n\nCONTEXTO RECENTE:\n{context}"
        )
        content = self.router.complete(task_type="formatacao",
                                       system="Você escreve documentação de procedimentos.",
                                       user=prompt)
        # nome a partir da primeira linha do front-matter, com fallback
        name = "skill_" + datetime.now().strftime("%Y%m%d_%H%M")
        for line in content.splitlines():
            if line.startswith("<!-- skill:"):
                name = line.split("skill:", 1)[1].split("|", 1)[0].strip()
                break
        saved = self.skills.save(name, content)
        self.episodic.log("skill_criada", instruction, saved)
        return f"✅ Skill salva: skills_library/{saved}.md"
