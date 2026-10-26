"""Testes do gerenciamento de dispositivos (registro)."""
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_gerenciamento():
    from yvakor.rede.registro import RegistroRede
    r = RegistroRede(Path(tempfile.mkdtemp()) / "rede.db")
    dev = r.upsert({"ip": "10.0.0.9", "mac": "aa:bb:cc:dd:ee:ff",
                    "tipo": "camera", "nome": "camera teste"})
    assert dev["online"] is True

    atual = r.atualizar("10.0.0.9", grupo="casa", favorito=True,
                        nome="Câmera da porta", notas="ao vivo falha")
    assert atual["grupo"] == "casa" and atual["favorito"] is True
    assert atual["nome"] == "Câmera da porta"

    assert r.grupos() == [{"grupo": "casa", "total": 1}]

    r.marcar_offline([])
    assert r.obter("10.0.0.9")["online"] is False

    r.upsert({"ip": "10.0.0.9"})
    assert r.obter("10.0.0.9")["online"] is True

    assert r.esquecer("10.0.0.9") is True
    assert r.obter("10.0.0.9") is None

    # YVAKOR no comando; edição manual tem prioridade
    from yvakor.rede.gerente import organizar

    class FakeRede:
        def __init__(self, reg):
            self.registro = reg
            self.cameras = None

    r.upsert({"ip": "10.0.0.10", "tipo": "camera"})
    r.atualizar("10.0.0.10", manual=True, grupo="meu-grupo")
    organizar(FakeRede(r))
    assert r.obter("10.0.0.10")["grupo"] == "meu-grupo"
    r.atualizar("10.0.0.10", manual=False)
    organizar(FakeRede(r))
    assert r.obter("10.0.0.10")["grupo"] == "câmeras"
    print("  ✅ governança — manual preservado; YVAKOR organiza o resto")
    print("  ✅ dispositivos — edição, grupo, favorito, online/offline, esquecer")


if __name__ == "__main__":
    test_gerenciamento()
