@echo off
where llama-server >nul 2>nul
if errorlevel 1 (
  echo llama.cpp non trovato. Esegui INSTALLA EXTRA ESTERNI.cmd.
  pause
  exit /b 1
)
echo Avvio llama.cpp con un modello 1B scaricato da Hugging Face al primo avvio.
llama-server -hf ggml-org/gemma-3-1b-it-GGUF --host 127.0.0.1 --port 8080
pause
