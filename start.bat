@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw "%~dp0ghost.py") || (start "" pythonw "%~dp0ghost.py")
