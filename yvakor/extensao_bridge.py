"""YVAKOR — ponte de comandos para o Chrome onde a extensão está aberta."""
from __future__ import annotations

import threading
import time
import uuid


class PonteExtensao:
    def __init__(self):
        self._lock = threading.RLock()
        # Acorda quem faz long-poll em pendentes() assim que um comando entra.
        self._cond = threading.Condition(self._lock)
        self._ultimo_ping = 0.0
        self._inicio = time.time()
        self._comandos: dict[str, dict] = {}
        self._eventos: dict[str, threading.Event] = {}
        self._resultados: dict[str, dict] = {}
        self.falhas = 0
        self.quedas = 0
        self._ultima_queda = 0.0
        # Por-requisição: se a mensagem pede explicitamente outro navegador.
        # Thread-local porque chat e cowork compartilham esta ponte singleton
        # e rodam em threads distintas (senão uma requisição liberava shell de
        # navegador para outra).
        self._tl = threading.local()

    @property
    def permitir_outro(self) -> bool:
        return getattr(self._tl, "permitir_outro", False)

    @permitir_outro.setter
    def permitir_outro(self, valor: bool) -> None:
        self._tl.permitir_outro = bool(valor)

    def ping(self) -> None:
        agora = time.time()
        # detecta "queda": ficou mais de 90 s sem ping após já ter conectado
        if self._ultimo_ping and (agora - self._ultimo_ping) > 90:
            self.quedas += 1
            self._ultima_queda = agora
        self._ultimo_ping = agora

    def registrar_falha(self) -> None:
        with self._lock:
            self.falhas += 1

    def disponivel(self, janela: float = 75.0) -> bool:
        return (time.time() - self._ultimo_ping) <= janela

    def status(self) -> dict:
        return {"disponivel": self.disponivel(),
                "ultimo_ping_ha_seg": round(time.time() - self._ultimo_ping, 1)
                if self._ultimo_ping else None,
                "uptime_s": round(time.time() - self._inicio),
                "comandos_na_fila": len(self._comandos),
                "falhas": self.falhas,
                "quedas": self.quedas}

    def abrir(self, url: str = "", ativo: bool = True,
              espera: float = 45.0) -> dict:
        return self.comando("open", {"url": url or "", "ativo": bool(ativo)},
                            espera=espera)

    def comando(self, tipo: str, args: dict | None = None,
                espera: float = 45.0) -> dict:
        # Não exigimos disponibilidade no instante do pedido: a extensão pode
        # estar dormindo (service worker) e acorda em até ~30s. Enfileiramos e
        # aguardamos; se ninguém consumir, devolvemos erro claro no fim.
        cid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        with self._lock:
            self._comandos[cid] = {"id": cid, "tipo": tipo,
                                   "args": args or {},
                                   "criado": time.time()}
            self._eventos[cid] = ev
            self._cond.notify_all()          # acorda o long-poll da extensão
        try:
            ok = ev.wait(espera)
        except Exception:
            ok = False
        with self._lock:
            if not ok:
                self._comandos.pop(cid, None)
                self._eventos.pop(cid, None)
                return {"ok": False,
                        "erro": "a extensão não respondeu (abra o painel do "
                                "YVAKOR no Chrome e tente de novo)"}
            r = self._resultados.pop(cid, {"ok": False, "erro": "sem resultado"})
            self._comandos.pop(cid, None)
            self._eventos.pop(cid, None)
        return r

    def pendentes(self, tipo: str | None = None, espera: float = 0.0) -> list[dict]:
        """Entrega cada comando UMA única vez.

        `espera` > 0 = long-poll: segura a chamada até aparecer um comando (ou o
        tempo acabar). Antes a extensão consultava a cada 1,2s, então cada
        comando esperava em média meio ciclo (~0,6s); com isso a entrega é
        quase instantânea e há bem menos requisições.

        Antes um comando era reentregue se ainda não tivesse resultado após
        10s. Só que open/snapshot/goto levam mais que isso (esperam a página
        carregar), então o mesmo comando era executado duas vezes — ex.: um
        `newtab` abria duas abas. Agora, entregue uma vez, não volta: se a
        extensão não responder, `comando()` expira com erro claro e o agente
        decide se repete (gerando um comando novo).
        """
        fim = time.time() + max(0.0, float(espera or 0.0))
        with self._cond:
            while True:
                saida = []
                for c in self._comandos.values():
                    if tipo and c.get("tipo") != tipo:
                        continue
                    if c.get("_entregue"):
                        continue
                    c["_entregue"] = time.time()
                    saida.append({k: v for k, v in c.items() if not k.startswith("_")})
                resto = fim - time.time()
                if saida or resto <= 0:
                    return saida
                self._cond.wait(min(resto, 1.0))

    def resultado(self, cid: str, ok: bool, erro: str = "",
                  tab_id: int | None = None, titulo: str = "",
                  dados: dict | None = None) -> None:
        with self._lock:
            ev = self._eventos.get(cid)
            if ev is None:
                # ninguém espera mais por este comando (cancelado/expirado):
                # descarta em vez de acumular resultados órfãos.
                return
            self._resultados[cid] = {"ok": bool(ok), "erro": erro,
                                     "tab_id": tab_id, "titulo": titulo,
                                     "via": "extensao", **(dados or {})}
        ev.set()

    def devolver(self, ids: list[str]) -> int:
        """Põe de volta na fila comandos entregues a uma conexão que já tinha caído."""
        n = 0
        with self._cond:
            for cid in ids:
                c = self._comandos.get(cid)
                if c is not None and c.pop("_entregue", None):
                    n += 1
            if n:
                self._cond.notify_all()
        return n

    def cancelar_pendentes(self, motivo: str = "cancelado pelo usuário") -> int:
        """Aborta TODOS os comandos em espera (botão Parar): quem aguarda em
        comando() acorda na hora com erro, em vez de esperar até 45s."""
        with self._lock:
            ids = list(self._eventos)
            for cid in ids:
                self._resultados[cid] = {"ok": False, "erro": motivo,
                                         "via": "extensao"}
            eventos = [self._eventos[c] for c in ids]
            self._comandos.clear()
        for ev in eventos:
            ev.set()
        return len(ids)


PONTE = PonteExtensao()
