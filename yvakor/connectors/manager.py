"""YVAKOR — Gerenciador de conectores.

- Carrega/salva credenciais em data/connectors.json (fora do git).
- Calcula o status (conectado quando os campos obrigatórios estão preenchidos).
- Injeta dinamicamente as ferramentas dos conectores conectados no ToolRegistry
  e marca as ações sensíveis para passarem pelo Confirmation Guard (popup).
"""
from __future__ import annotations
import json
from pathlib import Path

from yvakor.connectors.providers import CATALOGO


class ConnectorManager:
    def __init__(self, registry, store_path: Path):
        self.registry = registry
        self.store_path = Path(store_path)
        self.creds: dict[str, dict] = self._load()
        self._owned: set[str] = set()   # ferramentas registradas por conectores
        self.register_all()

    # ------------------------------------------------------------------ #
    # Persistência
    # ------------------------------------------------------------------ #
    def _load(self) -> dict:
        if self.store_path.exists():
            try:
                return json.loads(self.store_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(
            json.dumps(self.creds, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #
    def _effective_creds(self, cid: str) -> dict:
        """Credenciais usadas de fato: para conectores OAuth, mescla as
        credenciais de app compartilhadas (.env) com as do conector (que
        guardam o oauth_token e eventuais overrides próprios) e marca o
        provedor para o módulo oauth saber como renovar o token."""
        spec = CATALOGO.get(cid) or {}
        c = dict(self.creds.get(cid) or {})
        provider = (spec.get("oauth") or {}).get("provider")
        if provider:
            import yvakor.connectors.oauth as oauth
            c["_provider"] = provider
            gid, gsec = oauth.app_credentials(provider)
            if gid and not c.get("client_id"):
                c["client_id"] = gid
            if gsec and not c.get("client_secret"):
                c["client_secret"] = gsec
        return c

    def can_signin(self, cid: str) -> bool:
        """OAuth: há credenciais de app disponíveis (compartilhadas ou próprias)
        para iniciar o login em um clique?"""
        spec = CATALOGO.get(cid) or {}
        if not spec.get("oauth"):
            return False
        c = self._effective_creds(cid)
        return bool(c.get("client_id") and c.get("client_secret"))

    def is_connected(self, cid: str) -> bool:
        spec = CATALOGO.get(cid)
        if not spec:
            return False
        if spec.get("oauth"):
            c = self._effective_creds(cid)
            # Conectado = credenciais de app + autorização concluída (oauth_token)
            return bool(c.get("client_id") and c.get("client_secret")
                        and c.get("oauth_token"))
        c = self.creds.get(cid) or {}
        return all(str(c.get(k, "")).strip() for k in spec["required"])

    def _creds_saved(self, cid: str) -> bool:
        spec = CATALOGO.get(cid) or {}
        c = self.creds.get(cid) or {}
        return all(str(c.get(k, "")).strip() for k in spec.get("required", []))

    def catalog(self) -> list[dict]:
        """Lista pública para a interface — sem expor valores secretos.
        Cada campo indica apenas se já está preenchido (preenchido=True)."""
        out = []
        for cid, spec in CATALOGO.items():
            salvos = self.creds.get(cid) or {}
            campos = []
            for f in spec["fields"]:
                campos.append({
                    "key": f["key"], "label": f["label"],
                    "type": f.get("type", "text"),
                    "placeholder": f.get("placeholder", ""),
                    "default": f.get("default", ""),
                    "preenchido": bool(str(salvos.get(f["key"], "")).strip()),
                })
            out.append({
                "id": cid, "name": spec["name"], "icon": spec["icon"],
                "desc": spec["desc"], "fields": campos,
                "connected": self.is_connected(cid),
                "oauth": bool(spec.get("oauth")),     # usa fluxo de login externo
                "provider": (spec.get("oauth") or {}).get("provider", ""),
                "saved": self._creds_saved(cid),       # credenciais próprias salvas
                "can_signin": self.can_signin(cid),    # dá p/ entrar em um clique
            })
        return out

    # ------------------------------------------------------------------ #
    # Conectar / desconectar
    # ------------------------------------------------------------------ #
    def connect(self, cid: str, fields: dict) -> dict:
        spec = CATALOGO.get(cid)
        if not spec:
            return {"ok": False, "erro": f"conector desconhecido: {cid}"}
        # Monta num dict local; só persiste se a validação passar (um connect
        # inválido NÃO deve sujar/alterar as credenciais já salvas).
        atual = dict(self.creds.get(cid) or {})
        for f in spec["fields"]:
            k = f["key"]
            if k in fields and str(fields[k]).strip() != "":
                atual[k] = str(fields[k]).strip()
            elif k not in atual and f.get("default"):
                atual[k] = f["default"]
        # OAuth: as credenciais podem vir do app compartilhado (.env), então
        # não exigimos preenchimento — o login é feito pelo botão "Entrar com…".
        if not spec.get("oauth"):
            faltando = [k for k in spec["required"]
                        if not str(atual.get(k, "")).strip()]
            if faltando:
                return {"ok": False, "erro": "campos obrigatórios faltando: "
                        + ", ".join(faltando)}
        self.creds[cid] = atual
        self._save()
        self.register_all()
        return {"ok": True, "id": cid, "connected": self.is_connected(cid),
                "oauth": bool(spec.get("oauth")), "can_signin": self.can_signin(cid)}

    # ------------------------------------------------------------------ #
    # OAuth (Google)
    # ------------------------------------------------------------------ #
    def authorize_url(self, cid: str) -> dict:
        """Monta a URL de consentimento para conectores OAuth (após salvar creds)."""
        spec = CATALOGO.get(cid)
        if not spec or not spec.get("oauth"):
            return {"ok": False, "erro": "este conector não usa OAuth"}
        c = self._effective_creds(cid)
        if not (c.get("client_id") and c.get("client_secret")):
            prov = spec["oauth"]["provider"].upper()
            return {"ok": False, "erro": "credenciais do app não configuradas — "
                    f"defina {prov}_CLIENT_ID/{prov}_CLIENT_SECRET no .env ou "
                    "informe Client ID/Secret próprios (modo avançado)."}
        import yvakor.connectors.oauth as oauth
        if spec["oauth"]["provider"] in oauth.PROVIDERS:
            return {"ok": True, "auth_url": oauth.build_auth_url(
                spec["oauth"]["provider"], c["client_id"],
                spec["oauth"]["scope"], cid)}
        return {"ok": False, "erro": "provedor OAuth não suportado"}

    def oauth_callback(self, state: str, code: str) -> dict:
        """Recebe o code do redirect, troca por token e ativa o conector."""
        cid = state
        spec = CATALOGO.get(cid)
        if not spec or not spec.get("oauth"):
            return {"ok": False, "erro": "estado de OAuth inválido"}
        eff = self._effective_creds(cid)
        import yvakor.connectors.oauth as oauth
        provider = spec["oauth"]["provider"]
        if provider in oauth.PROVIDERS:
            r = oauth.exchange_code(provider, eff.get("client_id", ""),
                                    eff.get("client_secret", ""), code)
            if not r.get("ok"):
                return r
            # Guarda só o token no conector (client vem do app/efetivo)
            stored = dict(self.creds.get(cid) or {})
            stored["oauth_token"] = r["token"]
            self.creds[cid] = stored
            self._save()
            self.register_all()
            return {"ok": True, "id": cid}
        return {"ok": False, "erro": "provedor OAuth não suportado"}

    def disconnect(self, cid: str) -> dict:
        if cid in self.creds:
            del self.creds[cid]
            self._save()
        self.register_all()
        return {"ok": True, "id": cid, "connected": False}

    # ------------------------------------------------------------------ #
    # Injeção das ferramentas no agente
    # ------------------------------------------------------------------ #
    def register_all(self) -> None:
        """Remove ferramentas de conectores antigas e re-registra as ativas."""
        guard = self.registry.guard
        for nome in self._owned:
            self.registry.tools.pop(nome, None)
            self.registry.specs.pop(nome, None)
            guard.guarded.discard(nome)
            guard.always_confirm.discard(nome)
        self._owned.clear()

        def reg(nome, fn, desc="", args=None):
            self.registry.register(nome, fn, desc, args)
            self._owned.add(nome)

        def reg_guarded(nome, fn, desc="", args=None):
            reg(nome, fn, desc, args)
            guard.guarded.add(nome)        # exige confirmação
            guard.always_confirm.add(nome)  # nunca auto-aprova (popup sempre)

        for cid, spec in CATALOGO.items():
            if self.is_connected(cid):
                spec["register"](reg, reg_guarded, self._effective_creds(cid))

    def connected_ids(self) -> list[str]:
        return [cid for cid in CATALOGO if self.is_connected(cid)]
