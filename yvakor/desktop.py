"""YVAKOR Desktop — interface nativa (Tkinter), sem HTML.

Fala com o núcleo local em http://127.0.0.1:7777. Se o núcleo não estiver
no ar, inicia-o sozinho em segundo plano.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import queue
import subprocess
from yvakor import proc as _ywproc
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import urllib.error
import urllib.parse
import urllib.request
import wave
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from yvakor.textos import sem_json_de_ferramenta

BASE = os.environ.get("YVAKOR_URL", "http://127.0.0.1:7777")
ROOT = Path(__file__).resolve().parents[1]

# Paleta no estilo do Claude.ai (Tk não tem alpha por widget: cores opacas).
# Tema: variável YVAKOR_TEMA ou "tema" em data/preferencias.json
# ("claro" | "escuro" | "auto" = o do Windows). Trocar exige reiniciar o app.
def _tema_escuro() -> bool:
    pref = os.environ.get("YVAKOR_TEMA", "").strip().lower()
    if not pref:
        try:
            import json as _json
            pref = str(_json.loads((ROOT / "data" / "preferencias.json")
                                   .read_text(encoding="utf-8")).get("tema", "")
                       ).strip().lower()
        except Exception:
            pref = ""
    if pref in ("claro", "light"):
        return False
    if pref in ("escuro", "dark"):
        return True
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except Exception:
            pass
    return True


ESCURO = _tema_escuro()
if ESCURO:
    BG = "#262624"
    PANEL = "#1F1E1D"          # barra lateral
    PANEL2 = "#30302E"         # cartões e campo de mensagem
    CARD = "#30302E"
    FG = "#FAF9F5"
    MUTED = "#A8A69E"
    DIM = "#7C7A73"
    PLACEHOLDER = "#7C7A73"
    GOLD = "#D97757"           # terracota do Claude
    GOLD_SOFT = "#3A2D28"
    GOLD_HOVER = "#E58A6B"
    TEAL = "#7FBF8F"
    TEAL_BG = "#2A3A2F"
    TEAL_LINE = "#3C5443"
    LINE = "#3A3937"
    USER_BG = "#393937"
    AGENT_BG = "#262624"       # resposta sem balão
    ERR = "#E07A70"
    ERR_HOVER = "#EE9189"
    STATUS_BG = "#1F1E1D"
    SCROLL = "#4A4946"
    TEXTO2 = "#D8D6CD"
else:
    BG = "#FAF9F5"
    PANEL = "#F5F4EE"
    PANEL2 = "#FFFFFF"
    CARD = "#FFFFFF"
    FG = "#1F1E1D"
    MUTED = "#6B6A64"
    DIM = "#8E8C85"
    PLACEHOLDER = "#9A988F"
    GOLD = "#C96442"
    GOLD_SOFT = "#F6E7DF"
    GOLD_HOVER = "#B9573A"
    TEAL = "#4D8A5F"
    TEAL_BG = "#E4EFE7"
    TEAL_LINE = "#BFD6C6"
    LINE = "#E3E0D5"
    USER_BG = "#F0EEE6"
    AGENT_BG = "#FAF9F5"
    ERR = "#B4443B"
    ERR_HOVER = "#C25A51"
    STATUS_BG = "#F5F4EE"
    SCROLL = "#CFCBBE"
    TEXTO2 = "#3A3935"
ON_GOLD = "#FFFFFF"            # texto sobre botões terracota/erro
FONTES_DIR = ROOT / "interface" / "fonts"
UI = "Inter" if (FONTES_DIR / "Inter.ttf").is_file() else "Segoe UI"
UI_SEMI = UI
DISPLAY = ("Lora" if (FONTES_DIR / "Lora.ttf").is_file()
           else "Bahnschrift SemiBold")
FONT = (UI, 10)
FONT_S = (UI, 9)
FONT_XS = (UI, 8)
FONT_B = (UI_SEMI, 10)
TITLE = (DISPLAY, 19)
ACCENT = GOLD
OK = TEAL


def _preparar_windows():
    """DPI + fontes privadas (Sora/Unbounded) antes de criar o Tk."""
    if os.name != "nt":
        return
    try:
        import ctypes
        for arq in FONTES_DIR.glob("*.ttf"):
            try:
                ctypes.windll.gdi32.AddFontResourceExW(str(arq), 0x10, 0)
            except Exception:
                pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _barra_titulo_escura(root: tk.Tk):
    """Título escuro do Windows; no-op nas versões que não suportam."""
    if os.name != "nt":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        valor = ctypes.c_int(1 if ESCURO else 0)
        for atributo in (20, 19):  # 20 = Win11; 19 = Win10 antigo
            try:
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, atributo, ctypes.byref(valor),
                        ctypes.sizeof(valor)) == 0:
                    break
            except Exception:
                continue
    except Exception:
        pass


def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, raio, **kw):
    """Retângulo arredondado via polígono suavizado (sem Pillow)."""
    r = min(raio, (x2 - x1) // 2, (y2 - y1) // 2)
    pontos = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pontos, smooth=True, **kw)


def _limpar_texto(txt: str, limite: int) -> str:
    txt = " ".join((txt or "").split())
    return txt if len(txt) <= limite else txt[:limite - 1].rstrip() + "…"


def _misturar(c1: str, c2: str, t: float) -> str:
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{int(x + (y - x) * t):02x}"
                         for x, y in zip(a, b))


def _limpar_markdown(texto: str) -> str:
    """Exibe Markdown limpo em Label; o texto original continua copiável."""
    import re
    t = str(texto or "")
    t = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", t).replace("```", "")
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t, flags=re.S)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", t)
    t = re.sub(r"`([^`\n]+)`", r"\1", t)
    t = re.sub(r"!\[([^\]]*)\]\((https?://[^)]+|/[^)]+)\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1\n\2", t)
    t = re.sub(r"(?m)^\s*[-*]\s+", "• ", t)
    return t.strip()


class ChatView(tk.Frame):
    """Transcrição com bolhas: você à direita, YVAKOR à esquerda.

    A bolha tem faixa de acento (dourada/teal) como no HTML. A rolagem só
    acompanha o fim se o usuário já estava no fim (não sequestra a leitura).
    """

    LARGURA_MAX = 860

    def __init__(self, master, ao_sugestao=None):
        super().__init__(master, bg=BG)
        self._ao_sugestao = ao_sugestao
        self.canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=0,
                                takefocus=1)
        self.scroll = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview,
            style="YVAKOR.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self._labels: list[tk.Label] = []
        self._textos: list[tuple[str, str]] = []
        self._wrap = 640
        self._seguir = True
        self._vazio = None
        self._resize_job = None
        self._lote = 0
        self._rewrap_job = None
        self._rewrap_fila: list[tk.Label] = []
        self._rewrap_largura = None
        self._typing_frame = None
        self._typing_label = None
        self._typing_canvas = None
        self._typing_dots = []
        self._typing_job = None
        self._typing_texto = "pensando"
        self._typing_i = 0
        self.canvas.bind("<Configure>", self._agendar_resize)
        self.inner.bind("<Configure>", self._inner_config)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Prior>", lambda e: self._pagina(-1))
        self.canvas.bind("<Next>", lambda e: self._pagina(1))
        self.canvas.bind("<Home>", lambda e: self.canvas.yview_moveto(0))
        self.canvas.bind("<End>", lambda e: self.rolar_fim(True))
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set())

    # -------------------------- layout/rolagem ------------------------- #
    def _inner_config(self, _evt=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass

    def _agendar_resize(self, _evt=None):
        if self._resize_job:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(60, self._resize)

    def _resize(self):
        self._resize_job = None
        largura = max(320, min(self.canvas.winfo_width(), self.LARGURA_MAX))
        x = max(0, (self.canvas.winfo_width() - largura) // 2)
        try:
            self.canvas.coords(self._win, x, 0)
            self.canvas.itemconfigure(self._win, width=largura)
        except Exception:
            return
        wrap = max(260, int(largura * 0.88) - 40)
        if abs(wrap - self._wrap) > 12:
            self._wrap = wrap
            self._iniciar_rewrap(wrap)
        self._inner_config()

    def _iniciar_rewrap(self, wrap: int):
        """Reembrulha primeiro o que está visível; o resto em lotes."""
        self._cancelar_rewrap()
        try:
            topo = self.canvas.canvasy(0) - 160
            base = topo + self.canvas.winfo_height() + 320
            origem = self.inner.winfo_rooty()
        except Exception:
            topo, base, origem = 0, 10 ** 9, 0
        pendentes = []
        for lbl in self._labels:
            try:
                if not lbl.winfo_exists():
                    continue
                y = lbl.winfo_rooty() - origem
            except Exception:
                y = 0
            if topo <= y <= base:
                try:
                    lbl.configure(wraplength=wrap)
                except Exception:
                    pass
            else:
                pendentes.append(lbl)
        self._rewrap_fila = pendentes
        self._rewrap_largura = wrap
        if pendentes:
            self._rewrap_job = self.after(30, self._rewrap_lote)

    def _rewrap_lote(self):
        self._rewrap_job = None
        largura = self._rewrap_largura
        lote = self._rewrap_fila[:20]
        del self._rewrap_fila[:20]
        for lbl in lote:
            try:
                if lbl.winfo_exists():
                    lbl.configure(wraplength=largura)
            except Exception:
                pass
        if self._rewrap_fila:
            self._rewrap_job = self.after(16, self._rewrap_lote)

    def _cancelar_rewrap(self):
        if self._rewrap_job:
            try:
                self.after_cancel(self._rewrap_job)
            except Exception:
                pass
        self._rewrap_job = None
        self._rewrap_fila = []

    def inicio_lote(self):
        self._lote += 1

    def fim_lote(self, rolar: bool = True):
        self._lote = max(0, self._lote - 1)
        if self._lote:
            return
        self._inner_config()
        if rolar:
            self.rolar_fim()

    def _bind_roda(self, widget):
        widget.bind("<MouseWheel>", self._wheel)
        return widget

    def _wheel(self, evt):
        delta = int(getattr(evt, "delta", 0) or 0)
        if not delta:
            return "break"
        passos = int(-delta / 120) or (-1 if delta > 0 else 1)
        self.canvas.yview_scroll(passos * 3, "units")
        self._seguir = self._perto_do_fim()
        return "break"

    def _pagina(self, direcao: int):
        self.canvas.yview_scroll(direcao, "pages")
        self._seguir = self._perto_do_fim()

    def _perto_do_fim(self, tol: float = 0.015) -> bool:
        try:
            return self.canvas.yview()[1] >= 1 - tol
        except Exception:
            return True

    def rolar_fim(self, forcar: bool = False):
        if not (forcar or self._seguir):
            return
        self._inner_config()
        try:
            self.canvas.update_idletasks()
            self.canvas.yview_moveto(1)
            self._seguir = True
        except Exception:
            pass

    # ------------------------------ animação --------------------------- #
    @staticmethod
    def _fade_cor(widget, opcao: str, de: str, para: str,
                  passos: int = 6, atraso: int = 26):
        def passo(i=0):
            if not widget.winfo_exists():
                return
            t = i / max(1, passos)
            try:
                widget.configure(**{opcao: _misturar(de, para, t)})
            except Exception:
                return
            if i < passos:
                widget.after(atraso, lambda: passo(i + 1))
        passo()

    def _deslizar(self, linha, i: int = 0):
        if not linha.winfo_exists():
            return
        y = 10 - int(6 * (i / 6))
        try:
            linha.pack_configure(pady=(max(4, y), 0))
        except Exception:
            return
        if i < 6:
            linha.after(16, lambda: self._deslizar(linha, i + 1))

    # ----------------------------- mensagens --------------------------- #
    def clear(self):
        self.parar_typing()
        self._cancelar_rewrap()
        for w in self.inner.winfo_children():
            w.destroy()
        self._labels.clear()
        self._textos.clear()
        self._vazio = None
        self._seguir = True
        self._inner_config()
        try:
            self.canvas.yview_moveto(0)
        except Exception:
            pass

    def add_card(self, card):
        """Insere um painel ao vivo dentro da transcrição."""
        card.pack(fill="x", padx=26, pady=6)
        self._inner_config()
        self.canvas.yview_moveto(1)
        return card

    def add(self, tipo: str, texto: str, animar: bool = True,
            url: str | None = None, rolar: bool = True):
        texto = (texto or "").replace("\r", "")
        self._remover_vazio()
        linha = tk.Frame(self.inner, bg=BG)
        linha.pack(fill="x", padx=18, pady=(10 if animar else 3, 0))
        self._bind_roda(linha)

        if tipo == "system":
            lbl = tk.Label(linha, text=texto, bg=BG, fg=MUTED,
                           font=FONT_XS, justify="center",
                           wraplength=self._wrap)
            lbl.pack(anchor="center")
            self._labels.append(lbl)
            self._textos.append(("system", texto))
            self._bind_roda(lbl)
            if not self._lote:
                self._inner_config()
                if rolar:
                    self.rolar_fim()
            return

        usuario = tipo == "user"
        fundo = USER_BG if usuario else AGENT_BG
        lado = "right" if usuario else "left"
        bolha = tk.Frame(linha, bg=fundo)
        bolha.pack(anchor="e" if usuario else "w")
        faixa = tk.Frame(bolha, width=0, bg=fundo)   # (sem faixa colorida)
        faixa.pack(side=lado, fill="y")
        ancora = "e" if usuario else "w"

        if tipo == "meta":
            lbl = tk.Label(bolha, text="↗  " + (texto or "artefato"),
                           bg=fundo, fg=TEAL, font=(UI, 9, "underline"),
                           justify="left", anchor="w",
                           wraplength=self._wrap, cursor="hand2")
            lbl.pack(anchor="w", padx=(12, 12), pady=8)
            if url:
                lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            self._textos.append(("meta", texto or ""))
            self._bind_roda(lbl)
        else:
            exibicao = texto if usuario else _limpar_markdown(
                sem_json_de_ferramenta(texto))
            corpo = tk.Label(bolha, text=exibicao, bg=fundo, fg=FG,
                             justify="left",
                             anchor=ancora,
                             font=(UI, 10) if usuario else (DISPLAY, 11),
                             wraplength=self._wrap)
            corpo.pack(anchor=ancora, padx=(14, 14) if usuario else (2, 2),
                       pady=(8, 8) if usuario else (4, 10))
            self._labels.append(corpo)
            self._textos.append(("user" if usuario else "agent", texto))
            self._menu_copiar(corpo, texto)
            self._bind_roda(corpo)

        for w in (bolha, faixa):
            self._bind_roda(w)
        if animar:
            alvo = faixa.cget("bg")
            self._fade_cor(faixa, "bg", BG, alvo)
            self._deslizar(linha)
        if not self._lote:
            self._inner_config()
            if rolar:
                self.rolar_fim()

    def add_anexo(self, anexo: dict, usuario: bool = True):
        """Mostra imagem/vídeo anexado dentro da conversa."""
        caminho = str(anexo.get("caminho") or "")
        nome = str(anexo.get("nome") or Path(caminho).name or "anexo")
        url = str(anexo.get("url") or "")
        linha = tk.Frame(self.inner, bg=BG)
        linha.pack(fill="x", padx=18, pady=(2, 0))
        self._bind_roda(linha)
        fundo = USER_BG if usuario else AGENT_BG
        card = tk.Frame(linha, bg=fundo)
        card.pack(anchor="e" if usuario else "w")
        tipo = str(anexo.get("tipo") or "")
        if tipo == "imagem" and Image is not None and Path(caminho).is_file():
            try:
                img = Image.open(caminho)
                img.thumbnail((430, 320), Image.LANCZOS)
                foto = ImageTk.PhotoImage(img)
                alvo = tk.Label(card, image=foto, bg=fundo, cursor="hand2")
                alvo.image = foto
                alvo.pack(padx=8, pady=8)
                if url:
                    alvo.bind("<Button-1>", lambda e, u=BASE + url:
                              webbrowser.open(u))
            except Exception:
                tk.Label(card, text="🖼 " + nome, bg=fundo, fg=FG,
                         font=FONT_XS, padx=12, pady=8).pack()
        else:
            rotulo = ("🎬 " + nome if tipo == "video" else
                      "📄 " + nome if tipo == "documento" else "📎 " + nome)
            mostrou = False
            if tipo == "video" and Image is not None and Path(caminho).is_file():
                try:
                    temp = Path(tempfile.gettempdir()) / (
                        "yvakor_" + str(abs(hash(caminho))) + ".jpg")
                    _ywproc.run(
                        ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.4",
                         "-i", caminho, "-frames:v", "1", "-vf", "scale=430:-2",
                         str(temp)], capture_output=True, timeout=15)
                    if temp.is_file():
                        img = Image.open(temp)
                        img.thumbnail((430, 300), Image.LANCZOS)
                        foto = ImageTk.PhotoImage(img)
                        alvo = tk.Label(card, image=foto, bg=fundo,
                                        cursor="hand2")
                        alvo.image = foto
                        alvo.pack(padx=8, pady=(8, 2))
                        alvo.bind("<Button-1>", lambda e, p=caminho:
                                  os.startfile(p))
                        tk.Label(card, text="▶ " + nome, bg=fundo, fg=TEAL,
                                 font=(UI, 8), padx=8, pady=2,
                                 cursor="hand2").pack(anchor="w", padx=8,
                                                      pady=(0, 8))
                        mostrou = True
                except Exception:
                    mostrou = False
            if not mostrou:
                alvo = tk.Label(card, text=rotulo, bg=fundo, fg=TEAL,
                                font=FONT_XS, padx=12, pady=8, cursor="hand2")
                alvo.pack()
                if caminho and Path(caminho).is_file():
                    alvo.bind("<Button-1>", lambda e, p=caminho:
                              os.startfile(p))
        self._inner_config()
        self.rolar_fim()

    # ------------------------------- cópia ----------------------------- #
    def _menu_copiar(self, widget, texto):
        widget.bind("<Button-3>",
                    lambda e, t=texto: self._popup_copia(e, t))

    def _popup_copia(self, evt, texto):
        menu = tk.Menu(self, tearoff=0, bg=PANEL2, fg=FG,
                       activebackground=TEAL_BG, activeforeground=FG,
                       bd=0, font=FONT_XS)
        menu.add_command(label="Copiar mensagem",
                         command=lambda: self._copiar(texto))
        menu.add_command(label="Copiar conversa",
                         command=lambda: self._copiar(self.texto_tudo()))
        try:
            menu.tk_popup(evt.x_root, evt.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _copiar(self, texto: str):
        try:
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.update_idletasks()
        except Exception:
            pass

    def texto_tudo(self) -> str:
        partes = []
        for tipo, texto in self._textos:
            if tipo == "system":
                continue
            prefixo = "Você: " if tipo == "user" else "YVAKOR: "
            partes.append(prefixo + texto)
        return "\n\n".join(partes)

    @property
    def ultima_agente(self) -> str:
        for tipo, texto in reversed(self._textos):
            if tipo == "agent":
                return texto
        return ""

    # ------------------------------ typing ----------------------------- #
    def typing(self, texto: str = "pensando"):
        self.parar_typing()
        self._remover_vazio()
        linha = tk.Frame(self.inner, bg=BG)
        linha.pack(fill="x", padx=18, pady=(8, 0))
        bolha = tk.Frame(linha, bg=AGENT_BG)
        bolha.pack(anchor="w")
        faixa = tk.Frame(bolha, width=2, bg=GOLD)
        faixa.pack(side="left", fill="y")
        conteudo = tk.Frame(bolha, bg=AGENT_BG)
        conteudo.pack(side="left")
        self._typing_canvas = tk.Canvas(conteudo, width=36, height=14,
                                        bg=AGENT_BG, highlightthickness=0)
        self._typing_canvas.pack(side="left", padx=(10, 4), pady=8)
        self._typing_dots = [
            self._typing_canvas.create_oval(2 + i * 10, 4, 8 + i * 10, 10,
                                            fill=GOLD_SOFT, outline="")
            for i in range(3)
        ]
        self._typing_label = tk.Label(conteudo, text=texto, bg=AGENT_BG,
                                      fg=MUTED, font=(UI, 8),
                                      anchor="w")
        self._typing_label.pack(side="left", padx=(0, 12), pady=8)
        self._typing_frame = linha
        self._typing_texto = texto
        self._typing_i = 0
        for w in (linha, bolha, faixa, conteudo, self._typing_canvas,
                  self._typing_label):
            self._bind_roda(w)
        self._tic_typing()
        self._inner_config()
        self.rolar_fim()

    def _tic_typing(self):
        if not self._typing_label:
            return
        try:
            if not self._typing_label.winfo_exists():
                return
            if self.winfo_toplevel().state() not in ("iconic", "withdrawn"):
                for i, dot in enumerate(self._typing_dots):
                    self._typing_canvas.itemconfigure(
                        dot, fill=GOLD if i == (self._typing_i % 3)
                        else GOLD_SOFT)
            self._typing_i += 1
            self._typing_job = self.after(200, self._tic_typing)
        except Exception:
            return

    def set_typing_texto(self, texto: str):
        self._typing_texto = (texto or "pensando")[:120]
        lbl = self._typing_label
        if lbl:
            try:
                if lbl.winfo_exists():
                    lbl.configure(text=self._typing_texto)
            except Exception:
                pass

    def parar_typing(self):
        job = getattr(self, "_typing_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._typing_job = None
        frame = getattr(self, "_typing_frame", None)
        if frame:
            try:
                frame.destroy()
            except Exception:
                pass
        self._typing_frame = None
        self._typing_label = None
        self._typing_canvas = None
        self._typing_dots = []

    # ------------------------------- vazio ----------------------------- #
    def mostrar_vazio(self, titulo: str = "YVAKOR",
                      subtitulo: str = "Pergunte algo, peça uma tarefa ou "
                                       "diga “abra o Chrome”.",
                      sugestoes=()):
        if self.inner.winfo_children():
            return
        self._vazio = tk.Frame(self.inner, bg=BG)
        self._vazio.pack(fill="x", pady=(70, 20))
        marca = tk.Frame(self._vazio, bg=BG)
        marca.pack()
        tk.Label(marca, text="YVA", bg=BG, fg=FG,
                 font=(DISPLAY, 26)).pack(side="left")
        tk.Label(marca, text="KOR", bg=BG, fg=GOLD,
                 font=(DISPLAY, 26)).pack(side="left")
        if subtitulo:
            tk.Label(self._vazio, text=subtitulo, bg=BG, fg=MUTED,
                     font=FONT_XS, wraplength=460,
                     justify="center").pack(pady=(6, 18))
        for texto in sugestoes:
            btn = tk.Label(self._vazio, text=texto, bg=PANEL2, fg=FG,
                           font=FONT_XS, padx=14, pady=7, cursor="hand2",
                           anchor="w")
            btn.pack(fill="x", padx=110, pady=3)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=TEAL_BG))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=PANEL2))
            btn.bind("<Button-1>", lambda e, t=texto: self._sugerir(t))
            self._bind_roda(btn)
        for w in (self._vazio, marca):
            self._bind_roda(w)
        self._inner_config()

    def _sugerir(self, texto: str):
        if self._ao_sugestao:
            self._ao_sugestao(texto)

    def _remover_vazio(self):
        if self._vazio is not None:
            try:
                self._vazio.destroy()
            except Exception:
                pass
            self._vazio = None


class Abas(tk.Frame):
    """Barra de abas desenhada (substitui o ttk.Notebook de cara de Tk)."""

    def __init__(self, master, ao_mudar=None):
        super().__init__(master, bg=BG)
        self.ao_mudar = ao_mudar
        self._paginas: list[tk.Frame] = []
        self._botoes: list[tk.Label] = []
        self._ind: list[tk.Frame] = []
        self.atual = -1
        self.barra = tk.Frame(self, bg=BG)
        self.barra.pack(fill="x")
        self._linha = tk.Frame(self.barra, bg=LINE, height=1)
        self._linha.pack(side="bottom", fill="x")
        self.corpo = tk.Frame(self, bg=BG)
        self.corpo.pack(fill="both", expand=True)

    def adicionar(self, texto: str, construtor):
        i = len(self._paginas)
        pagina = tk.Frame(self.corpo, bg=BG)
        construtor(pagina)
        self._paginas.append(pagina)
        holder = tk.Frame(self.barra, bg=BG)
        holder.pack(side="left", padx=(0, 2))
        btn = tk.Label(holder, text=texto.upper(), bg=BG, fg=MUTED,
                       font=(UI_SEMI, 8), padx=16, pady=9,
                       cursor="hand2")
        btn.pack()
        ind = tk.Frame(holder, bg=BG, height=2)
        ind.pack(fill="x")
        btn.bind("<Enter>", lambda e, n=i: self._hover(n, True))
        btn.bind("<Leave>", lambda e, n=i: self._hover(n, False))
        btn.bind("<Button-1>", lambda e, n=i: self.selecionar(n))
        self._botoes.append(btn)
        self._ind.append(ind)
        return pagina

    def _hover(self, i: int, entrando: bool):
        if i == self.atual:
            return
        self._botoes[i].configure(fg=FG if entrando else MUTED)

    def selecionar(self, indice: int):
        if not self._paginas:
            return
        indice %= len(self._paginas)
        if indice == self.atual:
            return
        for pagina in self._paginas:
            pagina.pack_forget()
        self._paginas[indice].pack(fill="both", expand=True)
        for i, botao in enumerate(self._botoes):
            botao.configure(fg=FG if i == indice else MUTED)
            self._ind[i].configure(bg=GOLD if i == indice else BG)
        self.atual = indice
        if self.ao_mudar:
            self.ao_mudar(indice)

    def index(self, _qual="current") -> int:
        return self.atual


class SessaoLista(tk.Frame):
    """Lista rica de conversas (título, hora, preview, badge e ações)."""

    def __init__(self, master, ao_abrir, ao_renomear, ao_apagar):
        super().__init__(master, bg=PANEL)
        self._ao_abrir = ao_abrir
        self._ao_renomear = ao_renomear
        self._ao_apagar = ao_apagar
        self._sessoes: list[dict] = []
        self._ativa = None
        self._assinatura = None
        self._filtro = ""
        self.canvas = tk.Canvas(self, bg=PANEL, bd=0, highlightthickness=0)
        self.scroll = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview,
            style="YVAKOR.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.inner = tk.Frame(self.canvas, bg=PANEL)
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.inner.bind("<Configure>", self._inner_config)
        self.canvas.bind("<Configure>", self._resize)
        self._bind_roda(self.canvas)
        self._bind_roda(self.inner)
        self._vazio = None

    def _inner_config(self, _evt=None):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except Exception:
            pass

    def _resize(self, evt):
        try:
            self.canvas.itemconfigure(self._win, width=evt.width)
        except Exception:
            pass
        self._inner_config()

    def _bind_roda(self, widget):
        widget.bind("<MouseWheel>", self._wheel)
        return widget

    def _wheel(self, evt):
        delta = int(getattr(evt, "delta", 0) or 0)
        passos = int(-delta / 120) or (-1 if delta > 0 else 1)
        self.canvas.yview_scroll(passos * 2, "units")
        return "break"

    # ------------------------------ dados ------------------------------ #
    def definir(self, sessoes, ativa, forcar: bool = False):
        self._sessoes = list(sessoes or [])
        self._ativa = ativa
        assinatura = (self._filtro, ativa, tuple(
            (s.get("id"), s.get("title"), s.get("last_at"),
             s.get("preview"), s.get("episodes"))
            for s in self._sessoes))
        if not forcar and assinatura == self._assinatura:
            return
        self._assinatura = assinatura
        self._reconstruir()

    def marcar_ativa(self, sid):
        if sid == self._ativa:
            return
        self._ativa = sid
        self._assinatura = None
        self._reconstruir()

    def filtrar(self, texto: str):
        texto = (texto or "").strip().lower()
        if texto == self._filtro:
            return
        self._filtro = texto
        self._assinatura = None
        self._reconstruir()

    def _reconstruir(self):
        try:
            pos = 0.0 if self._filtro else self.canvas.yview()[0]
        except Exception:
            pos = 0.0
        for w in self.inner.winfo_children():
            w.destroy()
        self._vazio = None
        filtradas = [s for s in self._sessoes if self._passa(s)]
        if not self._sessoes:
            self._mostrar_vazio("Nenhuma conversa ainda.")
        elif not filtradas:
            self._mostrar_vazio("Nada encontrado para essa busca.")
        else:
            grupo = None
            for s in filtradas[:60]:
                rotulo = self._grupo(s.get("last_at"))
                if rotulo != grupo:
                    grupo = rotulo
                    tk.Label(self.inner, text=rotulo.upper(), bg=PANEL,
                             fg=DIM, font=(UI_SEMI, 7),
                             anchor="w").pack(fill="x", padx=14,
                                              pady=(10, 2))
                self._criar_item(s)
        self.inner.update_idletasks()
        self._inner_config()
        try:
            self.canvas.yview_moveto(pos)
        except Exception:
            pass

    def _passa(self, s) -> bool:
        if not self._filtro:
            return True
        alvo = " ".join((str(s.get("title") or ""),
                         str(s.get("preview") or ""))).lower()
        return self._filtro in alvo

    @staticmethod
    def _data(txt):
        try:
            return datetime.fromisoformat(str(txt or "").replace(" ", "T"))
        except Exception:
            return None

    def _grupo(self, txt) -> str:
        d = self._data(txt)
        if not d:
            return "Anteriores"
        dias = (datetime.now().date() - d.date()).days
        if dias <= 0:
            return "Hoje"
        if dias == 1:
            return "Ontem"
        if dias < 7:
            return "Últimos 7 dias"
        return "Anteriores"

    def _hora(self, txt) -> str:
        d = self._data(txt)
        if not d:
            return ""
        if d.date() == datetime.now().date():
            return d.strftime("%H:%M")
        return d.strftime("%d/%m")

    def _criar_item(self, s):
        sid = s.get("id")
        ativa = sid == self._ativa
        base = _misturar(PANEL, GOLD, 0.10) if ativa else PANEL
        row = tk.Frame(self.inner, bg=base)
        row.pack(fill="x", padx=(6, 6), pady=1)
        faixa = tk.Frame(row, width=2, bg=GOLD if ativa else base)
        faixa.pack(side="left", fill="y")
        corpo = tk.Frame(row, bg=base)
        corpo.pack(side="left", fill="both", expand=True, padx=(8, 6),
                   pady=6)
        topo = tk.Frame(corpo, bg=base)
        topo.pack(fill="x")
        titulo = tk.Label(
            topo, text=_limpar_texto(s.get("title") or sid, 30), bg=base,
            fg=FG if ativa else TEXTO2,
            font=(UI_SEMI if ativa else UI, 9),
            anchor="w")
        titulo.pack(side="left", fill="x", expand=True)

        acoes = []
        for glifo, funcao in (("✎", self._ao_renomear),
                              ("×", self._ao_apagar)):
            lbl = tk.Label(topo, text=glifo, bg=base,
                           fg=MUTED if ativa else base,
                           font=(UI, 8), padx=2, cursor="hand2")
            lbl.pack(side="right", padx=(2, 0))
            lbl.bind("<Button-1>", lambda e, f=funcao, x=sid: f(x))
            acoes.append(lbl)
        hora = tk.Label(topo, text=self._hora(s.get("last_at")), bg=base,
                        fg=DIM, font=(UI, 7))
        hora.pack(side="right", padx=(4, 2))

        baixo = tk.Frame(corpo, bg=base)
        baixo.pack(fill="x", pady=(3, 0))
        prev = tk.Label(baixo, text=_limpar_texto(s.get("preview") or
                                                 "sem mensagens", 58),
                        bg=base, fg=MUTED, font=(UI, 8), anchor="w")
        prev.pack(side="left", fill="x", expand=True)
        if int(s.get("episodes") or 0) > 1:
            badge = tk.Label(baixo, text=str(s.get("episodes")), bg=TEAL_BG,
                             fg=TEAL, font=(UI, 7), padx=4)
            badge.pack(side="right", padx=(6, 0))

        clicaveis = [row, corpo, topo, titulo, baixo, prev, hora, faixa]
        for w in clicaveis:
            w.bind("<Button-1>", lambda e, x=sid: self._ao_abrir(x))
            self._bind_roda(w)
        for w in acoes:
            self._bind_roda(w)

        def entrar(_e=None):
            if ativa:
                return
            for w in (row, corpo, topo, titulo, baixo, prev, hora):
                try:
                    w.configure(bg=PANEL2)
                except Exception:
                    pass
            for w in acoes:
                try:
                    w.configure(bg=PANEL2, fg=MUTED)
                except Exception:
                    pass

        def sair(_e=None):
            if ativa:
                return
            for w in (row, corpo, topo, titulo, baixo, prev, hora):
                try:
                    w.configure(bg=PANEL)
                except Exception:
                    pass
            for w in acoes:
                try:
                    w.configure(bg=PANEL, fg=PANEL)
                except Exception:
                    pass

        for w in (row, corpo, topo, titulo, baixo, prev, hora):
            w.bind("<Enter>", entrar)
            w.bind("<Leave>", sair)
        for w in acoes:
            w.bind("<Enter>", entrar)
            w.bind("<Leave>", sair)

        def menu(evt):
            m = tk.Menu(self, tearoff=0, bg=PANEL2, fg=FG,
                        activebackground=TEAL_BG, activeforeground=FG,
                        bd=0, font=FONT_XS)
            m.add_command(label="Abrir", command=lambda: self._ao_abrir(sid))
            m.add_command(label="Renomear",
                          command=lambda: self._ao_renomear(sid))
            m.add_separator()
            m.add_command(label="Apagar", command=lambda: self._ao_apagar(sid))
            try:
                m.tk_popup(evt.x_root, evt.y_root)
            finally:
                try:
                    m.grab_release()
                except Exception:
                    pass

        for w in (row, corpo, topo, titulo, baixo, prev):
            w.bind("<Button-3>", menu)

    def _mostrar_vazio(self, texto: str):
        self._vazio = tk.Label(self.inner, text=texto, bg=PANEL, fg=DIM,
                               font=FONT_XS, justify="center",
                               wraplength=220)
        self._vazio.pack(pady=30, padx=16)
        self._bind_roda(self._vazio)



class ErroAPI(RuntimeError):
    pass


_TOKEN_VIVO = ""


def _token(renovar: bool = False) -> str:
    """Token do servidor local, exigido em POST/DELETE.

    Normalmente vem de data/.server_token. Com renovar=True pergunta ao núcleo
    EM EXECUÇÃO (GET /api/token), que é a fonte da verdade: o arquivo pode estar
    velho se o servidor reiniciou ou se outro processo o sobrescreveu.
    """
    global _TOKEN_VIVO
    if _TOKEN_VIVO and not renovar:
        return _TOKEN_VIVO
    if renovar:
        try:
            with urllib.request.urlopen(BASE + "/api/token", timeout=3) as r:
                _TOKEN_VIVO = (json.loads(r.read().decode("utf-8"))
                               .get("token") or "")
            if _TOKEN_VIVO:
                return _TOKEN_VIVO
        except Exception:
            pass
    try:
        _TOKEN_VIVO = (ROOT / "data" / ".server_token").read_text(
            encoding="utf-8").strip()
    except Exception:
        _TOKEN_VIVO = os.environ.get("YVAKOR_TOKEN", "")
    return _TOKEN_VIVO


def _api_uma_vez(path: str, dados: dict | None, timeout: float,
                 metodo: str | None, token: str):
    url = BASE + path
    corpo = None
    headers = {"Accept": "application/json", "X-YVAKOR-Token": token}
    if dados is not None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    verbo = metodo or ("POST" if dados is not None else "GET")
    req = urllib.request.Request(url, data=corpo, headers=headers,
                                 method=verbo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        bruto = ""
        try:
            bruto = exc.read().decode("utf-8", errors="replace")
            j = json.loads(bruto)
            detalhe = j.get("error") or j.get("erro") or j.get("detail")
        except Exception:
            detalhe = bruto.strip()
        raise ErroAPI(f"{exc.code}: {detalhe or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ErroAPI(f"núcleo indisponível ({exc.reason})") from exc
    except TimeoutError as exc:
        raise ErroAPI("núcleo não respondeu a tempo") from exc


def api(path: str, dados: dict | None = None, timeout: float = 60,
        metodo: str | None = None):
    try:
        return _api_uma_vez(path, dados, timeout, metodo, _token())
    except ErroAPI as exc:
        # 403 = token velho (servidor reiniciou): renova com o núcleo e repete.
        if str(exc).startswith("403:"):
            return _api_uma_vez(path, dados, timeout, metodo,
                                _token(renovar=True))
        raise


def ping(timeout: float = 0.7) -> bool:
    try:
        api("/api/ping", timeout=timeout)
        return True
    except Exception:
        return False


def garantir_nucleo(timeout_s: float = 45.0, on_status=None) -> bool:
    """Sobe o núcleo se preciso, com backoff e log — sem travar a UI."""
    if ping():
        return True
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        pasta = ROOT / "data" / "logs"
        pasta.mkdir(parents=True, exist_ok=True)
        with open(pasta / "nucleo.log", "ab") as log:
            _ywproc.popen(
                [sys.executable, "-m", "yvakor.server"], cwd=str(ROOT),
                creationflags=flags, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, close_fds=True)
    except Exception:
        return False
    inicio = time.time()
    espera = 0.15
    ultimo_aviso = 0.0
    while time.time() - inicio < timeout_s:
        if ping(0.6):
            return True
        if on_status and time.time() - ultimo_aviso > 4:
            ultimo_aviso = time.time()
            try:
                on_status("núcleo subindo…")
            except Exception:
                pass
        time.sleep(espera)
        espera = min(espera * 1.4, 0.8)
    return False


try:
    from PIL import Image, ImageTk
except Exception:  # Pillow opcional; sem ele o popup mostra aviso
    Image = ImageTk = None


class JanelaCameras(tk.Toplevel):
    """Lista de câmeras com acesso à janela ao vivo."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("YVAKOR · Câmeras")
        self.configure(bg=BG)
        self.geometry("560x460")
        self.transient(app.root)
        cab = tk.Frame(self, bg=BG)
        cab.pack(fill="x", padx=18, pady=(14, 8))
        tk.Label(cab, text="CÂMERAS", bg=BG, fg=FG,
                 font=(DISPLAY, 14)).pack(side="left")
        tk.Button(cab, text="Atualizar", command=self._carregar, bg=PANEL2,
                  fg=FG, bd=0, padx=10, cursor="hand2").pack(side="right")
        self.corpo = tk.Frame(self, bg=BG)
        self.corpo.pack(fill="both", expand=True, padx=18, pady=8)
        tk.Label(self.corpo, text="carregando…", bg=BG, fg=MUTED).pack()
        self._carregar()

    def _carregar(self):
        def trabalho():
            try:
                j = api("/api/rede", timeout=20)
                cams = [d for d in (j.get("dispositivos") or [])
                        if (d.get("tipo") or "").lower() == "camera"]
                self.app._post(self._pintar, cams)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                self.app._post(self._erro, msg)
        threading.Thread(target=trabalho, daemon=True).start()

    def _erro(self, msg):
        for w in self.corpo.winfo_children():
            w.destroy()
        tk.Label(self.corpo, text=msg, bg=BG, fg=ERR, wraplength=500,
                 justify="left").pack(anchor="w")

    def _pintar(self, cams):
        for w in self.corpo.winfo_children():
            w.destroy()
        if not cams:
            tk.Label(self.corpo, text="Nenhuma câmera reconhecida na rede.",
                     bg=BG, fg=MUTED).pack(anchor="w")
            return
        for d in cams:
            card = tk.Frame(self.corpo, bg=PANEL2, highlightbackground=LINE,
                            highlightthickness=1)
            card.pack(fill="x", pady=5)
            info = tk.Frame(card, bg=PANEL2)
            info.pack(side="left", fill="x", expand=True, padx=12, pady=9)
            nome = d.get("nome") or d.get("hostname") or d.get("ip")
            tk.Label(info, text=nome, bg=PANEL2, fg=FG,
                     font=(UI_SEMI, 10)).pack(anchor="w")
            detalhe = f"{d.get('ip', '')} · {d.get('fabricante') or ''} " \
                      f"{'online' if d.get('online') else 'offline'}"
            tk.Label(info, text=detalhe, bg=PANEL2, fg=MUTED,
                     font=(UI, 8)).pack(anchor="w")
            tk.Button(card, text="Na conversa", bg=TEAL_BG, fg=TEAL, bd=0,
                      padx=10, pady=6, cursor="hand2",
                      command=lambda dev=d: self.app.abrir_camera_conversa(dev)
                      ).pack(side="right", padx=(0, 4))
            tk.Button(card, text="Janela", bg=PANEL2, fg=FG, bd=0, padx=10,
                      pady=6, cursor="hand2",
                      command=lambda dev=d: self.app.abrir_camera(dev)
                      ).pack(side="right", padx=(0, 6))


