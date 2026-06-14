"""Memória procedural — a biblioteca de skills (COMO fazer coisas).

Cada skill é um arquivo markdown em skills_library/ com front-matter simples:

    <!-- skill: nome | tags: tag1, tag2 | status: nova|estavel -->
    # Título
    ## Quando usar
    ## Procedimento (passos)
    ## Erros conhecidos

Este é o núcleo do aprendizado do YVAKOR: skills crescem com o uso e tornam
tarefas complexas executáveis até por modelos locais fracos.
"""
from __future__ import annotations
import re
from pathlib import Path


class SkillLibrary:
    def __init__(self, path: Path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)

    def all_skills(self) -> list[Path]:
        return sorted(self.path.glob("*.md"))

    def find_relevant(self, query: str, top_k: int = 2) -> list[str]:
        """Ranking simples por sobreposição de palavras (zero dependências).
        TODO: trocar por busca vetorial quando ChromaDB ativo."""
        words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 3}
        scored = []
        for f in self.all_skills():
            text = f.read_text(encoding="utf-8")
            header = text.splitlines()[0].lower() if text else ""
            score = sum(2 for w in words if w in header)
            score += sum(1 for w in words if w in text.lower())
            if score >= 2:
                scored.append((score, text))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:top_k]]

    def save(self, name: str, content: str):
        safe = re.sub(r"[^\w\-]+", "_", name.lower()).strip("_")[:60]
        (self.path / f"{safe}.md").write_text(content, encoding="utf-8")
        return safe
