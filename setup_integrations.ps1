$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".runtime-env\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Ambiente .runtime-env non trovato. Esegui prima 'Prepara ambiente.cmd'."
}

Write-Host "[1/5] Installo LangGraph, Mem0 e Pipecat nel runtime stabile JARVIS..."
& $Python -m pip install -r (Join-Path $Root "requirements-integrations.txt") -c (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Installazione LangGraph/Mem0/Pipecat fallita o incompatibile con il runtime stabile."
}

& $Python -c "import langgraph, mem0, pipecat; print('LangGraph, Mem0 e Pipecat importabili')"
if ($LASTEXITCODE -ne 0) {
    throw "Almeno una tra LangGraph, Mem0 e Pipecat non e' importabile."
}

Write-Host "[2/5] Installo Browser Use in un ambiente Python ISOLATO..."
$BrowserDir = Join-Path $Root "external_integrations\browser_use"
$BrowserEnv = Join-Path $BrowserDir ".browser-use-env"
$BrowserPython = Join-Path $BrowserEnv "Scripts\python.exe"
$BrowserReq = Join-Path $Root "requirements-browser-use.txt"
$BrowserRunner = Join-Path $BrowserDir "browser_use_runner.py"

New-Item -ItemType Directory -Force -Path $BrowserDir | Out-Null
if (-not (Test-Path $BrowserRunner)) {
    throw "Runner Browser Use mancante: $BrowserRunner"
}

if (-not (Test-Path $BrowserPython)) {
    & $Python -m venv $BrowserEnv
    if ($LASTEXITCODE -ne 0) {
        throw "Creazione ambiente isolato Browser Use fallita."
    }
}

& $BrowserPython -m pip install -U pip
if ($LASTEXITCODE -ne 0) { throw "Aggiornamento pip Browser Use fallito." }
& $BrowserPython -m pip install -r $BrowserReq
if ($LASTEXITCODE -ne 0) {
    throw "Installazione Browser Use nell'ambiente isolato fallita."
}
& $BrowserPython -c "import browser_use, openai; print('Browser Use isolato OK - OpenAI sidecar', openai.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "Browser Use installato ma non importabile nel sidecar."
}

Write-Host "[3/5] Preparo Chromium per Browser Use..."
if (Get-Command uvx -ErrorAction SilentlyContinue) {
    uvx browser-use install
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Chromium Browser Use non installato automaticamente; riprova con: uvx browser-use install"
    }
} else {
    Write-Warning "uvx non trovato. Browser Use e' installato; per Chromium installa uv e poi esegui: uvx browser-use install"
}

Write-Host "[4/5] Preparo bridge UI-TARS..."
$UiDir = Join-Path $Root "external_integrations\ui_tars"
if (Get-Command node -ErrorAction SilentlyContinue) {
    $VersionText = (& node --version).Trim().TrimStart('v')
    $Major = [int]($VersionText.Split('.')[0])
    if ($Major -lt 20) {
        Write-Warning "UI-TARS richiede Node.js 20 o superiore. Versione trovata: $VersionText"
    } elseif (Get-Command npm -ErrorAction SilentlyContinue) {
        Push-Location $UiDir
        try {
            npm install --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "npm install UI-TARS non completato."
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Warning "Node.js trovato ma npm non disponibile."
    }
} else {
    Write-Warning "Node.js non trovato: UI-TARS restera' non disponibile finche' Node 20+ non viene installato."
}

Write-Host "[5/5] Preparo Microsoft UFO in ambiente Python separato..."
$UfoDir = Join-Path $Root "external_integrations\UFO"
if (-not (Test-Path $UfoDir)) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Host "Clono Microsoft UFO in external_integrations\UFO..."
        git clone --depth 1 https://github.com/microsoft/UFO.git $UfoDir
        if ($LASTEXITCODE -ne 0) { Write-Warning "Clone UFO non completato." }
    } else {
        Write-Warning "Git non trovato: scarica Microsoft UFO manualmente in external_integrations\UFO."
    }
}

if (Test-Path (Join-Path $UfoDir "requirements.txt")) {
    $UfoEnv = Join-Path $UfoDir ".ufo-env"
    $UfoPython = Join-Path $UfoEnv "Scripts\python.exe"

    if (-not (Test-Path $UfoPython)) {
        $Created = $false
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            Write-Host "Installo Python 3.10 isolato per UFO..."
            uv python install 3.10
            if ($LASTEXITCODE -eq 0) {
                $BasePython = (& uv python find 3.10 | Select-Object -First 1).Trim()
                if ($BasePython -and (Test-Path $BasePython)) {
                    & $BasePython -m venv $UfoEnv
                    $Created = ($LASTEXITCODE -eq 0)
                }
            }
        }
        if (-not $Created -and (Get-Command py -ErrorAction SilentlyContinue)) {
            py -3.10 -m venv $UfoEnv
            $Created = ($LASTEXITCODE -eq 0)
        }
        if (-not $Created) {
            Write-Warning "Non riesco a creare l'ambiente UFO con Python 3.10. Installa Python 3.10 o usa uv, poi rilancia questo script."
        }
    }

    if (Test-Path $UfoPython) {
        & $UfoPython -m pip install -U pip
        if ($LASTEXITCODE -ne 0) { throw "Aggiornamento pip nell'ambiente UFO fallito." }
        & $UfoPython -m pip install -r (Join-Path $UfoDir "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "Installazione dipendenze UFO fallita." }
        Push-Location $UfoDir
        try {
            & $UfoPython -c "import ufo; print('UFO importabile')"
            if ($LASTEXITCODE -ne 0) { throw "UFO installato ma non importabile." }
        } finally {
            Pop-Location
        }

        $AgentsTemplate = Join-Path $UfoDir "config\ufo\agents.yaml.template"
        $AgentsConfig = Join-Path $UfoDir "config\ufo\agents.yaml"
        if ((Test-Path $AgentsTemplate) -and -not (Test-Path $AgentsConfig)) {
            Copy-Item $AgentsTemplate $AgentsConfig
            Write-Warning "Creato config\ufo\agents.yaml dal template. Inserisci la configurazione LLM prima di usare UFO."
        }
    }
}

Write-Host ""
Write-Host "Installazione integrazioni completata."
Write-Host "- LangGraph, Mem0, Pipecat: runtime JARVIS"
Write-Host "- Browser Use: ambiente isolato external_integrations\browser_use\.browser-use-env"
Write-Host "- UI-TARS: bridge Node separato"
Write-Host "- UFO: ambiente isolato external_integrations\UFO\.ufo-env"
Write-Host ""
Write-Host "Il runtime principale mantiene OpenAI 2.53.0; Browser Use usa la propria versione nel sidecar."
