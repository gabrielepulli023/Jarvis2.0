"""Optional Silero VAD adapter and conservative hybrid speech decision."""

from __future__ import annotations

import threading
from typing import Any, Callable

import numpy as np


class SileroVADProvider:
    """Lazy, single-instance-per-listener Silero scorer for 16 kHz PCM."""

    _load_lock = threading.Lock()
    _thread_configured = False
    _shared_model: Any = None
    _shared_torch: Any = None
    _shared_error = ""
    _shared_available = True

    def __init__(self, *, sample_rate: int = 16_000, threshold: float = 0.55):
        self.sample_rate = int(sample_rate)
        self.threshold = float(threshold)
        self._model: Any = None
        self._torch: Any = None
        self._buffer = np.empty(0, dtype=np.float32)
        self.available = True
        self.error = ""

    def _load(self) -> bool:
        if type(self)._shared_model is not None:
            self._model = type(self)._shared_model
            self._torch = type(self)._shared_torch
            return True
        if not type(self)._shared_available:
            self.available = False
            self.error = type(self)._shared_error
            return False
        try:
            import silero_vad
            import torch

            with self._load_lock:
                if type(self)._shared_model is None:
                    if not self._thread_configured:
                        torch.set_num_threads(1)
                        type(self)._thread_configured = True
                    type(self)._shared_model = silero_vad.load_silero_vad()
                    type(self)._shared_torch = torch
                    self._model = type(self)._shared_model
                    self._torch = type(self)._shared_torch
        except Exception as exc:
            type(self)._shared_available = False
            type(self)._shared_error = f"{type(exc).__name__}: {exc}"
            self.available = False
            self.error = type(self)._shared_error
            return False
        return True

    def score(self, audio: bytes) -> float | None:
        """Return the latest probability; incomplete/invalid chunks return None."""
        if not isinstance(audio, (bytes, bytearray, memoryview)) or not audio or len(audio) % 2:
            return None
        if not self.available or not self._load():
            return None
        try:
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            if samples.size == 0 or not np.isfinite(samples).all():
                return None
            self._buffer = np.concatenate((self._buffer, np.clip(samples, -1.0, 1.0)))
            probabilities = []
            while self._buffer.size >= 512:
                chunk, self._buffer = self._buffer[:512], self._buffer[512:]
                tensor = self._torch.from_numpy(chunk)
                with self._torch.no_grad():
                    value = self._model(tensor, self.sample_rate)
                probabilities.append(float(value.item() if hasattr(value, "item") else value))
            if not probabilities:
                return None
            return max(0.0, min(1.0, probabilities[-1]))
        except Exception as exc:
            type(self)._shared_available = False
            type(self)._shared_error = f"{type(exc).__name__}: {exc}"
            self.available = False
            self.error = type(self)._shared_error
            return None


class HybridVAD:
    """Use Silero to reject sustained noise, while preserving legacy grace."""

    def __init__(
        self,
        provider: SileroVADProvider | None,
        *,
        release_threshold: float = 0.35,
        grace_ms: int = 300,
        frame_ms: int = 30,
        log: Callable[[str], None] | None = print,
    ):
        self.provider = provider
        self.release_threshold = float(release_threshold)
        self.grace_frames = max(1, round(max(0, int(grace_ms)) / max(1, frame_ms)))
        self.log = log
        self._low_frames = 0
        self._reported_fallback = False

    def decide(self, frame: bytes, legacy_voice: bool) -> bool:
        if self.provider is None:
            return bool(legacy_voice)
        try:
            probability = self.provider.score(frame)
        except Exception as exc:
            self.provider.available = False
            self.provider.error = f"{type(exc).__name__}: {exc}"
            probability = None
        if probability is None:
            if not self.provider.available and not self._reported_fallback:
                self._reported_fallback = True
                if self.log:
                    self.log("Silero VAD unavailable -> legacy fallback")
            return bool(legacy_voice)
        if probability >= self.provider.threshold:
            self._low_frames = 0
            return True
        if probability < self.release_threshold:
            self._low_frames += 1
            return bool(legacy_voice) and self._low_frames <= self.grace_frames
        return bool(legacy_voice)


def create_hybrid_vad(get_setting: Callable[[str, Any], Any], *, sample_rate: int, frame_ms: int) -> HybridVAD:
    enabled = bool(get_setting("silero_enabled", True)) and str(get_setting("vad_provider", "silero")).lower() == "silero"
    provider = None
    if enabled:
        provider = SileroVADProvider(
            sample_rate=sample_rate,
            threshold=float(get_setting("silero_threshold", 0.55)),
        )
    return HybridVAD(
        provider,
        release_threshold=float(get_setting("silero_release_threshold", 0.35)),
        grace_ms=int(get_setting("silero_grace_ms", 300)),
        frame_ms=frame_ms,
    )
