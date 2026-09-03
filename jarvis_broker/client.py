from __future__ import annotations

import getpass
import socket
from dataclasses import asdict
from multiprocessing.connection import Client
from pathlib import Path
from typing import Any

from app_paths import data_path
from .credentials import load_or_create
from .protocol import BrokerProtocol, BrokerResponse

PIPE_ADDRESS = r"\\.\pipe\JarvisPrivilegedBroker"
PIPE_PREFIX = PIPE_ADDRESS + "_"


class BrokerClient:
    def __init__(self, *, address: Any = PIPE_ADDRESS, family: str = "AF_PIPE", credential_path: Path | None = None):
        self.address = address
        self.family = family
        self.credential_path = credential_path or (data_path("broker") / "credential.dpapi")

    def execute(
        self, action: str, parameters: dict, *, confirmed: bool = False, timeout: float = 30.0
    ) -> BrokerResponse:
        try:
            secret = load_or_create(self.credential_path)
            request = BrokerProtocol.create(secret, getpass.getuser(), action, parameters, user_confirmation=confirmed)
            if self.family == "AF_INET":
                with socket.create_connection(self.address, timeout=max(0.05, min(float(timeout), 0.5))):
                    pass
            connection = Client(self.address, family=self.family, authkey=secret)
        except (FileNotFoundError, ConnectionRefusedError, OSError, ValueError) as exc:
            return BrokerResponse(
                "unavailable", False, "Broker privilegiato non disponibile.", {"error": type(exc).__name__}
            )
        try:
            connection.send(asdict(request))
            payload = dict(connection.recv())
            return BrokerResponse(**payload)
        finally:
            connection.close()
