param(
    [string]$ReleaseName = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildEnv = Join-Path $ProjectRoot '.build-env-current'
$UvCache = Join-Path $ProjectRoot '.uv-cache'
$env:UV_CACHE_DIR = $UvCache

if (-not $ReleaseName) {
    $ReleaseName = "dist_reference_exact_release_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
}
$DistRoot = Join-Path $ProjectRoot $ReleaseName
$BuildRoot = Join-Path $ProjectRoot ($ReleaseName -replace '^dist_', 'build_')

$RuntimePython = Join-Path $ProjectRoot '.runtime-env\Scripts\python.exe'
if (Test-Path -LiteralPath $RuntimePython) {
    $PythonExe = $RuntimePython
} else {
    $PythonExe = (& uv python find 3.12 2>$null | Select-Object -First 1)
}

if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) {
    throw 'Python locale mancante. Esegui prima Prepara ambiente.cmd.'
}

if (-not (Test-Path -LiteralPath (Join-Path $BuildEnv 'Scripts\python.exe'))) {
    uv venv --python $PythonExe $BuildEnv
    if ($LASTEXITCODE -ne 0) { throw 'Creazione ambiente di build non riuscita.' }
}
$BuildPython = Join-Path $BuildEnv 'Scripts\python.exe'
$CoreRequirements = Join-Path $ProjectRoot 'requirements.txt'
$IntegrationRequirements = Join-Path $ProjectRoot 'requirements-integrations.txt'
if (Test-Path -LiteralPath $IntegrationRequirements) {
    uv pip install --python $BuildPython -r $CoreRequirements -r $IntegrationRequirements -c $CoreRequirements pyinstaller
} else {
    uv pip install --python $BuildPython -r $CoreRequirements pyinstaller
}
if ($LASTEXITCODE -ne 0) { throw 'Installazione dipendenze di build non riuscita.' }

$PyInstaller = Join-Path $BuildEnv 'Scripts\pyinstaller.exe'
if (-not (Test-Path -LiteralPath $PyInstaller)) { throw "PyInstaller mancante in $BuildEnv" }
& $PyInstaller `
    --noconfirm `
    --windowed `
    --distpath $DistRoot `
    --workpath $BuildRoot `
    --name JARVIS `
    --additional-hooks-dir (Join-Path $ProjectRoot 'pyinstaller_hooks') `
    --add-data "model-it;model-it" `
    --add-data "*.wav;." `
    --add-data "*.mp3;." `
    --add-data "chrome_extension;chrome_extension" `
    --add-data "plugins;plugins" `
    --add-data "config;config" `
    --add-data "assets;assets" `
    --add-data "$(Join-Path $BuildEnv 'Lib\site-packages\cv2\data');cv2\data" `
    --collect-all yfinance `
    --collect-all langgraph `
    --collect-all mem0 `
    --collect-all pipecat `
    --collect-binaries pygame `
    --collect-binaries vosk `
    --hidden-import football_analyst `
    (Join-Path $ProjectRoot 'jarvis_entry.py')

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller non ha completato la build (codice $LASTEXITCODE)."
}

$ExePath = Join-Path $DistRoot 'JARVIS\JARVIS.exe'
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build terminata senza produrre $ExePath"
}

# Alcune dipendenze includono OpenSSL con lo stesso nome; Python deve usare
# esattamente le DLL abbinate al proprio modulo _ssl.pyd.
$PythonBase = (& $PythonExe -c "import sys; print(sys.base_prefix)" | Select-Object -First 1)
$PythonDllDir = Join-Path $PythonBase 'DLLs'
$InternalDir = Join-Path $DistRoot 'JARVIS\_internal'
Copy-Item -LiteralPath (Join-Path $PythonDllDir 'libssl-3-x64.dll') -Destination $InternalDir -Force
Copy-Item -LiteralPath (Join-Path $PythonDllDir 'libcrypto-3-x64.dll') -Destination $InternalDir -Force

# UI-TARS resta un sidecar Node accanto all'EXE. Copia bridge, package e
# node_modules (se l'installer integrazioni li ha già preparati).
$UiTarsSource = Join-Path $ProjectRoot 'external_integrations\ui_tars'
$UiTarsDestination = Join-Path $DistRoot 'JARVIS\external_integrations\ui_tars'
if (Test-Path -LiteralPath $UiTarsSource) {
    New-Item -ItemType Directory -Force -Path $UiTarsDestination | Out-Null
    Copy-Item -Path (Join-Path $UiTarsSource '*') -Destination $UiTarsDestination -Recurse -Force
}


# Browser Use resta un sidecar Python isolato per evitare conflitti con l'SDK OpenAI
# del runtime principale. Copia runner e requirements; l'ambiente va installato
# accanto alla build con lo script integrazioni.
$BrowserSource = Join-Path $ProjectRoot 'external_integrations\browser_use'
$BrowserDestination = Join-Path $DistRoot 'JARVIS\external_integrations\browser_use'
if (Test-Path -LiteralPath $BrowserSource) {
    New-Item -ItemType Directory -Force -Path $BrowserDestination | Out-Null
    Get-ChildItem -LiteralPath $BrowserSource -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $BrowserDestination -Force
    }
}

Write-Host "Build completata: $ExePath"
