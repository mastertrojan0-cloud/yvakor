<!-- skill: verificar-rede-tailscale | tags: tailscale, rede, vpn, diagnostico | status: nova -->
# Verificar Estado da Rede Tailscale

## Quando usar
Use quando o usuário pedir "verifica a rede tailscale", "status do tailscale", "quais dispositivos estão online na VPN" ou relatar que não consegue acessar outra máquina pela rede Tailscale. Produz um relatório com todos os nós do tailnet, IPs e status online/offline.

## Pré-requisitos
- Tailscale instalado e autenticado na máquina local (Windows: `tailscale.exe` no PATH ou em `C:\Program Files\Tailscale\`)
- Sessão com permissão para executar o CLI (admin não obrigatório para leitura de status)

## Procedimento
1. **Confirmar que o Tailscale está instalado e o daemon ativo**
 ```powershell
 tailscale version
 tailscale status
 ```
 Se `tailscale` não for reconhecido, use o caminho completo:
 ```powershell
 & "C:\Program Files\Tailscale\tailscale.exe" status
 ```
 Se retornar erro de conexão com o daemon, o serviço está parado — inicie:
 ```powershell
 Start-Service Tailscale
 ```

2. **Listar todos os dispositivos do tailnet em formato legível**
 ```powershell
 tailscale status
 ```
 A saída traz uma linha por nó: `{ip}  {hostname}  {usuario}  {os}  {status}`.
 O nó local aparece marcado como `(this machine)` ou similar.

3. **Obter a lista estruturada em JSON (para montar tabela)**
 ```powershell
 tailscale status --json
 ```
 Campos úteis por peer: `.Peer[].HostName`, `.Peer[].TailscaleIPs[0]`, `.Peer[].OS`, `.Peer[].Online` (bool), `.Peer[].LastSeen` (timestamp RFC3339).
 O nó local está em `.Self`.

4. **Calcular dias offline** para cada peer com `Online = false`
 Converta `LastSeen` para dias decorridos:
 ```powershell
 $now = Get-Date
 tailscale status --json | ConvertFrom-Json | ForEach-Object {
   $_.Peer.PSObject.Properties.Value | ForEach-Object {
     [PSCustomObject]@{
       Host    = $_.HostName
       IP      = $_.TailscaleIPs[0]
       OS      = $_.OS
       Online  = $_.Online
       DiasOff = if ($_.Online) { 0 } else { [int]($now - [datetime]$_.LastSeen).TotalDays }
     }
   }
 } | Sort-Object Online -Descending | Format-Table -AutoSize
 ```

5. **Montar o relatório final** em tabela markdown com colunas:
 `Dispositivo | IP | Tipo | Status`
 - Status online: `🟢 online` (acrescente `(esta máquina)` no nó local)
 - Status offline: `⚪ offline ({N}d)`
 - Encerre com um resumo: total de dispositivos, quantos online, qual o offline mais recente.

6. **Se o objetivo for acessar um nó específico e ele estiver offline**
 Não há ação remota possível — o aparelho precisa ser ligado e reconectar o Tailscale. Informe isso no resumo em vez de tentar pingar (ping falhará e não agrega informação).

## Erros conhecidos e soluções
- **`tailscale: command not found`** → use o caminho completo `C:\Program Files\Tailscale\tailscale.exe` ou adicione ao PATH.
- **`failed to connect to local tailscaled`** → serviço parado; `Start-Service Tailscale` (pode exigir admin).
- **`Logged out` / `NeedsLogin`** → a máquina local não está autenticada; rodar `tailscale up` (exige login interativo do usuário — este passo é do usuário).
- **JSON vazio ou sem `.Peer`** → tailnet com apenas o nó local; reportar "nenhum outro dispositivo cadastrado".
- **`LastSeen` ausente em peer nunca conectado** → tratar como offline sem contagem de dias (`⚪ offline (nunca)`).

## Exemplo real (da tarefa que originou esta skill)
Pedido: "verifica a rede tailscale". Execução de `tailscale status --json` retornou 9 dispositivos; apenas `masterhouse` (100.113.252.27, Windows, esta máquina) online. Os 8 demais (Androids e Windows) offline, o mais recente `antonio-m` há 7 dias e o mais antigo `galaxy-a06` há 211 dias. Relatório entregue como tabela markdown + resumo indicando que não havia outro nó ativo para acessar.