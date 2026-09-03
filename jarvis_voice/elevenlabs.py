"""ElevenLabs TTS provider and speech preparation utilities.

The provider deliberately uses the stable official HTTP API rather than binding
the rest of JARVIS to a rapidly changing SDK surface. All defaults are internal;
only ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID are required from the user.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from llm_gateway import _environment_candidates

DEFAULT_MODEL = "eleven_flash_v2_5"
# Use a self-describing container for playback.  Raw PCM is very sensitive to
# device format/channel mismatches and was previously played through a second
# output path, which could turn a valid ElevenLabs response into loud noise.
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_VOICE_SETTINGS = {
    "stability": 0.40,
    "similarity_boost": 0.75,
    "style": 0.15,
    "speed": 0.95,
    "use_speaker_boost": True,
}
MOODS = {"normal", "friendly", "technical", "confirmation", "warning", "urgent", "success", "error"}


class ElevenLabsError(RuntimeError):
    """A safe, user-readable provider error without secret material."""


@dataclass(slots=True)
class TTSMetrics:
    requests: int = 0
    characters_sent: int = 0
    errors: int = 0
    first_audio_latency_ms: list[int] | None = None

    def __post_init__(self) -> None:
        if self.first_audio_latency_ms is None:
            self.first_audio_latency_ms = []

    def snapshot(self) -> dict:
        values = self.first_audio_latency_ms or []
        return {
            "tts_requests": self.requests,
            "characters_sent": self.characters_sent,
            "tts_errors": self.errors,
            "average_first_audio_latency": round(sum(values) / len(values), 2) if values else None,
        }


def format_for_speech(text: str) -> str:
    """Create a spoken-only representation; HUD text is never changed."""
    value = str(text or "")
    value = re.sub(r"```.*?```", " codice omesso ", value, flags=re.DOTALL)
    value = re.sub(r"`[^`]+`", " codice omesso ", value)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"https?://\S+", " link web ", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^[\s>*-]+", "", value, flags=re.MULTILINE)
    value = value.replace("**", "").replace("__", "").replace("*", "")
    value = re.sub(r"[\U00010000-\U0010ffff]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


class SpeechCostOptimizer:
    """Bound spoken output while retaining the complete HUD response."""

    def __init__(self, max_chars: int = 900):
        self.max_chars = max(120, int(max_chars))

    def optimize(self, text: str) -> str:
        value = format_for_speech(text)
        if not value:
            return ""
        lowered = value.casefold()
        if "traceback" in lowered or "stack trace" in lowered or "exception:" in lowered:
            return "Ho rilevato un errore tecnico. I dettagli completi sono visualizzati sul pannello."
        if len(value) <= self.max_chars:
            return value
        sentences = re.split(r"(?<=[.!?])\s+", value)
        result = " ".join(sentences[:3]).strip()
        if len(result) > self.max_chars:
            result = result[: self.max_chars].rsplit(" ", 1)[0]
        return result.rstrip(" .,;:") + ". I dettagli completi sono visualizzati sul pannello."


class ElevenLabsTTSProvider:
    """Reusable streaming HTTP client with bounded retry and cancellation."""

    def __init__(self, cache_dir: Path | None = None, *, timeout: float = 30.0, retries: int = 2):
        seen = set()
        for env_path in _environment_candidates():
            resolved = env_path.resolve()
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            load_dotenv(resolved, override=False)
        self.api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
        self.model = os.getenv("ELEVENLABS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.output_format = DEFAULT_OUTPUT_FORMAT
        self.settings = dict(DEFAULT_VOICE_SETTINGS)
        self.timeout = max(5.0, float(timeout))
        self.retries = max(0, min(3, int(retries)))
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.metrics = TTSMetrics()
        self._lock = threading.RLock()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.voice_id)

    @property
    def status(self) -> str:
        return "CONNECTED" if self.configured else "FALLBACK"

    def _cache_path(self, text: str) -> Path | None:
        if self.cache_dir is None or not text or bool(os.getenv("JARVIS_PRIVATE_MODE")):
            return None
        signature = f"{self.voice_id}|{self.model}|{self.output_format}|{self.settings}|{text}"
        return self.cache_dir / (hashlib.sha256(signature.encode("utf-8")).hexdigest() + ".mp3")

    def _request(
        self,
        text: str,
        target: Path,
        first_audio: Callable[[int], None] | None,
        cancel: threading.Event | None,
        on_audio: Callable[[bytes], None] | None,
    ):
        endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream"
        body = {
            "text": text,
            "model_id": self.model,
            "output_format": self.output_format,
            "voice_settings": self.settings,
        }
        request = Request(
            endpoint,
            data=__import__("json").dumps(body).encode("utf-8"),
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            method="POST",
        )
        started = time.perf_counter()
        received = 0
        target.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(request, timeout=self.timeout) as response, target.open("wb") as output:
            while True:
                if cancel and cancel.is_set():
                    raise asyncio.CancelledError()
                chunk = response.read(16384)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                if on_audio:
                    on_audio(chunk)
                if received == len(chunk) and first_audio:
                    first_audio(int((time.perf_counter() - started) * 1000))
        if received < 128:
            raise ElevenLabsError("ElevenLabs ha restituito un audio vuoto o non valido.")

    def synthesize(
        self,
        text: str,
        target: Path,
        *,
        mood: str = "normal",
        first_audio: Callable[[int], None] | None = None,
        cancel: threading.Event | None = None,
        on_audio: Callable[[bytes], None] | None = None,
    ) -> bool:
        if not self.configured:
            raise ElevenLabsError("ElevenLabs TTS non disponibile: controlla ELEVENLABS_API_KEY e ELEVENLABS_VOICE_ID.")
        value = SpeechCostOptimizer().optimize(text)
        if not value:
            return False
        cached = self._cache_path(value)
        if cached and cached.exists():
            cached_bytes = cached.read_bytes()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(cached_bytes)
            if on_audio:
                for offset in range(0, len(cached_bytes), 16384):
                    if cancel and cancel.is_set():
                        raise asyncio.CancelledError()
                    on_audio(cached_bytes[offset : offset + 16384])
            return True
        with self._lock:
            self.metrics.requests += 1
            self.metrics.characters_sent += len(value)
        # Mood is intentionally a subtle timbre/style adjustment; voice identity stays fixed.
        if mood in MOODS and mood != "normal":
            original = dict(self.settings)
            if mood in {"warning", "urgent", "error"}:
                self.settings["stability"] = min(0.55, original["stability"] + 0.05)
                self.settings["style"] = min(0.25, original["style"] + 0.05)
            elif mood in {"friendly", "success"}:
                self.settings["style"] = min(0.25, original["style"] + 0.03)
        else:
            original = None
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self._request(value, target, first_audio, cancel, on_audio)
                if cached:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_bytes(target.read_bytes())
                if original is not None:
                    self.settings = original
                return True
            except asyncio.CancelledError:
                raise
            except (HTTPError, URLError, TimeoutError, OSError, ElevenLabsError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(0.15 * (attempt + 1))
        if original is not None:
            self.settings = original
        with self._lock:
            self.metrics.errors += 1
        detail = "chiave API" if isinstance(last, HTTPError) and last.code in {401, 403} else "rete o servizio"
        raise ElevenLabsError(f"ElevenLabs TTS non disponibile: controlla {detail} e Voice ID.") from last

    async def synthesize_async(self, text: str, target: Path, **kwargs) -> bool:
        return await asyncio.to_thread(self.synthesize, text, target, **kwargs)
