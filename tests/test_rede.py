"""Teste do módulo de rede (offline, sem tocar em aparelhos reais).

    python tests/test_rede.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_escopo():
    from yvakor.rede.escopo import EscopoRede
    s = {"rede": {"allowed_subnets": ["10.9.8.0/24"], "allowed_hosts": ["10.9.8.50"],
                  "allow_public": False, "max_hosts": 32}}
    e = EscopoRede(s)
    assert e.permitido("10.9.8.7")
    assert e.permitido("10.9.8.50")
    assert e.permitido("127.0.0.1")          # loopback sempre pode
    assert not e.permitido("8.8.8.8")        # internet bloqueada
    assert not e.permitido("192.168.0.10")   # rede alheia
    try:
        e.exigir("8.8.8.8")
        raise AssertionError("deveria negar internet")
    except PermissionError as exc:
        assert "escopo" in str(exc).lower()

    e.allow_public = True
    assert e.permitido("8.8.8.8")
    print("  ✅ escopo — LAN autorizada, internet negada por padrão")


def test_registro():
    from yvakor.rede.registro import RegistroRede
    from yvakor.rede.descoberta import fabricante_por_mac
    assert fabricante_por_mac("c0:56:27:11:22:33") == "Hikvision"
    tmp = Path(tempfile.mkdtemp(prefix="yvk-rede-"))
    r = RegistroRede(tmp / "rede.db", tmp / "rede.json")
    d = r.upsert({"ip": "10.9.8.7", "mac": "c0:56:27:11:22:33",
                  "tipo": "camera", "portas": [80, 554],
                  "servicos": ["onvif"]})
    assert d["chave"] == "c0:56:27:11:22:33"
    assert r.obter("10.9.8.7")["ip"] == "10.9.8.7"
    # nome do usuário não é sobrescrito por uma nova varredura
    r.renomear("10.9.8.7", "câmera da garagem")
    r.upsert({"ip": "10.9.8.7", "mac": "c0:56:27:11:22:33", "tipo": "camera"})
    assert r.obter("10.9.8.7")["nome"] == "câmera da garagem"
    r.salvar_credenciais("10.9.8.7", user="admin", password="s3nha")
    assert r.credenciais("10.9.8.7")["user"] == "admin"
    assert "câmera da garagem" in r.resumo()
    print("  ✅ registro — upsert, nome preservado, credenciais")


def test_classificacao():
    from yvakor.rede.descoberta import classificar
    assert classificar({"servicos": ["_onvif._tcp"], "portas": [80]}) == "camera"
    assert classificar({"servicos": [], "portas": [554]}) == "camera"
    assert classificar({"servicos": ["_googlecast._tcp"], "portas": []}) == "tv"
    assert classificar({"servicos": [], "portas": [8001]}) == "tv"
    assert classificar({"servicos": [], "portas": [62078]}) == "telefone"
    assert classificar({"servicos": [], "portas": [445]}) == "computador"
    assert classificar({"servicos": [], "portas": [9100]}) == "impressora"
    assert classificar({"servicos": [], "portas": [], "ip": "10.9.8.1"},
                       "10.9.8.1") == "roteador"
    print("  ✅ classificação — câmera, TV, celular, PC, impressora, roteador")


def test_wol():
    from yvakor.rede.iot import wol
    r = wol("c0:56:27:11:22:33")
    assert r["ok"], r
    try:
        wol("nao-e-mac")
        raise AssertionError("MAC inválido deveria falhar")
    except ValueError:
        pass
    print("  ✅ wake-on-lan — pacote enviado, MAC inválido rejeitado")


def test_onvif_estruturas():
    from yvakor.rede import onvif
    env = onvif.envelope("<tds:GetDeviceInformation/>", "admin", "senha")
    texto = env.decode()
    assert "GetDeviceInformation" in texto
    assert "UsernameToken" in texto and "PasswordDigest" in texto
    assert "<Username>admin</Username>" in texto
    # Digest de uma câmera que pede autenticação HTTP
    auth = onvif._digest('Digest realm="cam", nonce="abc", qop="auth"',
                         "GET", "http://10.9.8.7/img.jpg", "admin", "senha")
    assert auth.startswith("Digest ")
    assert 'username="admin"' in auth and 'uri="/img.jpg"' in auth
    # URL de snapshot com credencial embutida é separada
    u, p, limpa = onvif.credenciais_da_url("http://adm:123@10.9.8.7/snap.jpg")
    assert (u, p, limpa) == ("adm", "123", "http://10.9.8.7/snap.jpg")
    print("  ✅ onvif — envelope WS-Security, digest e URL com credencial")


def test_http_dispositivo():
    from yvakor.rede.iot import HTTPDispositivo
    from yvakor.rede.escopo import EscopoRede

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            corpo = b'{"POWER":"ON","porta":"teste"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *a):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), H)
    porta = servidor.server_address[1]
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        e = EscopoRede({"rede": {"allowed_subnets": [], "allowed_hosts":
                                 ["127.0.0.1"], "allow_public": False}})
        d = HTTPDispositivo(e, timeout=4)
        r = d.requisicao(f"127.0.0.1:{porta}", "/cm?cmnd=Power", metodo="GET")
        assert r["ok"] and "POWER" in r["corpo"], r
        r2 = d.tasmota(f"127.0.0.1:{porta}", "Power")
        assert r2.get("json", {}).get("POWER") == "ON", r2
        try:
            d.requisicao("8.8.8.8", "/")
            raise AssertionError("deveria negar fora do escopo")
        except PermissionError:
            pass
    finally:
        servidor.shutdown()
    print("  ✅ http de dispositivo — GET/Tasmota e bloqueio fora do escopo")


if __name__ == "__main__":
    test_escopo()
    test_registro()
    test_classificacao()
    test_wol()
    test_onvif_estruturas()
    test_http_dispositivo()
