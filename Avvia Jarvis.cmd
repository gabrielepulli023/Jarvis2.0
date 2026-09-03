@echo off
setlocal
cd /d "%~dp0"
title JARVIS 2.0 - SOURCE
echo [JARVIS2.0] Avvio sorgente da "%~dp0"
set "JARVIS_DATA_DIR=%~dp0data"
set "JARVIS_PYTHON=%~dp0.runtime-env\Scripts\python.exe"
if not exist "%JARVIS_PYTHON%" (
  echo Ambiente runtime non trovato. Esegui Prepara ambiente.cmd una volta.
  pause
  exit /b 1
)
"%JARVIS_PYTHON%" "%~dp0main.py"
if errorlevel 1 pause
endlocal
