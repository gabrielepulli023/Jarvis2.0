from __future__ import annotations
import itertools
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Callable
from jarvis_core.logging import redact


class VoiceState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    STOPPED = "stopped"


class SpeechPriority(IntEnum):
    CRITICAL = 0
    HIGH = 10
    NORMAL = 20
    LOW = 30


@dataclass(order=True, slots=True)
class SpeechRequest:
    priority: int
    sequence: int
    id: str = field(compare=False)
    text: str = field(compare=False)
    interruptible: bool = field(compare=False, default=True)
    created_at: float = field(compare=False, default_factory=time.monotonic)


class VoiceSessionEngine:
    """Single-owner prioritized speech queue with deterministic barge-in."""

    def __init__(
        self,
        speaker: Callable[[str, bool], str | None],
        stop_speaker: Callable[[str | None], None],
        on_state: Callable[[VoiceState], None] | None = None,
        auto_start: bool = True,
        record_metric: Callable[[str, bool, int], None] | None = None,
    ):
        self._speaker = speaker
        self._stop_speaker = stop_speaker
        self._on_state = on_state or (lambda state: None)
        self._record_metric = record_metric or (lambda name, success, duration: None)
        self._auto_start = auto_start
        self._queue = queue.PriorityQueue(maxsize=32)
        self._sequence = itertools.count()
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread = None
        self._current = None
        self._state = VoiceState.IDLE
        self._history = []
        self._barge_text = None
        self._done = {}
        self._results = {}

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    def _set_state(self, state: VoiceState):
        with self._lock:
            self._state = state
        self._on_state(state)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-speech-queue", daemon=True)
        self._thread.start()

    def submit(self, text: str, priority: SpeechPriority = SpeechPriority.NORMAL, interruptible: bool = True) -> str:
        value = str(text).strip()
        if not value:
            raise ValueError("speech text cannot be empty")
        identity = uuid.uuid4().hex[:12]
        with self._lock:
            self._done[identity] = threading.Event()
        request = SpeechRequest(int(priority), next(self._sequence), identity, value, interruptible)
        try:
            self._queue.put_nowait(request)
        except queue.Full:
            if int(priority) <= int(SpeechPriority.HIGH):
                self.cancel_pending()
                self._queue.put_nowait(request)
            else:
                with self._lock:
                    self._results[identity] = None
                    self._done[identity].set()
        if self._auto_start:
            self.start()
        return identity

    def wait(self, request_id: str, timeout: float | None = None) -> str | None:
        with self._lock:
            event = self._done.get(request_id)
        if event is None:
            raise KeyError(request_id)
        if not event.wait(timeout):
            raise TimeoutError(f"speech request timed out: {request_id}")
        with self._lock:
            return self._results.pop(request_id, None)

    def speak_wait(
        self,
        text: str,
        priority: SpeechPriority = SpeechPriority.NORMAL,
        interruptible: bool = True,
        timeout: float | None = None,
        *,
        interrompibile: bool | None = None,
    ) -> str | None:
        if interrompibile is not None:
            interruptible = bool(interrompibile)
        return self.wait(self.submit(text, priority, interruptible), timeout)

    def interrupt(self, new_text: str | None = None) -> bool:
        with self._lock:
            current = self._current
        if current is None or not current.interruptible:
            return False
        self._barge_text = str(new_text).strip() if new_text else None
        self._stop_speaker(self._barge_text)
        self._set_state(VoiceState.INTERRUPTED)
        return True

    def _run(self):
        while not self._stop.is_set():
            try:
                request = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._lock:
                self._current = request
            self._set_state(VoiceState.SPEAKING)
            started = time.monotonic()
            error = None
            returned = None
            try:
                returned = self._speaker(request.text, request.interruptible)
            except Exception as exc:
                error = redact(f"{type(exc).__name__}: {exc}")
                self._set_state(VoiceState.ERROR)
            with self._lock:
                interrupted = self._state == VoiceState.INTERRUPTED
                final_result = self._barge_text or returned
                self._history.append(
                    {
                        "id": request.id,
                        "priority": request.priority,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "queue_latency_ms": int((started - request.created_at) * 1000),
                        "interrupted": interrupted,
                        "barge_text": final_result,
                        "error": error,
                    }
                )
                self._history = self._history[-500:]
                self._results[request.id] = final_result
                self._done[request.id].set()
                self._current = None
                self._barge_text = None
            self._queue.task_done()
            self._record_metric("tts", error is None, int((time.monotonic() - started) * 1000))
            if not error:
                self._set_state(VoiceState.IDLE)
        self._set_state(VoiceState.STOPPED)

    def cancel_pending(self) -> int:
        count = 0
        while True:
            try:
                request = self._queue.get_nowait()
                self._queue.task_done()
                count += 1
                with self._lock:
                    self._results[request.id] = None
                    self._done[request.id].set()
            except queue.Empty:
                return count

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "current": self._current.id if self._current else None,
                "queued": self._queue.qsize(),
                "history": list(self._history[-50:]),
            }

    def shutdown(self):
        self._stop.set()
        self.interrupt()
        self.cancel_pending()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        if not self._thread or not self._thread.is_alive():
            self._set_state(VoiceState.STOPPED)
