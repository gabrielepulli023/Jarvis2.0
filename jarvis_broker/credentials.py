from __future__ import annotations

import os
from pathlib import Path

from jarvis_identity.crypto import protect, unprotect


def load_or_create(path: Path) -> bytes:
    target = Path(path)
    if target.exists():
        secret = unprotect(target.read_bytes())
        if len(secret) != 32:
            raise ValueError("Credenziale broker corrotta")
        return secret
    target.parent.mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(protect(secret))
    os.replace(temporary, target)
    return secret
