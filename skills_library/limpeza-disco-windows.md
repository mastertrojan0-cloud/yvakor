<!-- skill: limpeza-disco-windows | tags: windows, limpeza, disco, temp, manutencao, espaco | status: atualizada -->
# Limpeza de disco no Windows (arquivos temporários)

## Quando usar
Quando o usuário pedir "limpeza", "liberar espaço", "limpar o PC" ou reclamar
de disco cheio em uma máquina Windows. Foco em arquivos temporários seguros.

## Pré-requisitos
- Acesso a um shell no Windows (PowerShell ou CMD) com permissão do usuário.
- Saber o nome de usuário do Windows (`{usuario}`) — normalmente em
  `C:\Users\{usuario}`.
- Não é necessário ser administrador para limpar o Temp do usuário.

## Procedimento
1. **Medir o espaço antes.** Registre o tamanho do Temp do usuário e o espaço
   livre em C: para poder comparar depois.
   ```powershell
   # Tamanho do Temp do usuário
   "{0:N1} MB" -f ((Get-ChildItem "$env:LOCALAPPDATA\Temp" -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1MB)
   # Espaço livre em C:
   Get-PSDrive C | Select-Object @{n='LivreGB';e={[math]::Round($_.Free/1GB,2)}}, @{n='TotalGB';e={[math]::Round(($_.Used+$_.Free)/1GB,2)}}
   ```
2. **Apagar o Temp do usuário**, ignorando arquivos em uso (sem abortar):
   ```powershell
   Get-ChildItem "$env:LOCALAPPDATA\Temp" -Recurse -Force -ErrorAction SilentlyContinue |
     Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
   ```
   O `-ErrorAction SilentlyContinue` faz os arquivos em uso serem pulados
   automaticamente — isso é esperado e não é erro.
3. **Verificar o Temp do sistema** (`C:\Windows\Temp`). Se estiver vazio, nada a
   fazer; se tiver conteúdo e houver admin, repetir o passo 2 apontando para
   `C:\Windows\Temp`.
4. **Medir o espaço depois** (mesmos comandos do passo 1) e calcular o ganho.
5. **Reportar** ao usuário em tabela: tamanho do Temp antes/depois, espaço livre
   antes/depois e total liberado. Se o disco continuar cheio (ex.: >80% de uso),
   sugerir próximos alvos (ver abaixo) e perguntar se deve prosseguir.

### Próximos alvos sugeridos (só se o disco continuar cheio)
- Cache do navegador (Edge/Chrome: 1–3 GB típicos).
- Windows Update: `C:\Windows\SoftwareDistribution\Download`.
- Downloads antigos e Lixeira.

## Erros conhecidos e soluções
- **"Acesso negado" / arquivo em uso:** normal no Temp. Ignorar — o
  `-ErrorAction SilentlyContinue` já contorna. Não insistir nem forçar.
- **`C:\Windows\Temp` exige admin:** se não houver elevação, pular e avisar.
- **Comando falha por caminho com espaços/acentos:** usar `$env:LOCALAPPDATA`
  em vez de digitar o caminho manualmente.
- **Ganho menor que o esperado:** arquivos em uso permanecem; reexecutar depois
  de reiniciar o PC se quiser recuperar o restante.
- **Ganho ZERO (Temp já limpo):** se o Temp do usuário já estiver pequeno
  (ex.: <10 MB, quase tudo em uso) e `C:\Windows\Temp` vazio, a limpeza não
  libera nada. **Não repetir a limpeza nem insistir** — reportar "nada novo
  liberado nesta rodada" e ir direto para os próximos alvos (passo 5). Isso
  indica que o Temp não é mais o gargalo do disco.

## Exemplo real (da tarefa que originou esta skill)
Pedido: "pode rodar a limpeza". Resultado:
- Temp do usuário: 284,1 MB → 2 MB.
- Espaço livre em C:: 37,9 GB → 39,63 GB (**+1,7 GB liberados**).
- `C:\Windows\Temp` já estava vazio; arquivos em uso foram ignorados sem erro.
- C: permaneceu com ~83% de uso (39,6 GB livres de ~48 GB).

### Rodada seguinte (aprendizado incorporado)
Pedido: "pode rodar a limpeza" (de novo). Resultado:
- Temp do usuário: 2,7 MB → 2,7 MB (quase tudo em uso).
- `C:\Windows\Temp`: já vazio (0 MB).
- Espaço livre em C:: 39,63 GB → 39,63 GB (**nada novo liberado**).
- Conclusão: a limpeza anterior já tinha feito o trabalho pesado; o Temp não é
  mais o gargalo. Próximos alvos recomendados: cache de navegador (maior ganho
  rápido), Windows Update e Downloads/Lixeira.