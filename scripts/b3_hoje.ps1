# Teste de um dia do modo B3 em DRY (papel), com sessão encurtada a partir de agora. Chamado pelo b3_hoje.bat.
# Tudo roda escondido (sem janela). Logs em data\logs\b3hoje-*.log. Para parar: parar.bat
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force "data\logs" | Out-Null
$uv = (Get-Command uv).Source

# sessão de teste: plano em até 25 min, entradas por ~30 min, zeragem 18:10 (o WIN negocia até ~18:25)
$deadline = (Get-Date).AddMinutes(25)
$open = $deadline.AddMinutes(5)
if ($open.ToString("HH:mm") -ge "17:50") { throw "tarde demais para o teste de hoje (abriria depois das 17:50)" }
$env:B3_TEST_SESSION = "{0:HH:mm},{1:HH:mm},17:55,18:10" -f $deadline, $open
"sessão de teste: $env:B3_TEST_SESSION" | Out-File "data\logs\b3hoje-sessao.log"

function Start-Hidden($name, [string[]]$module) {
    Start-Process -FilePath $uv -ArgumentList (@("run", "--frozen", "python", "-m") + $module) -WorkingDirectory $root `
        -WindowStyle Hidden -RedirectStandardOutput "data\logs\b3hoje-$name.log" -RedirectStandardError "data\logs\b3hoje-$name.err.log"
}

$running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'trader\.telegram_daemon' }
if (-not $running) { Start-Hidden "telegram" @("trader.telegram_daemon") }
$obs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'trader\.observatory' }
if (-not $obs) { Start-Hidden "observatorio" @("trader.observatory") }
Start-Hidden "executor" @("trader.executor")
Start-Hidden "manha" @("trader.morning", "--then-plan")
