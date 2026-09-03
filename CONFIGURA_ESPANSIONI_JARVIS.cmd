@echo off
cd /d "%~dp0"
set "PY=%~dp0external_integrations\expansion\.expansion-env\Scripts\python.exe"
if not exist "%PY%" (
  echo Ambiente espansioni non trovato. Esegui prima INSTALLA ESPANSIONI JARVIS.cmd
  pause
  exit /b 1
)
"%PY%" "%~dp0external_integrations\expansion\configure_expansion.py"
echo.
pause
