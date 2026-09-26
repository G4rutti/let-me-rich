@echo off
rem Loop de ciclos: roda um ciclo, espera 30 min, repete. Chamado pelo iniciar.bat.
title let-me-rich-ciclo
cd /d "%~dp0.."
:loop
echo [%date% %time%] ciclo >> data\logs\ciclos.log
uv run --frozen python -m trader.run_cycle >> data\logs\ciclos.log 2>&1
timeout /t 1800 /nobreak >nul
goto loop
