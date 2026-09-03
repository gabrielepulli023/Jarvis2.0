$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Expansion = Join-Path $Root "external_integrations\expansion"
$EnvPython = Join-Path $Expansion ".expansion-env\Scripts\python.exe"
$RuntimePython = Join-Path $Root ".runtime-env\Scripts\python.exe"

Write-Host "JARVIS - installazione Mega Expansion Pack" -ForegroundColor Cyan
if (-not (Test-Path $RuntimePython)) {
    Write-Host "Runtime Python JARVIS non trovato: $RuntimePython" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $EnvPython)) {
    Write-Host "[1/5] Creo ambiente Python isolato .expansion-env..."
    & $RuntimePython -m venv (Join-Path $Expansion ".expansion-env")
    if ($LASTEXITCODE -ne 0) { Write-Host "Creazione ambiente fallita." -ForegroundColor Red; exit 1 }
} else {
    Write-Host "[1/5] Ambiente .expansion-env gia' presente."
}

Write-Host "[2/5] Aggiorno pip/setuptools/wheel..."
& $EnvPython -m pip install --upgrade pip setuptools wheel

Write-Host "[3/5] Installa componenti core (MCP, Keyring, Watchdog, OpenTelemetry, DXcam, MarkItDown, Qdrant, Ruff, ESPHome, Silero VAD)..."
& $EnvPython -m pip install -r (Join-Path $Expansion "requirements-core.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "AVVISO: uno o piu' componenti core non si sono installati. JARVIS continuera' comunque ad avviarsi." -ForegroundColor Yellow
}

Write-Host "[4/5] Installa componenti AI/Web pesanti (Docling, Crawl4AI, LiteLLM)..."
& $EnvPython -m pip install -r (Join-Path $Expansion "requirements-ai-web.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "AVVISO: installazione Docling/Crawl4AI/LiteLLM parziale o fallita. Gli altri moduli restano utilizzabili." -ForegroundColor Yellow
}

Write-Host "[5/5] Preparo Chromium per Crawl4AI..."
& $EnvPython -m playwright install chromium 2>$null
if ($LASTEXITCODE -ne 0) {
    $CrawlSetup = Join-Path (Split-Path $EnvPython -Parent) "crawl4ai-setup.exe"
    if (Test-Path $CrawlSetup) { & $CrawlSetup }
}

Write-Host ""
Write-Host "Installazione Python completata." -ForegroundColor Green
Write-Host "Ora esegui 'TESTA ESPANSIONI JARVIS.cmd'."
Write-Host "Per Ollama/llama.cpp/Screenpipe/SearXNG/OpenHands usa i comandi nella cartella external_integrations\expansion."
