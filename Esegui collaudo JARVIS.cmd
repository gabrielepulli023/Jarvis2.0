@echo off
setlocal
cd /d "%~dp0"
echo Il collaudo apre e chiude un file temporaneo in Blocco note.
echo Nessuna finestra gia aperta verra chiusa.
set "JARVIS_TEST_ARGS="
choice /C SN /N /M "Vuoi misurare 2 secondi dal microfono senza salvare l'audio? [S/N] "
if errorlevel 2 goto broker_prompt
set "JARVIS_TEST_ARGS=--audio-sample"
:broker_prompt
choice /C SN /N /M "Vuoi includere il test broker con richiesta UAC? [S/N] "
if errorlevel 2 goto run_tests
set "JARVIS_TEST_ARGS=%JARVIS_TEST_ARGS% --broker"
:run_tests
".runtime-env\Scripts\python.exe" "tests\manual_windows_acceptance.py" %JARVIS_TEST_ARGS%
echo.
pause
