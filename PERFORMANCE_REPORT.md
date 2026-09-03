# Performance report

The original hot paths mixed blocking model calls, full-response TTS, repeated observations, unbounded audio/event histories and synchronous writes. The implementation now uses provider streaming into sentence-level TTS, incremental Vosk partials, bounded voice/browser/event queues, adaptive perception polling, rate-limited atomic metrics, cached settings, async lanes and lazy/preloaded components.

Measured telemetry includes wake, STT, first model token, tool dispatch, action, first TTS audio and total latency, with bounded samples and p50/p95/p99/max aggregation. Automated regression currently completes 304 tests in roughly tens of seconds on the target workstation; exact provider latency remains dependent on network and service load.

## Local benchmark evidence

Measured on 2026-08-19 with Windows 11, an 8-logical-core Intel CPU and 8 GB RAM using `python -m jarvis_core.benchmark`:

| Operation | p50 | p95 | p99 | maximum |
|---|---:|---:|---:|---:|
| Event publication | 0.0089 ms | 0.0210 ms | 0.0473 ms | 0.0844 ms |
| Trace mark | 0.0051 ms | 0.0070 ms | 0.0109 ms | 0.0545 ms |
| Buffered metric record | 0.0258 ms | 0.0595 ms | 0.1012 ms | 0.4230 ms |
| Semantic search over 200 records | 22.4855 ms | 27.2162 ms | 28.8015 ms | 29.8147 ms |

The benchmark process used 31,518,720 bytes RSS and seven threads. These figures prove the local coordination and retrieval hot paths only; they do not substitute for wake-to-audio measurements involving real audio hardware and network providers.

Remaining optimization gates are live wake-to-audio traces, idle CPU/RAM soak, GPU telemetry availability and profiling under the user's real multi-monitor/application workload. Native extensions should be introduced only after profiling identifies a stable CPU-bound target.

## Latest local runtime evidence

On 2026-08-19, the core HUD benchmark ran for 7.5 seconds in the managed Windows session at 20.67 paint FPS, 102.29 MB RSS and 12.3% process CPU. The local coordination benchmark completed with 0.0069 ms event-publication p50, 22.5063 ms p99 semantic search over 200 records, 31.0 MB RSS and seven threads. These measurements are diagnostic evidence, not a promise of a fixed FPS or provider latency.

The HUD benchmark accepts `--duration` (bounded to 1 hour) and reports `rss_before_mb` and `rss_growth_mb`, enabling repeatable soak checks without persisting frames or screenshots.

The latest 60-second runs completed without crash: core-only mode measured 20.60 FPS, 12.1% CPU and +9.31 MB RSS; the complete HUD measured 20.75 FPS, 36.2% CPU and +14.52 MB RSS. These are managed offscreen measurements and should be repeated on the user's visible desktop session before treating them as production SLOs.
