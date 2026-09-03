"""Include le DLL native che vosk carica dalla propria cartella a runtime."""

from PyInstaller.utils.hooks import collect_dynamic_libs

binaries = collect_dynamic_libs("vosk", destdir="vosk")
