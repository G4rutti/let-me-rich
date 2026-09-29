# Cria as tarefas do Agendador do Windows para o modo B3 (WIN). Rode SÓ depois do smoke com tudo OK.
#   powershell -ExecutionPolicy Bypass -File scripts\install_tasks_b3.ps1 [-ReviseEveryMin 20]
# Horários de Brasília; ajuste se mudar o pregão (horário de verão dos EUA) junto com config\b3.yaml.
# A trava de perda total (watchdog) desliga TODAS estas tarefas; religar é à mão (schtasks /Change /TN ... /ENABLE).
# O terminal MT5 tem que estar aberto e logado, com Algo Trading ligado, antes das 07:45.
param([int]$ReviseEveryMin = 20)

$root = Split-Path -Parent $PSScriptRoot
$uv = (Get-Command uv -ErrorAction Stop).Source
New-Item -ItemType Directory -Force "$root\data\logs" | Out-Null
$weekdays = @("/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI")

function New-B3Task($name, $module, $schedule) {
    $cmd = "cmd /c cd /d `"$root`" && `"$uv`" run --frozen python -m $module >> data\logs\b3.log 2>&1"
    schtasks /Create /TN $name /TR $cmd @schedule /F | Out-Null
    Write-Host "criada: $name"
}

New-B3Task "let-me-rich-b3-morning"  "trader.morning"                ($weekdays + @("/ST", "07:45"))
New-B3Task "let-me-rich-b3-plan"     "trader.run_b3 --kind plan"     ($weekdays + @("/ST", "08:15"))
New-B3Task "let-me-rich-b3-executor" "trader.executor"               ($weekdays + @("/ST", "08:55"))
New-B3Task "let-me-rich-b3-watchdog" "trader.watchdog"               ($weekdays + @("/ST", "08:56"))
New-B3Task "let-me-rich-b3-revise"   "trader.run_b3 --kind revise"   ($weekdays + @("/ST", "10:00", "/RI", "$ReviseEveryMin", "/DU", "06:05"))
New-B3Task "let-me-rich-b3-close"    "trader.run_b3 --kind close"    ($weekdays + @("/ST", "17:45"))
New-B3Task "let-me-rich-b3-weekly"   "trader.run_b3 --kind weekly"   @("/SC", "WEEKLY", "/D", "SAT", "/ST", "10:00")

Write-Host "Pronto. Parar tudo: /kill confirmar no Telegram, ou python -m trader.kill --yes (zera o WIN e desliga as tarefas)."
