# Development

Target Windows 10/11 and Python 3.12. Prepare with `Prepara ambiente.cmd`, run with `Avvia Jarvis.cmd`, and keep runtime data below `data/`.

```powershell
.\.runtime-env\Scripts\python.exe -m unittest discover -s tests -v
.\.runtime-env\Scripts\python.exe -m pip check
.\.runtime-env\Scripts\python.exe -m ruff check jarvis_core jarvis_apps jarvis_system jarvis_terminal jarvis_vault jarvis_plugins
.\.runtime-env\Scripts\python.exe -m black --check jarvis_core jarvis_apps jarvis_system jarvis_terminal jarvis_vault jarvis_plugins
.\.runtime-env\Scripts\python.exe -m mypy
.\.runtime-env\Scripts\python.exe -m pytest
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Preserve the critical path `startup -> HUD -> wake -> STT -> intent/AI -> response -> TTS`. Add typed, bounded implementations and regression tests. Do not add parallel buses, memory stores or voice stacks. Administrative features belong in the allowlisted broker. Significant phases require a secret-free checkpoint under `backups/`.
