"""YVAKOR — verificação de drivers do Windows (só leitura).

Na conversa 71, "verifica quais drivers precisam ser atualizados" virou um
tutorial genérico. Esta ferramenta responde com os dados da máquina:
  - aparelhos com problema (Gerenciador de Dispositivos ≠ OK);
  - drivers de terceiros mais antigos (data do driver);
  - atualizações de driver pendentes no Windows Update.
`sistema_drivers_atualizar` faz a parte prática (com o UAC do Windows):
instala o pendente do Windows Update, reinstala aparelhos com problema e
instala o assistente oficial da Intel.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from yvakor import proc
from yvakor.config import ROOT

_log = logging.getLogger(__name__)

PS_PROBLEMAS = (
    "Get-PnpDevice -PresentOnly | Where-Object { $_.Status -ne 'OK' } | "
    "Select-Object FriendlyName, Class, Status, Problem | ConvertTo-Json -Compress")
PS_DRIVERS = (
    "Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DriverDate -and "
    "$_.DeviceName -and $_.DriverProviderName -notmatch '^Microsoft' } | "
    "Select-Object DeviceName, DriverProviderName, DriverVersion, "
    "@{n='Data';e={$_.DriverDate.ToString('yyyy-MM-dd')}} | ConvertTo-Json -Compress")
PS_WINDOWS_UPDATE = (
    "$s = New-Object -ComObject Microsoft.Update.Session; "
    "$r = $s.CreateUpdateSearcher().Search(\"IsInstalled=0 and Type='Driver'\"); "
    "$r.Updates | ForEach-Object { [pscustomobject]@{ Titulo = $_.Title; "
    "Data = $_.LastDeploymentChangeTime.ToString('yyyy-MM-dd') } } | "
    "ConvertTo-Json -Compress")


def _ps(comando: str, timeout: float) -> list[dict]:
    r = proc.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                  "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + comando],
                 capture_output=True, timeout=timeout)
    saida = r.stdout.decode("utf-8", "replace").strip()
    if not saida:
        return []
    dados = json.loads(saida)
    return dados if isinstance(dados, list) else [dados]


def _progresso(texto: str) -> None:
    try:
        from yvakor.organizador import _progresso as p
        p(texto)
    except Exception:
        _log.debug("exceção ignorada", exc_info=True)


def verificar(windows_update: bool = True, anos_antigo: int = 3) -> dict:
    out: dict = {"ok": True}
    _progresso("🔧 drivers: aparelhos com problema")
    try:
        out["com_problema"] = [
            {"aparelho": d.get("FriendlyName"), "classe": d.get("Class"),
             "status": d.get("Status"), "codigo": d.get("Problem")}
            for d in _ps(PS_PROBLEMAS, 60)]
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        out["com_problema_erro"] = str(exc)[:120]

    _progresso("🔧 drivers: datas dos drivers instalados")
    try:
        limite = datetime.now().year - int(anos_antigo)
        drivers = _ps(PS_DRIVERS, 90)
        antigos = [d for d in drivers if int(str(d.get("Data") or "9999")[:4]) <= limite]
        antigos.sort(key=lambda d: d.get("Data") or "")
        out["drivers_terceiros"] = len(drivers)
        out["antigos"] = [{"aparelho": d.get("DeviceName"),
                           "fabricante": d.get("DriverProviderName"),
                           "versao": d.get("DriverVersion"), "data": d.get("Data")}
                          for d in antigos[:25]]
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        out["antigos_erro"] = str(exc)[:120]

    if windows_update:
        _progresso("🔧 drivers: consultando o Windows Update (pode levar 1 min)")
        try:
            out["windows_update"] = [{"titulo": u.get("Titulo"), "data": u.get("Data")}
                                     for u in _ps(PS_WINDOWS_UPDATE, 150)]
        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
            out["windows_update_erro"] = str(exc)[:120]
    out["como_atualizar"] = ("Os itens de windows_update instalam por Configurações → "
                             "Windows Update → Opções avançadas → Atualizações "
                             "opcionais; os antigos sem update: site do fabricante.")
    return out


# ---------------------------------------------------------------------- #
# Atualizar / reparar (com UAC: o YVAKOR não roda como administrador)
# ---------------------------------------------------------------------- #
DIR_TRABALHO = ROOT / "data" / "drivers"

PS1_WINDOWS_UPDATE = r"""
$ErrorActionPreference = 'Stop'
$s = New-Object -ComObject Microsoft.Update.Session
$r = $s.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Driver'")
$c = New-Object -ComObject Microsoft.Update.UpdateColl
foreach ($u in $r.Updates) { if (-not $u.EulaAccepted) { $u.AcceptEula() }; [void]$c.Add($u) }
$out = @{ total = $c.Count; itens = @() }
if ($c.Count -gt 0) {
  $d = $s.CreateUpdateDownloader(); $d.Updates = $c; [void]$d.Download()
  $i = $s.CreateUpdateInstaller(); $i.Updates = $c; $res = $i.Install()
  $out.reiniciar = $res.RebootRequired
  for ($k = 0; $k -lt $c.Count; $k++) {
    $out.itens += @{ titulo = $c.Item($k).Title; codigo = $res.GetUpdateResult($k).ResultCode }
  }
}
$out | ConvertTo-Json -Depth 4 | Out-File -Encoding utf8 '__SAIDA__'
"""
PS1_REPARAR = r"""
$res = @()
foreach ($id in @(__IDS__)) {
  $o = (pnputil /remove-device "$id" 2>&1 | Out-String).Trim()
  $res += @{ id = $id; saida = $o }
}
$scan = (pnputil /scan-devices 2>&1 | Out-String).Trim()
@{ reparados = $res; scan = $scan } | ConvertTo-Json -Depth 4 | Out-File -Encoding utf8 '__SAIDA__'
"""
# código do Windows Update: 2 = ok, 3 = ok com erros, 4 = falhou, 5 = abortado
_WU_CODIGO = {2: "instalado", 3: "instalado com avisos", 4: "falhou", 5: "abortado"}


def _elevado(script: str, nome: str, esperar_s: float | None) -> tuple[Path, object]:
    """Roda o script num PowerShell elevado (o Windows mostra o UAC)."""
    DIR_TRABALHO.mkdir(parents=True, exist_ok=True)
    saida = DIR_TRABALHO / f"{nome}_{int(time.time())}.json"
    ps1 = saida.with_suffix(".ps1")
    ps1.write_text(script.replace("__SAIDA__", str(saida)), encoding="utf-8-sig")
    cmd = ("Start-Process powershell -Verb RunAs -WindowStyle Hidden "
           + ("-Wait " if esperar_s else "")
           + f"-ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"{ps1}\"'")
    if esperar_s:
        r = proc.run(["powershell", "-NoProfile", "-Command", cmd],
                     capture_output=True, text=True, timeout=esperar_s)
        return saida, r
    return saida, proc.popen(["powershell", "-NoProfile", "-Command", cmd])


def _ler_saida(saida: Path) -> dict | None:
    if not saida.exists():
        return None
    try:
        return json.loads(saida.read_text(encoding="utf-8-sig"))
    except ValueError:
        return None


def _vigiar(saida: Path, limite_s: float = 3600) -> None:
    """Avisa quando a instalação em segundo plano terminar."""
    def _loop():
        fim = time.time() + limite_s
        while time.time() < fim:
            dados = _ler_saida(saida)
            if dados is not None:
                itens = dados.get("itens") or []
                ok = sum(1 for i in itens if i.get("codigo") in (2, 3))
                msg = (f"Drivers: {ok} de {len(itens)} atualizações instaladas"
                       + (" — reinicie o PC para concluir" if dados.get("reiniciar") else ""))
                try:
                    from yvakor.notificacoes import emitir
                    emitir(msg, "sistema", 2)
                except Exception:
                    _log.debug("exceção ignorada", exc_info=True)
                return
            time.sleep(10)
    threading.Thread(target=_loop, daemon=True, name="yvakor-drivers").start()


def _problemas() -> list[dict]:
    return _ps("Get-PnpDevice -PresentOnly | Where-Object { $_.Status -ne 'OK' } | "
               "Select-Object FriendlyName, Status, InstanceId | ConvertTo-Json -Compress",
               60)


def atualizar(acao: str = "auto", dispositivos: str = "") -> dict:
    acao = (acao or "auto").strip().lower()
    feito: dict = {"ok": True, "acao": acao}

    if acao in ("auto", "windows_update"):
        _progresso("🔧 procurando atualizações de driver no Windows Update")
        try:
            pendentes = _ps(PS_WINDOWS_UPDATE, 150)
        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
            pendentes, feito["windows_update_erro"] = [], str(exc)[:120]
        if pendentes:
            _progresso(f"🔧 instalando {len(pendentes)} driver(s) — aprove o UAC do Windows")
            saida, _ = _elevado(PS1_WINDOWS_UPDATE, "windows_update", None)
            _vigiar(saida)
            feito["windows_update"] = {
                "iniciado": [u.get("Titulo") for u in pendentes],
                "obs": "instalando em segundo plano; aviso quando terminar",
                "acompanhar": f"sistema_drivers_atualizar(acao='status', dispositivos='{saida.name}')"}
        else:
            feito["windows_update"] = "nenhuma atualização de driver pendente"

    if acao in ("auto", "reparar"):
        try:
            alvos = [d for d in _problemas()
                     if not dispositivos or d.get("InstanceId") in dispositivos]
        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
            alvos, feito["reparar_erro"] = [], str(exc)[:120]
        # ROOT\… = aparelho virtual criado por software: remover não reinstala
        virtuais = [d for d in alvos if str(d.get("InstanceId", "")).upper().startswith("ROOT\\")]
        fisicos = [d for d in alvos if d not in virtuais]
        if virtuais:
            feito["virtuais_ignorados"] = [
                f"{d.get('FriendlyName')} ({d.get('Status')}): aparelho virtual; "
                "remover não reinstala e não melhora o PC" for d in virtuais]
        if fisicos:
            _progresso(f"🔧 reinstalando {len(fisicos)} aparelho(s) — aprove o UAC do Windows")
            ids = ", ".join("'" + str(d["InstanceId"]).replace("'", "''") + "'" for d in fisicos)
            try:
                saida, r = _elevado(PS1_REPARAR.replace("__IDS__", ids), "reparar", 180)
                dados = _ler_saida(saida)
                feito["reparar"] = dados if dados is not None else {
                    "erro": "UAC recusado ou não concluído",
                    "detalhe": (getattr(r, "stderr", "") or "")[-200:]}
            except subprocess.TimeoutExpired:
                feito["reparar"] = {"erro": "tempo esgotado esperando o UAC"}
        elif acao == "reparar" and not virtuais:
            feito["reparar"] = "nenhum aparelho com problema"

    if acao == "intel":
        _progresso("🔧 instalando o Intel Driver & Support Assistant (winget)")
        try:
            r = proc.run(["winget", "install", "--id", "Intel.IntelDriverAndSupportAssistant",
                          "-e", "--silent", "--accept-package-agreements",
                          "--accept-source-agreements"],
                         capture_output=True, text=True, timeout=600)
            feito["intel"] = {"codigo": r.returncode, "saida": (r.stdout or "")[-400:],
                              "proximo": "abra o Intel DSA (ícone na bandeja) para "
                                         "aplicar os drivers Intel que ele encontrar"}
        except (subprocess.TimeoutExpired, OSError) as exc:
            feito["intel"] = {"erro": str(exc)[:160]}

    if acao == "status":
        dados = _ler_saida(DIR_TRABALHO / (dispositivos or ""))
        if dados is None:
            return {"ok": True, "status": "ainda instalando (ou UAC recusado)"}
        for i in dados.get("itens") or []:
            i["resultado"] = _WU_CODIGO.get(i.get("codigo"), i.get("codigo"))
        return {"ok": True, "status": "concluído", **dados}

    if acao not in ("auto", "windows_update", "reparar", "intel", "status"):
        return {"ok": False, "erro": "acao: auto | windows_update | reparar | intel | status"}
    return feito


def register_drivers_tools(registry) -> list[str]:
    def sistema_drivers(windows_update: bool = True, acao: str = "", **_extras) -> dict:
        # Exame de 29/10: o modelo chamou sistema_drivers(acao="atualizar") em
        # vez de sistema_drivers_atualizar — e só verificava de novo.
        a = (acao or "").strip().lower()
        if a and a not in ("verificar", "listar", "diagnosticar"):
            return atualizar("auto" if a in ("atualizar", "instalar", "resolver") else a)
        return verificar(str(windows_update).lower() not in ("false", "0", "nao", "não"))

    registry.register(
        "sistema_drivers_atualizar", atualizar,
        "ATUALIZA/REPARA drivers (abre o UAC do Windows para o usuário aprovar). "
        "acao: auto (instala o pendente do Windows Update e reinstala aparelhos "
        "com problema) | windows_update | reparar (dispositivos = InstanceIds, "
        "vazio = todos com problema) | intel (instala o assistente oficial de "
        "drivers da Intel via winget) | status (acompanha instalação).",
        {"acao": "str?", "dispositivos": "str?"})

    registry.register(
        "sistema_drivers", sistema_drivers,
        "Verifica os drivers deste PC (só leitura): aparelhos com problema, "
        "drivers antigos (com versão e data) e atualizações de driver pendentes "
        "no Windows Update. Uma chamada já traz tudo — não repita.",
        {"windows_update": "bool?", "acao": "str?"})
    return ["sistema_drivers", "sistema_drivers_atualizar"]
