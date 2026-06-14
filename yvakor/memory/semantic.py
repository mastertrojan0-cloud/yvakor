"""Memória semântica — conhecimento sobre o usuário, clientes, projetos.

Usa ChromaDB se instalado (busca vetorial real). Caso contrário, cai para
um índice simples por palavras-chave em JSONL — roda em qualquer máquina.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

try:
    import chromadb  # opcional
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False


class SemanticMemory:
    def __init__(self, index_dir: Path):
        index_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = index_dir / "facts.jsonl"
        if HAS_CHROMA:
            self.client = chromadb.PersistentClient(path=str(index_dir / "chroma"))
            self.coll = self.client.get_or_create_collection("yvakor_facts")
        else:
            self.client = None

    # ----------------------------- escrita ----------------------------- #
    def store(self, fact: str):
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "fact": fact}
        with open(self.jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.client:
            self.coll.add(documents=[fact], ids=[record["ts"] + str(hash(fact))[:8]])

    def maybe_store(self, user_msg: str, answer: str):
        """Heurística simples: frases declarativas do usuário sobre si/negócio.
        TODO: usar o modelo local p/ extrair fatos ('o usuário disse que...')."""
        triggers = ("meu ", "minha ", "eu sou", "eu uso", "prefiro", "trabalho",
                    "cliente", "sempre", "nunca")
        low = user_msg.lower()
        if any(t in low for t in triggers) and len(user_msg) < 400:
            self.store(f"Usuário: {user_msg}")

    # ----------------------------- leitura ----------------------------- #
    def search(self, query: str, top_k: int = 5) -> list[str]:
        if self.client:
            try:
                res = self.coll.query(query_texts=[query], n_results=top_k)
                return res["documents"][0] if res["documents"] else []
            except Exception:
                pass
        # fallback keyword
        if not self.jsonl.exists():
            return []
        words = {w for w in query.lower().split() if len(w) > 3}
        scored = []
        for line in self.jsonl.read_text(encoding="utf-8").splitlines():
            try:
                fact = json.loads(line)["fact"]
            except Exception:
                continue
            score = sum(1 for w in words if w in fact.lower())
            if score:
                scored.append((score, fact))
        scored.sort(reverse=True)
        return [f for _, f in scored[:top_k]]
