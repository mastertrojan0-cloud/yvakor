"""
YVAKOR — Sessão de voz (escopo de conversa + execução + narração)

Fluxo: fala → transcreve → (palavra de ativação abre a sessão) → o MESMO
orquestrador raciocina e executa ferramentas → a resposta é falada.

"Escopo da conversa": depois de acordar, os pedidos seguintes não precisam
repetir a palavra-chave enquanto a sessão estiver quente (padrão 45 s). Assim
vira uma conversa natural ("yvakor, abra a câmera" → "agora tire uma foto" →
"salve na área de trabalho").

Otimizações:
  • cache de TTS por hash do texto (frases repetidas não são regeradas)
  • pré-aquecimento do modelo STT e do motor de fala em segundo plano
  • fala assíncrona para a interface não bloquear
  • narração curta das ferramentas (throttle) para o usuário "ouvir" o trabalho
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata

from yvakor.voz.assistente import contem_ativacao, limpar_para_fala
import logging

_log = logging.getLogger(__name__)

# "para", "silêncio", "chega" — calar a fala na hora, sem passar pela IA
# (antes não havia como pausar a voz falando).
_CALAR = re.compile(
    r"^(yvakor[,\s]+)?(para|pare|parar|pausa|pausar|silencio|cala( a boca)?|chega|"
    r"basta|stop|quieto|para de falar|pare de falar|fica quieto|fique quieto)"
    r"( de falar| agora| por favor)?[.!\s]*$", re.I)


def pediu_calar(texto: str) -> bool:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c)).strip()
    return bool(_CALAR.match(t))


FRASES_FERRAMENTA = {
    "navegador_abrir": "Abrindo o navegador.",
    "navegador_ir": "Navegando.",
    "navegador_ver": "Lendo a página.",
    "navegador_clicar": "Clicando.",
    "navegador_preencher": "Preenchendo.",
    "navegador_pesquisar": "Pesquisando.",
    "navegador_captura": "Tirando um print.",
    "arquivos_ler": "Lendo o arquivo.",
    "arquivos_escrever": "Escrevendo o arquivo.",
    "arquivos_editar": "Editando o arquivo.",
    "arquivos_apagar": "Apagando.",
    "arquivos_buscar": "Procurando arquivos.",
    "executar_shell": "Executando um comando.",
    "executar_python": "Rodando código.",
    "rede_escanear": "Varrendo a rede.",
    "rede_camera_snapshot": "Tirando foto da câmera.",
    "rede_tv": "Falando com a TV.",
    "rede_cast": "Enviando para a TV.",
    "voz_falar": "Falando.",
    "cerebro_buscar": "Consultando a memória.",
}


class SessaoVoz:
    def __init__(self, orquestrador, voz, settings: dict):
        """`voz` é AssistenteVoz (STT/TTS); `orquestrador` é o Orchestrator."""
        self.orch = orquestrador
        self.voz = voz
        self.cfg = (settings or {}).get("voz", {}) or {}
        self.palavra = str(self.cfg.get("palavra_ativacao") or "")
        self.aliases = self.cfg.get("aliases_ativacao") or []
        self.janela = float(self.cfg.get("sessao_segundos", 45))
        self.narrar = bool(self.cfg.get("narrar", True))
        self._lock = threading.Lock()
        self.aberta_ate = 0.0
        self.turnos = 0
        self.ultima_pergunta = ""
        self.ultima_resposta = ""
        self._ultima_narracao = 0.0
        self._aquecido = False
        self.idioma = str(self.cfg.get("idioma") or "pt-BR")

    # ------------------------------------------------------------------ #
    # Escopo
    # ------------------------------------------------------------------ #
    def aberta(self) -> bool:
        return time.time() < self.aberta_ate

    def acordar(self, texto: str) -> bool:
        with self._lock:
            self.aberta_ate = time.time() + self.janela
            self.turnos += 1
        return True

    def fechar(self) -> None:
        with self._lock:
            self.aberta_ate = 0.0
            self.turnos = 0

    def interromper(self) -> dict:
        """Barge-in: para a fala e limpa narrações pendentes."""
        try:
            return self.voz.tts.parar()
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}

    def estado(self) -> dict:
        return {"aberta": self.aberta(), "turnos": self.turnos,
                "expira_em_s": max(0, round(self.aberta_ate - time.time(), 1)),
                "janela_s": self.janela, "palavra": self.palavra,
                "idioma": self.idioma}

    # ------------------------------------------------------------------ #
    # Aquecimento (não bloqueia o boot)
    # ------------------------------------------------------------------ #
    def aquecer(self) -> None:
        if self._aquecido:
            return
        self._aquecido = True

        def _tarefa():
            try:
                self.voz.stt._carregar()
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            try:
                self.voz.tts.gerar("Certo.")
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
        threading.Thread(target=_tarefa, daemon=True,
                         name="yvakor-voz-aquecer").start()

    # ------------------------------------------------------------------ #
    # Narração
    # ------------------------------------------------------------------ #
    def _narrar(self, tipo: str, dado: dict) -> None:
        if not (self.narrar and tipo == "ferramenta"):
            return
        agora = time.time()
        if agora - self._ultima_narracao < 2.0:
            return
        frase = FRASES_FERRAMENTA.get(str((dado or {}).get("nome", "")))
        if not frase:
            return
        self._ultima_narracao = agora
        try:
            self.voz.tts.falar(frase, assincrono=True,
                               idioma=getattr(self, "idioma", "pt-BR"))
        except Exception:
            _log.debug("exceção ignorada", exc_info=True)

    # ------------------------------------------------------------------ #
    # Comando
    # ------------------------------------------------------------------ #
    def processar(self, texto: str, falar: bool = True,
                  exigir_ativacao: bool = True,
                  idioma: str | None = None) -> dict:
        texto = (texto or "").strip()
        if not texto:
            return {"ok": False, "erro": "nada foi dito"}
        if pediu_calar(texto):
            r = self.interromper()
            return {"ok": True, "calou": True, "resposta": "", **r}

        # Comandos de câmera: executa direto, sem IA (voz → ação)
        from yvakor.voz.camera import detectar as detectar_camera
        from yvakor.voz.camera import executar as executar_camera
        orch = getattr(self.voz, "orch", None)
        if orch is not None and detectar_camera(texto):
            r = executar_camera(orch, texto)
            resposta = r.get("fala") or "Comando de câmera executado."
            if falar:
                try:
                    self.voz.tts.falar(resposta, assincrono=True,
                                       prioridade=2, idioma=self.idioma)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            self.turnos += 1
            self.aberta_ate = time.time() + self.janela
            try:
                orch.episodic.log(
                    "voz", texto, resposta,
                    session_id=getattr(orch.episodic,
                                       "active_id", "default"))
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            return {"ok": True, "resposta": resposta, "acao": r.get("acao"),
                    "comando": "camera"}

        # Comandos de rede (voz → ação, sem IA)
        from yvakor.voz.rede import detectar as detectar_rede
        from yvakor.voz.rede import executar as executar_rede
        if orch is not None and detectar_rede(texto):
            rr = executar_rede(orch, texto)
            resposta = rr.get("fala") or "Comando de rede executado."
            if falar:
                try:
                    self.voz.tts.falar(resposta, assincrono=True,
                                       prioridade=2, idioma=self.idioma)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            self.turnos += 1
            self.aberta_ate = time.time() + self.janela
            try:
                orch.episodic.log(
                    "voz", texto, resposta,
                    session_id=getattr(orch.episodic, "active_id", "default"))
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            return {"ok": True, "resposta": resposta, "acao": rr.get("acao"),
                    "comando": "rede"}

        # Aprendiz de entorno (mapear/aprender equipamento)
        from yvakor.voz.ambiente import detectar as detectar_amb
        from yvakor.voz.ambiente import executar as executar_amb
        if orch is not None and detectar_amb(texto):
            ra = executar_amb(orch, texto)
            resposta = ra.get("fala") or "Ambiente atualizado."
            if falar:
                try:
                    self.voz.tts.falar(resposta, assincrono=True,
                                       prioridade=2, idioma=self.idioma)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            self.turnos += 1
            self.aberta_ate = time.time() + self.janela
            return {"ok": True, "resposta": resposta,
                    "acao": ra.get("acao"), "comando": "ambiente"}

        from yvakor.voz.idiomas import detectar, normalizar_idioma
        self.idioma = (normalizar_idioma(idioma, self.idioma)
                       if idioma and idioma.lower() != "auto"
                       else detectar(texto, self.idioma))

        acordou = contem_ativacao(texto, self.palavra, self.aliases)
        if exigir_ativacao and not acordou and not self.aberta():
            return {"ok": True, "ignorado": True,
                    "motivo": "fora do escopo: diga a palavra de ativação",
                    "sessao": self.estado()}
        if acordou:
            self.acordar(texto)
        else:
            with self._lock:
                self.aberta_ate = time.time() + self.janela
                self.turnos += 1

        # Só o nome: confirma presença e mantém a sessão aberta.
        from yvakor.nome import separar as _separar_nome
        _chamou, _resto = _separar_nome(texto)
        if _chamou and not _resto:
            resposta = "Estou aqui. Pode falar."
            if falar:
                try:
                    self.voz.tts.falar(resposta, assincrono=True,
                                       prioridade=2, idioma=self.idioma)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            self.turnos += 1
            self.aberta_ate = time.time() + self.janela
            return {"ok": True, "resposta": resposta, "comando": "nome"}
        if _chamou and _resto:
            texto = _resto

        # Intenções diretas (hora, data, status, repetir…): sem IA.
        from yvakor.voz.diretos import detectar as _det_direto
        from yvakor.voz.diretos import executar as _exec_direto
        _int = _det_direto(texto)
        if _int:
            resposta = _exec_direto(self.orch, _int, self.ultima_resposta)
            if falar:
                try:
                    self.voz.tts.falar(resposta, assincrono=True,
                                       prioridade=2, idioma=self.idioma)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
            self.ultima_resposta = resposta
            self.turnos += 1
            self.aberta_ate = time.time() + self.janela
            return {"ok": True, "resposta": resposta,
                    "comando": "direto", "acao": _int.get("acao")}

        inicio = time.time()
        try:
            resposta = self.orch.process(
                texto, on_event=lambda t, d: self._narrar(t, d))
        except Exception as exc:
            erro = f"Não consegui concluir: {exc}"
            if falar:
                self.voz.tts.falar(erro, assincrono=True)
            return {"ok": False, "erro": str(exc), "resposta": erro,
                    "sessao": self.estado()}

        self.ultima_pergunta = texto
        self.ultima_resposta = resposta
        fala = {}
        if falar:
            # resposta tem prioridade sobre narrações pendentes
            try:
                self.voz.tts.falante.cancelar_abaixo(2)
            except Exception:
                _log.debug("exceção ignorada", exc_info=True)
            fala = self.voz.tts.falar(limpar_para_fala(resposta),
                                      assincrono=True, prioridade=2,
                                      idioma=self.idioma)
        return {"ok": True, "pergunta": texto, "resposta": resposta,
                "fala": fala, "segundos": round(time.time() - inicio, 1),
                "sessao": self.estado()}
