# YVAKOR — Dispositivos da rede (câmeras, TVs, celulares, IoT)

O agente enxerga e controla aparelhos **da rede local desta máquina** — como um
assistente doméstico, não como um scanner da internet.

---

## 1. Escopo autorizado (regra de ouro)

```yaml
rede:
  allowed_subnets: []      # vazio = sub-redes físicas detectadas na máquina
  allowed_hosts: []        # IPs/nomes extras
  allow_public: false      # internet só se você ligar explicitamente
```

- O padrão cobre as sub-redes **diretamente conectadas** (Wi-Fi/cabo) e o
  gateway. Adaptadores virtuais (Hyper-V, VMware, WSL, Docker, VPN) são
  ignorados na varredura.
- Fora disso: `PermissionError`. O agente explica e não contorna.
- `rede_escopo` mostra exatamente o que está liberado.

---

## 2. O que ele descobre

Varredura em duas fases (rápida → ARP → portas completas), mais:

| Camada | O que revela |
|---|---|
| TCP probe | hosts vivos + portas abertas (80, 443, 554, 8001, 1883, 62078…) |
| ARP | MAC (e fabricante pelo OUI) — pega até aparelho sem porta aberta |
| SSDP/UPnP | TVs, roteadores, media servers, câmeras |
| mDNS | Chromecast/Google TV, AirPlay, impressoras, Shelly, ESPHome |
| ONVIF WS-Discovery | câmeras IP profissionais |

Classificação automática: `camera`, `tv`, `telefone`, `roteador`,
`impressora`, `iot`, `computador`. Tudo fica em `data/rede.db` com nome e
anotações — `rede_nomear` dá nomes humanos ("câmera da garagem").

---

## 3. Ferramentas

| Ferramenta | O que faz |
|---|---|
| `rede_escanear(profundo=True)` | Descobre aparelhos (~10-15 s) |
| `rede_dispositivos(tipo?)` | Inventário conhecido |
| `rede_escopo()` | Mostra o que está autorizado |
| `rede_nomear(alvo, nome)` | Nome humano para o aparelho |
| `rede_camera_descobrir()` | Câmeras ONVIF (WS-Discovery) |
| `rede_camera_info(alvo)` | Fabricante, modelo, perfis, snapshot |
| `rede_camera_snapshot(alvo)` | Foto JPEG em `data/rede_shots/` |
| `rede_camera_ptz(alvo, x, y, zoom)` | Move a câmera |
| `rede_camera_gravar(alvo, s)` | Clipe RTSP (ffmpeg) |
| `rede_camera_credenciais(alvo, u, s)` | Salva login (data/rede.json) |
| `rede_cast(acao, alvo, valor)` | Chromecast: tocar/pausar/volume/status |
| `rede_tv(acao, alvo, valor)` | Samsung/LG: ligar/desligar/tecla/volume/app |
| `rede_telefone_dispositivos()` | Celulares Android via ADB |
| `rede_telefone_conectar(ip)` | Depuração sem fio (ip:5555) |
| `rede_telefone_tela(serial)` | Print da tela |
| `rede_telefone_acao(acao, …)` | tocar/deslizar/texto/tecla/app/shell |
| `rede_http_dispositivo(alvo, caminho)` | Tasmota `/cm?cmnd=`, Shelly `/rpc/` |
| `rede_mqtt_ler(topico, s)` | Escuta tópicos MQTT |
| `rede_mqtt_publicar(topico, payload)` | Liga/desliga por MQTT |
| `rede_wol(alvo)` | Wake-on-LAN (liga PC/TV) |

---

## 4. Receitas

**Câmera**
> "Veja a câmera da garagem e me diga se tem alguém."
`rede_camera_snapshot("câmera da garagem")` → caminho do JPEG.
Se pedir senha: salve com `rede_camera_credenciais`.

**TV**
> "Liga a TV e abre a Netflix."
`rede_tv("ligar", "tv da sala")` → `rede_tv("app", "tv da sala", "netflix")`.

**Chromecast**
> "Toca esse vídeo na TV." (com URL ou arquivo local)
`rede_cast("tocar", "sala", "https://…/video.mp4")` — arquivo local é servido
por HTTP temporário na LAN.

**Celular**
> "Tira um print da tela do meu celular."
`rede_telefone_tela()` (precisa de ADB + depuração autorizada).

**IoT**
> "Liga a luz da sala." → `rede_mqtt_publicar("casa/sala/luz", "ON")`.

---

## 5. Limites e segurança

- **Descoberta ≠ permissão de uso.** O agente não mexe em aparelho que não foi
  pedido.
- **Sem força bruta.** Se a câmera pede usuário/senha, o agente para e pede.
- **Ações com efeito** (PTZ, gravar, TV, celular, MQTT, HTTP) passam pelo
  Confirmation Guard; **segredos e ADB shell** pedem confirmação sempre.
- **iOS** não é suportado (Apple não expõe controle local sem pareamento
  proprietário); Android sim, via ADB autorizado pelo dono.
- **ADB** exige Depuração USB/sem fio ligada e o popup aceito no aparelho.
- Credenciais ficam em `data/rede.json` (fora do git), nunca no `settings.yaml`.

---

## 6. Problemas comuns

| Sintoma | Causa | Solução |
|---|---|---|
| "fora do escopo autorizado" | alvo em outra rede/internet | ajuste `allowed_hosts`/`allowed_subnets` |
| Nada encontrado | firewall/AP isolation no roteador | teste o ping/porta de outro PC |
| Câmera 401 | falta usuário/senha | `rede_camera_credenciais` |
| Câmera sem imagem | ONVIF desligado | o fallback tenta RTSP (Hikvision/Dahua) |
| TV não responde | porta 8001/3000 bloqueada ou sem pareamento | aceite o popup na TV |
| Celular "unauthorized" | popup não aceito | aceite "Permitir depuração" |
| MQTT não configurado | sem broker | `rede.mqtt.host` no settings.yaml |
