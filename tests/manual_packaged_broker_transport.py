"""Non-elevated packaged-entrypoint smoke; UAC behavior is covered by target acceptance."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis_broker.client import BrokerClient  # noqa: E402
from jarvis_broker.credentials import load_or_create  # noqa: E402


def main() -> int:
    executable = ROOT / "dist" / "JARVIS" / "JARVIS.exe"
    if not executable.is_file():
        print("packaged executable missing")
        return 2
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    with TemporaryDirectory() as temporary:
        data_root = Path(temporary)
        isolated_credential = data_root / "broker" / "credential.dpapi"
        isolated_credential.parent.mkdir(parents=True, exist_ok=True)
        # Bootstrap in the caller's Windows identity before the broker starts.
        # This mirrors BrokerManager and also avoids a client/server creation race.
        load_or_create(isolated_credential)
        environment = os.environ.copy()
        environment["JARVIS_DATA_DIR"] = str(data_root)
        process = subprocess.Popen(
            [str(executable), "--broker", "--broker-tcp-port", str(port)],
            cwd=str(ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
        client = BrokerClient(
            address=("127.0.0.1", port),
            family="AF_INET",
            credential_path=isolated_credential,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if client.execute("broker.ping", {}, timeout=0.5).success:
                    stopped = client.execute("broker.stop", {}, confirmed=True, timeout=0.5).success
                    print(f"packaged_broker_ping=true stopped={str(stopped).lower()}")
                    return 0 if stopped else 3
                time.sleep(0.1)
            print("packaged broker did not become ready")
            print(f"process_returncode={process.poll()}")
            return 4
        finally:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
