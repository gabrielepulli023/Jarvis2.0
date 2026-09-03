@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0TESTA_ESPANSIONI_JARVIS.ps1"
echo.
pause
