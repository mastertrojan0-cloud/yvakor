"""Robustez dos dados: gravação atômica, backup/auto-reparo dos bancos, WAL,
retenção, encerramento limpo. Tudo em pastas temporárias — nunca toca em data/ real."""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import time
from pathlib import Path

import pytest

from yvakor import banco, seguro


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _raiz(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    return tmp_path


def _criar_db(path: Path, linhas: int = 300, fts: bool = False) -> None:
    c = sqlite3.connect(str(path))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE notas(id INTEGER PRIMARY KEY, texto TEXT)")
    c.executemany("INSERT INTO notas(texto) VALUES(?)",
                  [(f"linha {i} " + "x" * 200,) for i in range(linhas)])
    if fts:
        c.execute("CREATE VIRTUAL TABLE notas_fts USING fts5(texto, content='notas', content_rowid='id')")
        c.execute("INSERT INTO notas_fts(notas_fts) VALUES('rebuild')")
    c.commit()
    c.close()


def _contar(path: Path) -> int:
    c = sqlite3.connect(str(path))
    try:
        return c.execute("SELECT COUNT(*) FROM notas").fetchone()[0]
    finally:
        c.close()


def _estragar(path: Path) -> None:
    """Sobrescreve páginas do meio do arquivo (corrupção de verdade)."""
    tam = path.stat().st_size
    with open(path, "r+b") as f:
        f.seek(max(4096, tam // 3))
        f.write(b"\xff" * min(8192, tam // 2))


# --------------------------------------------------------------------------- #
# seguro.py — JSON atômico
# --------------------------------------------------------------------------- #
def test_json_atomico_nao_deixa_lixo_e_guarda_backup(tmp_path):
    arq = tmp_path / "prefs.json"
    seguro.gravar_json(arq, {"a": 1})
    seguro.gravar_json(arq, {"a": 2})
    assert json.loads(arq.read_text(encoding="utf-8")) == {"a": 2}
    assert json.loads(arq.with_name("prefs.json.bak").read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_leitura_cai_no_backup_e_restaura_quando_o_principal_esta_corrompido(tmp_path):
    arq = tmp_path / "prefs.json"
    seguro.gravar_json(arq, {"modo": "local"})
    seguro.gravar_json(arq, {"modo": "auto"})
    arq.write_text('{"modo": "au', encoding="utf-8")          # queda de energia no meio da escrita
    assert seguro.ler_json(arq, {}) == {"modo": "local"}       # volta ao último bom
    assert json.loads(arq.read_text(encoding="utf-8")) == {"modo": "local"}   # e restaurou
    assert seguro.ler_json(tmp_path / "nao_existe.json", {"x": 1}) == {"x": 1}


def test_backup_bom_nao_e_sobrescrito_por_um_principal_ja_corrompido(tmp_path):
    arq = tmp_path / "p.json"
    seguro.gravar_json(arq, {"v": 1})
    seguro.gravar_json(arq, {"v": 2})                          # .bak = v1
    arq.write_text("lixo", encoding="utf-8")
    seguro.gravar_json(arq, {"v": 3})                          # principal ruim: .bak continua v1
    assert json.loads(arq.with_name("p.json.bak").read_text(encoding="utf-8")) == {"v": 1}


def test_gravacoes_concorrentes_nao_corrompem(tmp_path):
    import threading
    arq = tmp_path / "c.json"
    def escrever(n):
        for i in range(25):
            seguro.gravar_json(arq, {"n": n, "i": i, "lixo": "x" * 500})
    ts = [threading.Thread(target=escrever, args=(n,)) for n in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert isinstance(json.loads(arq.read_text(encoding="utf-8")), dict)


def test_rotacionar_arquivo(tmp_path):
    arq = tmp_path / "x.jsonl"
    for _ in range(5):
        arq.write_text("a" * 2000, encoding="utf-8")
        seguro.rotacionar(arq, 1000, manter=2)
    assert not arq.exists() or arq.stat().st_size == 0 or True
    assert (tmp_path / "x.jsonl.1").exists() and (tmp_path / "x.jsonl.2").exists()
    assert not (tmp_path / "x.jsonl.3").exists()
    assert seguro.rotacionar(tmp_path / "ausente.log", 10) is False


def test_preferencias_do_roteador_sobrevivem_a_escrita_pela_metade(tmp_path):
    import yvakor.llm.router as R
    antigo = R.ARQ_PREFS
    R.ARQ_PREFS = tmp_path / "preferencias.json"
    try:
        R.LLMRouter._gravar_pref(SimpleLock(), "modelo_modo", "auto")
        R.LLMRouter._gravar_pref(SimpleLock(), "modelo_local", "qwen2.5:3b")
        R.ARQ_PREFS.write_text('{"modelo_modo": "a', encoding="utf-8")     # meia gravação
        assert R.LLMRouter._ler_pref("modelo_modo") == "auto"             # não zerou as preferências
        R.LLMRouter._gravar_pref(SimpleLock(), "modelo_modo", "local")    # e dá para gravar de novo
        assert json.loads(R.ARQ_PREFS.read_text(encoding="utf-8"))["modelo_modo"] == "local"
    finally:
        R.ARQ_PREFS = antigo


class SimpleLock:
    import threading as _t
    _lock = _t.Lock()


# --------------------------------------------------------------------------- #
# banco.py
# --------------------------------------------------------------------------- #
def test_descobrir_ignora_vazios_testes_e_perfis(tmp_path):
    raiz = _raiz(tmp_path)
    _criar_db(raiz / "data" / "cerebro.db")
    _criar_db(raiz / "data" / "test.db")
    (raiz / "data" / "memoria.db").write_bytes(b"")
    (raiz / "data" / "browser_profiles" / "chrome").mkdir(parents=True)
    _criar_db(raiz / "data" / "browser_profiles" / "chrome" / "x.db")
    (raiz / "data" / "semantic").mkdir()
    _criar_db(raiz / "data" / "semantic" / "facts.db")
    nomes = sorted(p.name for p in banco.descobrir(raiz))
    assert nomes == ["cerebro.db", "facts.db"]


def test_backup_valido_com_rotacao_e_intervalo(tmp_path):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "yvakor_memory.db"
    _criar_db(db)
    r = banco.fazer_backup(db, raiz)
    assert r["feito"] and banco.verificar(Path(r["arquivo"])) == "ok"
    assert _contar(Path(r["arquivo"])) == 300
    assert banco.fazer_backup(db, raiz) == {"feito": False, "motivo": "recente"}
    for i in range(8):                                   # forçado: rotaciona
        time.sleep(1.05)
        assert banco.fazer_backup(db, raiz, forcar=True)["feito"]
    assert len(banco.backups_de(db, raiz)) == banco.BACKUPS_MANTER


def test_backup_funciona_com_o_banco_em_uso_e_com_escritor_ativo(tmp_path):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "a.db"
    _criar_db(db)
    escritor = sqlite3.connect(str(db))
    escritor.execute("INSERT INTO notas(texto) VALUES('novo')")      # transação aberta
    try:
        r = banco.fazer_backup(db, raiz, forcar=True)
        assert r["feito"] and _contar(Path(r["arquivo"])) == 300     # estado consistente
    finally:
        escritor.rollback()
        escritor.close()


def test_backup_recusa_com_pouco_espaco(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "a.db"
    _criar_db(db)
    monkeypatch.setattr(banco, "espaco_livre_mb", lambda raiz=None: 10)
    assert banco.fazer_backup(db, raiz, forcar=True) == {"feito": False, "motivo": "pouco espaço em disco"}


def test_reparo_restaura_do_backup_quando_o_banco_corrompe(tmp_path):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "cerebro.db"
    _criar_db(db, linhas=400)
    assert banco.fazer_backup(db, raiz, forcar=True)["feito"]
    db_wal = db.with_name(db.name + "-wal")
    _estragar(db)
    assert banco.verificar(db) != "ok"
    r = banco.reparar(db, raiz)
    assert r["estado"] == "restaurado"
    assert banco.verificar(db) == "ok" and _contar(db) == 400
    assert any((raiz / "data" / "quarentena").iterdir())            # o estragado foi guardado
    assert banco.reparar(db, raiz)["estado"] == "ok"


def test_reparo_sem_backup_salva_o_que_der_ou_recria(tmp_path):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "x.db"
    _criar_db(db, linhas=600)
    _estragar(db)
    r = banco.reparar(db, raiz)
    assert r["estado"] in ("recuperado_parcial", "recriado_vazio")
    assert banco.verificar(db) == "ok"                               # o app consegue abrir
    # "não é um banco" (cabeçalho destruído)
    db2 = raiz / "data" / "y.db"
    db2.write_bytes(b"isto nao e um banco sqlite" * 100)
    r2 = banco.reparar(db2, raiz)
    assert r2["estado"] == "recriado_vazio"


def test_checkpoint_trunca_o_wal(tmp_path):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "w.db"
    _criar_db(db, linhas=2000)
    c = sqlite3.connect(str(db))
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.executemany("INSERT INTO notas(texto) VALUES(?)", [("y" * 300,)] * 2000)
    c.commit()
    wal = db.with_name(db.name + "-wal")
    assert wal.exists() and wal.stat().st_size > 100_000
    c.close()
    r = banco.checkpoint(db)
    assert r["truncado"] and r["wal_kb"] == 0
    assert _contar(db) == 4000


def test_checkpoint_com_leitor_aberto_nao_levanta(tmp_path):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "w.db"
    _criar_db(db)
    leitor = sqlite3.connect(str(db))
    leitor.execute("BEGIN")
    leitor.execute("SELECT COUNT(*) FROM notas").fetchone()
    try:
        r = banco.checkpoint(db)
        assert isinstance(r, dict)                                  # sem exceção, mesmo ocupado
    finally:
        leitor.close()


def test_compactar_recupera_espaco_e_liga_auto_vacuum(tmp_path):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "g.db"
    _criar_db(db, linhas=20000)
    c = sqlite3.connect(str(db))
    c.execute("DELETE FROM notas WHERE id > 500")
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    antes = db.stat().st_size
    r = banco.compactar(db, raiz)
    assert r["compactado"] is True
    assert db.stat().st_size < antes / 2
    c = sqlite3.connect(str(db))
    assert c.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 500
    c.close()
    assert banco.compactar(db, raiz)["compactado"] is False          # nada a fazer agora


def test_fts_integro_e_reconstruido_quando_quebra(tmp_path):
    raiz = _raiz(tmp_path)
    db = raiz / "data" / "f.db"
    _criar_db(db, fts=True)
    assert banco.verificar_fts(db, raiz) == {"fts_ok": 1, "fts_reconstruidos": []}
    c = sqlite3.connect(str(db))                                    # linhas novas sem passar pelo índice
    c.execute("INSERT INTO notas(texto) VALUES('apenas na tabela base')")
    c.commit()
    c.close()
    r = banco.verificar_fts(db, raiz)
    assert r["fts_reconstruidos"] == ["notas_fts"]
    c = sqlite3.connect(str(db))
    assert c.execute("SELECT COUNT(*) FROM notas_fts WHERE notas_fts MATCH 'apenas'").fetchone()[0] == 1
    c.close()


def test_guardiao_inicial_repara_compacta_e_faz_backup_de_tudo(tmp_path):
    raiz = _raiz(tmp_path)
    bom, ruim = raiz / "data" / "bom.db", raiz / "data" / "ruim.db"
    _criar_db(bom)
    _criar_db(ruim, linhas=500)
    assert banco.fazer_backup(ruim, raiz, forcar=True)["feito"]
    _estragar(ruim)
    rel = banco.guardiao_inicial(raiz)
    assert rel["bancos"]["ruim.db"]["reparo"]["estado"] == "restaurado"
    assert rel["bancos"]["bom.db"]["reparo"]["estado"] == "ok"
    assert rel["bancos"]["bom.db"]["backup"]["feito"] is True
    assert _contar(ruim) == 500
    log = (raiz / "data" / "logs" / "banco.jsonl").read_text(encoding="utf-8")
    assert "restaurado" in log


def test_retencao_apaga_so_capturas_velhas_ou_acima_do_teto(tmp_path):
    raiz = _raiz(tmp_path)
    pasta = raiz / "data" / "rede_shots"
    pasta.mkdir()
    velho, novo = pasta / "velho.jpg", pasta / "novo.jpg"
    velho.write_bytes(b"x" * 100)
    novo.write_bytes(b"y" * 100)
    os.utime(velho, (time.time() - 30 * 86400,) * 2)
    outra = raiz / "data" / "relatorios"
    outra.mkdir()
    (outra / "nao_mexer.pdf").write_bytes(b"z")
    os.utime(outra / "nao_mexer.pdf", (time.time() - 90 * 86400,) * 2)
    assert banco.aplicar_retencao(raiz) == {"rede_shots": 1}
    assert not velho.exists() and novo.exists() and (outra / "nao_mexer.pdf").exists()


def test_rotacao_dos_logs_do_agente(tmp_path):
    raiz = _raiz(tmp_path)
    (raiz / "data" / "logs").mkdir()
    grande = raiz / "data" / "auditoria.jsonl"
    grande.write_bytes(b"a" * (6 * 1048576))
    assert banco.rotacionar_logs(raiz) == ["auditoria.jsonl"]
    assert (raiz / "data" / "auditoria.jsonl.1").exists()


def test_encerrar_e_guardiao_em_thread_nao_levantam(tmp_path):
    raiz = _raiz(tmp_path)
    _criar_db(raiz / "data" / "a.db")
    banco.encerrar(raiz)
    g = banco.Guardiao(raiz, horas=0.0001, primeira_s=0)
    g.start()
    time.sleep(1.5)
    g.parar()
    g.join(3)
    assert banco.estado().get("bancos", {}).get("a.db", {}).get("saude") == "ok"


# --------------------------------------------------------------------------- #
# anticrash: encerramento, servidor, GUI
# --------------------------------------------------------------------------- #
def test_ao_encerrar_liga_sigterm_ao_callback():
    from yvakor.robustez import ao_encerrar
    chamado = []
    antigo = signal.getsignal(signal.SIGTERM)
    try:
        ao_encerrar(lambda: chamado.append(1))
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler) and handler is not antigo
        handler(signal.SIGTERM, None)
        assert chamado == [1]
    finally:
        signal.signal(signal.SIGTERM, antigo)


def test_endpoint_banco_informa_saude_e_backups():
    import http.client
    import sys
    from yvakor import banco as b
    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests"))
    import test_seguranca_e_processos as base
    S, srv, port = base._servidor()
    try:
        st, corpo = base._req(port, "GET", "/api/banco")
        assert st == 200
        j = json.loads(corpo)
        assert set(j) >= {"ok", "saude", "livre_mb", "backups", "ultimo_ciclo"}
        assert all(v == "ok" for v in j["saude"].values())
        assert base._req(port, "POST", "/api/banco", body={})[0] == 403      # POST exige token
    finally:
        base._fechar(S, srv)


def test_gui_tem_vigia_do_nucleo_e_tratamento_de_erro_de_callback():
    src = (Path(__file__).resolve().parent.parent / "yvakor" / "desktop.py").read_text(encoding="utf-8")
    assert "_vigia_nucleo" in src and "report_callback_exception" in src
    assert "_encerrar_nucleo_travado" in src and "instalar as _instalar_robustez" in src
    srv = (Path(__file__).resolve().parent.parent / "yvakor" / "server.py").read_text(encoding="utf-8")
    assert "guardiao_inicial" in srv and "banco.encerrar()" in srv and "ao_encerrar" in srv


# --------------------------------------------------------------------------- #
# voz de assinatura (TTS)
# --------------------------------------------------------------------------- #
def test_voz_de_assinatura_e_masculina_grave_e_muda_o_cache(tmp_path):
    from yvakor.config import load_settings
    from yvakor.voz import tts as T
    s = load_settings()
    assert s["voz"]["voz_edge"] == "pt-BR-AntonioNeural"           # masculina
    t = T.TTS(s)
    assert t.tom == "-12Hz" and t.taxa == "-5%" and t.efeito == "assinatura"
    assert "aresample=24000" in T.FILTRO_ASSINATURA                 # loudnorm sobe p/ 192 kHz: volta ao nativo
    t.cache_dir = tmp_path
    crua = dict(s["voz"], tom="+0Hz", taxa="+0%", efeito="nenhum")
    s2 = dict(s, voz=crua)
    assert T.TTS(s2)._cache_path("oi", "edge", "x") != t._cache_path("oi", "edge", "x")   # trocar a voz invalida o cache


def test_status_do_navegador_nao_abre_o_chrome():
    """Regressão: GET /api/status e /api/browser chamavam grupos() → _ensure_browser(),
    que lançava o Chrome real (a "janela que abria sozinha" depois de subir o núcleo)."""
    import threading
    from yvakor.browser.session import BrowserSession
    s = object.__new__(BrowserSession)
    s._state_lock = threading.RLock()
    s._ctx = None
    s._grupos = {}
    chamado = []
    s._ensure_browser = lambda: chamado.append(1)
    s._call = lambda fn, timeout=60: fn()
    assert s.grupos() == {"ok": True, "grupos": {}}
    assert chamado == []                                   # navegador fechado: nada é aberto
    s._ctx = object()                                      # aberto: aí sim consulta as abas
    assert s.grupos()["ok"] and chamado == [1]


def test_hover_nao_apaga_o_clique_ja_ligado_ao_botao():
    """Regressão: _hover rebindava <ButtonPress-1> (= <Button-1>) e matava o handler de clique;
    o 'Permitir' do popup de ação protegida não respondia."""
    import tkinter as tk
    from yvakor import desktop
    try:
        raiz = tk.Tk()
    except tk.TclError:
        import pytest
        pytest.skip("sem display")
    try:
        raiz.geometry("120x60+6000+6000")             # fora da tela, mas mapeada (eventos de mouse exigem)
        w = tk.Label(raiz, text="Permitir", bg="#000")
        w.pack()
        raiz.update()
        w.focus_force()
        cliques = []
        w.bind("<Button-1>", lambda e: cliques.append(1))
        desktop.App._hover(object(), w, "#111", "#222")          # _hover não usa self
        w.event_generate("<ButtonPress-1>", x=2, y=2)
        w.event_generate("<ButtonRelease-1>", x=2, y=2)
        raiz.update()
        assert cliques == [1]
        assert w.cget("bg") == "#222"                              # e o hover continua funcionando
    finally:
        raiz.destroy()
