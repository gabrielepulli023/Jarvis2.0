from __future__ import annotations
import hashlib
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable
from jarvis_core.logging import redact


@dataclass(frozen=True, slots=True)
class UIElement:
    id: str
    name: str
    role: str
    bounds: tuple[int, int, int, int] | None = None
    state: dict = field(default_factory=dict)
    confidence: float = 1.0

    @classmethod
    def from_dict(cls, row: dict):
        identity = str(
            row.get("automation_id")
            or row.get("id")
            or hashlib.sha256(
                f"{row.get('name')}|{row.get('type')}|{row.get('x')}|{row.get('y')}".encode()
            ).hexdigest()[:16]
        )
        bounds = (
            (int(row.get("x", 0)), int(row.get("y", 0)), int(row.get("width", 0)), int(row.get("height", 0)))
            if any(k in row for k in ("x", "y", "width", "height"))
            else None
        )
        state = {
            k: row[k]
            for k in ("enabled", "offscreen", "invoke", "value", "select", "toggle", "text", "checked", "selected")
            if k in row
        }
        return cls(
            identity,
            str(row.get("name") or row.get("text") or ""),
            str(row.get("type") or row.get("role") or "unknown"),
            bounds,
            state,
            float(row.get("confidence", 1)),
        )


@dataclass(frozen=True, slots=True)
class ScreenState:
    application: str
    window: str
    source: str
    elements: tuple[UIElement, ...]
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {**asdict(self), "elements": [asdict(x) for x in self.elements]}


@dataclass(frozen=True, slots=True)
class ScreenDiff:
    appeared: tuple[UIElement, ...]
    disappeared: tuple[UIElement, ...]
    changed: tuple[tuple[UIElement, UIElement], ...]
    source_changed: bool

    @property
    def has_progress(self) -> bool:
        return bool(self.appeared or self.disappeared or self.changed or self.source_changed)


@dataclass(frozen=True, slots=True)
class FusedObservation:
    primary: ScreenState
    secondary: ScreenState
    corroborated_ids: tuple[str, ...]
    discrepancies: tuple[str, ...]
    confidence: float


def fuse_states(primary: ScreenState, secondary: ScreenState) -> FusedObservation:
    secondary_names = {" ".join(x.name.lower().split()) for x in secondary.elements if x.name.strip()}
    corroborated = []
    discrepancies = []
    for element in primary.elements:
        normalized = " ".join(element.name.lower().split())
        if not normalized:
            continue
        if normalized in secondary_names:
            corroborated.append(element.id)
        elif not element.state.get("offscreen", False):
            discrepancies.append(f"not visually corroborated: {element.name}")
    ratio = len(corroborated) / max(1, len(corroborated) + len(discrepancies))
    confidence = max(0, min(1, 0.6 * primary.confidence + 0.25 * secondary.confidence + 0.15 * ratio))
    return FusedObservation(primary, secondary, tuple(corroborated), tuple(discrepancies), confidence)


class PerceptionEngine:
    """Observes by strongest available structured source and retains temporal state."""

    def __init__(self, active_interval: float = 0.15, idle_interval: float = 2.0):
        self._observers: list[tuple[int, str, Callable[[], dict], Callable[[dict], ScreenState]]] = []
        self._previous: ScreenState | None = None
        self._current: ScreenState | None = None
        self._lock = threading.RLock()
        self._last_observed = 0.0
        self._active_interval = max(0.05, float(active_interval))
        self._idle_interval = max(self._active_interval, float(idle_interval))
        self._activity_until = 0.0

    def register(
        self, name: str, priority: int, observer: Callable[[], dict], normalizer: Callable[[dict], ScreenState]
    ) -> None:
        self._observers.append((int(priority), name, observer, normalizer))
        self._observers.sort(reverse=True, key=lambda x: x[0])

    def observe(self) -> ScreenState:
        failures = []
        for _, name, observer, normalizer in tuple(self._observers):
            try:
                result = observer()
                if result.get("successo", result.get("success", False)):
                    state = normalizer(result.get("dati", result.get("data", result)))
                    with self._lock:
                        self._previous, self._current = self._current, state
                        self._last_observed = time.monotonic()
                    return state
                failures.append(f"{name}: {result.get('messaggio','failed')}")
            except Exception as exc:
                failures.append(redact(f"{name}: {type(exc).__name__}: {exc}"))
        raise RuntimeError("; ".join(failures) or "no perception observers registered")

    def notify_activity(self, duration: float = 1.0) -> None:
        with self._lock:
            self._activity_until = max(self._activity_until, time.monotonic() + max(0.05, float(duration)))

    def observe_if_due(self, *, force: bool = False) -> ScreenState | None:
        now = time.monotonic()
        with self._lock:
            interval = self._active_interval if now < self._activity_until else self._idle_interval
            current = self._current
            due = force or current is None or now - self._last_observed >= interval
        return self.observe() if due else current

    def diff(self) -> ScreenDiff:
        with self._lock:
            previous, current = self._previous, self._current
        if current is None:
            return ScreenDiff((), (), (), False)
        if previous is None:
            return ScreenDiff(current.elements, (), (), False)
        old = {x.id: x for x in previous.elements}
        new = {x.id: x for x in current.elements}
        appeared = tuple(new[x] for x in new.keys() - old.keys())
        disappeared = tuple(old[x] for x in old.keys() - new.keys())
        changed = tuple((old[x], new[x]) for x in old.keys() & new.keys() if old[x] != new[x])
        return ScreenDiff(appeared, disappeared, changed, previous.source != current.source)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "previous": self._previous.as_dict() if self._previous else None,
                "current": self._current.as_dict() if self._current else None,
                "diff": asdict(self.diff()),
                "activity_until": self._activity_until,
                "last_observed": self._last_observed,
            }


def normalize_dom(data: dict) -> ScreenState:
    raw = data.get("elements") or data.get("controls") or []
    elements = tuple(UIElement.from_dict(x) for x in raw if isinstance(x, dict))
    title = str(data.get("title") or "Chrome")
    return ScreenState(
        "Chrome", title, "dom", elements, 0.98, metadata={k: data.get(k) for k in ("url", "received_at") if k in data}
    )


def normalize_uia(data: dict) -> ScreenState:
    elements = tuple(UIElement.from_dict(x) for x in data.get("elements", []) if isinstance(x, dict))
    window = str(data.get("window") or "Windows")
    return ScreenState(window.split(" - ")[-1], window, "uia", elements, 0.92)


def normalize_vision(data: dict) -> ScreenState:
    elements = tuple(UIElement.from_dict(x) for x in data.get("elements", []) if isinstance(x, dict))
    return ScreenState(
        str(data.get("application") or "unknown"),
        str(data.get("window") or "screen"),
        "vision",
        elements,
        float(data.get("confidence", 0.65)),
        metadata={"description": data.get("description", data.get("text", ""))},
    )
