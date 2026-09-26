@echo off
rem Liga o bot em segundo plano (janelas minimizadas): daemon do Telegram + ciclo a cada 30 min.
rem Para parar: parar.bat  (ou /pause no Telegram para so bloquear entradas novas)
cd /d "%~dp0"
if not exist data\logs mkdir data\logs

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bot_procs.ps1
if %errorlevel%==0 (
    echo O bot ja esta rodando. Use parar.bat antes de iniciar de novo.
    pause
    exit /b 1
)

start "let-me-rich-daemon" /min cmd /c "uv run --frozen python -m trader.telegram_daemon >> data\logs\daemon.log 2>&1"
start "let-me-rich-ciclo" /min cmd /c scripts\ciclo_loop.bat

echo Bot iniciado: 2 janelas minimizadas (let-me-rich-daemon e let-me-rich-ciclo).
echo Logs em data\logs\. Para parar: parar.bat
timeout /t 5 >nul
