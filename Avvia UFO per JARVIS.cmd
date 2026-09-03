@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "UFO_DIR=%~dp0external_integrations\UFO"
set "UFO_PY=%UFO_DIR%\.ufo-env\Scripts\python.exe"
set "KEY_FILE=%UFO_DIR%\.jarvis_ufo_server_key"

if not exist "%UFO_DIR%\ufo" (
  echo UFO non trovato. Esegui prima "Installa integrazioni JARVIS.cmd".
  pause
  exit /b 1
)
if not exist "%UFO_PY%" (
  echo Ambiente UFO non trovato.
  pause
  exit /b 1
)
if not exist "%UFO_DIR%\config\ufo\agents.yaml" (
  echo Configurazione UFO mancante: %UFO_DIR%\config\ufo\agents.yaml
  pause
  exit /b 1
)

if not exist "%KEY_FILE%" (
  powershell.exe -NoProfile -Command "$p='%KEY_FILE%'; $b=New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Fill($b); $k=[Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_'); [IO.File]::WriteAllText($p,$k,[Text.UTF8Encoding]::new($false))"
)
set /p UFO_KEY=<"%KEY_FILE%"
if "%UFO_KEY%"=="" (
  echo Chiave locale UFO non disponibile.
  pause
  exit /b 1
)

start "UFO Server" cmd /k "cd /d ""%UFO_DIR%"" && ""%UFO_PY%"" -m ufo.server.app --host 127.0.0.1 --port 5000 --api-key "%UFO_KEY%" --platform windows --log-level WARNING"
timeout /t 3 /nobreak >nul
start "UFO Client JARVIS" cmd /k "cd /d ""%UFO_DIR%"" && ""%UFO_PY%"" -m ufo.client.client --ws --ws-server ""ws://127.0.0.1:5000/ws?token=%UFO_KEY%"" --client-id jarvis_windows --platform windows --log-level WARNING"

echo UFO avviato manualmente con autenticazione locale.
pause
endlocal
