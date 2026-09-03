# Performance baseline

Date: 2026-08-10. Checkpoint before changes: `backups/performance_pre_20260810_192522.zip`.

Hardware detected: Windows 11 build 26200, Intel64 Family 6 Model 126 (8 logical CPUs), 8,361,132,032 bytes RAM. Measurements are local synthetic benchmarks; microphone, network AI, Chrome and visible HUD measurements require interactive hardware scenarios and are not represented here.

| Pipeline | Before P50 | Before P95 | Before P99 | After P50 | After P95 | After P99 |
|---|---:|---:|---:|---:|---:|---:|
| Metrics hot-path record | 0.4778 ms | 1.3017 ms | 1.5206 ms | 0.0240 ms | 0.0386 ms | 0.0730 ms |
| EventBus publish | 0.0044 ms | 0.0054 ms | 0.0079 ms | 0.0044 ms | 0.0050 ms | 0.0097 ms |
| Memory search, 200 records | 8.3610 ms | 9.6725 ms | 10.8699 ms | 9.2084 ms | 11.1781 ms | 13.2541 ms |
| Trace mark overhead | n/a | n/a | n/a | 0.0066 ms | 0.0141 ms | 0.0501 ms |

Metrics recording improved 95.0% at P50 and 95.2% at P99 by replacing read/parse/full-file-write on every event with locked in-memory aggregation, bounded samples and atomic rate-limited flush. It now records calls, success rate, average, P50, P95, P99 and maximum.

Memory search did not improve and fluctuated slightly worse in the second run; no optimization claim is made. EventBus remained effectively unchanged. Importing `main` measured 598 ms median over five separate processes (cold first sample 1,022 ms); no post-change import improvement is claimed.

Run the repeatable benchmark with:

```powershell
.\.runtime-env\Scripts\python.exe -m jarvis_core.benchmark
```

Current benchmark process footprint was 31,178,752 RSS bytes and seven threads. This is the benchmark process, not the full Qt application.

Outstanding performance gates: wake/VAD/STT accuracy and percentiles, AI first-token/streaming audio, real Windows/Chrome actions, vision fallback, HUD frame stalls, full startup stages, idle CPU/RAM and sustained load/soak tests.

## Identity pipeline

Synthetic local measurements after implementation: speaker descriptor 3.235 ms, face descriptor 2.668 ms and 1.96 MB peak allocation for the benchmark batch. Both are executed outside the Qt UI thread. Camera startup and frame capture were verified at 640x480; no diagnostic frame was retained.
