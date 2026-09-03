param(
    [switch]$SkipTests,
    [int]$TestTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".runtime-env\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Runtime Python non trovato: $python" }
Set-Location -LiteralPath $root

function Invoke-Gate([string]$Label, [scriptblock]$Command) {
    Write-Host "=== $Label ===" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label fallito con codice $LASTEXITCODE" }
}

$modernPaths = @(
    "llm_gateway.py", "jarvis_entry.py", "jarvis_core", "jarvis_apps", "jarvis_system",
    "jarvis_terminal", "jarvis_vault", "jarvis_plugins", "jarvis_browser", "jarvis_automation",
    "jarvis_companion", "jarvis_windows", "jarvis_files", "jarvis_missions", "jarvis_memory",
    "jarvis_perception", "jarvis_skills", "football_analyst.py"
)

if (-not $SkipTests) {
    Invoke-Gate "unittest" { & $python -m unittest discover -s tests -v }
}
Invoke-Gate "pip check" { & $python -m pip check }
Invoke-Gate "ruff (architettura moderna)" { & $python -m ruff check @modernPaths }
Invoke-Gate "black (architettura moderna)" { & $python -m black --check @modernPaths }
Invoke-Gate "mypy" { & $python -m mypy }

$testFiles = @(Get-ChildItem -LiteralPath (Join-Path $root "tests") -Filter "test_*.py" -File)
Write-Host ("Quality gate completato: {0} test module, timestamp {1}" -f $testFiles.Count, (Get-Date -Format o)) -ForegroundColor Green
