@echo off
rem Observatório 3D dos agentes: http://127.0.0.1:8765  (Ctrl+C para sair)
cd /d "%~dp0"
start "" http://127.0.0.1:8765
uv run --frozen python -m trader.observatory
