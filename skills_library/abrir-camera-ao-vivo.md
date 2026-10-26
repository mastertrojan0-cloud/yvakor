<!-- skill: abrir-camera-ao-vivo | tags: camera, rtsp, streaming, windows, vlc | status: nova -->
# Abrir câmera ao vivo (stream RTSP)

## Quando usar
Quando o usuário pedir para "abrir a câmera", "ver a câmera ao vivo", "mostrar o stream" ou similar. Por padrão, **sempre** tratar como transmissão ao vivo via RTSP — nunca como arquivo gravado.

## Pré-requisitos
- URL RTSP da câmera no formato `rtsp://{usuario}:{senha}@{host}:{porta}/{caminho}` (ex: `rtsp://admin:senha@192.168.1.10:554/Streaming/Channels/101`)
- Player instalado no Windows (VLC recomendado)
- Câmera acessível na rede (mesma LAN ou VPN)

## Procedimento
1. Confirmar que o pedido é para visualização **ao vivo** (padrão). Se o usuário não especificou, assumir ao vivo.
2. Montar a URL RTSP completa com as credenciais e o caminho do stream principal da câmera.
3. Disparar a abertura no handler padrão do Windows:
   ```cmd
   start "" "{url_rtsp}"
   ```
   (No PowerShell: `Start-Process "{url_rtsp}"`)
4. Informar ao usuário que o stream foi disparado e que o player padrão deve abrir.
5. Se nada abrir ou der erro em até ~10s, cair no plano B (passo 6).
6. **Plano B — chamar o VLC direto** (mais confiável que o handler do Windows):
   ```cmd
   "%ProgramFiles%\VideoLAN\VLC\vlc.exe" "{url_rtsp}"
   ```
   Se o VLC não estiver no caminho padrão, localizar com:
   ```cmd
   where vlc
   ```
   ou verificar `C:\Program Files (x86)\VideoLAN\VLC\vlc.exe`.
7. Se o VLC não estiver instalado, orientar instalação (`winget install VideoLAN.VLC`) ou usar outro player (ex: `ffplay "{url_rtsp}"` se houver FFmpeg).

## Erros conhecidos e soluções

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| Nada abre ao rodar `start ""` | Sem handler registrado para `rtsp://` | Usar plano B: chamar VLC direto com a URL |
| Player abre mas tela preta | Codec não suportado ou stream secundário | Trocar para o stream principal (ex: canal `101` em vez de `102` em Hikvision) |
| "Não foi possível conectar" | Credenciais erradas, IP/porta errados ou câmera offline | Testar com `ping {host}` e `ffplay "{url_rtsp}"` para isolar rede vs. credencial |
| Timeout na conexão | Firewall bloqueando porta 554 | Liberar porta RTSP ou testar de outra máquina na mesma rede |
| Autenticação falha (401) | Senha com caracteres especiais não escapados na URL | URL-encodar a senha (ex: `@` → `%40`) |

## Exemplo real (da tarefa que originou esta skill)
Usuário pediu: *"quando eu peço para abrir a camera sempre é ao vivo"*.

Ação executada: disparo do comando `start "" "rtsp://{usuario}:{senha}@{host}:554/{caminho}"`, que abriu o stream RTSP no player padrão do Windows (VLC, se instalado). Fallback previsto: se não abrisse, chamar o VLC diretamente com a URL, por ser mais confiável que o handler padrão do Windows.