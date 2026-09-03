from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from multiprocessing.connection import AuthenticationError, Listener

from app_paths import data_path
from .client import PIPE_ADDRESS, PIPE_PREFIX
from .credentials import load_or_create
from .protocol import BrokerProtocol, BrokerRequest, BrokerResponse
from jarvis_core.logging import redact


def _write_startup_status(stage: str, **details) -> None:
    """Persist broker lifecycle metadata only; credentials and requests are excluded."""
    path = data_path("acceptance") / "broker-startup.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload = {"stage": stage, "timestamp": time.time(), "pid": os.getpid(), **details}
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _run(command: list[str], timeout: float) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, shell=False)
    return {"exit_code": result.returncode, "stdout": result.stdout[-12000:], "stderr": result.stderr[-12000:]}


def execute(action: str, parameters: dict) -> dict:
    if action == "broker.ping":
        return {"exit_code": 0, "status": "healthy", "pid": os.getpid()}
    if action == "broker.stop":
        return {"exit_code": 0, "stopping": True}
    package = str(parameters.get("package_id", "")).strip()
    if action.startswith("winget."):
        if not shutil.which("winget"):
            raise FileNotFoundError("winget non disponibile")
        verb = action.split(".", 1)[1]
        if verb == "upgrade_all":
            return _run(
                [
                    "winget",
                    "upgrade",
                    "--all",
                    "--disable-interactivity",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
                1800,
            )
        command = ["winget", verb]
        if verb == "search":
            query = str(parameters.get("query", "")).strip()
            if not query or any(character in query for character in "\r\n\0"):
                raise ValueError("query non valida")
            command += [query, "--source", "winget"]
        elif verb != "list":
            if not package or any(character in package for character in "\r\n\0"):
                raise ValueError("package_id non valido")
            command += ["--id", package, "--exact"]
        command += ["--disable-interactivity"]
        if verb in {"install", "upgrade"}:
            command += ["--accept-package-agreements", "--accept-source-agreements"]
        return _run(command, 900 if verb != "list" else 30)
    if action == "system.info":
        script = (
            "$o=Get-CimInstance Win32_OperatingSystem;"
            "$c=Get-CimInstance Win32_ComputerSystem;"
            "[pscustomobject]@{Caption=$o.Caption;Version=$o.Version;Build=$o.BuildNumber;"
            "LastBoot=$o.LastBootUpTime;Manufacturer=$c.Manufacturer;Model=$c.Model;"
            "MemoryBytes=$c.TotalPhysicalMemory}|ConvertTo-Json -Compress"
        )
        return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], 30)
    if action == "software.list":
        script = (
            "$paths=@('HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
            "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
            "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*');"
            "Get-ItemProperty $paths -ErrorAction SilentlyContinue|Where-Object DisplayName|"
            "Select-Object DisplayName,DisplayVersion,Publisher|Sort-Object DisplayName -Unique|"
            "Select-Object -First 500|ConvertTo-Json -Compress"
        )
        return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], 60)
    if action == "service.list":
        return _run(["sc.exe", "query", "state=", "all"], 30)
    if action in {"service.start", "service.stop"}:
        name = str(parameters.get("name", "")).strip()
        if not name or not name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("nome servizio non valido")
        return _run(["sc.exe", action.split(".")[1], name], 60)
    if action == "firewall.list":
        return _run(["netsh", "advfirewall", "show", "allprofiles"], 30)
    if action == "firewall.profile":
        profile = str(parameters.get("profile", "")).casefold().strip()
        enabled = parameters.get("enabled")
        if profile not in {"domainprofile", "privateprofile", "publicprofile", "allprofiles"}:
            raise ValueError("profilo firewall non valido")
        if not isinstance(enabled, bool):
            raise ValueError("stato firewall non valido")
        return _run(["netsh", "advfirewall", "set", profile, "state", "on" if enabled else "off"], 30)
    if action in {"firewall.rule_add", "firewall.rule_remove"}:
        name = str(parameters.get("name", "")).strip()
        if not name or len(name) > 128 or not all(char.isalnum() or char in " ._-" for char in name):
            raise ValueError("nome regola firewall non valido")
        if action == "firewall.rule_remove":
            return _run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"], 30)
        program = os.path.abspath(str(parameters.get("program", "")).strip())
        direction = str(parameters.get("direction", "out")).casefold().strip()
        decision = str(parameters.get("decision", "allow")).casefold().strip()
        if not os.path.isfile(program) or os.path.splitext(program)[1].casefold() != ".exe":
            raise ValueError("programma firewall non valido")
        if direction not in {"in", "out"} or decision not in {"allow", "block"}:
            raise ValueError("parametri regola firewall non validi")
        return _run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={name}",
                f"dir={direction}",
                f"action={decision}",
                f"program={program}",
                "enable=yes",
            ],
            30,
        )
    if action == "task.list":
        return _run(["schtasks.exe", "/Query", "/FO", "CSV"], 30)
    if action in {"task.enable", "task.disable"}:
        task_name = str(parameters.get("task_name", "")).strip()
        if not task_name or len(task_name) > 240 or any(char in task_name for char in '\r\n\0"'):
            raise ValueError("nome task non valido")
        flag = "/ENABLE" if action == "task.enable" else "/DISABLE"
        return _run(["schtasks.exe", "/Change", "/TN", task_name, flag], 30)
    if action == "driver.list":
        return _run(["pnputil.exe", "/enum-drivers"], 60)
    if action == "driver.scan":
        return _run(["pnputil.exe", "/scan-devices"], 120)
    if action == "windows_update.history":
        script = (
            "$s=New-Object -ComObject Microsoft.Update.Session;"
            "$h=$s.CreateUpdateSearcher();$n=$h.GetTotalHistoryCount();"
            "$h.QueryHistory(0,[Math]::Min($n,100))|Select-Object Date,Title,ResultCode|ConvertTo-Json -Compress"
        )
        return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], 60)
    if action == "windows_update.scan":
        return _run(["UsoClient.exe", "StartScan"], 60)
    if action == "startup.status":
        return _run(["schtasks.exe", "/Query", "/TN", "JARVIS AI OS", "/FO", "LIST"], 30)
    if action == "startup.disable":
        return _run(["schtasks.exe", "/Delete", "/TN", "JARVIS AI OS", "/F"], 30)
    if action == "startup.enable":
        executable = os.path.abspath(str(parameters.get("executable", "")).strip())
        arguments = parameters.get("arguments", [])
        if not os.path.isfile(executable) or os.path.basename(executable).casefold() not in {
            "jarvis.exe",
            "python.exe",
            "pythonw.exe",
        }:
            raise ValueError("Eseguibile startup non valido")
        if (
            not isinstance(arguments, list)
            or len(arguments) > 8
            or any(any(char in str(value) for char in "\r\n\0") for value in arguments)
        ):
            raise ValueError("Argomenti startup non validi")
        if os.path.basename(executable).casefold() in {"python.exe", "pythonw.exe"}:
            if (
                not arguments
                or os.path.basename(str(arguments[0])).casefold() != "main.py"
                or not os.path.isfile(os.path.abspath(str(arguments[0])))
            ):
                raise ValueError("Entrypoint sorgente non valido")
        launch = subprocess.list2cmdline([executable, *map(str, arguments)])
        return _run(
            [
                "schtasks.exe",
                "/Create",
                "/TN",
                "JARVIS AI OS",
                "/SC",
                "ONLOGON",
                "/DELAY",
                "0000:30",
                "/TR",
                launch,
                "/RL",
                "LIMITED",
                "/F",
            ],
            30,
        )
    power = {
        "power.shutdown": ["shutdown.exe", "/s", "/t", "0"],
        "power.restart": ["shutdown.exe", "/r", "/t", "0"],
        "power.logout": ["shutdown.exe", "/l"],
        "power.lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
    }
    if action in power:
        return _run(power[action], 10)
    raise ValueError("azione broker non supportata")


