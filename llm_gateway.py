"""Central construction point for remote model SDK clients."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


class MissingProviderCredentials(RuntimeError):
    """Raised only when a remote provider is actually used without a key."""


def _environment_candidates() -> list[Path]:
    """Return safe user-owned environment locations for source and frozen runs."""

    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"]
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.insert(0, executable_dir / ".env")
        candidates.insert(1, executable_dir / "Jarvis2.0" / ".env")
    return candidates


def _load_project_environment() -> None:
    """Load an adjacent/user-owned .env without ever packaging its contents."""

    seen = set()
    for path in _environment_candidates():
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        load_dotenv(resolved, override=False)


_load_project_environment()


class _DeferredOpenAIClient:
    """Keep imports/startup alive and resolve the SDK only on first API use."""

    def __init__(self, *, profile: str, timeout: float, retries: int):
        self.profile = profile
        self.timeout = timeout
        self.retries = retries
        self._client: OpenAI | None = None

    def _resolve(self) -> OpenAI:
        _load_project_environment()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise MissingProviderCredentials(
                "OPENAI_API_KEY non configurata: imposta la chiave nell'ambiente "
                "o in un file .env accanto a JARVIS2.0.exe."
            )
        if self._client is None:
            self._client = OpenAI(api_key=api_key, timeout=self.timeout, max_retries=self.retries)
        return self._client

    def __getattr__(self, name):
        return getattr(self._resolve(), name)


class _DeferredKimiClient:
    """Keep Kimi imports safe when its optional credential is not configured."""

    def __init__(self):
        self._client: OpenAI | None = None

    def _resolve(self) -> OpenAI:
        _load_project_environment()
        key = os.getenv("MOONSHOT_API_KEY") or os.getenv("KIMI_API_KEY")
        if not key:
            raise MissingProviderCredentials(
                "MOONSHOT_API_KEY o KIMI_API_KEY non configurata: imposta la chiave "
                "nell'ambiente o in un file .env accanto a JARVIS2.0.exe."
            )
        if self._client is None:
            self._client = OpenAI(
                api_key=key,
                base_url="https://api.moonshot.ai/v1",
                timeout=90.0,
                max_retries=1,
            )
        return self._client

    def __getattr__(self, name):
        return getattr(self._resolve(), name)


@lru_cache(maxsize=8)
def openai_client(*, profile: str = "interactive") -> OpenAI | _DeferredOpenAIClient:
    policies = {
        "router": (25.0, 0),
        "interactive": (90.0, 1),
        "vision": (35.0, 1),
        # STT gets one bounded attempt; a stalled upload must return control
        # to the local Vosk fallback instead of blocking continuous listening.
        "transcription": (20.0, 0),
    }
    if profile not in policies:
        raise ValueError(f"Profilo client sconosciuto: {profile}")
    timeout, retries = policies[profile]
    _load_project_environment()
    if not os.getenv("OPENAI_API_KEY"):
        return _DeferredOpenAIClient(profile=profile, timeout=timeout, retries=retries)
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=timeout, max_retries=retries)


@lru_cache(maxsize=2)
def kimi_client() -> OpenAI | _DeferredKimiClient:
    _load_project_environment()
    key = os.getenv("MOONSHOT_API_KEY") or os.getenv("KIMI_API_KEY")
    if not key:
        return _DeferredKimiClient()
    return OpenAI(api_key=key, base_url="https://api.moonshot.ai/v1", timeout=90.0, max_retries=1)
