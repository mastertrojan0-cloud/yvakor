"""
YVAKOR — Absorvedor de Conhecimento
Pipeline que "ordenha" a IA principal (DeepSeek V4) automaticamente:
a cada interação, fatos e procedimentos são extraídos e gravados nas
memórias locais. É o motor da independência gradual.

Prompts em /prompts (editáveis sem tocar em código).
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS = ROOT / "prompts"


def _load(name: str, **vars) -> str:
    text = (PROMPTS / name).read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v)[:3000])
    return text


def _parse_json(raw: str) -> dict | None:
    """Tolera respostas com cercas ```json ... ```"""
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


class KnowledgeAbsorber:
    def __init__(self, router, semantic, skills, episodic):
        self.router = router
        self.semantic = semantic
        self.skills = skills
        self.episodic = episodic

    # ------------------------------------------------------------------ #
    # 1. Extração de fatos — roda após cada resposta
    # ------------------------------------------------------------------ #
    def absorb_facts(self, user_message: str, answer: str) -> int:
        prompt = _load("01_extrator_de_fatos.md",
                       user_message=user_message, answer=answer)
        try:
            raw = self.router.complete(task_type="classificacao",
                                       system="Responda apenas JSON válido.",
                                       user=prompt)
            data = _parse_json(raw) or {}
            facts = [f for f in data.get("fatos", []) if isinstance(f, str)]
            for f in facts:
                self.semantic.store(f)
            return len(facts)
        except Exception:
            return 0  # absorção nunca quebra o fluxo principal

    # ------------------------------------------------------------------ #
    # 2. Destilação de skill — quando a reflexão detecta padrão repetível
    # ------------------------------------------------------------------ #
    def distill_skill(self, user_message: str, answer: str) -> str | None:
        existing = "\n---\n".join(self.skills.find_relevant(user_message, top_k=1))
        prompt = _load("02_destilador_de_skill.md",
                       user_message=user_message, answer=answer,
                       existing_skills=existing or "(nenhuma)")
        try:
            content = self.router.complete(
                task_type="formatacao",
                system="Você escreve documentação de procedimentos. "
                       "Responda apenas com o markdown da skill.",
                user=prompt)
            name = "skill_" + datetime.now().strftime("%Y%m%d_%H%M")
            for line in content.splitlines():
                if line.startswith("<!-- skill:"):
                    name = line.split("skill:", 1)[1].split("|", 1)[0].strip()
                    break
            saved = self.skills.save(name, content)
            self.episodic.log("skill_destilada", user_message[:300], saved)
            return saved
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # 3. Autoavaliação — decide o que absorver e o que rotear local
    # ------------------------------------------------------------------ #
    def evaluate(self, user_message: str, answer: str, task_type: str) -> dict:
        prompt = _load("04_autoavaliacao.md", user_message=user_message,
                       answer=answer, task_type=task_type)
        try:
            raw = self.router.complete(task_type="classificacao",
                                       system="Responda apenas JSON válido.",
                                       user=prompt)
            return _parse_json(raw) or {}
        except Exception:
            return {}

    # ------------------------------------------------------------------ #
    # Pipeline completo pós-resposta (chamado pelo orquestrador)
    # ------------------------------------------------------------------ #
    def after_response(self, user_message: str, answer: str, task_type: str):
        self.absorb_facts(user_message, answer)
        if task_type in {"codigo", "prospeccao", "analise_complexa",
                         "pesquisa_sintese"}:
            verdict = self.evaluate(user_message, answer, task_type)
            if verdict.get("padrao_repetivel") and verdict.get("sucesso"):
                self.distill_skill(user_message, answer)
            if verdict.get("erro_a_registrar"):
                self.episodic.log("erro", user_message[:300],
                                  verdict["erro_a_registrar"], success=False)

    # ------------------------------------------------------------------ #
    # 4. Geração de dataset (lote manual/agendado) p/ fine-tuning futuro
    # ------------------------------------------------------------------ #
    def build_dataset(self, tema: str, out_dir: Path | None = None) -> Path:
        out_dir = out_dir or (ROOT / "data" / "dataset")
        out_dir.mkdir(parents=True, exist_ok=True)
        knowledge = "\n---\n".join(
            f.read_text(encoding="utf-8") for f in self.skills.all_skills())
        facts = "\n".join(self.semantic.search(tema, top_k=10))
        prompt = _load("03_professor_dataset.md", tema=tema,
                       skills_e_fatos=(knowledge + "\n\nFATOS:\n" + facts)[:6000])
        raw = self.router.complete(task_type="analise_complexa",
                                   system="Responda apenas JSONL, uma linha por par.",
                                   user=prompt)
        out = out_dir / f"dataset_{datetime.now():%Y%m%d_%H%M}.jsonl"
        lines = [l for l in raw.splitlines() if l.strip().startswith("{")]
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    # ------------------------------------------------------------------ #
    # 5. Consolidação semanal da memória semântica
    # ------------------------------------------------------------------ #
    def consolidate_memory(self) -> dict:
        facts = self.semantic.search("", top_k=200) or []
        if not self.semantic.jsonl.exists():
            return {"removidos": 0}
        all_facts = []
        for line in self.semantic.jsonl.read_text(encoding="utf-8").splitlines():
            try:
                all_facts.append(json.loads(line)["fact"])
            except Exception:
                continue
        if not all_facts:
            return {"removidos": 0}
        prompt = _load("05_consolidador_memoria.md", fatos="\n".join(all_facts))
        raw = self.router.complete(task_type="analise_complexa",
                                   system="Responda apenas JSON válido.",
                                   user=prompt)
        data = _parse_json(raw) or {}
        clean = data.get("fatos_limpos")
        if clean:
            self.semantic.jsonl.write_text(
                "\n".join(json.dumps(
                    {"ts": datetime.now().isoformat(timespec="seconds"),
                     "fact": f}, ensure_ascii=False) for f in clean) + "\n",
                encoding="utf-8")
        return data
