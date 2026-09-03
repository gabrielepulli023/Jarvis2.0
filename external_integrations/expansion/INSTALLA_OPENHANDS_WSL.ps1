$ErrorActionPreference = "Stop"
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "WSL non trovato. OpenHands CLI su Windows richiede WSL."
}
$distros = @(wsl.exe -l -q 2>$null | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($distros.Count -eq 0) {
    throw "Nessuna distribuzione WSL installata. Installa Ubuntu/WSL prima di OpenHands."
}
Write-Host "Installazione OpenHands dentro WSL tramite uv..." -ForegroundColor Cyan
wsl.exe bash -lc 'command -v uv >/dev/null 2>&1 || (curl -LsSf https://astral.sh/uv/install.sh | sh); export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"; uv tool install openhands --python 3.12'
Write-Host "OpenHands installato in WSL. Al primo uso potrebbe chiedere la configurazione LLM." -ForegroundColor Green
