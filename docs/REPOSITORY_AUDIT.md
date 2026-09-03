# Repository audit

Evidence date: 2026-08-18. This document describes the executable repository state, not an aspirational design.

## Runtime map

- Entry point: `main.py`; Windows launcher: `Avvia Jarvis.cmd`; package recipe: `build_exe.ps1` / `JARVIS.spec`.
- `jarvis_core` owns configuration, events, typed state, lifecycle, health, process supervision, recovery, emergency stop and service composition.
- `brain.py` remains the compatibility tool-calling surface used by the existing HUD/voice path. Remote SDK construction is centralized in `llm_gateway.py`; work classification and OpenAI/Claude/Kimi fallback live in `provider_router.py`.
- `jarvis_voice` owns the bounded voice queue and session state. `voice.py`, `wakeword.py` and `transcriber.py` adapt the existing Vosk/PyAudio/OpenAI transcription and local/remote TTS path to it.
- `hud.py` is the production PySide6 UI. It consumes runtime diagnostics/state and exposes Home, Registro and the 14-category Command Center.
- `jarvis_windows`, `jarvis_apps`, `jarvis_files`, `jarvis_browser`, `jarvis_perception` and `jarvis_terminal` provide the structured control planes. Direct input is the lowest-priority desktop fallback behind UIA/accessibility.
- `jarvis_missions`, `jarvis_automation`, `jarvis_memory`, `jarvis_companion`, `jarvis_developer`, `jarvis_plugins` and `jarvis_vault` extend shared core services rather than creating independent buses or stores.
- `jarvis_broker` is a separate elevated process using per-launch HMAC-authenticated loopback IPC. JARVIS itself remains non-elevated.

## Persistence and configuration

- Runtime state is confined below `data/`; SQLite stores are migrated by their owning modules.
- Deterministic JSON configuration is loaded from `config/`; secrets come from environment variables or DPAPI and are excluded by `.gitignore`.
- Logs and audit records are rotating, bounded and recursively redacted. Screen frames and clipboard summaries are not persisted.

## Dependency and execution boundaries

- PySide6 owns the UI loop; voice, automation, monitoring, recovery and tool work use separate bounded workers.
- OpenAI-compatible clients are created only by `llm_gateway.py`. Claude uses a bounded HTTPS streaming adapter; Kimi uses the same centralized compatible-client gateway.
- External process execution is confined to named adapters: the validated Terminal Agent, App/Winget manager, network diagnostics, GPU probe, developer lab and privileged broker. Model text is never passed directly to a shell.
- Browser priority is authenticated extension/DOM, loopback-only CDP, accessibility and then visual fallback. CDP deliberately exposes no arbitrary JavaScript evaluation.

## Duplication and compatibility debt

- `computer.py`, `tools.py`, `ai.py`, `voice.py` and `brain.py` are large legacy compatibility surfaces. Structured implementations under `jarvis_*` are authoritative for new work; deleting the adapters now would break the proven critical path and is therefore deferred rather than disguised as cleanup.
- `event_automation.py` is retained for old HUD commands; `jarvis_automation` is the authoritative event-driven engine.
- The old convenience system/search functions remain referenced by the legacy tool schema. They are not classified as dead until call-site migration is complete.
- Packaged reference directories and backups are artifacts, not imported source, and are excluded from static quality/audit scans.

## Risks and bottlenecks found

- Direct SDK construction was scattered across seven modules; it is now centralized and guarded by an AST regression test.
- Bare exception handlers could hide automation failures; project source now has an AST gate forbidding every bare `except:`.
- Visual desktop control is slower and less deterministic than UIA/DOM; it remains a bounded last fallback with post-action verification.
- Legacy modules still contain broad, but non-bare, compatibility catches. These return/log structured failures; narrowing them further requires call-site-specific migration.
- Model, microphone, speaker, multi-monitor/DPI, UAC and third-party UI performance depend on target hardware and Windows policy. Automated evidence cannot replace controlled interactive acceptance tests.
- Importing the legacy HUD/AI surface is comparatively expensive. Startup uses staged preload/lazy initialization, while the critical UI state is shown before optional services finish.

## Concurrency and shutdown audit

- Shared queues and histories are bounded; long operations use timeouts and cancellation tokens.
- Event handlers are isolated, event automation deduplicates IDs and ignores automation-originated recursion.
- Emergency stop propagates to missions, subprocesses, automation, voice and held input state.
- Watchdog recovery is restricted to restartable secondary workers; it does not attempt unsafe in-process reconstruction of the primary Qt event loop.
- Runtime shutdown stops producers before stores/process supervision and avoids joining the current worker thread.

## Security audit summary

- Permission decisions are centralized by capability and risk; sensitive/admin/destructive work uses expiring one-time confirmation.
- The broker validates caller, action, parameters, timestamp, risk, confirmation, signature and replay state.
- Safe Mode denies control/write/process/browser/system capabilities centrally.
- Trading is advisory only. Credential theft, access-control bypass, arbitrary browser script execution and self-modification of permission policy are forbidden.

## Verification gates

- `tests/test_architecture_audit.py` enforces the SDK and bare-exception boundaries.
- Unit/integration/failure tests cover permissions, broker protocol, planner, recovery, cancellation, memory, files, browser, voice, plugins and system agents.
- Ruff, Black, scoped strict mypy, pytest and `pip check` are the maintained automated gates.
- Live GUI, audio, multi-monitor/DPI and UAC acceptance remain explicitly manual because the managed runner is not attached to the interactive Windows desktop.
