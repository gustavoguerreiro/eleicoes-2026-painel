@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
python painel_server.py --web %*
pause
