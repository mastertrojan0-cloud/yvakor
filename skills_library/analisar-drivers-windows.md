<!-- skill: analisar-drivers-windows | tags: drivers, windows, manutencao, diagnostico | status: nova -->
# Analisar Drivers do Windows e Priorizar Atualizações

## Quando usar
Use quando o usuário pedir "análise de drivers", "verificar drivers", "drivers desatualizados" ou relatar lentidão/instabilidade sem causa aparente. Produz um relatório com drivers problemáticos e prioridades de atualização.

## Pré-requisitos
- Acesso ao Windows (PowerShell com permissão de leitura; admin recomendado)
- Nenhuma instalação necessária — usa cmdlets nativos

## Procedimento
Atalho: `sistema_drivers()` faz os passos 1, 2 e 4 numa chamada (não repita).
Se o usuário pedir para ATUALIZAR/RESOLVER ("atualiza", "de qualquer forma",
"você escolhe"): chame `sistema_drivers_atualizar(acao="auto")` direto, sem
menu de opções — o UAC do Windows é a confirmação. Para Intel antigo sem
update no Windows Update: `sistema_drivers_atualizar(acao="intel")`.

1. **Listar todos os drivers com status e data**
   Execute no PowerShell:
   ```powershell
   Get-CimInstance Win32_PnPSignedDriver |
     Select-Object DeviceName, DriverClass, DriverVersion, DriverDate, IsSigned |
     Sort-Object DriverDate
   ```
   Anote: total de drivers, quantos têm data anterior a `{ano_limite}` (ex: 2022), e qualquer `IsSigned = False`.

2. **Identificar drivers com problema (status Degraded/Error)**
   ```powershell
   Get-PnpDevice | Where-Object { $_.Status -ne 'OK' } |
     Select-Object FriendlyName, Class, Status, Problem, InstanceId
   ```
   Para cada item, registre `FriendlyName`, `Class`, `Status` e `Problem` (código).

3. **Classificar cada driver problemático**
   - Se `Class = System` e o nome contém `RemoteFX`, `Hyper-V`, `Virtual`, `VSP` → **virtual, inofensivo** (só ativa em sessão RDP/Hyper-V). Marcar como "não crítico".
   - Se `Class = Display/Net/Media` → **crítico**, priorizar.
   - Código `Problem = 0` com status Degraded → geralmente virtual/inativo, não requer ação.

4. **Verificar atualizações pendentes no Windows Update**
   ```powershell
   Get-WindowsUpdate -MicrosoftUpdate 2>$null
   ```
   (Se o módulo `PSWindowsUpdate` não existir, use: `UsoClient StartScan` e consulte Configurações > Windows Update.)
   Se retornar vazio → caminho de atualização é o **site do fabricante**.

5. **Montar tabela de prioridades** para drivers antigos (data < `{ano_limite}`):
   | Classe | Prioridade |
   |---|---|
   | Display (vídeo) | **Alta** |
   | Net (rede) | **Média** |
   | Security / Management Engine | **Média** |
   | Storage / SATA / Chipset | Baixa (estável para a geração) |
   | Áudio / periféricos | Baixa |
   | Túneis/VPN (ex: Tailscale) | Baixa — atualiza pelo próprio app |

6. **Identificar geração do hardware** para calibrar expectativa
   ```powershell
   Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product
   Get-CimInstance Win32_Processor | Select-Object Name
   ```
   Drivers de chipset com data próxima ao lançamento da plataforma são **normais** — não há versão mais nova relevante.

7. **Se pediram para atualizar, execute** (`sistema_drivers_atualizar`) e reporte o resultado; senão, **emita a conclusão** com: (a) nada crítico quebrado? (b) lista de prioridade Alta/Média com link do fabricante da placa-mãe/notebook, (c) itens que NÃO valem atualizar.

## Erros conhecidos e soluções

| Erro | Solução |
|---|---|
| `Get-WindowsUpdate` não reconhecido | Módulo `PSWindowsUpdate` ausente; use `UsoClient StartScan` ou a UI do Windows Update |
| Muitos drivers "Degraded" de virtualização | Ignorar se `Class = System` e nome contém `RemoteFX`/`Hyper-V`/`VSP` — inofensivos |
| Driver antigo de chipset marcado como "desatualizado" | Comparar data com ano da placa-mãe; se próximo, é normal — não atualizar |
| Sem permissão para `Get-PnpDevice` | Reexecutar PowerShell como Administrador |
| Driver de VPN/túnel desatualizado | Orientar atualização pelo próprio aplicativo, não pelo Windows |

## Exemplo real (da tarefa que originou esta skill)

**Pedido:** "preciso que voce faça o analise" (de drivers).

**Resultado produzido:**
- 1 driver Degraded: `Microsoft RemoteFX Synth3D VSP Driver` (Class System, código 0) → **virtual, inofensivo**.
- 16 drivers de terceiros, 16 antigos (2006–2021); Windows Update sem pendências.
- Prioridades: **Alta** = Intel HD Graphics (2020); **Média** = Realtek PCIe GbE (2021) e Intel Management Engine (2016); **Baixa** = SATA AHCI (2013), chipset 7 Series (2018), áudio (2014), Tailscale (2021).
- Conclusão: nada crítico quebrado; atualizar vídeo e rede pelo site do fabricante; chipset de 2013–2018 é normal para plataforma Intel 7 Series (~2012).