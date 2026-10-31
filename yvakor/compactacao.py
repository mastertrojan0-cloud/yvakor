"""
YVAKOR — Compactação da conversa (como o auto-compact do Claude)

Só os últimos turnos da conversa vão inteiros ao modelo
(memory.episodic_context_last_n). Antes, o que ficava para trás simplesmente
sumia: numa conversa longa o YVAKOR "esquecia" o que foi combinado no começo.

Agora os turnos que saem da janela viram um RESUMO contínuo por conversa
(tabela conversa_resumos no banco episódico), atualizado em segundo plano a
cada `lote` turnos novos, e o resumo entra no system prompt:

  ## RESUMO DA CONVERSA ATÉ AQUI  ← decisões, dados informados, pendências
  [últimos N turnos inteiros]
  [mensagem atual]

O comando "/compactar" no chat força o resumo na hora.
"""
from __future__ import annotations

import logging
import threading
import time

_log = logging.getLogger(__name__)

PROMPT = (
    "Você compacta conversas entre o usuário e o YVAKOR (assistente pessoal). "
    "Atualize o RESUMO com os TURNOS NOVOS. Guarde só o que serve para continuar "
    "a conversa: objetivo, decisões tomadas, dados que o usuário informou "
    "(nomes, números, endereços, caminhos, links), o que já foi entregue/gerado "
    "e o que ficou pendente. Descarte cumprimentos e repetições. Escreva em "
    "português, em tópicos curtos, no máximo {limite} caracteres. Responda só "
    "com o resumo.")


class CompactadorConversa:
    def __init__(self, episodic, router, janela: int = 10, lote: int = 6,
                 limite: int = 1800, tarefa: str = "pesquisa_sintese"):
        self.episodic = episodic
        self.router = router
        self.janela = max(1, min(int(janela), 12))   # igual a history_messages
        self.lote = max(1, int(lote))
        self.limite = int(limite)
        self.tarefa = tarefa
        self._rodando: set[str] = set()
        self._lock = threading.Lock()
        with self.episodic._lock:
            self.episodic.conn.execute("""
                CREATE TABLE IF NOT EXISTS conversa_resumos (
                    session_id TEXT PRIMARY KEY,
                    ate_id INTEGER NOT NULL DEFAULT 0,
                    resumo TEXT NOT NULL DEFAULT '',
                    ts TEXT DEFAULT '')""")
            self.episodic.conn.commit()

    # ------------------------------------------------------------------ #
    def _estado(self, sid: str) -> tuple[int, str]:
        with self.episodic._lock:
            r = self.episodic.conn.execute(
                "SELECT ate_id, resumo FROM conversa_resumos WHERE session_id=?",
                (sid,)).fetchone()
        return (int(r[0]), r[1] or "") if r else (0, "")

    def _fora_da_janela(self, sid: str, depois_de: int) -> list[tuple]:
        """Turnos mais antigos que a janela e ainda não resumidos."""
        with self.episodic._lock:
            ids = [r[0] for r in self.episodic.conn.execute(
                "SELECT id FROM episodes WHERE kind='conversa' AND session_id=? "
                "ORDER BY id DESC LIMIT ?", (sid, self.janela))]
            if len(ids) < self.janela:
                return []
            corte = min(ids)
            return self.episodic.conn.execute(
                "SELECT id, input, output FROM episodes WHERE kind='conversa' "
                "AND session_id=? AND id>? AND id<? ORDER BY id",
                (sid, depois_de, corte)).fetchall()

    def resumo(self, sid: str | None) -> str:
        return self._estado(sid)[1] if sid else ""

    def bloco_prompt(self, sid: str | None) -> str:
        texto = self.resumo(sid)
        return ("## RESUMO DA CONVERSA ATÉ AQUI (turnos antigos, compactados — "
                "use como memória desta conversa)\n" + texto) if texto else ""

    # ------------------------------------------------------------------ #
    def atualizar(self, sid: str, forcar: bool = False) -> dict:
        ate, anterior = self._estado(sid)
        novos = self._fora_da_janela(sid, ate)
        if not novos or (len(novos) < self.lote and not forcar):
            return {"ok": True, "compactou": 0}
        turnos = "\n".join(f"USUÁRIO: {(i or '')[:800]}\nYVAKOR: {(o or '')[:800]}"
                           for _, i, o in novos)
        msgs = [{"role": "system", "content": PROMPT.format(limite=self.limite)},
                {"role": "user", "content": f"RESUMO ATUAL:\n{anterior or '(vazio)'}"
                                            f"\n\nTURNOS NOVOS:\n{turnos[:14000]}"}]
        try:
            texto = (self.router.complete_messages(self.tarefa, msgs, timeout=90) or "").strip()
        except Exception as exc:
            _log.warning("compactação da conversa falhou: %s", exc)
            return {"ok": False, "error": str(exc)}
        if not texto:
            return {"ok": False, "error": "o modelo não devolveu resumo"}
        with self.episodic._lock:
            self.episodic.conn.execute(
                "INSERT INTO conversa_resumos (session_id, ate_id, resumo, ts) "
                "VALUES (?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET "
                "ate_id=excluded.ate_id, resumo=excluded.resumo, ts=excluded.ts",
                (sid, int(novos[-1][0]), texto[:self.limite + 400],
                 time.strftime("%Y-%m-%d %H:%M:%S")))
            self.episodic.conn.commit()
        return {"ok": True, "compactou": len(novos), "resumo": texto}

    def atualizar_fundo(self, sid: str | None) -> None:
        """Depois de cada resposta: compacta sem atrasar o usuário."""
        if not sid:
            return
        with self._lock:
            if sid in self._rodando:
                return
            self._rodando.add(sid)

        def rodar():
            try:
                self.atualizar(sid)
            finally:
                with self._lock:
                    self._rodando.discard(sid)
        threading.Thread(target=rodar, daemon=True, name="yvakor-compactar").start()

    def esquecer(self, sid: str) -> None:
        with self.episodic._lock:
            self.episodic.conn.execute("DELETE FROM conversa_resumos WHERE session_id=?",
                                       (sid,))
            self.episodic.conn.commit()