class JanelaCamera(tk.Toplevel):
    """Popup nativo com atualização periódica do snapshot da câmera."""

    def __init__(self, app, dev):
        super().__init__(app.root)
        self.app = app
        self.dev = dev
        self.ip = str(dev.get("ip") or "")
        self.nome = dev.get("nome") or self.ip
        self.vivo = True
        self._foto = None
        self._job = None
        self._ultimo = b""
        self.title(f"YVAKOR · {self.nome}")
        self.configure(bg=BG)
        self.geometry("960x680")
        self.minsize(640, 460)
        self.protocol("WM_DELETE_WINDOW", self.fechar)

        cab = tk.Frame(self, bg=PANEL)
        cab.pack(fill="x")
        tk.Label(cab, text="●", bg=PANEL, fg=TEAL,
                 font=(UI, 10)).pack(side="left", padx=(14, 4),
                                             pady=10)
        tk.Label(cab, text=self.nome, bg=PANEL, fg=FG,
                 font=(UI_SEMI, 11)).pack(side="left")
        tk.Label(cab, text=f"  {self.ip}", bg=PANEL, fg=MUTED,
                 font=(UI, 9)).pack(side="left")
        self.status = tk.Label(cab, text="conectando…", bg=PANEL, fg=MUTED,
                               font=(UI, 8))
        self.status.pack(side="right", padx=12)
        self.btn_vlc = tk.Button(cab, text="Abrir no VLC", bg=PANEL2, fg=FG,
                                 bd=0, padx=10, command=self._vlc)
        self.btn_vlc.pack(side="right", padx=4, pady=6)
        self.btn_foto = tk.Button(cab, text="Salvar foto", bg=PANEL2, fg=FG,
                                  bd=0, padx=10, command=self._salvar)
        self.btn_foto.pack(side="right", padx=4, pady=6)

        self.tela = tk.Label(self, bg="#000000", fg=MUTED,
                             text="carregando imagem…")
        self.tela.pack(fill="both", expand=True, padx=12, pady=12)
        self._agendar(100)

    def _agendar(self, atraso=2500):
        if self.vivo:
            self._job = self.after(atraso, self._atualizar)

    def _atualizar(self):
        if not self.vivo:
            return

        def trabalho():
            try:
                url = (f"{BASE}/api/rede/camera/{urllib.parse.quote(self.ip)}"
                       "/snapshot")
                req = urllib.request.Request(
                    url, headers={"Accept": "image/jpeg",
                                  "Cache-Control": "no-cache"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    dados = r.read()
                self.app._post(self._mostrar, dados)
            except Exception as exc:
                msg = f"sem imagem: {type(exc).__name__}: {exc}"
                self.app._post(self._erro, msg)
        threading.Thread(target=trabalho, daemon=True).start()

    def _mostrar(self, dados):
        if not self.vivo:
            return
        self._ultimo = dados
        if Image is None:
            self.tela.configure(text="Pillow não instalado para exibir imagem.")
            self._agendar()
            return
        try:
            img = Image.open(io.BytesIO(dados))
            largura = max(320, self.tela.winfo_width() - 8)
            altura = max(240, self.tela.winfo_height() - 8)
            img.thumbnail((largura, altura), Image.LANCZOS)
            self._foto = ImageTk.PhotoImage(img)
            self.tela.configure(image=self._foto, text="")
            self.status.configure(text="ao vivo · atualiza a cada 2,5 s", fg=TEAL)
        except Exception as exc:
            self._erro(f"imagem inválida: {exc}")
            return
        self._agendar()

    def _erro(self, msg):
        if self.vivo:
            self.status.configure(text=msg[:90], fg=ERR)
        self._agendar(4000)

    def _salvar(self):
        if not self._ultimo:
            self.status.configure(text="nenhuma imagem ainda", fg=ERR)
            return
        destino = (ROOT / "data" / "frontend" /
                   f"camera_{self.ip.replace('.', '-')}_{int(time.time())}.jpg")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(self._ultimo)
        self.status.configure(text=f"salvo em {destino.name}", fg=TEAL)

    def _vlc(self):
        self.status.configure(text="abrindo no VLC…", fg=GOLD)

        def trabalho():
            try:
                api("/api/chat", {"message": f"abra a câmera {self.nome} ao vivo"},
                    timeout=120)
                self.app._post(self.status.configure,
                               {"text": "VLC solicitado", "fg": TEAL})
            except Exception as exc:
                self.app._post(self._erro, f"VLC: {exc}")
        threading.Thread(target=trabalho, daemon=True).start()

    def fechar(self):
        self.vivo = False
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        try:
            self.app._cameras_abertas.pop(self.ip, None)
        except Exception:
            pass
        self.destroy()


class JanelaCameraVivo(tk.Toplevel):
    """Vídeo RTSP ao vivo embutido via libVLC (sem snapshots)."""

    def __init__(self, app, dev):
        super().__init__(app.root)
        self.app = app
        self.dev = dev
        self.ip = str(dev.get("ip") or "")
        self.nome = dev.get("nome") or self.ip
        self.vivo = True
        self.instance = None
        self.player = None
        self.title(f"YVAKOR · {self.nome} — AO VIVO")
        self.configure(bg=BG)
        self.geometry("1000x700")
        self.minsize(680, 480)
        self.protocol("WM_DELETE_WINDOW", self.fechar)

        cab = tk.Frame(self, bg=PANEL)
        cab.pack(fill="x")
        tk.Label(cab, text="●", bg=PANEL, fg=TEAL,
                 font=(UI, 11)).pack(side="left", padx=(14, 4),
                                             pady=10)
        tk.Label(cab, text=self.nome, bg=PANEL, fg=FG,
                 font=(UI_SEMI, 11)).pack(side="left")
        tk.Label(cab, text=f"  {self.ip}  ·  RTSP", bg=PANEL, fg=MUTED,
                 font=(UI, 9)).pack(side="left")
        self.status = tk.Label(cab, text="conectando ao vivo…", bg=PANEL,
                               fg=GOLD, font=(UI, 8))
        self.status.pack(side="right", padx=12)
        tk.Button(cab, text="Fechar", bg=PANEL2, fg=FG, bd=0, padx=10,
                  command=self.fechar).pack(side="right", padx=4, pady=6)
        self.btn_pausa = tk.Button(cab, text="Reiniciar", bg=PANEL2, fg=FG,
                                   bd=0, padx=10, command=self._reiniciar)
        self.btn_pausa.pack(side="right", padx=4, pady=6)

        self.video = tk.Frame(self, bg="#000000")
        self.video.pack(fill="both", expand=True, padx=10, pady=10)
        self.tela = tk.Label(self.video, bg="#000000", fg=MUTED,
                             text="conectando ao vídeo ao vivo…")
        self.tela.pack(fill="both", expand=True)
        self._proc = None
        self._dim = (960, 540)
        self._foto = None
        self._pendente = False
        self._frame_visto = False
        self.after(250, self._iniciar)

    def _iniciar(self):
        if not self.vivo:
            return

        def trabalho():
            try:
                j = api(f"/api/rede/camera/{urllib.parse.quote(self.ip)}/url",
                        timeout=30)
                if not j.get("ok"):
                    raise RuntimeError(j.get("erro") or "sem URL RTSP")
                self.app._post(self._play, j["url"], j.get("transporte") or "")
            except Exception as exc:
                self.app._post(self._erro, f"{type(exc).__name__}: {exc}")
        threading.Thread(target=trabalho, daemon=True).start()

    def _play(self, url, transporte: str = ""):
        if not self.vivo:
            return
        self._parar_proc()
        largura, altura = 960, 540
        self._dim = (largura, altura)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               "-rtsp_transport", "tcp" if str(transporte).lower() == "tcp"
               else "udp",
               "-fflags", "nobuffer", "-flags", "low_delay",
               "-i", url, "-an", "-vf", f"scale={largura}:{altura}",
               "-r", "12", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = _ywproc.popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL,
                                          creationflags=flags)
        except Exception as exc:
            self._erro(f"ffmpeg: {exc}")
            return
        self._frame_visto = False
        self.status.configure(text="AO VIVO · conectando…", fg=GOLD)
        threading.Thread(target=self._ler_frames, daemon=True).start()
        self.after(9000, self._sem_frame)

    def _ler_frames(self):
        tamanho = self._dim[0] * self._dim[1] * 3
        proc = self._proc
        while self.vivo and proc is not None and proc.poll() is None:
            dados = proc.stdout.read(tamanho)
            if len(dados) < tamanho:
                break
            if not self._pendente:
                self._pendente = True
                self.app._post(self._mostrar_frame, dados)
        if self.vivo:
            self.app._post(self._erro, "stream ao vivo encerrou")

    def _mostrar_frame(self, dados):
        self._pendente = False
        if not self.vivo or Image is None:
            return
        try:
            img = Image.frombytes("RGB", self._dim, dados)
            largura = max(320, self.tela.winfo_width() - 4)
            altura = max(240, self.tela.winfo_height() - 4)
            img.thumbnail((largura, altura), Image.BILINEAR)
            self._foto = ImageTk.PhotoImage(img)
            self.tela.configure(image=self._foto, text="")
            if not self._frame_visto:
                self._frame_visto = True
                self.status.configure(text="AO VIVO · RTSP", fg=TEAL)
        except Exception as exc:
            self._erro(f"frame inválido: {exc}")

    def _sem_frame(self):
        if self.vivo and not self._frame_visto:
            self.status.configure(text="sem vídeo do RTSP", fg=ERR)

    def _reiniciar(self):
        self.tela.configure(image="", text="reconectando…")
        self._iniciar()

    def _parar_proc(self):
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            _ywproc.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

    def _estado(self):
        if not self.vivo or self.player is None:
            return
        try:
            import vlc
            estado = self.player.get_state()
            if estado == vlc.State.Error:
                self.status.configure(text="erro no stream RTSP", fg=ERR)
                return
            if estado == vlc.State.Ended:
                self.status.configure(text="stream encerrado", fg=ERR)
                return
            if self.player.is_playing():
                self.status.configure(text="AO VIVO · RTSP", fg=TEAL)
        except Exception:
            pass
        self.after(1200, self._estado)

    def _pausar(self):
        if self.player is None:
            return
        try:
            if self.player.is_playing():
                self.player.pause()
                self.btn_pausa.configure(text="Retomar")
                self.status.configure(text="PAUSADO", fg=GOLD)
            else:
                self.player.play()
                self.btn_pausa.configure(text="Pausar")
                self.status.configure(text="AO VIVO · RTSP", fg=TEAL)
        except Exception as exc:
            self._erro(str(exc))

    def _erro(self, msg):
        if self.vivo:
            self.status.configure(text=str(msg)[:100], fg=ERR)

    def fechar(self):
        self.vivo = False
        self._parar_proc()
        try:
            self.app._cameras_abertas.pop(self.ip, None)
        except Exception:
            pass
        self.destroy()


class TelaBrowser(tk.Frame):
    """Navegador ao vivo embutido na própria conversa."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=PANEL2, highlightbackground=LINE,
                         highlightthickness=1)
        self.app = app
        self.vivo = True
        self._job = None
        self._foto = None
        cab = tk.Frame(self, bg=PANEL2)
        cab.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(cab, text="NAVEGADOR AO VIVO", bg=PANEL2, fg=GOLD,
                 font=(UI_SEMI, 8)).pack(side="left")
        self.status = tk.Label(cab, text="conectando…", bg=PANEL2, fg=MUTED,
                               font=(UI, 8))
        self.status.pack(side="right", padx=6)
        tk.Button(cab, text="Fechar", bg=PANEL, fg=FG, bd=0, padx=8,
                  command=self.fechar).pack(side="right", padx=3)
        tk.Button(cab, text="Janela", bg=PANEL, fg=FG, bd=0, padx=8,
                  command=self._janela).pack(side="right", padx=3)
        self.tela = tk.Label(self, bg="#000000", fg=MUTED,
                             text="aguardando o navegador…")
        self.tela.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.bind("<Destroy>", self._destruir)
        self.after(200, self._atualizar)

    def _atualizar(self):
        if not self.vivo:
            return

        def trabalho():
            try:
                req = urllib.request.Request(
                    BASE + "/api/browser/screenshot",
                    headers={"Cache-Control": "no-cache"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    self.app._post(self._mostrar, r.read())
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    self.app._post(self._erro, "navegador fechado")
                else:
                    self.app._post(self._erro, f"HTTP {exc.code}")
            except Exception as exc:
                self.app._post(self._erro, f"{type(exc).__name__}: {exc}")
        threading.Thread(target=trabalho, daemon=True).start()

    def _mostrar(self, dados):
        if not self.vivo or Image is None:
            return
        try:
            img = Image.open(io.BytesIO(dados))
            largura = max(320, self.tela.winfo_width() - 6)
            altura = max(220, self.tela.winfo_height() - 6)
            img.thumbnail((largura, altura), Image.LANCZOS)
            self._foto = ImageTk.PhotoImage(img)
            self.tela.configure(image=self._foto, text="")
            self.status.configure(text="AO VIVO · 1,5 s", fg=TEAL)
        except Exception as exc:
            self._erro(f"frame: {exc}")
        self._agendar()

    def _erro(self, msg):
        if self.vivo:
            self.status.configure(text=str(msg)[:90], fg=ERR)
        self._agendar(2500)

    def _agendar(self, atraso=1500):
        if self.vivo:
            self._job = self.after(atraso, self._atualizar)

    def _janela(self):
        webbrowser.open(BASE)

    def fechar(self):
        self.vivo = False
        if self._job:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self.destroy()

    def _destruir(self, evt):
        if evt.widget is self:
            self.vivo = False


class TelaCamera(tk.Frame):
    """Stream RTSP ao vivo (ffmpeg) embutido na conversa."""

    def __init__(self, parent, app, dev):
        super().__init__(parent, bg=PANEL2, highlightbackground=LINE,
                         highlightthickness=1)
        self.app = app
        self.dev = dev
        self.ip = str(dev.get("ip") or "")
        self.nome = dev.get("nome") or self.ip
        self.vivo = True
        self._proc = None
        self._dim = (960, 540)
        self._foto = None
        self._pendente = False
        self._frame_visto = False
        cab = tk.Frame(self, bg=PANEL2)
        cab.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(cab, text="●", bg=PANEL2, fg=TEAL,
                 font=(UI, 9)).pack(side="left")
        tk.Label(cab, text=f" {self.nome} · AO VIVO", bg=PANEL2, fg=FG,
                 font=(UI_SEMI, 8)).pack(side="left")
        self.status = tk.Label(cab, text="conectando…", bg=PANEL2, fg=MUTED,
                               font=(UI, 8))
        self.status.pack(side="right", padx=6)
        tk.Button(cab, text="Fechar", bg=PANEL, fg=FG, bd=0, padx=8,
                  command=self.fechar).pack(side="right", padx=3)
        tk.Button(cab, text="Reiniciar", bg=PANEL, fg=FG, bd=0, padx=8,
                  command=self._iniciar).pack(side="right", padx=3)
        tk.Button(cab, text="Janela", bg=PANEL, fg=FG, bd=0, padx=8,
                  command=self._janela).pack(side="right", padx=3)
        self.tela = tk.Label(self, bg="#000000", fg=MUTED,
                             text="conectando ao vídeo…")
        self.tela.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.bind("<Destroy>", self._destruir)
        self.after(250, self._iniciar)

    def _janela(self):
        self.app.abrir_camera(self.dev)

    def _iniciar(self):
        if not self.vivo:
            return

        def trabalho():
            try:
                j = api(f"/api/rede/camera/{urllib.parse.quote(self.ip)}/url",
                        timeout=30)
                if not j.get("ok"):
                    raise RuntimeError(j.get("erro") or "sem URL")
                self.app._post(self._play, j["url"], j.get("transporte") or "")
            except Exception as exc:
                self.app._post(self._erro, f"{type(exc).__name__}: {exc}")
        threading.Thread(target=trabalho, daemon=True).start()

    def _play(self, url, transporte=""):
        if not self.vivo:
            return
        self._parar_proc()
        largura, altura = 960, 540
        self._dim = (largura, altura)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               "-rtsp_transport",
               "tcp" if str(transporte).lower() == "tcp" else "udp",
               "-fflags", "nobuffer", "-flags", "low_delay",
               "-i", url, "-an", "-vf", f"scale={largura}:{altura}",
               "-r", "12", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self._proc = _ywproc.popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL,
                                          creationflags=flags)
        except Exception as exc:
            self._erro(f"ffmpeg: {exc}")
            return
        self.status.configure(text="AO VIVO · conectando…", fg=GOLD)
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self):
        tamanho = self._dim[0] * self._dim[1] * 3
        proc = self._proc
        while self.vivo and proc is not None and proc.poll() is None:
            dados = proc.stdout.read(tamanho)
            if len(dados) < tamanho:
                break
            if not self._pendente:
                self._pendente = True
                self.app._post(self._mostrar, dados)
        if self.vivo:
            self.app._post(self._erro, "stream encerrou")

    def _mostrar(self, dados):
        self._pendente = False
        if not self.vivo or Image is None:
            return
        try:
            img = Image.frombytes("RGB", self._dim, dados)
            largura = max(320, self.tela.winfo_width() - 6)
            altura = max(240, self.tela.winfo_height() - 6)
            img.thumbnail((largura, altura), Image.BILINEAR)
            self._foto = ImageTk.PhotoImage(img)
            self.tela.configure(image=self._foto, text="")
            if not self._frame_visto:
                self._frame_visto = True
            self.status.configure(text="AO VIVO · RTSP", fg=TEAL)
        except Exception as exc:
            self._erro(f"frame: {exc}")

    def _erro(self, msg):
        if self.vivo:
            self.status.configure(text=str(msg)[:90], fg=ERR)

    def _parar_proc(self):
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            _ywproc.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

    def fechar(self):
        self.vivo = False
        self._parar_proc()
        self.destroy()

    def _destruir(self, evt):
        if evt.widget is self:
            self.vivo = False
            self._parar_proc()


class App:
    def __init__(self, nova: bool = False):
        _preparar_windows()
        self.root = tk.Tk()
        self.root.title("YVAKOR — Agente Pessoal")
        try:
            dpi = self.root.winfo_fpixels("1i")
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass
        largura = min(1180, self.root.winfo_screenwidth() - 80)
        altura = min(760, self.root.winfo_screenheight() - 120)
        x = max(0, (self.root.winfo_screenwidth() - largura) // 2)
        y = max(0, (self.root.winfo_screenheight() - altura) // 3)
        self.root.geometry(f"{largura}x{altura}+{x}+{y}")
        self.root.minsize(min(820, largura), min(520, altura))
        self.root.configure(bg=BG)

        self._vivo = True
        self._fila: queue.Queue = queue.Queue()
        self._jobs: set[str] = set()
        self.sessao = None
        self._privado = False
        self.voz_ativa = True
        self._nova_boot = bool(nova)
        self._anexos: list[dict] = []
        self.sessoes: list[dict] = []
        self.enviando = False          # compatibilidade
        self._cameras_abertas: dict = {}
        self._janela_cameras = None
        self._online = None
        self._envios: dict[str, int] = {}
        self._pedido = 0
        self._pedido_sessoes = 0
        self._pedido_chat = 0
        self._pedido_tarefa = 0
        self._hist: list[tuple[str, str]] = []
        self._hist_sid = None
        self._artefatos: dict[str, list] = {}
        self._status_cor = MUTED
        self._st: dict[str, tk.Label] = {}
        self._prog_job = None
        self._prog_sid = None
        self._pend_id = None
        self._confirm_win = None
        self._poll_job = None
        self._buscando_tarefas = False
        self._buscando_sistema = False
        self._tid_selecionado = None
        self._tarefas_sig = None
        self._sistema_ts = 0.0
        self._criando = False
        self._gravando = False
        self._bootando = False
        self._ph = True
        self._ultimo_passo = ""
        self._suprimir_selecao = False

        self._montar()
        _barra_titulo_escura(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
        self.root.bind("<Destroy>", self._root_destruido, add="+")
        self._agendar(50, self._drenar)
        self._agendar(120, self._focar_entrada)
        self._agendar(160, self._boot)
        self._agendar(300, self._pulsar, 0)

    # ------------------------- ciclo de vida/threads -------------------- #
    def _agendar(self, ms: int, fn, *args):
        if not self._vivo:
            return None
        job = None

        def _exec():
            self._jobs.discard(job)
            if not self._vivo:
                return
            try:
                fn(*args)
            except Exception as exc:
                self.set_status(f"erro interno: {type(exc).__name__}", ERR)

        try:
            job = self.root.after(ms, _exec)
        except Exception:
            return None
        self._jobs.add(job)
        return job

    def _cancelar(self, job):
        if not job:
            return
        try:
            self.root.after_cancel(job)
        except Exception:
            pass
        self._jobs.discard(job)

    def _post(self, fn, *args):
        """Único caminho permitido para uma thread tocar a UI."""
        if not self._vivo:
            return
        self._fila.put((fn, args))

    def _drenar(self):
        if not self._vivo:
            return
        for _ in range(60):
            try:
                fn, args = self._fila.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception as exc:
                self.set_status(f"erro interno: {type(exc).__name__}: {exc}",
                                ERR)
        self._agendar(50, self._drenar)

    def _root_destruido(self, evt=None):
        if evt is None or evt.widget is self.root:
            self._vivo = False

    def _focar_entrada(self):
        try:
            self.entrada.focus_set()
        except Exception:
            pass

    # ----------------------------- animações --------------------------- #
    def _pulsar(self, i: int = 0):
        if not self._vivo:
            return
        try:
            if self.root.state() not in ("iconic", "withdrawn"):
                op = 0.35 + 0.65 * (0.5 - 0.5 * math.cos(2 * math.pi * i / 24))
                cor = _misturar(self._status_cor, BG, 1 - op)
                if getattr(self, "_dot_item", None):
                    self._dot_canvas.itemconfigure(self._dot_item, fill=cor)
                if getattr(self, "_canal_dot_item", None):
                    self._canal_dot.itemconfigure(self._canal_dot_item,
                                                  fill=cor)
        except Exception:
            pass
        self._agendar(100, self._pulsar, (i + 1) % 24)

    @staticmethod
    def _mix_cor(c1: str, c2: str, t: float) -> str:
        return _misturar(c1, c2, t)

    def _hover(self, widget, normal: str, hover: str,
               fg_normal=None, fg_hover=None):
        def pintar(cor, fg):
            try:
                widget.configure(bg=cor)
                if fg is not None:
                    widget.configure(fg=fg)
            except Exception:
                pass

        try:
            widget.configure(cursor="hand2")
        except Exception:
            pass
        widget.bind("<Enter>", lambda e: pintar(hover, fg_hover))
        widget.bind("<Leave>", lambda e: pintar(normal, fg_normal))
        widget.bind("<ButtonPress-1>", lambda e: pintar(hover, fg_hover))
        widget.bind("<ButtonRelease-1>", lambda e: pintar(hover, fg_hover))


    # ------------------------------------------------------------------ #
    def _montar(self):
        self.root.option_add("*Font", FONT)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("YVAKOR.Vertical.TScrollbar", troughcolor=BG,
                        background=SCROLL, lightcolor=SCROLL,
                        darkcolor=SCROLL, bordercolor=BG,
                        arrowcolor=BG, width=8, arrowsize=0,
                        relief="flat")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=FG, rowheight=30, borderwidth=0,
                        font=FONT_XS)
        style.layout("Treeview", [("Treeview.treearea",
                                   {"sticky": "nswe"})])
        style.configure("Treeview.Heading", background=STATUS_BG,
                        foreground=MUTED, borderwidth=0,
                        font=(UI_SEMI, 8))
        style.map("Treeview", background=[("selected", TEAL_BG)],
                  foreground=[("selected", FG)])

        # ------------------------------ topo --------------------------- #
        topo = tk.Frame(self.root, bg=BG, height=58)
        topo.pack(fill="x")
        topo.pack_propagate(False)
        marca = tk.Canvas(topo, width=30, height=30, bg=BG,
                          highlightthickness=0)
        marca.pack(side="left", padx=(18, 10))
        _round_rect(marca, 1, 1, 29, 29, 7, fill=GOLD, outline="")
        marca.create_text(15, 15, text="Y", fill=BG,
                          font=(DISPLAY, 15))
        bloco = tk.Frame(topo, bg=BG)
        bloco.pack(side="left")
        titulo = tk.Frame(bloco, bg=BG)
        titulo.pack(anchor="w")
        tk.Label(titulo, text="YVA", bg=BG, fg=FG,
                 font=(DISPLAY, 18)).pack(side="left")
        tk.Label(titulo, text="KOR", bg=BG, fg=GOLD,
                 font=(DISPLAY, 18)).pack(side="left")
        tk.Label(bloco, text="AGENTE PESSOAL · INTERFACE NATIVA", bg=BG,
                 fg=MUTED, font=(UI, 7)).pack(anchor="w")
        self.btn_menu = tk.Label(topo, text="⋯", bg=BG, fg=MUTED,
                                 font=(UI, 16), padx=12,
                                 cursor="hand2")
        self.btn_menu.pack(side="right", padx=18)
        self._hover(self.btn_menu, BG, PANEL2, fg_normal=MUTED, fg_hover=FG)
        self.btn_menu.bind("<Button-1>", self._menu_principal)
        self.btn_cam = tk.Label(topo, text="CÂMERAS", bg=BG, fg=MUTED,
                                font=(UI_SEMI, 7), padx=10,
                                cursor="hand2")
        self.btn_cam.pack(side="right")
        self._hover(self.btn_cam, BG, PANEL2, fg_normal=MUTED, fg_hover=TEAL)
        self.btn_cam.bind("<Button-1>", lambda e: self.abrir_cameras())
        self.btn_tela = tk.Label(topo, text="TELA", bg=BG, fg=MUTED,
                                 font=(UI_SEMI, 7), padx=9,
                                 cursor="hand2")
        self.btn_tela.pack(side="right", padx=(0, 4))
        self._hover(self.btn_tela, BG, PANEL2, fg_normal=MUTED, fg_hover=GOLD)
        self.btn_tela.bind("<Button-1>", lambda e: self.abrir_browser_conversa())
        self.btn_voz = tk.Label(topo, text="🔊 VOZ", bg=BG, fg=TEAL,
                                font=(UI_SEMI, 7), padx=9,
                                cursor="hand2")
        self.btn_voz.pack(side="right", padx=(0, 4))
        self._hover(self.btn_voz, BG, PANEL2, fg_normal=TEAL, fg_hover=GOLD)
        self.btn_voz.bind("<Button-1>", lambda e: self.alternar_voz())
        acento = tk.Frame(topo, bg=LINE, height=2)
        acento.pack(side="bottom", fill="x")
        tk.Frame(acento, bg=GOLD, height=2, width=110).pack(side="left")
        tk.Frame(acento, bg=TEAL, height=2, width=42).pack(side="left")

        self._montar_rodape()

        corpo = tk.Frame(self.root, bg=BG)
        corpo.pack(fill="both", expand=True, padx=16, pady=(8, 10))

        lateral = tk.Frame(corpo, bg=PANEL, width=300,
                           highlightbackground=LINE, highlightthickness=1)
        lateral.pack(side="left", fill="y")
        lateral.pack_propagate(False)
        self._montar_lateral(lateral)

        direita = tk.Frame(corpo, bg=BG)
        direita.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.abas = Abas(direita, ao_mudar=self._aba_mudou)
        self.abas.pack(fill="both", expand=True)
        self.abas.adicionar("Conversa", self._aba_chat)
        self.abas.adicionar("Tarefas", self._aba_tarefas)
        self.abas.adicionar("Agenda", self._aba_agenda)
        self.abas.adicionar("Sistema", self._aba_sistema)
        self.abas.selecionar(0)
        self._atalhos()
        self._agendar(650, self._carregar_voz)

    def _montar_rodape(self):
        rodape = tk.Frame(self.root, bg=STATUS_BG, height=30,
                          highlightbackground=LINE, highlightthickness=1)
        rodape.pack(side="bottom", fill="x")
        rodape.pack_propagate(False)
        for rotulo, chave in (("ESTADO", "estado"), ("MODELO", "modelo"),
                              ("MEMÓRIAS", "memorias"), ("SKILLS", "skills"),
                              ("BUILD", "build")):
            item = tk.Frame(rodape, bg=STATUS_BG)
            item.pack(side="left", padx=(14, 0))
            tk.Label(item, text=rotulo, bg=STATUS_BG, fg=DIM,
                     font=(UI_SEMI, 7)).pack(side="left")
            if chave == "modelo":
                # Clicável: escolhe Local / Automático / DeepSeek e o modelo local.
                lbl = tk.Menubutton(
                    item, text="—", bg=STATUS_BG, fg=GOLD, font=FONT_XS, bd=0,
                    relief="flat", cursor="hand2", highlightthickness=0,
                    activebackground=STATUS_BG, activeforeground=FG, padx=0,
                    pady=0)
                menu = tk.Menu(lbl, tearoff=0, bg=PANEL, fg=FG, bd=0,
                               activebackground=GOLD, activeforeground=ON_GOLD,
                               font=FONT_XS)
                menu.configure(
                    postcommand=lambda m=menu: self._montar_menu_modelo(m))
                lbl.configure(menu=menu)
                lbl.pack(side="left", padx=(5, 0))
                self._st[chave] = lbl
                continue
            lbl = tk.Label(item, text="—", bg=STATUS_BG, fg=MUTED,
                           font=FONT_XS)
            lbl.pack(side="left", padx=(5, 0))
            self._st[chave] = lbl
        tk.Label(rodape, text="NÚCLEO LOCAL · SQLITE", bg=STATUS_BG,
                 fg=DIM, font=(UI, 7)).pack(side="right", padx=14)

    # ------------------------- seletor de modelo ------------------------ #
    def _montar_menu_modelo(self, menu):
        """Preenche o menu na hora de abrir (modelos locais mudam com o Ollama)."""
        menu.delete(0, "end")
        try:
            info = api("/api/modelo", timeout=3)
        except Exception:
            menu.add_command(label="núcleo indisponível", state="disabled")
            return
        atual = info.get("modo")
        for m in info.get("modos", []):
            marca = "● " if m.get("id") == atual else "    "
            menu.add_command(
                label=f"{marca}{m.get('rotulo')} — {m.get('descricao')}",
                command=lambda i=m.get("id"): self._escolher_modelo({"modo": i}))
        locais = info.get("locais") or []
        if locais:
            menu.add_separator()
            menu.add_command(label="Modelo local (Ollama):", state="disabled")
            atual_local = (info.get("local") or {}).get("modelo")
            for nome in locais:
                marca = "● " if nome == atual_local else "    "
                menu.add_command(
                    label=f"{marca}{nome}",
                    command=lambda n=nome: self._escolher_modelo({"local": n}))

    def _escolher_modelo(self, payload: dict):
        def trabalho():
            try:
                info = api("/api/modelo", payload, timeout=10)
            except Exception as exc:
                self._post(self.set_status, f"modelo: {exc}", ERR)
                return
            self._post(self._modelo_trocado, info)
        threading.Thread(target=trabalho, daemon=True).start()

    def _modelo_trocado(self, info: dict):
        modo = info.get("modo")
        rotulo = next((m.get("rotulo") for m in info.get("modos", [])
                       if m.get("id") == modo), modo)
        self.set_status(
            f"modelo: {rotulo} · {(info.get('local') or {}).get('modelo', '')}",
            OK)
        self.carregar_sistema()

    def _montar_lateral(self, lat):
        cab = tk.Frame(lat, bg=PANEL)
        cab.pack(fill="x", padx=14, pady=(14, 6))
        tk.Label(cab, text="C O N V E R S A S", bg=PANEL, fg=MUTED,
                 font=(UI_SEMI, 7)).pack(side="left")
        self.btn_nova = tk.Button(
            cab, text="+ nova", command=self.nova_conversa, bg=GOLD, fg=ON_GOLD,
            font=(UI_SEMI, 8), padx=8, pady=2, bd=0, relief="flat",
            highlightthickness=0, activebackground=GOLD_HOVER,
            activeforeground=ON_GOLD, cursor="hand2")
        self.btn_nova.pack(side="right")
        self.btn_priv = tk.Button(
            cab, text="privada", command=self.nova_conversa_privada, bg=PANEL,
            fg=MUTED, font=(UI_SEMI, 7), padx=6, pady=2, bd=0,
            relief="flat", highlightthickness=0, activebackground=PANEL2,
            activeforeground=TEAL, cursor="hand2")
        self.btn_priv.pack(side="right", padx=(0, 8))
        self.btn_janela = tk.Button(
            cab, text="aqui", command=self.nova_conversa, bg=PANEL, fg=MUTED,
            font=(UI_SEMI, 7), padx=5, pady=2, bd=0, relief="flat",
            highlightthickness=0, activebackground=PANEL2,
            activeforeground=GOLD, cursor="hand2")
        self.btn_janela.pack(side="right", padx=(0, 4))

        busca_box = tk.Frame(lat, bg=PANEL2)
        busca_box.pack(fill="x", padx=12, pady=(2, 6))
        self.busca = tk.Entry(busca_box, bg=PANEL2, fg=PLACEHOLDER, bd=0,
                              highlightthickness=1,
                              highlightbackground=PANEL2,
                              highlightcolor=TEAL, insertbackground=GOLD,
                              font=FONT_XS)
        self.busca.pack(fill="x", padx=8, pady=5)
        self.busca.insert(0, "buscar conversa")
        self._busca_ph = True
        self.busca.bind("<FocusIn>", lambda e: self._busca_foco(True))
        self.busca.bind("<FocusOut>", lambda e: self._busca_foco(False))
        self.busca.bind("<KeyRelease>", self._busca_digitou)
        self.busca.bind("<Escape>", lambda e: (self._escapar(), "break")[1])

        rodape_lat = tk.Frame(lat, bg=PANEL)
        rodape_lat.pack(side="bottom", fill="x")
        tk.Frame(rodape_lat, bg=LINE, height=1).pack(fill="x", padx=12)
        self.lbl_contagem = tk.Label(rodape_lat, text="0 conversas", bg=PANEL,
                                     fg=DIM, font=(UI, 7))
        self.lbl_contagem.pack(side="right", padx=12, pady=8)
        tk.Label(rodape_lat, text="histórico local · SQLite", bg=PANEL,
                 fg=DIM, font=(UI, 7)).pack(side="left", padx=12,
                                                    pady=8)

        self.lista = SessaoLista(lat, ao_abrir=self._abrir_sessao,
                                 ao_renomear=self.renomear_sessao,
                                 ao_apagar=self.apagar_sessao)
        self.lista.pack(fill="both", expand=True, padx=(2, 0), pady=(0, 4))

    def _atalhos(self):
        r = self.root
        r.bind("<Control-n>", lambda e: (self.nova_conversa(), "break")[1])
        r.bind("<Control-Shift-N>",
               lambda e: (self.nova_conversa_privada(), "break")[1])
        r.bind("<Control-l>", lambda e: (self._focar_entrada(), "break")[1])
        r.bind("<Control-k>", lambda e: (self._focar_busca(), "break")[1])
        r.bind("<Control-Shift-T>", lambda e: (self._alternar_tema(), "break")[1])
        r.bind("<F5>", lambda e: (self._atualizar_tudo(), "break")[1])
        r.bind("<Control-Tab>", lambda e: (self.abas.selecionar(
            self.abas.atual + 1), "break")[1])
        for i in range(1, 5):
            r.bind(f"<Control-Key-{i}>",
                   lambda e, n=i - 1: (self.abas.selecionar(n), "break")[1])
        r.bind("<Control-Shift-C>",
               lambda e: (self._copiar_ultima(), "break")[1])
        r.bind("<Escape>", lambda e: (self._escapar(), "break")[1])

    def _menu_principal(self, evt=None):
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=FG,
                       activebackground=TEAL_BG, activeforeground=FG,
                       bd=0, font=FONT_XS)
        menu.add_command(label="Nova conversa     Ctrl+N",
                         command=self.nova_conversa)
        menu.add_command(label="Conversa privada     Ctrl+Shift+N",
                         command=self.nova_conversa_privada)
        menu.add_command(label="Câmeras ao vivo",
                         command=self.abrir_cameras)
        menu.add_command(label="Navegador na conversa",
                         command=self.abrir_browser_conversa)
        menu.add_command(label="Atualizar     F5",
                         command=self._atualizar_tudo)
        menu.add_separator()
        menu.add_command(label="Abrir interface web",
                         command=lambda: webbrowser.open(BASE))
        menu.add_command(label="Galeria",
                         command=lambda: webbrowser.open(BASE + "/galeria"))
        menu.add_separator()
        menu.add_command(label="Sobre o YVAKOR", command=self._sobre)
        menu.add_command(label="Sair", command=self.fechar)
        x = evt.x_root if evt else self.btn_menu.winfo_rootx()
        y = evt.y_root if evt else self.btn_menu.winfo_rooty() + 24
        try:
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _focar_busca(self):
        if self._busca_ph:
            self.busca.delete(0, "end")
            self.busca.configure(fg=FG)
            self._busca_ph = False
        self.busca.focus_set()

    def _busca_foco(self, entrando: bool):
        if entrando:
            if self._busca_ph:
                self.busca.delete(0, "end")
                self.busca.configure(fg=FG)
                self._busca_ph = False
        elif not self.busca.get().strip():
            self._busca_ph = True
            self.busca.insert(0, "buscar conversa")
            self.busca.configure(fg=PLACEHOLDER)

    def _busca_digitou(self, _evt=None):
        texto = "" if self._busca_ph else self.busca.get()
        self.lista.filtrar(texto)

    def _escapar(self):
        if self._confirm_win is not None:
            try:
                self._confirm_win.destroy()
            except Exception:
                pass
            self._confirm_win = None
            return
        if not self._busca_ph or self.busca.get().strip():
            self.busca.delete(0, "end")
            self._busca_ph = False
            self._busca_foco(False)
            self.lista.filtrar("")
        self._focar_entrada()

    def _copiar_ultima(self):
        texto = self.chat.ultima_agente
        if not texto:
            self.set_status("nada para copiar", MUTED)
            return
        self.chat._copiar(texto)
        self.set_status("resposta copiada", OK)

    def _atualizar_tudo(self):
        self.set_status("atualizando…", GOLD)
        if not self._online:
            self._boot()
        self.carregar_sessoes()
        self.atualizar_tarefas()
        self.carregar_sistema()

    def _aba_mudou(self, indice: int):
        if indice == 1:
            self.atualizar_tarefas()
        elif indice == 2:
            self.carregar_agenda()
        elif indice == 3 and time.time() - self._sistema_ts > 20:
            self.carregar_sistema()

    def _sugestao(self, texto: str):
        self._definir_entrada(texto)

    # ------------------------------ conversa ------------------------- #
    def _aba_chat(self, aba):
        canal = tk.Frame(aba, bg=BG, height=38)
        canal.pack(fill="x", padx=16)
        canal.pack_propagate(False)
        self._canal_dot = tk.Canvas(canal, width=14, height=14, bg=BG,
                                    highlightthickness=0)
        self._canal_dot.pack(side="left", pady=12)
        self._canal_dot_item = self._canal_dot.create_oval(
            3, 3, 10, 10, fill=TEAL, outline="")
        self._canal_txt = tk.Label(canal, text="EM ESCUTA", bg=BG, fg=MUTED,
                                   font=(UI_SEMI, 7))
        self._canal_txt.pack(side="left", padx=(6, 0))
        self._canal_provider = tk.Label(canal, text="—", bg=BG, fg=GOLD,
                                        font=(UI, 8))
        self._canal_provider.pack(side="right")
        self.chat = ChatView(aba, ao_sugestao=self._sugestao)
        self.chat.pack(fill="both", expand=True)
        self._composer(aba)
        self.chat.mostrar_vazio()

    def anexar_arquivos(self):
        caminhos = filedialog.askopenfilenames(
            parent=self.root, title="Anexar imagem ou vídeo",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"),
                       ("Vídeos", "*.mp4 *.webm *.mov *.mkv *.avi *.m4v"),
                       ("Documentos", "*.pdf *.txt *.md"),
                       ("Todos", "*.*")])
        for caminho in caminhos:
            self._enviar_anexo(Path(caminho))

    def _enviar_anexo(self, caminho: Path):
        try:
            if caminho.stat().st_size > 80 * 1024 * 1024:
                messagebox.showerror("YVAKOR", "Arquivo acima de 80 MB.")
                return
        except OSError as exc:
            self.set_status(f"anexo: {exc}", ERR)
            return
        self.set_status(f"enviando {caminho.name}…", GOLD)

        def trabalho():
            try:
                dados = base64.b64encode(caminho.read_bytes()).decode()
                ext = caminho.suffix.lower()
                videos = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
                docs = {".pdf", ".txt", ".md"}
                j = api("/api/upload", {"nome": caminho.name,
                                        "dados_b64": dados,
                                        "tipo": ("video" if ext in videos else
                                                 "documento" if ext in docs
                                                 else "imagem")},
                        timeout=180)
            except Exception as exc:
                self._post(self._anexo_erro, f"{type(exc).__name__}: {exc}")
                return
            self._post(self._anexo_ok, j)
        threading.Thread(target=trabalho, daemon=True).start()

    def _anexo_ok(self, j: dict):
        self._anexos.append(j)
        self._render_anexos()
        self.set_status("anexo pronto", OK)

    def _anexo_erro(self, msg: str):
        self.set_status("anexo: " + msg, ERR)
        self.chat.add("system", "Não foi possível anexar: " + msg)

    def _render_anexos(self):
        for w in self.anexos_box.winfo_children():
            w.destroy()
        for i, a in enumerate(self._anexos):
            chip = tk.Frame(self.anexos_box, bg=PANEL2,
                            highlightbackground=LINE, highlightthickness=1)
            chip.pack(side="left", padx=(0, 6), pady=2)
            icone = ("🎬" if a.get("tipo") == "video" else
                     "📄" if a.get("tipo") == "documento" else "🖼")
            tk.Label(chip, text=f"{icone} {str(a.get('nome'))[:28]}",
                     bg=PANEL2, fg=FG, font=(UI, 8), padx=7,
                     pady=3).pack(side="left")
            tk.Label(chip, text="×", bg=PANEL2, fg=ERR, font=(UI, 10),
                     padx=5, cursor="hand2").pack(side="left")
            for w in chip.winfo_children():
                if w.cget("text") == "×":
                    w.bind("<Button-1>", lambda e, n=i: self._remover_anexo(n))

    def _remover_anexo(self, indice: int):
        try:
            self._anexos.pop(indice)
        except IndexError:
            pass
        self._render_anexos()

    def _composer(self, aba):
        barra = tk.Frame(aba, bg=BG)
        barra.pack(fill="x", padx=16, pady=(4, 12))
        self.anexos_box = tk.Frame(barra, bg=BG)
        self.anexos_box.pack(fill="x", pady=(0, 4))
        caixa = tk.Frame(barra, bg=PANEL2, highlightbackground=LINE,
                         highlightthickness=1)
        caixa.pack(fill="x")
        self.caixa_entrada = caixa

        self.btn_mais = tk.Label(caixa, text="+", bg=PANEL2, fg=MUTED,
                                 font=(UI, 16), padx=10,
                                 cursor="hand2")
        self.btn_mais.pack(side="left")
        self.btn_anexo = tk.Label(caixa, text="anexar", bg=PANEL2, fg=MUTED,
                                  font=(UI_SEMI, 7), padx=7,
                                  cursor="hand2")
        self.btn_anexo.pack(side="left")
        self.btn_enviar = tk.Label(caixa, text="Enviar", bg=GOLD, fg=ON_GOLD,
                                   font=(UI_SEMI, 9), padx=14,
                                   pady=7, cursor="hand2")
        self.btn_enviar.pack(side="right", padx=(2, 6), pady=6)
        self.btn_mic = tk.Canvas(caixa, width=28, height=28, bg=PANEL2,
                                 highlightthickness=0, cursor="hand2")
        self.btn_mic.pack(side="right", padx=(2, 2), pady=5)
        self._desenhar_mic(TEAL)

        self.entrada = tk.Text(caixa, height=2, bg=PANEL2, fg=PLACEHOLDER,
                               bd=0, highlightthickness=0,
                               insertbackground=GOLD, wrap="word", padx=4,
                               pady=7, font=FONT, spacing1=1, spacing2=2,
                               spacing3=4)
        self.entrada.pack(side="left", fill="both", expand=True,
                          padx=(2, 6), pady=4)
        self.entrada.insert("1.0", "Fale com o YVAKOR…")
        self._ph = True
        self.entrada.bind("<Return>", self._enter)
        self.entrada.bind("<Shift-Return>", lambda e: None)
        self.entrada.bind("<KeyPress>", self._entrada_tecla, add="+")
        self.entrada.bind("<KeyRelease>", self._auto_crescer)
        self.entrada.bind("<FocusIn>", lambda e: self._entrada_foco(True))
        self.entrada.bind("<FocusOut>", lambda e: self._entrada_foco(False))
        self.entrada.bind("<Control-Return>", lambda e: (self.enviar(),
                                                         "break")[1])
        self.entrada.bind("<Tab>", lambda e: (
            self.entrada.tk_focusNext().focus_set(), "break")[1])
        self.entrada.bind("<Shift-Tab>", lambda e: (
            self.entrada.tk_focusPrev().focus_set(), "break")[1])

        self.btn_enviar.bind("<Button-1>", lambda e: self._acao_envio())
        self.btn_mais.bind("<Button-1>", self._menu_mais)
        self.btn_anexo.bind("<Button-1>", lambda e: self.anexar_arquivos())
        self.btn_mic.bind("<Button-1>", lambda e: self.ditar())
        self.btn_mic.bind("<Enter>", lambda e: self._desenhar_mic(GOLD))
        self.btn_mic.bind("<Leave>", lambda e: self._desenhar_mic(TEAL))
        self.btn_enviar.bind("<Enter>", lambda e: self._hover_envio(True))
        self.btn_enviar.bind("<Leave>", lambda e: self._hover_envio(False))
        self._hover(self.btn_mais, PANEL2, LINE, fg_normal=MUTED, fg_hover=FG)
        self._hover(self.btn_anexo, PANEL2, LINE, fg_normal=MUTED,
                    fg_hover=TEAL)
        dica = tk.Frame(barra, bg=BG)
        dica.pack(fill="x", pady=(4, 0))
        tk.Label(dica, text="Enter envia · Shift+Enter nova linha · Ctrl+K "
                            "busca · Ctrl+Shift+C copia a última resposta",
                 bg=BG, fg=DIM, font=(UI, 7)).pack(side="right")

    def _desenhar_mic(self, cor: str):
        try:
            c = self.btn_mic
            c.delete("all")
            c.create_oval(10, 4, 18, 15, outline=cor, width=1.6)
            c.create_arc(6, 9, 22, 22, start=190, extent=160, style="arc",
                         outline=cor, width=1.4)
            c.create_line(14, 21, 14, 24, fill=cor, width=1.4)
            c.create_line(10, 24, 18, 24, fill=cor, width=1.4)
        except Exception:
            pass

    def _menu_mais(self, evt):
        menu = tk.Menu(self.root, tearoff=0, bg=PANEL2, fg=FG,
                       activebackground=TEAL_BG, activeforeground=FG,
                       bd=0, font=FONT_XS)
        for rotulo, texto in (
                ("O que você sabe sobre mim?",
                 "O que você sabe sobre mim?"),
                ("Listar ferramentas", "[ferramentas]"),
                ("Criar skill", "[criar skill] "),
                ("Resumir a conversa", "Resuma nossa conversa até agora."),
        ):
            menu.add_command(label=rotulo,
                             command=lambda t=texto: self._inserir_comando(t))
        menu.add_separator()
        menu.add_command(label="Nova tarefa em segundo plano…",
                         command=self.nova_tarefa)
        try:
            menu.tk_popup(evt.x_root, evt.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _inserir_comando(self, texto: str):
        atual = self._texto_entrada().strip()
        self._definir_entrada((atual + " " + texto).strip() if atual
                              else texto)

    def _entrada_foco(self, entrando: bool):
        if entrando:
            self.caixa_entrada.configure(highlightbackground=TEAL)
            if not self.entrada.get("1.0", "end").strip():
                self._mostrar_placeholder()
        else:
            self.caixa_entrada.configure(highlightbackground=LINE)
            if not self.entrada.get("1.0", "end").strip():
                self._mostrar_placeholder()

    def _mostrar_placeholder(self):
        self.entrada.delete("1.0", "end")
        self.entrada.insert("1.0", "Fale com o YVAKOR…")
        self.entrada.configure(fg=PLACEHOLDER)
        self._ph = True

    def _entrada_tecla(self, evt):
        if not self._ph:
            return None
        if evt.keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                          "Alt_L", "Alt_R", "Super_L", "Super_R",
                          "Caps_Lock", "Escape", "Tab", "Left", "Right",
                          "Up", "Down", "Home", "End", "Prior", "Next",
                          "Return", "KP_Enter"):
            return None
        self.entrada.delete("1.0", "end")
        self.entrada.configure(fg=FG)
        self._ph = False
        return None

    def _texto_entrada(self) -> str:
        if self._ph:
            return ""
        return self.entrada.get("1.0", "end")

    def _definir_entrada(self, texto: str):
        self._ph = False
        self.entrada.delete("1.0", "end")
        self.entrada.insert("1.0", texto)
        self.entrada.configure(fg=FG)
        self.entrada.focus_set()
        self._auto_crescer()

    def _auto_crescer(self, _evt=None):
        try:
            linhas = int(self.entrada.count("1.0", "end",
                                            "displaylines")[0])
        except Exception:
            linhas = self.entrada.get("1.0", "end").count("\n") + 1
        linhas = max(2, min(5, linhas))
        try:
            if int(self.entrada.cget("height")) != linhas:
                self.entrada.configure(height=linhas)
        except Exception:
            pass

    # ------------------------------ tarefas -------------------------- #
    def _aba_tarefas(self, aba):
        topo = tk.Frame(aba, bg=BG)
        topo.pack(fill="x", padx=16, pady=(10, 8))
        tk.Label(topo, text="Tarefas em segundo plano", bg=BG, fg=FG,
                 font=FONT_B).pack(side="left")
        nova = tk.Label(topo, text="+ nova tarefa", bg=GOLD, fg=ON_GOLD,
                        font=(UI_SEMI, 8), padx=12, pady=5,
                        cursor="hand2")
        nova.pack(side="right")
        nova.bind("<Button-1>", lambda e: self.nova_tarefa())
        self._hover(nova, GOLD, GOLD_HOVER)
        atualizar = tk.Label(topo, text="Atualizar", bg=PANEL2, fg=FG,
                             font=FONT_XS, padx=12, pady=5,
                             cursor="hand2")
        atualizar.pack(side="right", padx=(0, 6))
        atualizar.bind("<Button-1>", lambda e: self.atualizar_tarefas())
        self._hover(atualizar, PANEL2, LINE)

        wrap = tk.Frame(aba, bg=BG)
        wrap.pack(fill="both", expand=True, padx=16)
        self.tree = ttk.Treeview(wrap, columns=("id", "status", "desc"),
                                 show="headings", height=10,
                                 selectmode="browse")
        for coluna, titulo, largura in (("id", "ID", 76),
                                        ("status", "STATUS", 118),
                                        ("desc", "TAREFA", 540)):
            self.tree.heading(coluna, text=titulo, anchor="w")
            self.tree.column(coluna, width=largura, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(wrap, orient="vertical",
                               command=self.tree.yview,
                               style="YVAKOR.Vertical.TScrollbar")
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("executando", foreground=GOLD)
        self.tree.tag_configure("na_fila", foreground=MUTED)
        self.tree.tag_configure("concluida", foreground=TEAL)
        self.tree.tag_configure("falha", foreground=ERR)
        self.tree.tag_configure("cancelada", foreground=ERR)
        self.tree.tag_configure("interrompida", foreground=ERR)
        self.tree.bind("<<TreeviewSelect>>", self._ver_tarefa)
        self.lbl_tarefas_vazio = tk.Label(
            wrap, text="Nenhuma tarefa ainda.\nUse “+ nova tarefa” para "
                       "disparar uma em segundo plano.",
            bg=BG, fg=DIM, font=FONT_XS, justify="center")
        self.lbl_tarefas_vazio.place(relx=0.5, rely=0.3, anchor="center")

        self.detalhe = tk.Text(aba, height=9, bg=PANEL, fg=FG, bd=0,
                               wrap="word", padx=14, pady=10, font=FONT_XS,
                               highlightthickness=0, insertbackground=GOLD)
        self.detalhe.pack(fill="both", expand=True, padx=16, pady=(10, 6))
        self.detalhe.configure(state="disabled")
        self._texto(self.detalhe, "Selecione uma tarefa para ver plano, "
                                  "passos, resultado e artefatos.")

        botoes = tk.Frame(aba, bg=BG)
        botoes.pack(fill="x", padx=16, pady=(0, 8))
        self.btn_cancelar = tk.Button(
            botoes, text="Cancelar",
            command=lambda: self._acao_tarefa("cancel"), bg=PANEL2,
            fg=ERR, bd=0, padx=14, pady=5, font=FONT_XS,
            activebackground=LINE, activeforeground=ERR,
            disabledforeground=DIM, cursor="hand2", relief="flat",
            highlightthickness=0)
        self.btn_cancelar.pack(side="left")
        self.btn_retomar = tk.Button(
            botoes, text="Retomar",
            command=lambda: self._acao_tarefa("resume"), bg=PANEL2,
            fg=OK, bd=0, padx=14, pady=5, font=FONT_XS,
            activebackground=LINE, activeforeground=OK,
            disabledforeground=DIM, cursor="hand2", relief="flat",
            highlightthickness=0)
        self.btn_retomar.pack(side="left", padx=6)
        self.btn_cancelar.configure(state="disabled")
        self.btn_retomar.configure(state="disabled")
        tk.Label(botoes, text="A tarefa continua no núcleo mesmo com a "
                              "janela fechada.", bg=BG, fg=DIM,
                 font=(UI, 7)).pack(side="right")

    # ------------------------------ sistema -------------------------- #
    def _aba_agenda(self, aba):
        barra = tk.Frame(aba, bg=BG)
        barra.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(barra, text="AGENDA", bg=BG, fg=FG,
                 font=(UI_SEMI, 9)).pack(side="left")
        novo = tk.Label(barra, text="+ agendar", bg=GOLD, fg=ON_GOLD,
                        font=(UI_SEMI, 8), padx=9, pady=3, cursor="hand2")
        novo.pack(side="right")
        novo.bind("<Button-1>", lambda e: self._nova_agenda())
        self._hover(novo, GOLD, GOLD_HOVER)
        atualizar = tk.Label(barra, text="Atualizar", bg=PANEL2, fg=FG,
                             font=(UI_SEMI, 7), padx=9, pady=3,
                             cursor="hand2")
        atualizar.pack(side="right", padx=6)
        atualizar.bind("<Button-1>", lambda e: self.carregar_agenda())
        self._hover(atualizar, PANEL2, LINE)

        self.agenda_tree = ttk.Treeview(
            aba, columns=("id", "quando", "titulo", "tipo", "rep"),
            show="headings", height=12)
        for col, titulo, largura in (("id", "ID", 24),
                                     ("quando", "Quando", 130),
                                     ("titulo", "Tarefa", 380),
                                     ("tipo", "Tipo", 70),
                                     ("rep", "Repete", 80)):
            self.agenda_tree.heading(col, text=titulo)
            self.agenda_tree.column(col, width=largura,
                                    anchor="w" if col in ("titulo", "quando")
                                    else "center")
        self.agenda_tree.pack(fill="both", expand=True, padx=14, pady=4)
        self.agenda_tree.bind("<Double-1>",
                              lambda e: self._cancelar_agenda())
        rodape = tk.Frame(aba, bg=BG)
        rodape.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(rodape, text="duplo clique cancela · tarefas repetem "
                             "diariamente/semanalmente",
                 bg=BG, fg=DIM, font=(UI, 7)).pack(side="left")
        self.agenda_vazio = tk.Label(aba, text="Nenhuma tarefa agendada.",
                                     bg=BG, fg=MUTED, font=FONT_XS)

    def carregar_agenda(self):
        def trabalho():
            try:
                j = api("/api/agenda", timeout=10)
                self._post(self._pintar_agenda, j.get("tarefas") or [])
            except Exception as exc:
                self.set_status(f"agenda: {exc}", ERR)
        threading.Thread(target=trabalho, daemon=True).start()

    def _pintar_agenda(self, tarefas):
        for iid in self.agenda_tree.get_children():
            self.agenda_tree.delete(iid)
        for t in tarefas:
            self.agenda_tree.insert("", "end", values=(
                t.get("id"), str(t.get("quando", "")).replace("T", " ")[:16],
                (t.get("titulo") or "")[:100], t.get("tipo") or "chat",
                t.get("repetir") or "—"))
        if tarefas:
            self.agenda_vazio.place_forget()
        else:
            self.agenda_vazio.place(relx=0.5, rely=0.5, anchor="center")

    def _nova_agenda(self):
        janela = tk.Toplevel(self.root)
        janela.title("Agendar tarefa")
        janela.configure(bg=BG)
        janela.geometry("500x300")
        janela.transient(self.root)
        tk.Label(janela, text="Título", bg=BG, fg=FG).pack(anchor="w",
                                                           padx=14, pady=(12, 2))
        titulo = tk.Entry(janela, bg=PANEL2, fg=FG, bd=0,
                          insertbackground=GOLD)
        titulo.pack(fill="x", padx=14)
        tk.Label(janela, text="Quando (ISO, HH:MM, amanhã 09:00)",
                 bg=BG, fg=MUTED, font=(UI, 8)).pack(anchor="w", padx=14,
                                                      pady=(10, 2))
        quando = tk.Entry(janela, bg=PANEL2, fg=FG, bd=0,
                          insertbackground=GOLD)
        quando.insert(0, "amanhã 09:00")
        quando.pack(fill="x", padx=14)
        tk.Label(janela, text="Instrução para o agente", bg=BG, fg=FG
                 ).pack(anchor="w", padx=14, pady=(10, 2))
        texto = tk.Text(janela, height=4, bg=PANEL2, fg=FG, bd=0,
                        insertbackground=GOLD)
        texto.pack(fill="both", expand=True, padx=14)

        def criar():
            def trabalho():
                try:
                    api("/api/agenda", {"titulo": titulo.get().strip(),
                                        "quando": quando.get().strip(),
                                        "texto": texto.get("1.0", "end").strip(),
                                        "tipo": "chat"}, timeout=15)
                    self._post(self.carregar_agenda)
                except Exception as exc:
                    self._post(self.set_status, f"agenda: {exc}", ERR)
            threading.Thread(target=trabalho, daemon=True).start()
            janela.destroy()
        tk.Button(janela, text="Agendar", command=criar, bg=GOLD, fg=ON_GOLD,
                  bd=0, padx=14, pady=6).pack(anchor="e", padx=14, pady=8)

    def _cancelar_agenda(self):
        sel = self.agenda_tree.selection()
        if not sel:
            return
        tid = self.agenda_tree.item(sel[0], "values")[0]

        def trabalho():
            try:
                api(f"/api/agenda/{tid}", metodo="DELETE", timeout=10)
                self._post(self.carregar_agenda)
            except Exception as exc:
                self._post(self.set_status, f"agenda: {exc}", ERR)
        threading.Thread(target=trabalho, daemon=True).start()

    def _janela_qualidade(self):
        janela = tk.Toplevel(self.root)
        janela.title("YVAKOR · Qualidade")
        janela.configure(bg=BG)
        janela.geometry("620x480")
        caixa = tk.Text(janela, bg=BG, fg=FG, bd=0, wrap="word",
                        padx=16, pady=12, font=FONT_S)
        caixa.pack(fill="both", expand=True)

        def trabalho():
            try:
                j = api("/api/avaliacoes", timeout=10)
                itens = j.get("avaliacoes") or []
            except Exception as exc:
                self._post(lambda: caixa.insert("end", f"Erro: {exc}"))
                return

            def pintar():
                if not itens:
                    caixa.insert("end", "Nenhuma avaliação ainda.\n")
                    return
                notas = [float(i.get("nota") or 0) for i in itens]
                media = sum(notas) / len(notas)
                caixa.insert("end", f"Últimas {len(itens)} avaliações · "
                                    f"média {media:.1f}/5\n\n")
                for i in itens[-12:]:
                    caixa.insert("end",
                                 f"{i.get('ts','')} · nota {i.get('nota')} "
                                 f"· {i.get('problemas') or 'sem problemas'}\n"
                                 f"  {str(i.get('pergunta',''))[:100]}\n\n")
            self._post(pintar)
        threading.Thread(target=trabalho, daemon=True).start()

    def _aba_sistema(self, aba):
        barra = tk.Frame(aba, bg=BG)
        barra.pack(side="bottom", fill="x", padx=16, pady=10)
        atualizar = tk.Label(barra, text="Atualizar", bg=PANEL2, fg=FG,
                             font=FONT_XS, padx=12, pady=5, cursor="hand2")
        atualizar.pack(side="left")
        atualizar.bind("<Button-1>", lambda e: self.carregar_sistema())
        self._hover(atualizar, PANEL2, LINE)
        galeria = tk.Label(barra, text="Galeria", bg=PANEL2, fg=FG,
                           font=FONT_XS, padx=12, pady=5, cursor="hand2")
        galeria.pack(side="left", padx=6)
        galeria.bind("<Button-1>", lambda e: webbrowser.open(
            BASE + "/galeria"))
        self._hover(galeria, PANEL2, LINE)
        qualidade = tk.Label(barra, text="Qualidade", bg=PANEL2, fg=FG,
                             font=FONT_XS, padx=12, pady=5, cursor="hand2")
        qualidade.pack(side="left", padx=6)
        qualidade.bind("<Button-1>", lambda e: self._janela_qualidade())
        self._hover(qualidade, PANEL2, LINE)
        navegador = tk.Label(barra, text="Abrir navegador do agente",
                             bg=PANEL2, fg=FG, font=FONT_XS, padx=12,
                             pady=5, cursor="hand2")
        navegador.pack(side="left")
        navegador.bind("<Button-1>", lambda e: self.abrir_navegador())
        self._hover(navegador, PANEL2, LINE)

        self.sistema = tk.Text(aba, bg=BG, fg=FG, bd=0, wrap="word",
                               padx=18, pady=14, font=FONT,
                               highlightthickness=0, insertbackground=GOLD)
        self.sistema.pack(fill="both", expand=True)
        self.sistema.configure(state="disabled")
        self.sistema.tag_configure("titulo", foreground=GOLD,
                                   font=(DISPLAY, 16))
        self.sistema.tag_configure("rotulo", foreground=MUTED,
                                   font=(UI_SEMI, 8),
                                   spacing1=12)
        self.sistema.tag_configure("valor", foreground=FG, font=FONT_S,
                                   spacing1=2)
        self.sistema.tag_configure("dica", foreground=DIM, font=FONT_XS,
                                   spacing1=8)
        self._texto_sistema([("carregando sistema…", "dica")])


    # ------------------------------------------------------------------ #
    def _texto(self, widget, texto: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", texto)
        widget.configure(state="disabled")

    def _texto_sistema(self, linhas):
        try:
            w = self.sistema
            w.configure(state="normal")
            w.delete("1.0", "end")
            for texto, tag in linhas:
                w.insert("end", texto + "\n", tag or ())
            w.configure(state="disabled")
        except Exception:
            pass

    def add(self, tipo: str, texto: str):
        self.chat.add(tipo, texto)

    def set_status(self, texto: str, cor: str = MUTED):
        self._status_cor = cor
        lbl = self._st.get("estado")
        if lbl:
            try:
                curto = texto if len(texto) <= 58 else texto[:57] + "…"
                lbl.configure(text=curto, fg=cor)
            except Exception:
                pass
        self._atualizar_canal()

    def _atualizar_canal(self):
        try:
            if self._online is False:
                canal, ponto = "SEM CONEXÃO", ERR
            elif self._online is None:
                canal, ponto = "CONECTANDO", GOLD
            elif self.sessao in self._envios:
                canal, ponto = "PROCESSANDO", GOLD
            else:
                canal, ponto = "EM ESCUTA", TEAL
            self._canal_txt.configure(text=canal)
            self._canal_dot.itemconfigure(self._canal_dot_item, fill=ponto)
        except Exception:
            pass

    def _status_contexto(self):
        if self.sessao in self._envios:
            self.set_status(self._ultimo_passo or "pensando…", GOLD)
        elif self._envios:
            self.set_status(
                f"{len(self._envios)} envio(s) em andamento", GOLD)
        elif self._online is False:
            self.set_status("núcleo offline", ERR)
        else:
            self.set_status("pronto", OK)

    # ---------------------------- conversas --------------------------- #
    def carregar_sessoes(self, recarregar_chat: bool = False):
        if getattr(self, "_privado", False):
            return
        self._pedido_sessoes += 1
        token = self._pedido_sessoes

        def trabalho():
            try:
                j = api("/api/sessions", timeout=10)
            except Exception as exc:
                self._post(self._sessoes_erro,
                           f"{type(exc).__name__}: {exc}", token)
                return
            self._post(self._pintar_sessoes, j, token, recarregar_chat)

        threading.Thread(target=trabalho, daemon=True).start()

    def _sessoes_erro(self, msg: str, token: int):
        if not self._vivo or token != self._pedido_sessoes:
            return
        self._online = False
        self.set_status(f"núcleo: {msg}", ERR)

    def _pintar_sessoes(self, j, token: int, recarregar_chat: bool = False):
        if not self._vivo or token != self._pedido_sessoes:
            return
        sessoes = j.get("sessions") or []
        ativa = j.get("active")
        self.sessoes = sessoes
        ids = {s.get("id") for s in sessoes}
        carregar = recarregar_chat
        if self.sessao not in ids:
            self.sessao = ativa if ativa in ids else (
                sessoes[0].get("id") if sessoes else None)
            carregar = True
        self.lista.definir(sessoes, self.sessao)
        try:
            self.lbl_contagem.configure(
                text=f"{len(sessoes)} conversa" +
                     ("" if len(sessoes) == 1 else "s"))
        except Exception:
            pass
        if self._online is not True:
            self._online = True
            self.set_status("online", OK)
        if not sessoes:
            if not self._criando:
                self.nova_conversa()
            return
        if carregar:
            self._carregar_conversa(self.sessao)

    def _abrir_sessao(self, sid):
        if not sid:
            return
        self._privado = False
        self._pintar_botao_privado(False)
        if sid == self.sessao and self._hist_sid == sid:
            return
        self.sessao = sid
        self.lista.marcar_ativa(sid)
        self._carregar_conversa(sid)

    def _carregar_conversa(self, sid):
        if not sid:
            return
        self._pedido_chat += 1
        token = self._pedido_chat
        self._hist = []
        self._hist_sid = sid
        self.chat.clear()
        self.chat.add("system", "carregando conversa…", animar=False)
        self.set_status("carregando conversa…", GOLD)
        if sid in self._envios:
            self.chat.typing(self._ultimo_passo or "pensando")
        self._atualizar_botao_envio()

        def trabalho():
            aviso = ""
            try:
                api(f"/api/sessions/{sid}/activate", {}, timeout=10)
            except Exception as exc:
                aviso = f"{type(exc).__name__}: {exc}"
            try:
                j = api(f"/api/sessions/{sid}/messages", timeout=20)
            except Exception as exc:
                self._post(self._mensagens_erro,
                           f"{type(exc).__name__}: {exc}", sid, token)
                return
            self._post(self._pintar_mensagens, j, sid, token, aviso)

        threading.Thread(target=trabalho, daemon=True).start()

    def _mensagens_erro(self, msg: str, sid, token: int):
        if not self._vivo or sid != self.sessao or token != self._pedido_chat:
            return
        self.set_status(f"conversa: {msg}", ERR)
        self.chat.clear()
        self.chat.add("system", "Não foi possível carregar a conversa.\n" +
                      msg, animar=False)

    def _pintar_mensagens(self, j, sid, token: int, aviso: str = ""):
        if not self._vivo or sid != self.sessao or token != self._pedido_chat:
            return
        msgs = j.get("messages") or []
        atual = [("user" if m.get("role") == "user" else "agent",
                  m.get("content") or "") for m in msgs]
        prefixo_ok = (self._hist_sid == sid and bool(self._hist)
                      and len(atual) >= len(self._hist)
                      and atual[:len(self._hist)] == self._hist)
        if not prefixo_ok:
            self.chat.clear()
            self._hist = []
            inicio = 0
        else:
            inicio = len(self._hist)
        self.chat.inicio_lote()
        try:
            for tipo, texto in atual[inicio:]:
                self.chat.add(tipo, texto, animar=False, rolar=False)
        finally:
            self.chat.fim_lote(rolar=False)
        self._hist = atual
        self._hist_sid = sid
        if not prefixo_ok:
            for a in self._artefatos.get(sid, []):
                self._adicionar_artefato(a, rolar=False)
        self.chat.rolar_fim(True)
        if not atual and not self._artefatos.get(sid):
            self.chat.mostrar_vazio()
        if sid in self._envios:
            self.chat.typing(self._ultimo_passo or "pensando")
            self._iniciar_progresso(sid)
        if aviso:
            self.set_status(f"conversa ok; ativação falhou: {aviso}", GOLD)
        elif self._online is not True:
            self._online = True
            self._status_contexto()
        else:
            self._status_contexto()

    def _adicionar_artefato(self, a: dict, rolar: bool = True):
        url = a.get("url") or ""
        if not url:
            return
        titulo = a.get("titulo") or a.get("tipo") or "artefato"
        tipo = a.get("tipo") or "arquivo"
        caminho = a.get("caminho") or ""
        if tipo == "imagem" and caminho and Path(caminho).is_file():
            self.chat.add_anexo({"tipo": "imagem", "caminho": caminho,
                                 "nome": a.get("nome") or Path(caminho).name,
                                 "url": url}, usuario=False)
            if a.get("fonte") or a.get("autor"):
                self.chat.add("meta",
                              f"foto · {titulo} — {a.get('autor') or a.get('fonte')} "
                              f"({a.get('licenca') or 'ver fonte'})",
                              animar=False, url=BASE + url, rolar=rolar)
            return
        icone = {"pdf": "📕", "planilha": "📊", "relatorio": "📄",
                 "documento": "📝", "pacote": "🗜", "projeto": "🌐"}.get(tipo, "📎")
        self.chat.add("meta", f"{icone} {titulo}", animar=False,
                      url=BASE + url, rolar=rolar)


    def abrir_browser_conversa(self):
        """Mostra o navegador ao vivo dentro da conversa atual."""
        self.chat.add_card(TelaBrowser(self.chat.inner, self))

    def abrir_camera_conversa(self, dev: dict):
        """Mostra a câmera ao vivo dentro da conversa atual."""
        self.chat.add_card(TelaCamera(self.chat.inner, self, dev))

    def abrir_cameras(self):
        """Popup com a lista de câmeras da rede."""
        if self._janela_cameras and self._janela_cameras.winfo_exists():
            self._janela_cameras.deiconify()
            self._janela_cameras.lift()
            return
        self._janela_cameras = JanelaCameras(self)

    def abrir_camera(self, dev: dict):
        """Popup ao vivo de uma câmera, sem duplicar a mesma janela."""
        ip = str((dev or {}).get("ip") or "")
        if not ip:
            return
        janela = self._cameras_abertas.get(ip)
        if janela and janela.winfo_exists():
            janela.deiconify()
            janela.lift()
            return
        janela = JanelaCameraVivo(self, dev)
        self._cameras_abertas[ip] = janela

    def _pintar_botao_privado(self, ativo: bool):
        try:
            if ativo:
                self.btn_priv.configure(bg=TEAL_BG, fg=TEAL, text="privada ●")
            else:
                self.btn_priv.configure(bg=PANEL, fg=MUTED, text="privada")
        except Exception:
            pass

    def nova_conversa_privada(self):
        """Conversa efêmera: sem histórico, memória ou registro no SQLite."""
        self._privado = True
        self.sessao = f"priv-{int(time.time() * 1000)}"
        self._hist = []
        self._hist_sid = self.sessao
        self.chat.clear()
        self.chat.add("system", "Modo privado ativo. Esta conversa não é "
                                "salva no histórico nem na memória.")
        try:
            self.lista.marcar_ativa(None)
        except Exception:
            pass
        self._pintar_botao_privado(True)
        self.set_status("conversa privada · nada será salvo", TEAL)
        self._atualizar_botao_envio()
        self._focar_entrada()

    def _sobre(self):
        try:
            v = api("/api/version", timeout=5)
        except Exception:
            v = {"version": "0.8.0", "build": "local"}
        janela = tk.Toplevel(self.root)
        janela.title("Sobre o YVAKOR")
        janela.configure(bg=BG)
        janela.geometry("520x330")
        janela.transient(self.root)
        tk.Label(janela, text="YVAKOR", bg=BG, fg=FG,
                 font=(DISPLAY, 22)).pack(anchor="w", padx=18, pady=(18, 0))
        tk.Label(janela, text="Agente pessoal autônomo", bg=BG, fg=MUTED,
                 font=(UI, 9)).pack(anchor="w", padx=18)
        tk.Label(janela,
                 text=f"Versão {v.get('version')} · build {v.get('build')}\n"
                      "© 2026 Antonio José Cordero Martinez / ACM Digital\n"
                      "Todos os direitos reservados.",
                 bg=BG, fg=MUTED, font=(UI, 9), justify="left").pack(
                     anchor="w", padx=18, pady=(14, 0))
        tk.Label(janela,
                 text="Núcleo local · Chrome CDP · MCP · OCR/PDF · Agenda\n"
                      "Extensão Chrome · app desktop · memória SQLite",
                 bg=PANEL2, fg=FG, font=(UI, 8), justify="left",
                 padx=12, pady=10).pack(fill="x", padx=18, pady=14)
        barra = tk.Frame(janela, bg=BG)
        barra.pack(fill="x", padx=18, pady=4)
        tk.Button(barra, text="Documentação", bg=PANEL2, fg=FG, bd=0,
                  padx=10, command=lambda: os.startfile(
                      str(ROOT / "docs" / "PRODUCT.md"))).pack(side="left")
        tk.Button(barra, text="Fechar", bg=GOLD, fg=ON_GOLD, bd=0, padx=12,
                  command=janela.destroy).pack(side="right")

    def nova_janela(self):
        """Compatibilidade: nova conversa sempre na janela atual."""
        self.nova_conversa()

    def nova_conversa(self):
        self._privado = False
        self._pintar_botao_privado(False)
        if self._criando:
            return
        self._criando = True
        self.set_status("criando conversa…", GOLD)

        def trabalho():
            try:
                j = api("/api/sessions", {}, timeout=12)
            except Exception as exc:
                self._post(self._nova_erro, f"{type(exc).__name__}: {exc}")
                return
            self._post(self._nova_ok, j)

        threading.Thread(target=trabalho, daemon=True).start()

    def _nova_ok(self, j):
        self._criando = False
        self._privado = False
        self._pintar_botao_privado(False)
        sid = j.get("active")
        if sid:
            self.sessao = sid
            self._hist = []
            self._hist_sid = sid
            self.chat.clear()
            self.chat.mostrar_vazio()
            self.set_status("nova conversa", OK)
            self._atualizar_botao_envio()
            self._focar_entrada()
        self.carregar_sessoes()

    def _nova_erro(self, msg: str):
        self._criando = False
        self.set_status(f"nova conversa: {msg}", ERR)
        self.chat.add("system", "Não foi possível criar a conversa: " + msg)

    # ------------------------------ envio ----------------------------- #
    def _enter(self, evt):
        if evt.state & 0x0001:  # Shift
            return None
        self.enviar()
        return "break"

    def _acao_envio(self):
        if self.sessao in self._envios:
            self._destravar()
        else:
            self.enviar()

    def enviar(self):
        sid = self.sessao
        if not sid:
            self.set_status("nenhuma conversa selecionada", ERR)
            return
        texto = self._texto_entrada().strip()
        anexos = list(self._anexos)
        if not texto and not anexos:
            return
        mensagem = texto
        if texto.startswith("/"):
            from yvakor import atalhos as _atalhos
            ex = _atalhos.expandir(texto)
            if ex.get("erro"):
                self.add("system", ex["erro"])
                return
            if ex.get("ok"):
                mensagem = ex["prompt"]
        if not texto:
            texto = mensagem = "Analise o anexo enviado."
        if sid in self._envios:
            self.set_status("já existe um envio nesta conversa", GOLD)
            return
        self._limpar_entrada()
        self.add("user", texto)
        for anexo in anexos:
            self.chat.add_anexo(anexo, usuario=True)
        self._anexos = []
        self._render_anexos()
        if self._hist_sid == sid:
            self._hist.append(("user", texto))
        self._pedido += 1
        token = self._pedido
        self._envios[sid] = token
        self._ultimo_passo = ""
        self.chat.typing("pensando")
        self.set_status("pensando…", GOLD)
        self._atualizar_botao_envio()
        self._iniciar_progresso(sid)
        self._agendar(250, self._focar_entrada)

        def trabalho():
            try:
                corpo = {"message": mensagem, "session": sid}
                if anexos:
                    corpo["attachments"] = anexos
                if self._privado:
                    corpo["private"] = True
                    corpo["history"] = [
                        {"role": ("assistant" if r == "assistant" else "user"),
                         "content": c}
                        for r, c in self._hist[:-1][-12:]]
                j = api("/api/chat", corpo, timeout=600)
            except Exception as exc:
                self._post(self._falha, f"{type(exc).__name__}: {exc}",
                           sid, token, texto)
                return
            self._post(self._resposta, j, sid, token)

        threading.Thread(target=trabalho, daemon=True).start()

    def _limpar_entrada(self):
        self.entrada.delete("1.0", "end")
        self._ph = False
        self.entrada.configure(fg=FG, height=2)
        self._mostrar_placeholder()

    def _atualizar_botao_envio(self):
        pendente = self.sessao in self._envios
        try:
            if pendente:
                self.btn_enviar.configure(text="Destravar", bg=PANEL2,
                                          fg=ERR)
            else:
                self.btn_enviar.configure(text="Enviar", bg=GOLD, fg=ON_GOLD)
        except Exception:
            pass
        self._atualizar_canal()

    def _alternar_tema(self):
        """Ctrl+Shift+T: alterna claro/escuro (vale ao reabrir o app)."""
        import json as _json
        arq = ROOT / "data" / "preferencias.json"
        try:
            dados = _json.loads(arq.read_text(encoding="utf-8"))
        except Exception:
            dados = {}
        novo = "claro" if ESCURO else "escuro"
        dados["tema"] = novo
        try:
            arq.parent.mkdir(parents=True, exist_ok=True)
            arq.write_text(_json.dumps(dados, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            self.add("system", f"Tema {novo} salvo. Feche e abra o YVAKOR "
                               "para aplicar.")
        except Exception as exc:
            self.add("system", f"Não consegui salvar o tema: {exc}")

    def _hover_envio(self, entrando: bool):
        try:
            if self.sessao in self._envios:
                self.btn_enviar.configure(bg=LINE if entrando else PANEL2)
            else:
                self.btn_enviar.configure(bg=GOLD_HOVER if entrando
                                          else GOLD)
        except Exception:
            pass

    def _destravar(self):
        sid = self.sessao
        if sid not in self._envios:
            return
        self._envios.pop(sid, None)
        if sid == self.sessao:
            self.chat.parar_typing()
        if self._prog_sid == sid:
            self._parar_progresso()
        self.chat.add("system", "Envio liberado localmente. Se o núcleo "
                      "terminar depois, a resposta aparece no histórico "
                      "(F5).")
        self.set_status("envio liberado", GOLD)
        self._atualizar_botao_envio()

    def _resposta(self, j, sid, token: int):
        if self._envios.get(sid) != token:
            return  # destravado ou resposta tardia: não sequestra a tela
        self._envios.pop(sid, None)
        if self._prog_sid == sid:
            self._parar_progresso()
        self._online = True
        artefatos = j.get("artefatos") or []
        if artefatos:
            self._artefatos[sid] = artefatos
        if sid == self.sessao:
            self.chat.parar_typing()
            resposta = (j.get("answer") or j.get("error")
                        or "(sem resposta)")
            self.add("agent", resposta)
            if self.voz_ativa and not self._privado:
                threading.Thread(target=self._falar_resposta,
                                 args=(resposta,), daemon=True).start()
            if self._hist_sid == sid:
                self._hist.append(("assistant", resposta))
            for a in artefatos:
                self._adicionar_artefato(a)
            self.set_status("pronto", OK)
        else:
            self.set_status("resposta pronta em outra conversa", GOLD)
        self._atualizar_botao_envio()
        if not self._privado:
            self.carregar_sessoes()
        else:
            self.set_status("privada · não salva", TEAL)
        self._agendar(150, self._focar_entrada)

    def _falha(self, msg: str, sid, token: int, texto: str):
        if self._envios.get(sid) != token:
            return
        self._envios.pop(sid, None)
        if self._prog_sid == sid:
            self._parar_progresso()
        if sid == self.sessao:
            self.chat.parar_typing()
            self.set_status("falha na conexão", ERR)
            self.chat.add("system", "Falha ao falar com o núcleo: " + msg)
            if not self._texto_entrada().strip():
                self._definir_entrada(texto)
            self._agendar(3500, self._recarregar_se, sid, token)
        self._atualizar_botao_envio()

    def _recarregar_se(self, sid, token: int):
        if getattr(self, "_privado", False):
            return
        if not self._vivo or sid != self.sessao:
            return
        if token in self._envios.values():
            return
        self._carregar_conversa(sid)

    # ------------------------------- voz ------------------------------ #
    def _pintar_botao_voz(self):
        try:
            self.btn_voz.configure(text="🔊 VOZ" if self.voz_ativa else "🔇 VOZ",
                                   fg=TEAL if self.voz_ativa else MUTED)
        except Exception:
            pass

    def _carregar_voz(self):
        def trabalho():
            try:
                j = api("/api/voz/ativo", timeout=5)
                self.voz_ativa = bool(j.get("ativo", True))
            except Exception:
                pass
            self._post(self._pintar_botao_voz)
        threading.Thread(target=trabalho, daemon=True).start()

    def alternar_voz(self):
        self.voz_ativa = not self.voz_ativa
        self._pintar_botao_voz()
        estado = "ativada" if self.voz_ativa else "desativada"
        self.set_status(f"voz {estado}", TEAL if self.voz_ativa else MUTED)

        def salvar():
            try:
                api("/api/voz/ativo", {"ativo": self.voz_ativa}, timeout=8)
            except Exception:
                pass
        threading.Thread(target=salvar, daemon=True).start()

    def _falar_resposta(self, texto: str):
        if not self.voz_ativa or self._privado:
            return
        import re
        fala = re.sub(r"```.*?```", " ", texto or "", flags=re.S)
        fala = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", fala)
        fala = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", fala)
        fala = re.sub(r"https?://\S+", " ", fala)
        fala = re.sub(r"[#*_`>|]", " ", fala)
        fala = " ".join(fala.split())[:900]
        if not fala:
            return
        try:
            api("/api/voz/falar", {"texto": fala}, timeout=120)
        except Exception:
            pass

    def ditar(self):
        if self._gravando:
            return
        self._gravando = True
        self.set_status("gravando 5 s… fale agora", GOLD)
        self._desenhar_mic(GOLD)

        def trabalho():
            try:
                import sounddevice as sd
                frames = int(5 * 16000)
                audio = sd.rec(frames, samplerate=16000, channels=1,
                               dtype="int16")
                sd.wait()
                buf = io.BytesIO()
                with wave.open(buf, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(audio.tobytes())
                dados = base64.b64encode(buf.getvalue()).decode()
                j = api("/api/voz/transcrever",
                        {"audio_b64": dados, "ext": "wav"}, timeout=120)
            except Exception as exc:
                self._post(self._ditado_erro,
                           f"{type(exc).__name__}: {exc}")
                return
            self._post(self._ditado, j)

        threading.Thread(target=trabalho, daemon=True).start()

    def _gravar_terminou(self):
        self._gravando = False
        self._desenhar_mic(TEAL)

    def _ditado(self, j):
        self._gravar_terminou()
        if not j.get("ok", True):
            erro = str(j.get("erro") or "falhou")
            self.set_status("microfone: " + erro, ERR)
            self.chat.add("system", "Transcrição falhou: " + erro)
            return
        texto = (j.get("texto") or "").strip()
        if not texto:
            self.set_status("nada reconhecido", GOLD)
            return
        atual = self._texto_entrada().strip()
        self._definir_entrada((atual + " " + texto).strip() if atual
                              else texto)
        self.set_status("transcrito", OK)

    def _ditado_erro(self, msg: str):
        self._gravar_terminou()
        self.set_status("microfone: " + msg, ERR)
        self.chat.add("system", "Microfone indisponível: " + msg)

    # --------------------- renomear/apagar conversa ------------------- #
    def renomear_sessao(self, sid):
        atual = ""
        for s in self.sessoes:
            if s.get("id") == sid:
                atual = s.get("title") or ""
                break
        self._dialogo_texto(
            "Renomear conversa", "Novo título", atual,
            lambda titulo: self._renomear_ok(sid, titulo), altura=2)

    def _renomear_ok(self, sid, titulo: str):
        def trabalho():
            try:
                api(f"/api/sessions/{sid}/rename", {"title": titulo},
                    timeout=12)
            except Exception as exc:
                self._post(self.set_status,
                           f"renomear: {type(exc).__name__}: {exc}", ERR)
                return
            self._post(self.carregar_sessoes)

        threading.Thread(target=trabalho, daemon=True).start()

    def apagar_sessao(self, sid):
        titulo = next((s.get("title") for s in self.sessoes
                       if s.get("id") == sid), sid)
        self._dialogo_confirmar(
            "Apagar conversa",
            f"Apagar “{titulo}”?\nEssa ação não pode ser desfeita.",
            lambda: self._apagar_ok(sid))

    def _apagar_ok(self, sid):
        def trabalho():
            try:
                api(f"/api/sessions/{sid}", metodo="DELETE", timeout=12)
            except Exception as exc:
                self._post(self.set_status,
                           f"apagar: {type(exc).__name__}: {exc}", ERR)
                return
            self._post(self._apagar_pintar, sid)

        threading.Thread(target=trabalho, daemon=True).start()

    def _apagar_pintar(self, sid):
        if sid == self.sessao:
            self.sessao = None
            self._hist = []
            self._hist_sid = None
            self.chat.clear()
            self.chat.mostrar_vazio()
        self.set_status("conversa apagada", OK)
        self.carregar_sessoes()

    # ----------------------------- diálogos --------------------------- #
    def _dialogo_texto(self, titulo: str, rotulo: str, inicial: str,
                       ao_ok, altura: int = 2):
        win = tk.Toplevel(self.root)
        win.title(titulo)
        win.configure(bg=BG)
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()
        _barra_titulo_escura(win)
        tk.Label(win, text=titulo, bg=BG, fg=FG, font=FONT_B).pack(
            anchor="w", padx=18, pady=(16, 2))
        tk.Label(win, text=rotulo, bg=BG, fg=MUTED, font=FONT_XS).pack(
            anchor="w", padx=18)
        caixa = tk.Text(win, height=altura, bg=PANEL2, fg=FG, bd=0,
                        insertbackground=GOLD, wrap="word", padx=10, pady=8,
                        font=FONT, highlightthickness=1,
                        highlightbackground=LINE, highlightcolor=TEAL)
        caixa.pack(fill="both", expand=True, padx=18, pady=10)
        caixa.insert("1.0", inicial or "")
        caixa.focus_set()

        def enviar():
            texto = caixa.get("1.0", "end").strip()
            if not texto:
                return
            win.destroy()
            ao_ok(texto)

        def cancelar():
            try:
                win.destroy()
            except Exception:
                pass

        botoes = tk.Frame(win, bg=BG)
        botoes.pack(fill="x", padx=18, pady=(0, 14))
        salvar = tk.Label(botoes, text="Salvar", bg=GOLD, fg=ON_GOLD,
                          font=(UI_SEMI, 9), padx=14, pady=6,
                          cursor="hand2")
        salvar.pack(side="right")
        salvar.bind("<Button-1>", lambda e: enviar())
        self._hover(salvar, GOLD, GOLD_HOVER)
        cancelar_btn = tk.Label(botoes, text="Cancelar", bg=PANEL2,
                                fg=MUTED, font=FONT_XS, padx=12, pady=6,
                                cursor="hand2")
        cancelar_btn.pack(side="right", padx=(0, 6))
        cancelar_btn.bind("<Button-1>", lambda e: cancelar())
        self._hover(cancelar_btn, PANEL2, LINE, fg_normal=MUTED,
                    fg_hover=FG)
        caixa.bind("<Return>", lambda e: (enviar(), "break")[1]) \
            if altura <= 2 else caixa.bind(
                "<Control-Return>", lambda e: (enviar(), "break")[1])
        win.bind("<Escape>", lambda e: cancelar())
        win.protocol("WM_DELETE_WINDOW", cancelar)
        try:
            self.root.update_idletasks()
            largura = min(560, max(380, self.root.winfo_width() - 120))
            altura_win = 170 + altura * 22
            x = self.root.winfo_rootx() + (self.root.winfo_width() - largura) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - altura_win) // 2
            win.geometry(f"{largura}x{altura_win}+{x}+{y}")
        except Exception:
            win.geometry("520x220")
        return win

    def _dialogo_confirmar(self, titulo: str, mensagem: str, ao_ok):
        win = tk.Toplevel(self.root)
        win.title(titulo)
        win.configure(bg=BG)
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()
        _barra_titulo_escura(win)
        tk.Label(win, text=titulo, bg=BG, fg=FG, font=FONT_B).pack(
            anchor="w", padx=18, pady=(18, 4))
        tk.Label(win, text=mensagem, bg=BG, fg=MUTED, font=FONT_XS,
                 justify="left", wraplength=390).pack(anchor="w", padx=18)
        botoes = tk.Frame(win, bg=BG)
        botoes.pack(fill="x", padx=18, pady=16)
        ok = tk.Label(botoes, text="Confirmar", bg=ERR, fg=ON_GOLD,
                      font=(UI_SEMI, 9), padx=14, pady=6,
                      cursor="hand2")
        ok.pack(side="right")
        ok.bind("<Button-1>", lambda e: (win.destroy(), ao_ok()))
        self._hover(ok, ERR, ERR_HOVER)
        cancelar = tk.Label(botoes, text="Cancelar", bg=PANEL2, fg=MUTED,
                            font=FONT_XS, padx=12, pady=6, cursor="hand2")
        cancelar.pack(side="right", padx=(0, 6))
        cancelar.bind("<Button-1>", lambda e: win.destroy())
        self._hover(cancelar, PANEL2, LINE, fg_normal=MUTED, fg_hover=FG)
        win.bind("<Escape>", lambda e: win.destroy())
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        try:
            self.root.update_idletasks()
            largura = 440
            altura = 200
            x = self.root.winfo_rootx() + (self.root.winfo_width() - largura) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - altura) // 2
            win.geometry(f"{largura}x{altura}+{x}+{y}")
        except Exception:
            win.geometry("440x200")
        return win


    # ----------------------------- tarefas ---------------------------- #
    def poll_tarefas(self):
        if not self._vivo:
            return
        try:
            visivel = (self.abas.atual == 1
                       and self.root.state() not in ("iconic", "withdrawn"))
        except Exception:
            visivel = False
        atraso = 15000
        if visivel:
            self.atualizar_tarefas()
            atraso = 4000 if self._tem_tarefa_ativa() else 20000
        self._poll_job = self._agendar(atraso, self.poll_tarefas)

    def _tem_tarefa_ativa(self) -> bool:
        for item in self._tarefas_sig or []:
            if item[1] in ("executando", "na_fila"):
                return True
        return False

    def atualizar_tarefas(self):
        if self._buscando_tarefas:
            return
        self._buscando_tarefas = True

        def trabalho():
            try:
                j = api("/api/cowork", timeout=20)
            except Exception as exc:
                self._post(self._tarefas_erro,
                           f"{type(exc).__name__}: {exc}")
                return
            self._post(self._pintar_tarefas, j)

        threading.Thread(target=trabalho, daemon=True).start()

    def _tarefas_erro(self, msg: str):
        self._buscando_tarefas = False
        self.set_status(f"tarefas: {msg}", ERR)

    def _pintar_tarefas(self, j):
        self._buscando_tarefas = False
        tarefas = j.get("tasks") or []
        nova_sig = tuple((str(t.get("id")), str(t.get("status") or ""),
                          (t.get("description") or "")[:110])
                         for t in tarefas)
        if nova_sig == self._tarefas_sig:
            self._atualizar_vazio_tarefas(bool(tarefas))
            return
        self._tarefas_sig = nova_sig
        vistos = set()
        self._suprimir_selecao = True
        try:
            for t in tarefas:
                iid = str(t.get("id"))
                vistos.add(iid)
                valores = (t.get("id"), t.get("status"),
                           (t.get("description") or "")[:110])
                status = str(t.get("status") or "")
                if self.tree.exists(iid):
                    atual = tuple(str(x) for x in
                                  self.tree.item(iid, "values"))
                    if atual != tuple(str(x) for x in valores):
                        self.tree.item(iid, values=valores,
                                       tags=(status,))
                else:
                    self.tree.insert("", "end", iid=iid, values=valores,
                                     tags=(status,))
            for iid in self.tree.get_children():
                if iid not in vistos:
                    self.tree.delete(iid)
            if (self._tid_selecionado
                    and self.tree.exists(str(self._tid_selecionado))):
                self.tree.selection_set(str(self._tid_selecionado))
        finally:
            self._suprimir_selecao = False
        self._atualizar_vazio_tarefas(bool(tarefas))

    def _atualizar_vazio_tarefas(self, tem_tarefas: bool):
        try:
            if tem_tarefas:
                self.lbl_tarefas_vazio.place_forget()
            else:
                self.lbl_tarefas_vazio.place(relx=0.5, rely=0.3,
                                             anchor="center")
        except Exception:
            pass

    def _ver_tarefa(self, _evt=None):
        if getattr(self, "_suprimir_selecao", False):
            return
        sel = self.tree.selection()
        if not sel:
            return
        tid = str(self.tree.item(sel[0], "values")[0])
        self._tid_selecionado = tid
        self._pedido_tarefa += 1
        token = self._pedido_tarefa

        def trabalho():
            try:
                t = api(f"/api/cowork/{tid}", timeout=15)
            except Exception as exc:
                self._post(self.set_status,
                           f"tarefa: {type(exc).__name__}: {exc}", ERR)
                return
            self._post(self._mostrar_tarefa, t, tid, token)

        threading.Thread(target=trabalho, daemon=True).start()

    @staticmethod
    def _passo_texto(p) -> str:
        if isinstance(p, dict):
            return str(p.get("texto") or p.get("label") or p)
        return str(p)

    def _mostrar_tarefa(self, t: dict, tid, token: int):
        if (not self._vivo or token != self._pedido_tarefa
                or str(self._tid_selecionado) != str(tid)
                or str(t.get("id")) != str(tid)):
            return
        linhas = [f"Tarefa {t.get('id')} · {t.get('status')}", "",
                  t.get("description") or ""]
        plano = (t.get("plano") or {}).get("etapas") or []
        if plano:
            linhas += ["", "Plano:"]
            linhas += [f"  {e.get('id')}. {e.get('titulo')}" for e in plano]
        prog = t.get("progresso") or {}
        if prog.get("concluidas"):
            linhas += ["", "Concluídas: " + ", ".join(
                str(x) for x in prog["concluidas"])]
        passos = t.get("steps") or []
        if passos:
            linhas += ["", "Passos:"]
            linhas += [f"  · {self._passo_texto(p)[:180]}"
                       for p in passos[-12:]]
        artefatos = t.get("artefatos") or []
        if artefatos:
            linhas += ["", "Artefatos:"]
            linhas += [f"  ↗ {a.get('nome') or a.get('caminho') or a}"
                       for a in artefatos[:12]]
        if t.get("result"):
            linhas += ["", "Resultado:", t["result"][:4000]]
        if t.get("error"):
            linhas += ["", "Erro: " + str(t["error"])]
        self._texto(self.detalhe, "\n".join(linhas))
        status = str(t.get("status") or "")
        try:
            self.btn_cancelar.configure(
                state="normal" if status in ("na_fila", "executando")
                else "disabled")
            self.btn_retomar.configure(
                state="normal" if status in ("interrompida", "falha",
                                             "cancelada")
                else "disabled")
        except Exception:
            pass

    def _acao_tarefa(self, acao: str):
        sel = self.tree.selection()
        if not sel:
            self.set_status("selecione uma tarefa", MUTED)
            return
        tid = str(self.tree.item(sel[0], "values")[0])

        def trabalho():
            erro = None
            try:
                api(f"/api/cowork/{tid}/{acao}", {}, timeout=15)
            except Exception as exc:
                erro = f"{type(exc).__name__}: {exc}"
            self._post(self._acao_tarefa_ok, tid, acao, erro)

        threading.Thread(target=trabalho, daemon=True).start()

    def _acao_tarefa_ok(self, tid, acao: str, erro):
        if erro:
            self.set_status(f"{acao}: {erro}", ERR)
            self.chat.add("system", f"Tarefa {tid}: {erro}")
        else:
            self.set_status("cancelamento pedido" if acao == "cancel"
                            else "retomando tarefa", GOLD)
        self.atualizar_tarefas()

    def nova_tarefa(self):
        self._dialogo_texto(
            "Nova tarefa",
            "Descreva a tarefa que o YVAKOR deve executar em segundo plano.",
            "", self._criar_tarefa, altura=5)

    def _criar_tarefa(self, desc: str):
        self.set_status("disparando tarefa…", GOLD)

        def trabalho():
            try:
                j = api("/api/cowork", {"description": desc}, timeout=20)
            except Exception as exc:
                self._post(self._tarefa_erro, f"{type(exc).__name__}: {exc}")
                return
            self._post(self._tarefa_ok, j)

        threading.Thread(target=trabalho, daemon=True).start()

    def _tarefa_ok(self, j):
        tarefa = j.get("task") or {}
        self.set_status(f"tarefa {tarefa.get('id') or ''} na fila", OK)
        self.abas.selecionar(1)
        self.atualizar_tarefas()

    def _tarefa_erro(self, msg: str):
        self.set_status(f"tarefa: {msg}", ERR)
        self.chat.add("system", "Não foi possível disparar a tarefa: " + msg)


    # ----------------------------- sistema ---------------------------- #
    def carregar_sistema(self):
        if self._buscando_sistema:
            return
        self._buscando_sistema = True
        lbl = self._st.get("modelo")
        if lbl is not None and lbl.cget("text") == "—":
            self._texto_sistema([("carregando sistema…", "dica")])

        def trabalho():
            try:
                h = api("/api/health", timeout=25)
                s = api("/api/status", timeout=25)
            except Exception as exc:
                self._post(self._sistema_erro,
                           f"{type(exc).__name__}: {exc}")
                return
            self._post(self._mostrar_sistema, h, s)

        threading.Thread(target=trabalho, daemon=True).start()

    def _sistema_erro(self, msg: str):
        self._buscando_sistema = False
        self.set_status(f"sistema: {msg}", ERR)
        self._texto_sistema([
            ("YVAKOR — núcleo local", "titulo"),
            ("", None),
            ("Não foi possível ler o estado do núcleo.", "valor"),
            (msg, "dica"),
            ("", None),
            ("Use Atualizar para tentar de novo.", "dica"),
        ])

    @staticmethod
    def _duracao(seg) -> str:
        try:
            seg = int(float(seg))
        except Exception:
            return "—"
        if seg < 60:
            return f"{seg} s"
        if seg < 3600:
            return f"{seg // 60} min"
        return f"{seg // 3600} h {(seg % 3600) // 60} min"

    def _mostrar_sistema(self, h, s):
        self._buscando_sistema = False
        self._sistema_ts = time.time()
        episodios = s.get("episodes")
        memoria = s.get("memoria") or {}
        skills = s.get("skills") or []
        browser = s.get("browser") or {}
        motores = browser.get("motores") or {}
        padrao = browser.get("padrao") or "edge"
        motor = motores.get(padrao) or {}
        try:
            rotulo_modo = {"local": "local", "auto": "auto",
                           "deepseek": "deepseek"}.get(
                s.get("modo_modelo"), s.get("provider"))
            self._st["modelo"].configure(
                text=f"{rotulo_modo} · {s.get('model')}  ▾")
            self._st["memorias"].configure(
                text=str(episodios) if episodios is not None else "—")
            self._st["skills"].configure(text=str(len(skills)))
            self._st["build"].configure(text=str(s.get("build") or "—"))
            self._canal_provider.configure(text=str(s.get("model") or "—"))
        except Exception:
            pass
        if self._online is not True and h.get("ok"):
            self._online = True
            self.set_status("online", OK)
        linhas = [
            ("YVAKOR — núcleo local", "titulo"),
            ("", None),
            ("ESTADO", "rotulo"),
            (f"online: {'sim' if h.get('ok') else 'não'} · uptime: "
             f"{self._duracao(h.get('uptime_s'))}", "valor"),
            ("PROVEDOR", "rotulo"),
            (f"{s.get('provider')} · {s.get('model')}", "valor"),
            ("MEMÓRIA", "rotulo"),
            (f"{episodios} episódios · {memoria.get('fatos', '—')} fatos · "
             f"{memoria.get('notas', '—')} notas", "valor"),
            ("SKILLS", "rotulo"),
            (f"{len(skills)} instaladas", "valor"),
            ("NAVEGADOR", "rotulo"),
            (f"{padrao} · aberto: {'sim' if motor.get('aberto') else 'não'}"
             f" · visível: {'sim' if motor.get('visivel') else 'não'}",
             "valor"),
            ("TAREFAS", "rotulo"),
            (f"{s.get('cowork_pending', 0)} pendentes em segundo plano",
             "valor"),
            ("BUILD", "rotulo"),
            (f"{s.get('build') or '—'}", "valor"),
            ("", None),
            ("Interface nativa Tkinter. O núcleo HTTP continua disponível",
             "dica"),
            ("para automações, celular e integrações.", "dica"),
        ]
        self._texto_sistema(linhas)

    def abrir_navegador(self):
        self.set_status("abrindo navegador do agente…", GOLD)

        def trabalho():
            try:
                j = api("/api/browser/action",
                        {"action": "open", "url": "https://www.google.com"},
                        timeout=90)
            except Exception as exc:
                self._post(self._navegador_erro,
                           f"{type(exc).__name__}: {exc}")
                return
            self._post(self._navegador_ok, j)

        threading.Thread(target=trabalho, daemon=True).start()

    def _navegador_ok(self, j):
        self.set_status("navegador do agente aberto", OK)
        self.carregar_sistema()

    def _navegador_erro(self, msg: str):
        self.set_status(f"navegador: {msg}", ERR)
        self.chat.add("system", "Navegador do agente: " + msg)

    # ------------------------- inicialização -------------------------- #
    def _boot(self):
        if not self._vivo or self._bootando:
            return
        self._bootando = True
        self.set_status("conectando ao núcleo…", GOLD)

        def aviso(msg):
            self._post(self.set_status, msg, GOLD)

        def trabalho():
            try:
                ok = garantir_nucleo(on_status=aviso)
            except Exception:
                ok = False
            self._post(self._boot_ok, ok)

        threading.Thread(target=trabalho, daemon=True).start()

    def _boot_ok(self, ok: bool):
        self._bootando = False
        if not self._vivo:
            return
        if not ok:
            self._online = False
            self.set_status("núcleo offline · F5 tenta de novo", ERR)
            self._texto_sistema([
                ("YVAKOR — núcleo local", "titulo"),
                ("", None),
                ("O núcleo não respondeu em 127.0.0.1:7777.", "valor"),
                ("O log está em data\\logs\\nucleo.log.", "dica"),
                ("Pressione F5 para tentar de novo.", "dica"),
            ])
            return
        self._online = True
        self.set_status("online", OK)
        self.carregar_sessoes()
        self.carregar_sistema()
        if self._nova_boot:
            self._nova_boot = False
            self._agendar(900, self.nova_conversa)
        self._cancelar(self._poll_job)
        self._poll_job = self._agendar(400, self.poll_tarefas)

    # --------------------- progresso e confirmação ------------------- #
    def _iniciar_progresso(self, sid):
        self._parar_progresso()
        self._prog_sid = sid

        def tick():
            if not self._vivo or self._prog_sid != sid:
                return
            if sid not in self._envios:
                return

            def trabalho():
                try:
                    p = api("/api/progress?session=" +
                            urllib.parse.quote(str(sid)), timeout=5)
                except Exception:
                    return
                self._post(self._progresso, p)

            threading.Thread(target=trabalho, daemon=True).start()
            self._prog_job = self._agendar(900, tick)

        tick()

    def _parar_progresso(self):
        self._cancelar(self._prog_job)
        self._prog_job = None
        self._prog_sid = None

    def _progresso(self, p):
        sid = self._prog_sid
        if not sid or not self._vivo:
            return
        passos = p.get("steps") or []
        if passos:
            self._ultimo_passo = self._passo_texto(passos[-1])[:110]
            if sid == self.sessao:
                self.chat.set_typing_texto(self._ultimo_passo)
        pend = p.get("pending")
        if not pend:
            self._pend_id = None
        elif pend.get("id") != self._pend_id:
            self._pend_id = pend.get("id")
            self._abrir_confirmacao(pend)

    def _abrir_confirmacao(self, pend: dict):
        if self._confirm_win is not None:
            return
        acao = pend.get("action") or "ação protegida"
        detalhe = pend.get("detail") or ""
        win = tk.Toplevel(self.root)
        win.title("Ação protegida")
        win.configure(bg=BG)
        win.transient(self.root)
        win.resizable(False, False)
        win.grab_set()
        _barra_titulo_escura(win)
        tk.Label(win, text="AÇÃO PROTEGIDA", bg=BG, fg=GOLD,
                 font=(UI_SEMI, 7)).pack(anchor="w", padx=20,
                                                     pady=(18, 4))
        tk.Label(win, text=acao, bg=BG, fg=FG, font=FONT_B, wraplength=420,
                 justify="left").pack(anchor="w", padx=20)
        if detalhe:
            tk.Label(win, text=detalhe, bg=PANEL2, fg=MUTED, font=FONT_XS,
                     wraplength=410, justify="left", anchor="w", padx=10,
                     pady=8).pack(fill="x", padx=20, pady=(10, 0))
        tk.Label(win, text=f"Sem resposta em {int(pend.get('timeout') or 90)} s "
                           "a ação é negada.",
                 bg=BG, fg=DIM, font=(UI, 7)).pack(anchor="w",
                                                          padx=20,
                                                          pady=(8, 0))
        botoes = tk.Frame(win, bg=BG)
        botoes.pack(fill="x", padx=20, pady=16)

        def responder(allow):
            self._responder_confirmacao(win, pend, allow)

        permitir = tk.Label(botoes, text="Permitir", bg=GOLD, fg=ON_GOLD,
                            font=(UI_SEMI, 9), padx=16, pady=6,
                            cursor="hand2")
        permitir.pack(side="right")
        permitir.bind("<Button-1>", lambda e: responder(True))
        self._hover(permitir, GOLD, GOLD_HOVER)
        negar = tk.Label(botoes, text="Negar", bg=PANEL2, fg=ERR,
                         font=FONT_XS, padx=14, pady=6, cursor="hand2")
        negar.pack(side="right", padx=(0, 6))
        negar.bind("<Button-1>", lambda e: responder(False))
        self._hover(negar, PANEL2, LINE, fg_normal=ERR, fg_hover=FG)
        win.bind("<Escape>", lambda e: responder(False))
        win.protocol("WM_DELETE_WINDOW", lambda: responder(False))
        self._confirm_win = win
        try:
            self.root.update_idletasks()
            largura = 470
            altura = 300 if detalhe else 250
            x = (self.root.winfo_rootx()
                 + (self.root.winfo_width() - largura) // 2)
            y = (self.root.winfo_rooty()
                 + (self.root.winfo_height() - altura) // 2)
            win.geometry(f"{largura}x{altura}+{x}+{y}")
        except Exception:
            win.geometry("470x300")
        # A conversa está PARADA esperando esta resposta: o popup precisa ser
        # visto. Sobe para a frente (mesmo com a janela principal atrás de
        # outros apps ou minimizada), pega o foco e avisa com um bipe.
        try:
            if self.root.state() == "iconic":
                self.root.deiconify()
            win.lift()
            win.attributes("-topmost", True)
            win.after(1500, lambda: win.attributes("-topmost", False))
            win.focus_force()
            self.root.bell()
        except Exception:
            pass

    def _responder_confirmacao(self, win, pend: dict, allow: bool):
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        self._confirm_win = None
        sid = pend.get("session") or self.sessao
        self.set_status("ação permitida" if allow else "ação negada",
                        OK if allow else MUTED)

        def trabalho():
            try:
                api("/api/confirm",
                    {"session": sid, "allow": bool(allow)}, timeout=15)
            except Exception as exc:
                self._post(self.set_status,
                           f"confirmação: {type(exc).__name__}: {exc}", ERR)

        threading.Thread(target=trabalho, daemon=True).start()

    def fechar(self):
        if not self._vivo:
            try:
                self.root.destroy()
            except Exception:
                pass
            return
        self._vivo = False
        for job in list(self._jobs):
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._jobs.clear()
        if self._confirm_win is not None:
            try:
                self._confirm_win.destroy()
            except Exception:
                pass
            self._confirm_win = None
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()



if __name__ == "__main__":
    App(nova="--nova" in sys.argv).run()
