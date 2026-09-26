# Cria as tarefas do Agendador do Windows. Rode SÓ depois do primeiro ciclo live manual (etapa 7).
#   powershell -ExecutionPolicy Bypass -File scripts\install_tasks.ps1 [-IntervalMin 30]
# As tarefas rodam com o seu usuário logado (usam o login do Claude Code em %USERPROFILE%\.claude).
param([int]$IntervalMin = 30)

$root = Split-Path -Parent $PSScriptRoot
$uv = (Get-Command uv -ErrorAction Stop).Source
New-Item -ItemType Directory -Force "$root\data\logs" | Out-Null

function New-BotTask($name, $args, $schedule) {
    $cmd = "cmd /c cd /d `"$root`" && `"$uv`" run --frozen python -m $args >> data\logs\scheduler.log 2>&1"
    schtasks /Create /TN $name /TR $cmd @schedule /F | Out-Null
    Write-Host "criada: $name"
}

New-BotTask "let-me-rich-cycle"  "trader.run_cycle"          @("/SC", "MINUTE", "/MO", "$IntervalMin")
New-BotTask "let-me-rich-weekly" "trader.run_cycle --weekly" @("/SC", "WEEKLY", "/D", "SUN", "/ST", "20:00")
New-BotTask "let-me-rich-daemon" "trader.telegram_daemon"    @("/SC", "ONLOGON")

Write-Host "Pronto. Para parar tudo: /kill confirmar no Telegram, ou: schtasks /Change /TN let-me-rich-cycle /DISABLE"
