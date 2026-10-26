@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  YVAKOR - instalacao da extensao do Chrome
echo  ==========================================
echo.
echo  1) Em chrome://extensions, ative "Modo do desenvolvedor".
echo  2) Clique em "Carregar sem compactacao".
echo  3) Escolha a pasta que sera aberta agora:
echo     %~dp0chrome-extension
echo.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" "chrome://extensions"
start "" explorer "%~dp0chrome-extension"
echo  Apos carregar, clique no icone do YVAKOR na barra do Chrome.
pause
