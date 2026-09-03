@echo off
where npx >nul 2>nul
if errorlevel 1 (
  echo Node.js/npm non trovato. Installa Node.js LTS prima di Screenpipe.
  pause
  exit /b 1
)
echo Screenpipe registrera' schermo/audio localmente. Chiudi questa finestra per fermarlo.
echo.
npx -y screenpipe record
pause
