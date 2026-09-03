@echo off
"%~dp0.runtime-env\Scripts\python.exe" -c "import chrome_bridge; chrome_bridge.write_extension_config()"
if errorlevel 1 (
  echo Impossibile generare la credenziale locale del bridge.
  pause
  exit /b 1
)
start "" chrome "chrome://extensions"
start "" explorer "%~dp0chrome_extension"
echo Attiva Modalita sviluppatore, scegli Carica estensione non pacchettizzata e seleziona la cartella aperta.
pause
