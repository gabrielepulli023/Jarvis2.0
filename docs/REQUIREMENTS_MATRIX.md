# JARVIS requirements matrix

Evidence date: 2026-08-19. `VERIFIED` means covered by current code plus automated or recorded target-PC acceptance evidence.

| # | Requirement | Status | Authoritative evidence / remaining gate |
|---:|---|---|---|
| 1 | Repository audit | VERIFIED | `docs/REPOSITORY_AUDIT.md` maps runtime, dependencies, persistence, duplication, bottlenecks, concurrency, security and remaining compatibility debt. |
| 2 | Core architecture | VERIFIED | `jarvis_core/runtime.py`, shared lifecycle/events/state/recovery. |
| 3 | Privileged broker | VERIFIED | Per-launch authenticated loopback IPC covers packages, services, firewall, tasks, power, driver inventory/scan and Windows Update history/scan; target-PC UAC and read-only inventory pass. |
| 4 | Permission engine | VERIFIED | Typed risks, confirmation, forbidden fail-closed and tests. |
| 5 | Mouse/keyboard | VERIFIED | Typed `InputController` and structured skills cover absolute/relative movement, clicks, drag, scroll, bounded text input, shortcuts, press/down/up and virtual multi-monitor bounds. |
| 6 | Windows UI Automation | VERIFIED | Named operations plus bounded timeout/retry and tests. |
| 7 | Window Manager | VERIFIED | Inventory, state, geometry, monitor and window actions with backend tests. |
| 8 | Process Manager | VERIFIED | OS resource/hierarchy inventory, supervision, restart, stop/kill/tree and events. |
| 9 | App Manager | VERIFIED | Known/Start Menu/registry discovery, ambiguity handling and broker Winget operations. |
| 10 | File System Agent | VERIFIED | Transaction plans, dry-run, undo, archive/extract, compare/checksum/metadata. |
| 11 | PC search | VERIFIED | Incremental secret-aware metadata/content index and filtered search. |
| 12 | Browser Agent | VERIFIED | Authenticated DOM bridge plus loopback-only bounded CDP tab fallback and visual fallback; arbitrary JavaScript remains deliberately forbidden. |
| 13 | Screen perception | VERIFIED | Volatile region/window/monitor capture, diff and adaptive polling. |
| 14 | Action verification | VERIFIED | Verified action runner, postconditions, retry/fallback and anti-loop tests. |
| 15 | Recovery Engine | VERIFIED | Bounded strategies, state capture, timeouts and cancellation. |
| 16 | Task Planner | VERIFIED | Persisted graph, dependencies, pre/postconditions, evidence and rollback. |
| 17 | Tool Registry | VERIFIED | Structured registry includes the complete input and clipboard surfaces plus permission/risk/timeout/retry/verification metadata. |
| 18 | Terminal Agent | VERIFIED | Validator, sanitizer, cwd guard, allowlists, bounded output and no inline model shell. |
| 19 | Coding Agent | VERIFIED | Repository analyzer and transactional LAB edit/test/promote/rollback pipeline. |
| 20 | OpenAI intelligence | VERIFIED | `llm_gateway.py` is the sole SDK construction boundary; task routing, context selection, streaming and per-provider fallback are tested. |
| 21 | Speed | VERIFIED | Streaming, queues, cache, preload and stage metrics are integrated; the local p50/p95/p99 benchmark is recorded in `PERFORMANCE_REPORT.md`. |
| 22 | Event Bus | VERIFIED | Typed bounded pub/sub usage and event isolation tests. |
| 23 | Context Engine | VERIFIED | Active window, apps, task, conversation, state and recent event snapshot. |
| 24 | Memory System | VERIFIED | Working plus session/preference/task/episodic/semantic/procedural stores and local vector retrieval. |
| 25 | Credential Vault | VERIFIED | SQLite metadata plus per-value DPAPI encryption; inventory never returns values. |
| 26 | Proactivity Engine | VERIFIED | Modes, scoring, budget, cooldown, deduplication and silence-first tests. |
| 27 | Companion Mode | VERIFIED | Contextual continuity, suppression and event-storm behavior tested. |
| 28 | Trading Copilot | VERIFIED | Authenticated TradingView DOM context is filtered and combined with visual evidence; output is advisory and order execution remains absent. |
| 29 | Coding Copilot | VERIFIED | Build/task/dependency/process/traceback events and repeated test failures are detected with silence-first cooldowns. |
| 30 | Voice pipeline | VERIFIED | Streaming STT/TTS, VAD, barge-in and cancellation pass; target-PC input/output enumeration and volatile microphone capture are recorded. |
| 31 | HUD states | VERIFIED | Typed core/voice/emergency/broker state projected to HUD. |
| 32 | Command Center | VERIFIED | Live 14-category page: System through Voice. |
| 33 | Audit log | VERIFIED | Full action schema, rotation and recursive secret redaction. |
| 34 | Action history | VERIFIED | Recent structured action records exposed by runtime diagnostics. |
| 35 | Emergency stop | VERIFIED | Global shortcut and priority cancellation fan-out. |
| 36 | Safe Mode | VERIFIED | Central capability denial and tests. |
| 37 | Watchdog | VERIFIED | Heartbeats and probes cover core services; companion, hardware and automation workers restart when safe, while the primary Qt loop fails visibly. |
| 38 | Health monitor | VERIFIED | Core/voice/broker/audio/wake probes and typed health states. |
| 39 | Performance monitor | VERIFIED | Bounded process CPU/RAM/VMS/thread/handle/queue telemetry plus cached NVIDIA GPU telemetry when the vendor tool is present. |
| 40 | Network Agent | VERIFIED | Interfaces, IP, DNS, bounded connectivity and injection-safe ping. |
| 41 | System information | VERIFIED | CPU/RAM/storage/battery/temp/OS/uptime/monitors/audio and cached GPU detail, with explicit vendor-tool unavailability. |
| 42 | Hardware events | VERIFIED | Low-frequency storage, network, audio-device and display topology diffs emit bounded events; hardware presence remains machine-dependent. |
| 43 | Multi-monitor | VERIFIED | Native work areas, normalized coordinates, geometry and snap tests. |
| 44 | Clipboard intelligence | VERIFIED | Explicit text/image/files inspection, confined image save and bounded non-persistent `clipboard.summarize` shortcut. |
| 45 | Notification Center | VERIFIED | Bounded prioritized runtime/HUD event center. |
| 46 | Automation Engine | VERIFIED | Persistent triggers, chains, retries, deduplication and history. |
| 47 | Startup | VERIFIED | Confirmed broker-created delayed ONLOGON task running at LIMITED level. |
| 48 | Plugin architecture | VERIFIED | JSON-only composition with permission/risk monotonicity. |
| 49 | App-specific plugins | VERIFIED | Seven manifests, including the advisory football analyzer, packaged and validated. |
| 50 | State machine | VERIFIED | Authoritative typed transitions and emergency path. |
| 51 | Async architecture | VERIFIED | Separate Qt, voice, automation, recovery and async lanes with cancellation. |
| 52 | Message bus | VERIFIED | Event identity/type/time/source/payload/priority/confidence/dedup fields. |
| 53 | Priority system | VERIFIED | Emergency and voice priorities with interruption. |
| 54 | Task cancellation | VERIFIED | Missions, subprocesses, async, TTS and automation fan-out. |
| 55 | Transactions | VERIFIED | File and developer transactions with rollback. |
| 56 | Dry run | VERIFIED | Mission and file-plan simulation without side effects. |
| 57 | Explain mode | VERIFIED | Persisted mission evidence is exposed through `/explain` and Italian natural-language variants with current step, reason and progress. |
| 58 | Configuration | VERIFIED | Layered deterministic JSON config directory plus environment overrides. |
| 59 | Secrets | VERIFIED | Environment/DPAPI, git exclusions, redaction and persistence filters. |
| 60 | Database | VERIFIED | Migrated SQLite stores for memory, missions, metrics, automation, vault and developer state. |
| 61 | Test suite | VERIFIED | Current full suite: 310 passed, 1 environment-only DPAPI skip where applicable; executed by `quality_gate.ps1`. |
| 62 | Desktop automation tests | VERIFIED | Target-PC report proves exact-HWND Notepad write/save, Calculator UIA and File Explorer UIA; deterministic tests cover retries, failure and virtual multi-monitor geometry. |
| 63 | Admin broker tests | VERIFIED | Target-PC UAC smoke proves authenticated IPC and system/driver/software queries; protocol tests cover invalid token, replay, expiry, malformed arguments and confirmation. |
| 64 | Failure injection | VERIFIED | Crash, missing app, UI failure, network loss, API/STT/TTS/broker failures covered. |
| 65 | Logging | VERIFIED | Structured levels, rotation and secret redaction. |
| 66 | Error handling | VERIFIED | Named common exception hierarchy, explicit result paths and an AST regression gate rejecting every bare `except:` in project code. |
| 67 | Type hints | VERIFIED | Mypy checks 67 source files across the modern `jarvis_*` architecture plus the LLM gateway with no errors; legacy adapters remain compatibility-only. |
| 68 | Code quality tools | VERIFIED | The deterministic `quality_gate.ps1` passes scoped Ruff, Black, mypy, unittest and dependency checks; dependency integrity passes. |
| 69–72 | Documentation/reports | VERIFIED | README plus architecture, security, permissions, tools, development and reports. |
| 73 | Prohibited shortcuts | VERIFIED | AST gates forbid bare handlers and scattered SDK construction; shell, broker, secrets and safety boundaries have dedicated tests. |
| 74 | Best API principle | VERIFIED | DOM/CDP/UIA/Win32 precede input/vision fallbacks in the implemented tool manifests and architecture audit. |
| 75 | Verification principle | VERIFIED | Missions and `VerifiedActionRunner` enforce permission, execution, evidence, recovery and final status. |
| 76 | Speed principle | VERIFIED | Streaming, bounded queues, events, adaptive polling and measured latency stages replace fixed multi-second synchronization sleeps. |
| 77 | Modularity principle | VERIFIED | The modern `jarvis_*` service architecture is split by bounded responsibility and composed only by `CoreRuntime`. |
| 78 | Autonomy principle | VERIFIED | Mission planning, retry, fallback, rollback, cancellation and Explain mode operate without per-step user questions except policy confirmations. |
| 79–81 | Phased workflow/progress | VERIFIED | Checkpoints, tests and `JARVIS_UPGRADE_PROGRESS.md`. |
| 82 | Final command scenarios | VERIFIED | Structured skills cover every listed scenario class; target-PC desktop and broker primitives pass, while destructive examples remain deliberately confirmation-gated rather than executed during acceptance. |
| 83 | Final platform | VERIFIED | Integrated AI assistant, desktop/browser/coding agents, voice, memory, proactivity, broker, verification/recovery and HUD are implemented, tested and target-PC accepted. |
