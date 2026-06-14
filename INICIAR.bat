@echo off
REM ============================================================
REM  YVAKOR - Inicializador do sistema (Windows)
REM  (c) 2026 Antonio Jose Cordero Martinez / ACM Digital
REM ============================================================
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title YVAKOR - Agente Pessoal Evolutivo

cd /d "%~dp0"

echo.
echo  ============================================
echo    YVAKOR - inicializando ambiente...
echo  ============================================
echo.

REM --- 1. Verifica Python -----------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo  [ERRO] Python nao encontrado no PATH.
    echo         Instale Python 3.10+ em https://python.org
    echo.
    pause
    exit /b 1
)

REM --- 2. Cria/usa ambiente virtual -------------------------
if not exist "venv\Scripts\python.exe" (
    echo  [setup] Criando ambiente virtual ^(venv^)...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERRO] Falha ao criar o venv.
        pause
        exit /b 1
    )
)
set PY=venv\Scripts\python.exe

REM --- 3. Instala/atualiza dependencias ---------------------
echo  [setup] Verificando dependencias...
"%PY%" -m pip install --quiet --upgrade pip >nul 2>nul
"%PY%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo  [ERRO] Falha ao instalar dependencias.
    pause
    exit /b 1
)

REM --- 4. Verifica arquivo .env -----------------------------
if not exist ".env" (
    echo.
    echo  [aviso] Arquivo .env nao encontrado. Criando a partir do exemplo...
    copy ".env.example" ".env" >nul
    echo  [acao]  EDITE o arquivo .env e coloque sua DEEPSEEK_API_KEY
    echo          antes de conversar com o agente.
    echo.
)

REM --- 5. Smoke test rapido ---------------------------------
echo  [check] Testando integridade do nucleo...
"%PY%" tests\test_smoke.py
if errorlevel 1 (
    echo  [ERRO] Smoke test falhou. Verifique a instalacao.
    pause
    exit /b 1
)

REM --- 6. Menu de inicializacao -----------------------------
:menu
echo.
echo  ============================================
echo    Como deseja iniciar o YVAKOR?
echo  ============================================
echo    [1] Interface 3D ^(navegador, http://localhost:7777^)
echo    [2] Terminal ^(modo chat no console^)
echo    [3] Autoaprendizado ^(gera novas skills do seu perfil^)
echo    [4] Apenas sair
echo  ============================================
set /p OPC="  Escolha (1/2/3/4): "

if "%OPC%"=="1" goto web
if "%OPC%"=="2" goto cli
if "%OPC%"=="3" goto aprender
if "%OPC%"=="4" exit /b 0
echo  Opcao invalida.
goto menu

:aprender
echo.
echo  Iniciando autoaprendizado (usa a IA principal)...
"%PY%" -m yvakor.learning.bootstrap
echo.
pause
goto menu

:web
echo.
echo  Encerrando qualquer servidor antigo na porta 7777...
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 7777 -State Listen -ErrorAction SilentlyContinue; if($c){$c.OwningProcess|Sort-Object -Unique|ForEach-Object{Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue}}"
echo  Limpando cache Python (.pyc)...
for /d /r "%~dp0yvakor" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
echo  Iniciando interface 3D... abrindo navegador.
start "" "http://localhost:7777"
"%PY%" -m yvakor.server
goto end

:cli
echo.
"%PY%" -m yvakor.main
goto end

:end
echo.
echo  YVAKOR encerrado.
pause
