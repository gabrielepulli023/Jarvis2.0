from __future__ import annotations
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import psutil
from jarvis_core.logging import redact


@dataclass(frozen=True, slots=True)
class AppRecord:
    name: str
    executable: str | None = None
    shortcut: str | None = None
    source: str = "known"
    package_id: str | None = None


@dataclass(frozen=True, slots=True)
class Resolution:
    query: str
    matches: tuple[AppRecord, ...]
    exact: AppRecord | None
    ambiguous: bool


class AppManager:
    """Installed-app discovery and broker-routed package management."""

    _PROTECTED = {"csrss.exe", "lsass.exe", "services.exe", "smss.exe", "wininit.exe", "winlogon.exe", "system"}

    def __init__(self, broker, processes, windows=None):
        self.broker = broker
        self.processes = processes
        self.windows = windows

    @staticmethod
    def _key(value: str) -> str:
        return " ".join(str(value).casefold().replace(".exe", "").split())

    def discover(self) -> list[AppRecord]:
        records: dict[str, AppRecord] = {}
        try:
            from tools import APPS

            for name, data in APPS.items():
                executable = next(
                    (
                        os.path.expandvars(path)
                        for path in data.get("percorsi", ())
                        if "\\" not in path or Path(os.path.expandvars(path)).exists()
                    ),
                    None,
                )
                records.setdefault(self._key(name), AppRecord(name, executable=executable, source="known"))
        except (ImportError, AttributeError, TypeError):
            pass
        roots = [
            Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.getenv("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        for root in roots:
            if not root.exists():
                continue
            try:
                shortcuts = root.rglob("*.lnk")
            except OSError:
                continue
            for path in shortcuts:
                name = path.stem.strip()
                records.setdefault(self._key(name), AppRecord(name, shortcut=str(path), source="start_menu"))
        if os.name == "nt":
            self._registry_apps(records)
        return sorted(records.values(), key=lambda item: item.name.casefold())

    def _registry_apps(self, records: dict) -> None:
        try:
            import winreg
        except ImportError:
            return
        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, key_name in locations:
            try:
                key = winreg.OpenKey(hive, key_name)
            except OSError:
                continue
            with key:
                for index in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        child = winreg.OpenKey(key, winreg.EnumKey(key, index))
                        name = str(winreg.QueryValueEx(child, "DisplayName")[0]).strip()
                        try:
                            location = str(winreg.QueryValueEx(child, "InstallLocation")[0]).strip()
                        except OSError:
                            location = ""
                        child.Close()
                        records.setdefault(
                            self._key(name), AppRecord(name, executable=location or None, source="registry")
                        )
                    except OSError:
                        continue

    def resolve(self, query: str) -> Resolution:
        key = self._key(query)
        matches = tuple(
            item for item in self.discover() if key and (key == self._key(item.name) or key in self._key(item.name))
        )
        exact = next((item for item in matches if self._key(item.name) == key), None)
        return Resolution(str(query), matches, exact, len(matches) > 1 and exact is None)

    def open(self, query: str) -> dict:
        resolution = self.resolve(query)
        if resolution.ambiguous:
            return {
                "success": False,
                "message": "Nome applicazione ambiguo.",
                "data": {"matches": [asdict(x) for x in resolution.matches[:20]]},
            }
        app = resolution.exact or (resolution.matches[0] if len(resolution.matches) == 1 else None)
        if app is None:
            return {"success": False, "message": "Applicazione non trovata."}
        target = app.shortcut or app.executable
        if not target:
            return {"success": False, "message": "Applicazione rilevata senza percorso avviabile."}
        try:
            if os.name == "nt":
                os.startfile(target)
            else:
                self.processes.start([target])
        except OSError as exc:
            return {"success": False, "message": redact(f"Avvio fallito: {exc}")}
        return {"success": True, "message": f"Avvio di {app.name} richiesto.", "data": asdict(app)}

    def close(self, query: str, timeout: float = 5) -> dict:
        """Request WM_CLOSE through WindowManager; never force-kills a process."""
        if self.windows is None:
            return {"success": False, "message": "Window Manager non disponibile."}
        matches = self.windows.find(query)
        if not matches:
            return {"success": False, "message": "Nessuna finestra applicazione trovata."}
        requested = sum(bool(self.windows.backend.close(item.handle)) for item in matches)
        deadline = __import__("time").monotonic() + max(0.1, min(float(timeout), 30))
        while __import__("time").monotonic() < deadline:
            remaining = {item.handle for item in self.windows.find(query)}
            if not remaining:
                return {
                    "success": True,
                    "message": f"Chiuse {requested} finestre.",
                    "data": {"requested": requested, "remaining": []},
                }
            __import__("time").sleep(0.05)
        return {
            "success": False,
            "message": "Alcune finestre non si sono chiuse entro il timeout.",
            "data": {"requested": requested, "remaining": sorted(remaining)},
        }

    def close_except(self, keep: list[str] | tuple[str, ...], timeout: float = 5) -> dict:
        """Gracefully close visible application windows except an explicit allowlist."""
        if self.windows is None:
            return {"success": False, "message": "Window Manager non disponibile."}
        needles = {self._key(item) for item in keep if self._key(item)}
        if not needles:
            return {"success": False, "message": "Indicare almeno un'applicazione da mantenere aperta."}
        requested = []
        skipped = []
        for item in self.windows.backend.list_windows():
            identity = self._key(f"{item.title} {item.executable or ''}")
            executable = Path(item.executable or "").name.casefold()
            if executable in self._PROTECTED or "jarvis" in identity or any(key in identity for key in needles):
                skipped.append(item.handle)
                continue
            if self.windows.backend.close(item.handle):
                requested.append(item.handle)
        deadline = __import__("time").monotonic() + max(0.1, min(float(timeout), 30))
        remaining = set(requested)
        while remaining and __import__("time").monotonic() < deadline:
            open_handles = {item.handle for item in self.windows.backend.list_windows()}
            remaining &= open_handles
            if remaining:
                __import__("time").sleep(0.05)
        return {
            "success": not remaining,
            "message": "Chiusura selettiva completata." if not remaining else "Alcune finestre non si sono chiuse.",
            "data": {"requested": requested, "remaining": sorted(remaining), "kept": skipped},
        }

    def terminate(self, query: str, timeout: float = 5) -> dict:
        resolution = self.resolve(query)
        app = resolution.exact or (resolution.matches[0] if len(resolution.matches) == 1 else None)
        if resolution.ambiguous:
            return {
                "success": False,
                "message": "Nome applicazione ambiguo.",
                "data": {"matches": [x.name for x in resolution.matches[:20]]},
            }
        if app is None:
            return {"success": False, "message": "Applicazione non trovata."}
        expected = (
            Path(app.executable).name.casefold()
            if app.executable and Path(app.executable).suffix
            else self._key(app.name).replace(" ", "") + ".exe"
        )
        if expected in self._PROTECTED:
            return {"success": False, "message": "Processo Windows protetto."}
        targets = []
        for process in psutil.process_iter(("pid", "name")):
            try:
                if str(process.info.get("name") or "").casefold() == expected:
                    process.terminate()
                    targets.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        _, alive = psutil.wait_procs(targets, timeout=max(0.1, min(float(timeout), 30))) if targets else ([], [])
        return {
            "success": not alive and bool(targets),
            "message": f"Terminati {len(targets)-len(alive)} processi di {app.name}.",
            "data": {"matched": len(targets), "alive": [p.pid for p in alive]},
        }

    def restart(self, query: str, timeout: float = 5) -> dict:
        closed = self.close(query, timeout)
        if not closed.get("success"):
            return {
                "success": False,
                "message": "Riavvio interrotto: " + str(closed.get("message")),
                "data": {"close": closed},
            }
        opened = self.open(query)
        return {
            "success": bool(opened.get("success")),
            "message": "Applicazione riavviata." if opened.get("success") else str(opened.get("message")),
            "data": {"close": closed, "open": opened},
        }

    def packages(self, query: str) -> dict:
        response = self.broker.client.execute("winget.search", {"query": str(query)})
        return {"success": response.success, "message": response.message, "data": response.data}

    def package_action(self, action: str, package_id: str) -> dict:
        if action not in {"install", "upgrade", "uninstall"}:
            return {"success": False, "message": "Operazione pacchetto non valida."}
        if hasattr(self.broker, "ensure_available") and not self.broker.ensure_available():
            return {"success": False, "message": "Broker privilegiato non disponibile o elevazione annullata."}
        response = self.broker.client.execute(f"winget.{action}", {"package_id": str(package_id)}, confirmed=True)
        return {"success": response.success, "message": response.message, "data": response.data}
