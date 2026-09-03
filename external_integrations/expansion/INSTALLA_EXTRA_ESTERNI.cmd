@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALLA_EXTRA_ESTERNI.ps1"
echo.
pause
