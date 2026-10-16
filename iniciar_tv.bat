@echo off
rem Modo TV / noite da eleição: sobe o servidor (que reinicia sozinho se cair), espera ele responder e só então abre
rem o navegador em tela cheia. Para os amigos acessarem, veja "Noite do 2º turno e colocar no ar" no README.
chcp 65001 >nul
start "Painel (servidor)" /min "%~dp0servidor_loop.bat" %*
echo Aguardando o servidor subir...
:espera
curl -s -f -o nul http://localhost:8765/healthz && goto pronto
timeout /t 1 >nul
goto espera
:pronto
start "" msedge --kiosk "http://localhost:8765/?tv=1#/tela/RN" --edge-kiosk-type=fullscreen
