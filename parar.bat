@echo off
rem Para o bot (daemon + loop de ciclos). NAO vende nada: stops e alvos continuam na Binance.
rem Para zerar tudo (cancelar ordens e vender): /kill confirmar no Telegram.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bot_procs.ps1 -Kill
echo Bot parado. Ordens de protecao continuam ativas na Binance.
timeout /t 5 >nul
