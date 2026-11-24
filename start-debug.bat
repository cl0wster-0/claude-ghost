@echo off
chcp 65001 >nul
cd /d "%~dp0"
py "%~dp0ghost.py" || python "%~dp0ghost.py"
pause
