# Lista (ou mata, com -Kill) os processos do bot pela linha de comando. Usado por iniciar.bat e parar.bat.
param([switch]$Kill)
$roots = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'cmd.exe' -and $_.CommandLine -match 'ciclo_loop\.bat|trader\.telegram_daemon'
}
if ($Kill) {
    foreach ($p in $roots) { taskkill /T /F /PID $p.ProcessId 2>&1 | Out-Null }
    # sobras (ex.: ciclo órfão)
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'trader\.(run_cycle|mcp_server|telegram_daemon)' } |
        ForEach-Object { taskkill /T /F /PID $_.ProcessId 2>&1 | Out-Null }
} elseif ($roots) { exit 0 } else { exit 1 }
