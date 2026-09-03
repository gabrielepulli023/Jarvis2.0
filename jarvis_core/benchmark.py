"""Repeatable local-only JARVIS micro-benchmark: python -m jarvis_core.benchmark."""

import json
import platform
import statistics
import tempfile
import time
from pathlib import Path

import psutil

from jarvis_core.events import EventBus
from jarvis_core.tracing import PerformanceTrace
from jarvis_memory import MemoryStore
import performance_metrics


def summarize(values):
    ordered = sorted(values)

    def pick(p):
        return ordered[max(0, min(len(ordered) - 1, int(len(ordered) * p) - 1))]

    return {
        "p50_ms": round(statistics.median(values), 4),
        "p95_ms": round(pick(0.95), 4),
        "p99_ms": round(pick(0.99), 4),
        "max_ms": round(max(values), 4),
    }


def timed(function, count):
    values = []
    for _ in range(count):
        started = time.perf_counter_ns()
        function()
        values.append((time.perf_counter_ns() - started) / 1_000_000)
    return summarize(values)


def run():
    bus = EventBus()
    database = Path(tempfile.gettempdir()) / "jarvis_benchmark_memory.db"
    database.unlink(missing_ok=True)
    memory = MemoryStore(database)
    for index in range(200):
        memory.remember(f"benchmark item {index} project audio", importance=0.5)
    old_store = performance_metrics.STORE
    performance_metrics.STORE = Path(tempfile.gettempdir()) / "jarvis_benchmark_metrics.json"
    performance_metrics.STORE.unlink(missing_ok=True)
    performance_metrics._DATA = None
    performance_metrics._DIRTY = False
    performance_metrics._LAST_FLUSH = time.monotonic()
    result = {
        "timestamp": time.time(),
        "hardware": {
            "platform": platform.platform(),
            "cpu": platform.processor(),
            "logical_cpus": psutil.cpu_count(),
            "ram_bytes": psutil.virtual_memory().total,
        },
        "metrics": {
            "event_bus": timed(lambda: bus.publish("benchmark"), 1000),
            "trace_mark": timed(lambda: PerformanceTrace().mark("intent"), 1000),
            "metrics_record": timed(lambda: performance_metrics.record_tool("benchmark", True, 1), 1000),
            "memory_search_200": timed(lambda: memory.search("project audio", limit=5), 100),
        },
        "process": {"rss_bytes": psutil.Process().memory_info().rss, "threads": psutil.Process().num_threads()},
    }
    performance_metrics.STORE = old_store
    performance_metrics._DATA = None
    database.unlink(missing_ok=True)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
