@echo off
cd /d "%~dp0"
where docker >nul 2>nul
if errorlevel 1 (
  echo Docker non trovato. Installa Docker Desktop prima di SearXNG.
  pause
  exit /b 1
)
docker compose up -d
if errorlevel 1 (
  echo Avvio SearXNG fallito.
  pause
  exit /b 1
)
echo SearXNG avviato su http://127.0.0.1:8088
pause
