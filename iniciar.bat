@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
python -c "import sys; print('Python em uso:', sys.executable)"
python painel_server.py --web %*
pause
