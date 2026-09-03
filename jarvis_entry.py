"""Minimal packaged entrypoint separating the elevated broker from the user UI."""

from __future__ import annotations

import sys


def _option(name: str) -> str | None:
    try:
        index = sys.argv.index(name)
    except ValueError:
        return None
    return sys.argv[index + 1] if index + 1 < len(sys.argv) else None


def run() -> int:
    if "--broker" in sys.argv:
        from jarvis_broker.client import PIPE_ADDRESS
        from jarvis_broker.server import serve_forever

        address = _option("--broker-address") or PIPE_ADDRESS
        port_value = _option("--broker-tcp-port")
        serve_forever(address, tcp_port=int(port_value) if port_value is not None else None)
        return 0
    from main import main

    result = main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(run())
