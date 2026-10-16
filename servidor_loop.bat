@echo off
rem Mantém o servidor do painel no ar: se ele cair, sobe de novo em 3 s. Usado por iniciar_tv.bat.
chcp 65001 >nul
cd /d "%~dp0backend"
:laco
python painel_server.py --web --sem-navegador %*
echo O servidor caiu. Reiniciando em 3 s... (feche esta janela para parar)
timeout /t 3 >nul
goto laco
