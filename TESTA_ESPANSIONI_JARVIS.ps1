$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$KeyFile = Join-Path $Root "external_integrations\expansion\.jarvis_expansion_key"
$Port = 5199

Write-Host "JARVIS - test Mega Expansion Pack" -ForegroundColor Cyan
$checks = 0
$fails = 0
function Result($name, $ok, $detail="") {
    $script:checks++
    if ($ok) { Write-Host "[OK]   $name $detail" -ForegroundColor Green }
    else { $script:fails++; Write-Host "[FAIL] $name $detail" -ForegroundColor Red }
}

Result "jarvis_expansion package" (Test-Path (Join-Path $Root "jarvis_expansion\client.py"))
Result "expansion_server.py" (Test-Path (Join-Path $Root "external_integrations\expansion\expansion_server.py"))
Result ".expansion-env" (Test-Path (Join-Path $Root "external_integrations\expansion\.expansion-env\Scripts\python.exe"))

$listen = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
Result "sidecar porta 5199" ($listen.Count -gt 0) "(JARVIS deve essere aperto)"

if (Test-Path $KeyFile) {
    $key = (Get-Content $KeyFile -Raw).Trim()
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:5199/health" -Headers @{"X-JARVIS-Expansion-Key"=$key} -TimeoutSec 5
        Result "Expansion health" ($health.success -and $health.status -eq "healthy")
    } catch { Result "Expansion health" $false }

    try {
        $body = @{action="status"; arguments=@{deep=$false}} | ConvertTo-Json -Depth 6
        $status = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5199/execute" -Headers @{"X-JARVIS-Expansion-Key"=$key} -ContentType "application/json" -Body $body -TimeoutSec 30
        Result "Expansion status" ($status.success)
        if ($status.success) {
            $status.data.PSObject.Properties | ForEach-Object {
                $name = $_.Name
                $value = $_.Value | ConvertTo-Json -Compress -Depth 4
                Write-Host ("       {0}: {1}" -f $name, $value) -ForegroundColor DarkGray
            }
        }
    } catch { Result "Expansion status" $false }
} else {
    Result "chiave sidecar" $false "(avvia JARVIS una volta)"
}

Write-Host ""
Write-Host "Test: $checks  Falliti: $fails"
if ($fails -eq 0) { Write-Host "MEGA EXPANSION PACK OPERATIVO" -ForegroundColor Green }
else { Write-Host "Alcuni moduli/servizi possono essere opzionali o non ancora configurati." -ForegroundColor Yellow }
