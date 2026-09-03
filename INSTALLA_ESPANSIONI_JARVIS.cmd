@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLA_ESPANSIONI_JARVIS.ps1"
echo.
pause
