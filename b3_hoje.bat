@echo off
rem Teste de HOJE do modo B3 em dry (papel): Telegram + observatorio + executor + equipe da manha e plano.
rem Roda em segundo plano, sem janela. Logs: data\logs\b3hoje-*.log   Parar: parar.bat
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File scripts\b3_hoje.ps1
if errorlevel 1 (
    echo Falhou ao iniciar. Veja a mensagem acima.
    pause
    exit /b 1
)
start "" http://127.0.0.1:8765
echo Rodando em segundo plano. Telegram: /b3 e /plano. Observatorio: http://127.0.0.1:8765
timeout /t 5 >nul
