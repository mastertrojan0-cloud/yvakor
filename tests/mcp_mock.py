"""Servidor MCP mínimo para testes locais (stdio/JSON-RPC)."""
import json
import sys


def responder(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for linha in sys.stdin:
    linha = linha.strip()
    if not linha:
        continue
    try:
        req = json.loads(linha)
    except Exception:
        continue
    metodo = req.get("method")
    rid = req.get("id")
    if metodo == "initialize":
        responder(rid, {"protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mock", "version": "1"}})
    elif metodo == "notifications/initialized":
        pass
    elif metodo == "tools/list":
        responder(rid, {"tools": [{
            "name": "echo",
            "description": "Devolve o texto recebido.",
            "inputSchema": {"type": "object",
                            "properties": {"texto": {"type": "string"}}}}]})
    elif metodo == "tools/call":
        args = (req.get("params") or {}).get("arguments") or {}
        responder(rid, {"content": [{"type": "text",
                                     "text": "eco: " + str(args.get("texto", ""))}]})
    elif rid is not None:
        responder(rid, error={"code": -32601, "message": "método desconhecido"})
