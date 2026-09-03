$ErrorActionPreference = "Continue"
Write-Host "JARVIS - installazione componenti esterni" -ForegroundColor Cyan
Write-Host "Questi programmi restano separati dal runtime Python di JARVIS." -ForegroundColor DarkGray

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "`n[1/2] Ollama..."
    winget install --id Ollama.Ollama -e --source winget --accept-source-agreements --accept-package-agreements
    Write-Host "`n[2/2] llama.cpp..."
    winget install llama.cpp --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "winget non trovato: Ollama e llama.cpp non installati automaticamente." -ForegroundColor Yellow
}

Write-Host "`nScreenpipe: adapter pronto. Per attivare la registrazione usa AVVIA_SCREENPIPE.cmd." -ForegroundColor Yellow
Write-Host "SearXNG: richiede Docker/Podman. Usa la cartella searxng inclusa dopo aver installato Docker." -ForegroundColor Yellow
Write-Host "OpenHands: su Windows e' supportato tramite WSL. Usa INSTALLA_OPENHANDS_WSL.ps1." -ForegroundColor Yellow
Write-Host "Home Assistant/ESPHome: adapter pronto; richiedono il tuo server/dispositivi." -ForegroundColor Yellow
