@echo off
setlocal
cd /d "%~dp0"
set "UV_CACHE_DIR=%~dp0.uv-cache"
set "UV_PYTHON_INSTALL_DIR=%~dp0.python"
uv python install 3.12
if errorlevel 1 (
  echo Installazione Python non riuscita. Verifica che uv sia installato.
  pause
  exit /b 1
)
set "JARVIS_BASE_PYTHON="
for /f "delims=" %%P in ('uv python find 3.12 2^>nul') do set "JARVIS_BASE_PYTHON=%%P"
if not exist "%JARVIS_BASE_PYTHON%" (
  echo Runtime Python 3.12 non trovata.
  pause
  exit /b 1
)
if not exist "%~dp0.runtime-env\Scripts\python.exe" (
  "%JARVIS_BASE_PYTHON%" -m venv "%~dp0.runtime-env"
  if errorlevel 1 exit /b 1
)
"%~dp0.runtime-env\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo Installazione dipendenze non riuscita.
  pause
  exit /b 1
)
echo Ambiente JARVIS pronto.
pause
endlocal
