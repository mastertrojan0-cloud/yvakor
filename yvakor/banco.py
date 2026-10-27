"""YVAKOR — guardião dos bancos de dados (robustez + anticrash).

O que cada banco SQLite do agente passa a ter, sem depender de ninguém lembrar:

  • verificação de integridade na partida (`quick_check`) e do FTS5;
  • AUTO-REPARO: banco corrompido vai para `data/quarentena/` e é restaurado do
    backup mais recente válido (ou salvo parcialmente por dump, se não houver);
  • BACKUP consistente (API de backup do SQLite) com rotação, em
    `data/backups/<banco>/`, só se há espaço em disco e se o último é antigo;
  • WAL sob controle: `wal_checkpoint(TRUNCATE)` periódico (os arquivos `-wal`
    chegavam a 4 MB para bancos de 12 KB porque nada os truncava);
  • compactação (VACUUM) quando há muito espaço livre, ligando auto_vacuum
    incremental para os próximos;
  • rotação dos logs/jsonl que cresciam sem limite e retenção de capturas.

Tudo é tolerante a falhas: nenhuma função aqui levanta para quem chama.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from yvakor import seguro

ROOT = Path(__file__).resolve().parent.parent

BACKUPS_MANTER = 5              # quantos backups por banco
BACKUP_INTERVALO_H = 6.0        # só gera novo se o último for mais velho que isso
LIVRE_MIN_MB = 300              # abaixo disso não faz backup nem VACUUM
COMPACTAR_LIVRE_PCT = 0.30      # >30% de páginas livres ...
COMPACTAR_LIVRE_MIN_MB = 2.0    # ... e pelo menos 2 MB recuperáveis

JSONL_ROTACAO = {               # arquivo -> (max MB, cópias)
    "auditoria.jsonl": (5, 3), "avaliacoes.jsonl": (5, 3),
    "notificacoes.jsonl": (3, 2), "rede_monitor.jsonl": (3, 2),
    "logs/falhas.jsonl": (3, 2), "logs/crash.log": (3, 2),
    "logs/supervisor.jsonl": (2, 2),
}
RETENCAO = {                    # pasta de capturas regeneráveis -> (dias, max MB)
    "rede_shots": (14, 300), "browser_shots": (14, 200),
}


def _log(raiz: Path, evento: dict) -> None:
    try:
        pasta = raiz / "data" / "logs"
        pasta.mkdir(parents=True, exist_ok=True)
        evento = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **evento}
        with (pasta / "banco.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Descoberta e verificação
# --------------------------------------------------------------------------- #
def descobrir(raiz: Path = ROOT) -> list[Path]:
    """Bancos do agente (ignora vazios, de teste e os dos perfis de navegador)."""
    dados = raiz / "data"
    achados = []
    for p in sorted(dados.glob("*.db")):
        if p.stat().st_size > 0 and not p.name.startswith("test"):
            achados.append(p)
    sem = dados / "semantic" / "facts.db"
    if sem.exists() and sem.stat().st_size > 0:
        achados.append(sem)
    return achados


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=3)


def verificar(path: Path) -> str:
    """'ok' ou a descrição do problema. Nunca levanta."""
    try:
        c = _ro(path)
        try:
            return str(c.execute("PRAGMA quick_check").fetchone()[0])
        finally:
            c.close()
    except Exception as exc:
        return f"erro: {exc}"


def _nome_backup(path: Path, raiz: Path) -> str:
    try:
        rel = path.relative_to(raiz / "data")
    except ValueError:
        rel = Path(path.name)
    return "_".join(rel.with_suffix("").parts)


def _pasta_backup(path: Path, raiz: Path) -> Path:
    return raiz / "data" / "backups" / _nome_backup(path, raiz)


def backups_de(path: Path, raiz: Path = ROOT) -> list[Path]:
    pasta = _pasta_backup(path, raiz)
    return sorted(pasta.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if pasta.is_dir() else []


# --------------------------------------------------------------------------- #
# Backup
# --------------------------------------------------------------------------- #
def espaco_livre_mb(raiz: Path = ROOT) -> float:
    try:
        return shutil.disk_usage(raiz).free / 1048576
    except OSError:
        return 1e9


def fazer_backup(path: Path, raiz: Path = ROOT, forcar: bool = False) -> dict:
    """Backup consistente (funciona com o banco em uso). Valida e rotaciona."""
    try:
        existentes = backups_de(path, raiz)
        if (not forcar and existentes and
                time.time() - existentes[0].stat().st_mtime < BACKUP_INTERVALO_H * 3600):
            return {"feito": False, "motivo": "recente"}
        tamanho_mb = path.stat().st_size / 1048576
        if espaco_livre_mb(raiz) < max(LIVRE_MIN_MB, tamanho_mb * 3):
            return {"feito": False, "motivo": "pouco espaço em disco"}
        pasta = _pasta_backup(path, raiz)
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"{path.stem}-{time.strftime('%Y%m%d-%H%M%S')}.db"
        parcial = destino.with_suffix(".partial")
        origem = _ro(path)
        try:
            alvo = sqlite3.connect(str(parcial))
            try:
                origem.backup(alvo)
            finally:
                alvo.close()
        finally:
            origem.close()
        if verificar(parcial) != "ok":
            parcial.unlink(missing_ok=True)
            return {"feito": False, "motivo": "backup não passou na verificação"}
        os.replace(parcial, destino)
        for antigo in backups_de(path, raiz)[BACKUPS_MANTER:]:
            antigo.unlink(missing_ok=True)
        return {"feito": True, "arquivo": str(destino), "mb": round(tamanho_mb, 2)}
    except Exception as exc:
        return {"feito": False, "motivo": f"erro: {exc}"}


# --------------------------------------------------------------------------- #
# Auto-reparo
# --------------------------------------------------------------------------- #
def _salvar_por_dump(corrompido: Path, destino: Path) -> int:
    """Copia o que ainda for legível de um banco danificado. Devolve nº de linhas."""
    linhas = 0
    novo = sqlite3.connect(str(destino))
    try:
        try:
            velho = sqlite3.connect(str(corrompido))
            velho.text_factory = bytes
            tabelas = velho.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL").fetchall()
        except sqlite3.DatabaseError:
            return 0
        for nome, sql in tabelas:
            nome = nome.decode("utf-8", "replace")
            if "fts" in nome.lower() and "VIRTUAL" in sql.decode("utf-8", "replace").upper():
                continue                # FTS é reconstruído pelo código a partir da tabela base
            try:
                novo.execute(sql.decode("utf-8", "replace"))
            except sqlite3.DatabaseError:
                continue
            try:
                cur = velho.execute(f'SELECT * FROM "{nome}"')
                colunas = len(cur.description)
                marcas = ",".join("?" * colunas)
                while True:
                    try:
                        lote = cur.fetchmany(500)
                    except sqlite3.DatabaseError:
                        break           # parou no trecho danificado: fica com o que leu
                    if not lote:
                        break
                    novo.executemany(f'INSERT OR IGNORE INTO "{nome}" VALUES ({marcas})', lote)
                    linhas += len(lote)
            except sqlite3.DatabaseError:
                continue
        novo.commit()
        velho.close()
    finally:
        novo.close()
    return linhas


def reparar(path: Path, raiz: Path = ROOT) -> dict:
    """Se o banco estiver corrompido: quarentena + restauração. Chamar ANTES de abri-lo."""
    estado = verificar(path)
    if estado == "ok":
        return {"banco": path.name, "estado": "ok"}
    carimbo = time.strftime("%Y%m%d-%H%M%S")
    quarentena = raiz / "data" / "quarentena" / f"{path.stem}-{carimbo}"
    resultado = {"banco": path.name, "estado": "corrompido", "detalhe": estado[:200],
                 "quarentena": str(quarentena)}
    try:
        quarentena.mkdir(parents=True, exist_ok=True)
        for sufixo in ("", "-wal", "-shm"):
            arq = path.with_name(path.name + sufixo)
            if arq.exists():
                shutil.move(str(arq), str(quarentena / arq.name))
    except OSError as exc:
        resultado["erro"] = f"não consegui isolar o banco: {exc}"
        return resultado
    for bkp in backups_de(path, raiz):
        if verificar(bkp) == "ok":
            shutil.copy2(bkp, path)
            resultado.update(estado="restaurado", de=str(bkp))
            _log(raiz, resultado)
            return resultado
    salvas = _salvar_por_dump(quarentena / path.name, path)
    resultado.update(estado="recuperado_parcial" if salvas else "recriado_vazio",
                     linhas_salvas=salvas)
    _log(raiz, resultado)
    return resultado


# --------------------------------------------------------------------------- #
# FTS, compactação e WAL
# --------------------------------------------------------------------------- #
def verificar_fts(path: Path, raiz: Path = ROOT) -> dict:
    """Confere os índices FTS5; reconstrói os inconsistentes. Exige acesso de escrita."""
    reconstruidos, ok = [], 0
    try:
        c = sqlite3.connect(str(path), timeout=5)
        try:
            tabelas = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND sql LIKE '%fts5%'")]
            for t in tabelas:
                try:
                    try:   # rank=1 também confere o índice contra a tabela base (conteúdo externo)
                        c.execute(f'INSERT INTO "{t}"("{t}", rank) VALUES(\'integrity-check\', 1)')
                    except sqlite3.OperationalError:
                        c.execute(f'INSERT INTO "{t}"("{t}") VALUES(\'integrity-check\')')
                    ok += 1
                except sqlite3.DatabaseError:
                    try:
                        c.execute(f'INSERT INTO "{t}"("{t}") VALUES(\'rebuild\')')
                        c.commit()
                        reconstruidos.append(t)
                    except sqlite3.DatabaseError:
                        pass
        finally:
            c.close()
    except sqlite3.DatabaseError:
        pass
    if reconstruidos:
        _log(raiz, {"banco": path.name, "fts_reconstruido": reconstruidos})
    return {"fts_ok": ok, "fts_reconstruidos": reconstruidos}


def compactar(path: Path, raiz: Path = ROOT) -> dict:
    """VACUUM quando há muito espaço livre (liga auto_vacuum incremental).
    Só na partida: precisa de acesso exclusivo."""
    try:
        c = sqlite3.connect(str(path), timeout=2)
        try:
            paginas = c.execute("PRAGMA page_count").fetchone()[0]
            livres = c.execute("PRAGMA freelist_count").fetchone()[0]
            tam = c.execute("PRAGMA page_size").fetchone()[0]
            av = c.execute("PRAGMA auto_vacuum").fetchone()[0]
            recuperavel_mb = livres * tam / 1048576
            if not paginas or (livres / paginas < COMPACTAR_LIVRE_PCT
                               or recuperavel_mb < COMPACTAR_LIVRE_MIN_MB):
                return {"compactado": False, "auto_vacuum": av}
            if espaco_livre_mb(raiz) < max(LIVRE_MIN_MB, paginas * tam / 1048576 * 2):
                return {"compactado": False, "motivo": "pouco espaço em disco"}
            c.execute("PRAGMA auto_vacuum=INCREMENTAL")
            c.execute("VACUUM")
            return {"compactado": True, "recuperado_mb": round(recuperavel_mb, 2)}
        finally:
            c.close()
    except sqlite3.DatabaseError as exc:
        return {"compactado": False, "motivo": str(exc)[:120]}


def checkpoint(path: Path) -> dict:
    """Esvazia o -wal para dentro do banco. Se há leitores, faz o que dá (PASSIVE)."""
    try:
        c = sqlite3.connect(str(path), timeout=2)
        try:
            c.execute("PRAGMA busy_timeout=2000")
            ocupado, _, _ = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if ocupado:
                c.execute("PRAGMA wal_checkpoint(PASSIVE)")
            c.execute("PRAGMA optimize")
            wal = path.with_name(path.name + "-wal")
            return {"truncado": not ocupado,
                    "wal_kb": (wal.stat().st_size // 1024) if wal.exists() else 0}
        finally:
            c.close()
    except sqlite3.DatabaseError as exc:
        return {"truncado": False, "erro": str(exc)[:120]}


# --------------------------------------------------------------------------- #
# Arquivos que crescem (jsonl/logs) e capturas
# --------------------------------------------------------------------------- #
def rotacionar_logs(raiz: Path = ROOT) -> list[str]:
    feitos = []
    for rel, (mb, copias) in JSONL_ROTACAO.items():
        if seguro.rotacionar(raiz / "data" / rel, int(mb * 1048576), copias):
            feitos.append(rel)
    return feitos


def aplicar_retencao(raiz: Path = ROOT) -> dict:
    """Apaga capturas antigas / acima do teto (só pastas regeneráveis)."""
    removidos = {}
    for nome, (dias, max_mb) in RETENCAO.items():
        pasta = raiz / "data" / nome
        if not pasta.is_dir():
            continue
        arqs = []
        for p in pasta.rglob("*"):
            try:
                if p.is_file():
                    st = p.stat()
                    arqs.append((st.st_mtime, st.st_size, p))
            except OSError:
                continue
        arqs.sort()                                  # mais antigos primeiro
        total = sum(t for _, t, _ in arqs)
        corte = time.time() - dias * 86400
        n = 0
        for mtime, tam, p in arqs:
            if mtime < corte or total > max_mb * 1048576:
                try:
                    p.unlink()
                    total -= tam
                    n += 1
                except OSError:
                    pass
        if n:
            removidos[nome] = n
    return removidos


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #
_ULTIMO: dict = {}


def guardiao_inicial(raiz: Path = ROOT) -> dict:
    """Na partida, ANTES de o agente abrir os bancos: repara, confere FTS,
    compacta, trunca o WAL e garante um backup recente."""
    relatorio = {"inicio": time.strftime("%Y-%m-%dT%H:%M:%S"), "bancos": {}}
    for p in descobrir(raiz):
        item: dict = {}
        try:
            item["reparo"] = reparar(p, raiz)
            if item["reparo"]["estado"] in ("ok", "restaurado", "recuperado_parcial"):
                item.update(verificar_fts(p, raiz))
                item["compactacao"] = compactar(p, raiz)
                item["wal"] = checkpoint(p)
                item["backup"] = fazer_backup(p, raiz)
        except Exception as exc:
            item["erro"] = str(exc)[:200]
        relatorio["bancos"][p.name if p.parent.name == "data" else f"{p.parent.name}/{p.name}"] = item
    relatorio["logs_rotacionados"] = rotacionar_logs(raiz)
    relatorio["retencao"] = aplicar_retencao(raiz)
    _ULTIMO.clear()
    _ULTIMO.update(relatorio)
    problemas = [n for n, i in relatorio["bancos"].items()
                 if i.get("reparo", {}).get("estado") not in (None, "ok") or i.get("erro")]
    if problemas:
        _log(raiz, {"evento": "partida", "problemas": problemas})
    return relatorio


def ciclo_periodico(raiz: Path = ROOT) -> dict:
    """Rotina em segundo plano (banco em uso): WAL, backup, logs, capturas."""
    r = {"quando": time.strftime("%Y-%m-%dT%H:%M:%S"), "bancos": {}}
    for p in descobrir(raiz):
        r["bancos"][p.name] = {"wal": checkpoint(p), "backup": fazer_backup(p, raiz),
                               "saude": verificar(p)}
    r["logs_rotacionados"] = rotacionar_logs(raiz)
    r["retencao"] = aplicar_retencao(raiz)
    r["livre_mb"] = round(espaco_livre_mb(raiz))
    _ULTIMO.clear()
    _ULTIMO.update(r)
    return r


def encerrar(raiz: Path = ROOT) -> None:
    """Ao desligar: leva o WAL para dentro dos bancos (próxima partida limpa)."""
    for p in descobrir(raiz):
        checkpoint(p)


def estado() -> dict:
    return dict(_ULTIMO)


class Guardiao(threading.Thread):
    """Thread daemon que roda `ciclo_periodico` a cada `horas` (1ª após 5 min)."""

    def __init__(self, raiz: Path = ROOT, horas: float = 1.0, primeira_s: float = 300):
        super().__init__(daemon=True, name="yvakor-guardiao-bancos")
        self.raiz, self.horas, self.primeira_s = raiz, horas, primeira_s
        self._parar = threading.Event()

    def run(self) -> None:
        if self._parar.wait(self.primeira_s):
            return
        while not self._parar.is_set():
            try:
                ciclo_periodico(self.raiz)
            except Exception as exc:
                _log(self.raiz, {"evento": "ciclo_falhou", "erro": str(exc)[:200]})
            self._parar.wait(self.horas * 3600)

    def parar(self) -> None:
        self._parar.set()
