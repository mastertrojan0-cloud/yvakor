# YVAKOR remoto pela Tailscale

## Por que Tailscale Serve

- HTTPS com certificado válido da tailnet (sem instalar CA).
- **Só a tailnet acessa** — nada exposto na internet, sem abrir porta no roteador.
- O servidor continua escutando apenas em `127.0.0.1`; o Serve faz o proxy.
- Não conflita com o serviço que já usa a porta 443 (`/` → DSH).

## URL

```
https://masterhouse.tailc6d704.ts.net:8443
```

Porta **8443** dedicada ao YVAKOR; a 443 continua com o serviço atual.

## Comandos

```powershell
# ativar (uma vez)
tailscale serve --bg --https=8443 http://127.0.0.1:7777

# ver o que está publicado
tailscale serve status

# desativar apenas o YVAKOR
tailscale serve --https=8443 off
```

O servidor precisa estar rodando:

```powershell
cd E:\YVAKOR\yvakor
.\venv\Scripts\python.exe -m yvakor.server
```

## Celular / outro computador

1. Instale o Tailscale e entre com a mesma conta (`cordero831@`).
2. Abra `https://masterhouse.tailc6d704.ts.net:8443`.
3. A câmera usa `/camera/<ip>` e o espelho do Yoosee continua funcionando
   enquanto o app estiver aberto na máquina.

## Segurança

- **Nunca use `tailscale funnel`** para o YVAKOR: isso publicaria o agente na
  internet.
- O agente tem privilégios totais. Mantenha a tailnet só com seus aparelhos e
  remova dispositivos antigos no admin do Tailscale.
- ACL sugerida (admin → Access controls): permitir a porta 8443 apenas para os
  seus dispositivos/usuários, negando o resto.
- Próximo endurecimento recomendado: token de acesso no YVAKOR
  (`YVAKOR_TOKEN`) exigido para requisições que não venham do loopback, além do
  login da tailnet.

## Diagnóstico

| Sintoma | Verifique |
|---|---|
| 502 no navegador | servidor local rodando em `127.0.0.1:7777` |
| certificado inválido | HTTPS/MagicDNS habilitados no admin do Tailscale |
| funciona local, não remoto | `tailscale status` e ACL da tailnet |
| porta 8443 ocupada | `tailscale serve status`; escolha outra porta |
