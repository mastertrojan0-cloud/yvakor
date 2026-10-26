"""
YVAKOR — Registro de dispositivos da rede (memória do ambiente)

Guarda o que já foi descoberto em data/rede.db (SQLite) para o agente não
redescobrir tudo a cada tarefa e para o usuário poder nomear os aparelhos.

Credenciais por dispositivo (usuário/senha de câmera ONVIF, token de TV…)
ficam em data/rede.json — fora do git, nunca no settings.yaml.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class RegistroRede:
    def __init__(self, db_path: Path | None = None,
                 cred_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else (ROOT / "data" / "rede.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cred_path = Path(cred_path) if cred_path else (ROOT / "data" / "rede.json")
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        self._migrate()
        self._creds: dict[str, dict] = self._load_creds()

    def _migrate(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                chave TEXT PRIMARY KEY,
                ip TEXT, mac TEXT, nome TEXT, tipo TEXT,
                fabricante TEXT, modelo TEXT,
                servicos TEXT DEFAULT '[]',
                portas TEXT DEFAULT '[]',
                primeira_vez TEXT, ultima_vez TEXT,
                notas TEXT, visivel INTEGER DEFAULT 1,
                grupo TEXT DEFAULT '', favorito INTEGER DEFAULT 0,
                online INTEGER DEFAULT 1, ultimo_teste TEXT DEFAULT '',
                manual INTEGER DEFAULT 0
            )""")
        colunas = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(devices)").fetchall()}
        for nome, tipo in (("grupo", "TEXT DEFAULT ''"),
                           ("favorito", "INTEGER DEFAULT 0"),
                           ("online", "INTEGER DEFAULT 1"),
                           ("ultimo_teste", "TEXT DEFAULT ''"),
                           ("manual", "INTEGER DEFAULT 0")):
            if nome not in colunas:
                self.conn.execute(f"ALTER TABLE devices ADD COLUMN {nome} {tipo}")
        self.conn.commit()

    # ------------------------------------------------------------------ #
    # Credenciais (data/rede.json)
    # ------------------------------------------------------------------ #
    def _load_creds(self) -> dict:
        if self.cred_path.exists():
            try:
                return json.loads(self.cred_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_creds(self) -> None:
        self.cred_path.parent.mkdir(parents=True, exist_ok=True)
        self.cred_path.write_text(
            json.dumps(self._creds, ensure_ascii=False, indent=2), encoding="utf-8")

    def credenciais(self, chave: str) -> dict:
        """Credenciais por IP, MAC, chave de registro ou nome."""
        for k in (chave, str(chave).lower()):
            if k in self._creds:
                return dict(self._creds[k])
        dev = self.obter(chave)
        if dev:
            for k in (dev.get("ip"), dev.get("mac"), dev.get("chave")):
                if k and k in self._creds:
                    return dict(self._creds[k])
        return {}

    def salvar_credenciais(self, chave: str, **campos) -> dict:
        atual = dict(self._creds.get(chave) or {})
        atual.update({k: v for k, v in campos.items() if v is not None})
        self._creds[chave] = atual
        self._save_creds()
        return atual

    # ------------------------------------------------------------------ #
    # Dispositivos
    # ------------------------------------------------------------------ #
    @staticmethod
    def _chave(dev: dict) -> str:
        mac = (dev.get("mac") or "").strip().lower()
        if mac:
            return mac
        return str(dev.get("ip") or "").strip()

    def upsert(self, dev: dict) -> dict:
        """Insere/atualiza um dispositivo; preserva nome/notas já dados."""
        chave = self._chave(dev)
        if not chave:
            raise ValueError("dispositivo sem ip/mac")
        if not dev.get("mac") and dev.get("ip"):
            existente = self.obter(dev["ip"])
            if existente:
                chave = existente["chave"]
        atual = self.obter(chave) or {}
        if not atual and dev.get("ip"):
            atual = self.obter(dev["ip"]) or {}
            if atual:
                chave = atual["chave"]
        nome = dev.get("nome") or atual.get("nome") or ""
        notas = dev.get("notas") or atual.get("notas") or ""
        primeiro = atual.get("primeira_vez") or _agora()
        servicos = json.dumps(dev.get("servicos") or atual.get("servicos") or [],
                              ensure_ascii=False)
        portas = json.dumps(dev.get("portas") or atual.get("portas") or [],
                            ensure_ascii=False)
        with self._lock:
            self.conn.execute("""
                INSERT INTO devices (chave, ip, mac, nome, tipo, fabricante,
                    modelo, servicos, portas, primeira_vez, ultima_vez, notas,
                    visivel)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(chave) DO UPDATE SET
                    ip=excluded.ip, mac=COALESCE(excluded.mac, devices.mac),
                    nome=COALESCE(NULLIF(excluded.nome,''), devices.nome),
                    tipo=excluded.tipo,
                    fabricante=COALESCE(excluded.fabricante, devices.fabricante),
                    modelo=COALESCE(excluded.modelo, devices.modelo),
                    servicos=excluded.servicos, portas=excluded.portas,
                    ultima_vez=excluded.ultima_vez,
                    visivel=excluded.visivel
            """, (chave, dev.get("ip"), dev.get("mac"), nome,
                  dev.get("tipo") or atual.get("tipo") or "desconhecido",
                  dev.get("fabricante") or atual.get("fabricante") or "",
                  dev.get("modelo") or atual.get("modelo") or "",
                  servicos, portas, primeiro, _agora(), notas,
                  1 if dev.get("visivel", True) else 0))
            self.conn.execute(
                "UPDATE devices SET online=1, ultima_vez=? WHERE chave=?",
                (_agora(), chave))
            self.conn.commit()
        return self.obter(chave) or {}

    def obter(self, alvo: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT chave, ip, mac, nome, tipo, fabricante, modelo, servicos, "
                "portas, primeira_vez, ultima_vez, notas, visivel, grupo, "
                "favorito, online, ultimo_teste, manual FROM devices "
                "WHERE chave=? OR ip=? OR lower(nome)=lower(?) "
                "ORDER BY ultima_vez DESC LIMIT 1",
                (alvo, alvo, alvo)).fetchone()
        return self._row(row) if row else None

    def listar(self, tipo: str | None = None,
               somente_visiveis: bool = True) -> list[dict]:
        sql = ("SELECT chave, ip, mac, nome, tipo, fabricante, modelo, servicos, "
               "portas, primeira_vez, ultima_vez, notas, visivel, grupo, "
               "favorito, online, ultimo_teste, manual FROM devices")
        cond, params = [], []
        if tipo:
            cond.append("tipo=?")
            params.append(tipo)
        if somente_visiveis:
            cond.append("visivel=1")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY tipo, ip"
        with self._lock:
            rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [self._row(r) for r in rows]

    def remover(self, alvo: str) -> bool:
        dev = self.obter(alvo)
        if not dev:
            return False
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM devices WHERE ip=?", (dev["ip"],))
        return True

    def renomear(self, alvo: str, nome: str) -> dict | None:
        dev = self.obter(alvo)
        if not dev:
            return None
        with self._lock:
            self.conn.execute("UPDATE devices SET nome=? WHERE chave=?",
                              (nome, dev["chave"]))
            self.conn.commit()
        return self.obter(dev["chave"])

    def atualizar(self, alvo: str, manual: bool | None = None,
                  **campos) -> dict | None:
        dev = self.obter(alvo)
        if not dev:
            return None
        sets, vals = [], []
        for chave in ("nome", "tipo", "grupo", "notas", "favorito"):
            if chave in campos and campos[chave] is not None:
                valor = (int(bool(campos[chave])) if chave == "favorito"
                         else campos[chave])
                sets.append(f"{chave}=?")
                vals.append(valor)
        if "manual" not in campos and manual is not None:
            sets.append("manual=?")
            vals.append(1 if manual else 0)
        if not sets:
            return dev
        vals.append(dev["chave"])
        with self._lock, self.conn:
            self.conn.execute(
                f"UPDATE devices SET {', '.join(sets)} WHERE chave=?", vals)
        return self.obter(dev["chave"])

    def esquecer(self, alvo: str) -> bool:
        dev = self.obter(alvo)
        if not dev:
            return False
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM devices WHERE chave=?", (dev["chave"],))
        return True

    def marcar_offline(self, vistos: list[str]) -> None:
        with self._lock, self.conn:
            if vistos:
                marcas = ",".join("?" for _ in vistos)
                self.conn.execute(
                    f"UPDATE devices SET online=0 WHERE visivel=1 "
                    f"AND ip NOT IN ({marcas})", vistos)
            else:
                self.conn.execute(
                    "UPDATE devices SET online=0 WHERE visivel=1")

    def grupos(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT grupo, COUNT(*) FROM devices WHERE visivel=1 "
                "AND grupo != '' GROUP BY grupo ORDER BY 2 DESC").fetchall()
        return [{"grupo": r[0], "total": r[1]} for r in rows]

    def anotar(self, alvo: str, texto: str) -> dict | None:
        dev = self.obter(alvo)
        if not dev:
            return None
        with self._lock:
            self.conn.execute("UPDATE devices SET notas=? WHERE chave=?",
                              (texto, dev["chave"]))
            self.conn.commit()
        return self.obter(dev["chave"])

    @staticmethod
    def _row(row) -> dict:
        def _json(v):
            try:
                return json.loads(v or "[]")
            except Exception:
                return []
        return {
            "chave": row[0], "ip": row[1], "mac": row[2], "nome": row[3],
            "tipo": row[4], "fabricante": row[5], "modelo": row[6],
            "servicos": _json(row[7]), "portas": _json(row[8]),
            "primeira_vez": row[9], "ultima_vez": row[10], "notas": row[11],
            "visivel": bool(row[12]), "grupo": row[13] or "",
            "favorito": bool(row[14]), "online": bool(row[15]),
            "ultimo_teste": row[16] or "", "manual": bool(row[17]),
        }

    # ------------------------------------------------------------------ #
    # Apresentação
    # ------------------------------------------------------------------ #
    def resumo(self) -> str:
        devs = self.listar()
        if not devs:
            return "Nenhum dispositivo na rede conhecido ainda. Rode uma varredura."
        linhas = [f"{len(devs)} dispositivo(s) conhecido(s):"]
        for d in devs:
            rot = d["nome"] or d["modelo"] or d["fabricante"] or d["tipo"]
            portas = ",".join(str(p) for p in d["portas"][:6])
            linhas.append(f"- [{d['tipo']}] {rot} · {d['ip']}"
                          f"{(' · ' + d['mac']) if d['mac'] else ''}"
                          f"{(' · portas ' + portas) if portas else ''}"
                          f"{(' · ' + d['notas']) if d['notas'] else ''}")
        return "\n".join(linhas)