def serve_forever(address: str = PIPE_ADDRESS, *, tcp_port: int | None = None) -> None:
    if os.name != "nt":
        raise OSError("Il broker privilegiato richiede Windows")
    if tcp_port is None and address != PIPE_ADDRESS:
        suffix = address.removeprefix(PIPE_PREFIX)
        if (
            not address.startswith(PIPE_PREFIX)
            or len(suffix) != 32
            or any(char not in "0123456789abcdef" for char in suffix)
        ):
            raise ValueError("Indirizzo named pipe non valido")
    _write_startup_status("starting")
    try:
        secret = load_or_create(data_path("broker") / "credential.dpapi")
    except Exception as exc:
        _write_startup_status("failed", component="credential", error_type=type(exc).__name__, error=redact(str(exc)[:500]))
        raise
    _write_startup_status("credential_ready")
    try:
        if tcp_port is not None:
            if not 1024 <= int(tcp_port) <= 65535:
                raise ValueError("Porta loopback non valida")
            listener = Listener(("127.0.0.1", int(tcp_port)), family="AF_INET", authkey=secret)
        else:
            listener = Listener(address, family="AF_PIPE", authkey=secret)
    except Exception as exc:
        _write_startup_status("failed", component="pipe", error_type=type(exc).__name__, error=redact(str(exc)[:500]))
        raise
    _write_startup_status("listening", transport="loopback" if tcp_port is not None else "named_pipe", port=tcp_port)
    seen: set[str] = set()
    running = True
    while running:
        try:
            connection = listener.accept()
        except (AuthenticationError, EOFError, OSError):
            continue
        try:
            request = BrokerRequest(**dict(connection.recv()))
            BrokerProtocol.validate(request, secret, expected_caller=getpass.getuser(), seen=seen)
            data = execute(request.action, request.parameters)
            response = BrokerResponse(
                request.request_id, data.get("exit_code", 1) == 0, "Operazione broker completata.", data
            )
            running = not bool(data.get("stopping"))
        except Exception as exc:
            request_id = getattr(locals().get("request", None), "request_id", "invalid")
            response = BrokerResponse(request_id, False, redact(str(exc)), {"error": type(exc).__name__})
        connection.send(asdict(response))
        connection.close()
    listener.close()
    _write_startup_status("stopped")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--address", default=PIPE_ADDRESS)
    parser.add_argument("--tcp-port", type=int)
    arguments = parser.parse_args(argv)
    try:
        serve_forever(arguments.address, tcp_port=arguments.tcp_port)
        return 0
    except Exception as exc:
        try:
            path = data_path("acceptance") / "broker-startup.json"
            current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if current.get("stage") != "failed":
                _write_startup_status(
                    "failed", component="runtime", error_type=type(exc).__name__, error=redact(str(exc)[:500])
                )
        except (OSError, ValueError, TypeError):
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
