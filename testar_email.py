"""Teste rápido do conector de e-mail (SMTP).

Uso:
    venv\\Scripts\\python.exe testar_email.py

Lê as credenciais salvas em data/connectors.json (conector "email" ou
"outlook"), envia um e-mail de teste para você mesmo e mostra o resultado.
Serve para validar a Senha de App ANTES de usar pela conversa.
"""
import sys
import json
from pathlib import Path

# console do Windows com UTF-8 (evita quebra de acentos)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from yvakor.connectors.providers import _email_enviar  # noqa: E402

STORE = ROOT / "data" / "connectors.json"


def main():
    if not STORE.exists():
        print("[x] Nenhum conector salvo ainda (data/connectors.json não existe).")
        print("    Conecte o e-mail primeiro na interface (🔌 conectores).")
        return
    dados = json.loads(STORE.read_text(encoding="utf-8"))
    creds = dados.get("email") or dados.get("outlook")
    if not creds:
        print("[x] Conector de e-mail não encontrado. Conecte 'E-mail (SMTP/IMAP)'.")
        return

    destino = creds.get("usuario", "")
    print(f"[..] Enviando e-mail de teste de {destino} para {destino} ...")
    r = _email_enviar(creds, destino,
                      "YVAKOR — teste de conexão",
                      "Se você recebeu este e-mail, o conector SMTP está funcionando. 🚀")
    if r.get("ok"):
        print(f"[OK] Enviado! Verifique a caixa de entrada de {destino}.")
    else:
        print(f"[x] Falhou: {r.get('erro')}")
        print("    Dicas: use a SENHA DE APP (não a senha normal); confira")
        print("    smtp.gmail.com / porta 587; 2FA precisa estar ativa.")


if __name__ == "__main__":
    main()
