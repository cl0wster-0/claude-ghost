@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] Устанавливаю зависимости Python...
py -m pip install --upgrade -r requirements.txt || python -m pip install --upgrade -r requirements.txt
echo.
echo [2/2] Проверяю Claude Code CLI...
where claude >nul 2>nul
if errorlevel 1 (
  echo Claude Code не найден. Установите его в PowerShell:
  echo     irm https://claude.ai/install.ps1 ^| iex
  echo затем откройте новый терминал и выполните: claude   ^(и войдите через /login^)
) else (
  echo Claude Code найден. Если ещё не входили - выполните в терминале: claude
)
echo.
echo Готово. Запуск: start.bat
pause
