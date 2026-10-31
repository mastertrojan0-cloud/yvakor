"""
YVAKOR — Bootstrap de Autoaprendizado

Dispara ATIVAMENTE o aprendizado (diferente do absorber, que é passivo após
cada conversa). A partir do seu perfil (identity/core_identity.md) e dos
recursos da IA principal (DeepSeek), o agente:

  1. Extrai e grava fatos-base do seu perfil na memória semântica.
  2. Planeja um lote de skills + ferramentas de alto valor para o seu contexto.
  3. Gera cada skill completa em markdown e salva em skills_library/.
  4. Registra um blueprint das ferramentas a implementar em data/blueprints/.

Uso:
    python -m yvakor.learning.bootstrap            # lote padrão
    python -m yvakor.learning.bootstrap --skills 6 # nº de skills
"""
from __future__ import annotations
import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS = ROOT / "prompts"


def _load(name: str, **vars) -> str:
    text = (PROMPTS / name).read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v)[:4000])
    return text


def _parse_json(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


class LearningBootstrap:
    def __init__(self, orchestrator=None):
        # Reaproveita o orquestrador já montado (router + memórias + skills).
        if orchestrator is None:
            from yvakor.orchestrator import Orchestrator
            orchestrator = Orchestrator()
        self.o = orchestrator
        self.router = orchestrator.router
        self.skills = orchestrator.skills
        self.semantic = orchestrator.semantic
        self.episodic = orchestrator.episodic
        self.absorber = orchestrator.absorber
        self.identity = orchestrator.identity_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------ #
    def _existing_skill_names(self) -> list[str]:
        return [self.skills.nome_de(f) for f in self.skills.all_skills()]

    # 1. Fatos-base do perfil ------------------------------------------- #
    def seed_facts(self) -> int:
        print("  [1/4] Extraindo fatos-base do seu perfil...")
        n = self.absorber.absorb_facts(
            "Este é meu perfil completo, registre os fatos estáveis sobre mim, "
            "meu negócio, stack e prioridades.", self.identity)
        print(f"        {n} fato(s) gravado(s) na memória semântica.")
        return n

    # 2. Plano de aprendizado ------------------------------------------- #
    def plan(self, n_skills: int, n_tools: int) -> dict:
        print("  [2/4] Planejando lote de skills e ferramentas (IA principal)...")
        prompt = _load(
            "06_plano_aprendizado.md",
            min=max(3, n_skills - 1), max=n_skills, max_tools=n_tools,
            identidade=self.identity,
            skills_existentes="\n".join(self._existing_skill_names()) or "(nenhuma)",
            fatos="\n".join(self.semantic.search("perfil negócio stack", top_k=15)) or "(nenhum)",
        )
        raw = self.router.complete(task_type="analise_complexa",
                                   system="Responda apenas JSON válido.",
                                   user=prompt)
        plan = _parse_json(raw) or {"skills": [], "ferramentas": []}
        print(f"        Plano: {len(plan.get('skills', []))} skills, "
              f"{len(plan.get('ferramentas', []))} ferramentas.")
        return plan

    # 3. Geração das skills --------------------------------------------- #
    def generate_skills(self, plan: dict) -> list[str]:
        print("  [3/4] Gerando skills...")
        created = []
        existing = set(self._existing_skill_names())
        for item in plan.get("skills", []):
            nome = re.sub(r"[^\w\-]+", "-", str(item.get("nome", "")).lower()).strip("-")
            if not nome or nome in existing:
                continue
            prompt = _load("07_gerar_skill.md",
                           nome=nome,
                           titulo=item.get("titulo", nome),
                           quando_usar=item.get("quando_usar", ""),
                           identidade=self.identity)
            try:
                content = self.router.complete(
                    task_type="formatacao",
                    system="Você escreve documentação de procedimentos. "
                           "Responda apenas com o markdown da skill.",
                    user=prompt)
                saved = self.skills.save(nome, content.strip() + "\n")
                created.append(saved)
                existing.add(saved)
                self.episodic.log("skill_bootstrap", nome, saved)
                print(f"        ✓ {saved}.md")
            except Exception as e:
                print(f"        ✗ falhou em '{nome}': {e}")
        return created

    # 4. Blueprints de ferramentas -------------------------------------- #
    def save_tool_blueprints(self, plan: dict) -> Path | None:
        tools = plan.get("ferramentas", [])
        if not tools:
            return None
        print("  [4/4] Registrando blueprints de ferramentas a implementar...")
        out_dir = ROOT / "data" / "blueprints"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"ferramentas_{datetime.now():%Y%m%d_%H%M}.md"
        lines = ["# Ferramentas propostas pelo autoaprendizado",
                 f"<!-- gerado em {datetime.now():%Y-%m-%d %H:%M} -->", ""]
        for t in tools:
            lines += [
                f"## {t.get('nome', '?')}  (risco: {t.get('risco', '?')})",
                f"- **Objetivo:** {t.get('objetivo', '')}",
                f"- **Entrada:** {t.get('entrada', '')}",
                f"- **Saída:** {t.get('saida', '')}",
                "",
            ]
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"        Blueprint salvo: {out.relative_to(ROOT)}")
        return out

    # Pipeline completo -------------------------------------------------- #
    def run(self, n_skills: int = 5, n_tools: int = 4) -> dict:
        print("\n  ===== YVAKOR · BOOTSTRAP DE AUTOAPRENDIZADO =====\n")
        self.seed_facts()
        plan = self.plan(n_skills, n_tools)
        created = self.generate_skills(plan)
        bp = self.save_tool_blueprints(plan)
        self.episodic.log("bootstrap", f"skills={n_skills}",
                          f"criadas={len(created)}")
        print(f"\n  ===== Concluído: {len(created)} skills novas. =====\n")
        return {"skills_criadas": created,
                "blueprint": str(bp) if bp else None,
                "plano": plan}


def main():
    ap = argparse.ArgumentParser(description="Bootstrap de autoaprendizado do YVAKOR")
    ap.add_argument("--skills", type=int, default=5, help="nº de skills a gerar")
    ap.add_argument("--tools", type=int, default=4, help="nº de ferramentas a propor")
    args = ap.parse_args()
    LearningBootstrap().run(n_skills=args.skills, n_tools=args.tools)


if __name__ == "__main__":
    main()
