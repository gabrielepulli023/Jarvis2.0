# JARVIS upgrade progress

Updated: 2026-08-19

## COMPLETED

- Phase 0 repository audit baseline: inventoried the active source packages, entry point, runtime services, tests, dependencies and major unsafe patterns while excluding environments and packaged builds.
- Recoverable pre-change checkpoint: `backups/ai_os_upgrade_phase0_20260818_193815.zip`.
- Permission hardening increment: deterministic `RiskClassifier`, typed `RiskLevel`, `ActionPolicy` and `PermissionEngine`.
- Restored real confirmation handling for sensitive, administrative and destructive tools; forbidden actions fail closed.
- Replaced unconditional PIN acceptance with salted PBKDF2-HMAC-SHA256 verification.
- Prevented tool/model JSON from forging the internal confirmation marker.
- Added enforced `--safe` / `JARVIS_SAFE_MODE` runtime mode: chat/read-only diagnostics remain available while desktop control, file writes, processes, browser automation and system settings are denied centrally.
- Added a separate elevated broker protocol with DPAPI-protected credentials, HMAC signatures, caller binding, timestamps, anti-replay request IDs, declared risk and mandatory confirmation. Target-PC integrity-level restrictions required the final transport to use a per-launch `127.0.0.1` endpoint rather than a fixed named pipe; no external interface is exposed.
- Added broker-side allowlisted handlers for Winget, service queries/control, firewall status, scheduled-task queries, system information and power actions. Arbitrary shell commands are not accepted.
- Routed Winget install/upgrade out of the user process; broker unavailability fails closed.
- Added broker lifecycle management: native Windows UAC launch (`runas`), packaged/source entrypoints, authenticated ping/stop and watchdog health integration.
- Added a typed Win32 `WindowManager` with title/PID/executable/geometry/monitor/state/active-window inventory, focus, close, minimize/maximize/restore, move/resize and deterministic multi-monitor snap layouts.
- Added `WindowsUIAgent` with structured element/window lookup, invoke, focus, text set/read, selection and bounded wait/hidden operations. UI Automation remains above coordinate/visual fallback.
- Added transactional `FileAgent` plans with path confinement, massive-operation confirmation, dry-run, atomic journals, overwrite/delete backups, explicit rollback and automatic rollback on partial failure.
- Expanded provider routing into an explicit capability matrix: OpenAI for tool execution/current information/vision/interactive conversation, Claude for coding/planning, and Kimi for summarization/long context, with configured-provider fallback and independent work-item routing.
- Added a priority-1000 `EmergencyStopCoordinator` and global `CTRL+ALT+SHIFT+J` hook. It fans cancellation out to async work, active missions, managed processes, automations, voice/TTS and input release without closing the HUD.
- Added automation pause/resume, mission-wide cancellation and managed-process termination APIs used by emergency stop.
- Added a bounded `RecoveryEngine` with per-action/global timeouts, finite retries, alternative strategies, before/after state capture, verification, cancellation and typed final status.
- Added the authoritative typed core state machine covering BOOTING through ERROR, with transition validation and emergency return to IDLE.
- Added incremental file indexing across Desktop/Documents/Downloads with name, extension, path, timestamps and bounded safe textual content. Credential paths/files are excluded and inline secret assignments are redacted; search supports extension and time filters.
- Hardened the Chrome bridge with a per-installation DPAPI-backed token, generated extension-local configuration excluded from version control, bounded command queue, request IDs, expiry, acknowledgements/results, payload limits and server-side secret redaction.
- Expanded browser operations to open/close/activate/list tabs and inspect downloads while continuing to reject arbitrary JavaScript execution and sensitive form fields.
- Added adaptive perception polling so unchanged idle state is reused while recent activity shortens the observation interval; structured DOM/UIA sources remain ahead of vision.
- Added volatile full-screen, active-window, monitor and arbitrary-region capture with in-memory JPEG encoding, fingerprinting and visual change ratio. No frames are persisted.
- Integrated MissionEngine with permission decisions, explicit confirmation state, preconditions, dry-run plans, evidence-based postconditions, alternative recovery strategies and reverse-order rollback actions.
- Added `WAITING_USER` and `SKIPPED` task states and dependency blocking semantics; destructive/admin declarations cannot silently execute.
- Expanded every `SkillManifest` with risk, timeout, bounded retries and verification strategy metadata. Sensitive skills now produce a staged one-time confirmation ID; JSON arguments cannot forge confirmation and forbidden skills cannot be confirmed.
- Added shared local streaming Vosk transcription with incremental partial hypotheses and immediate recognition of `fermati`, `annulla`, `lascia stare` and equivalent stop phrases.
- Connected voice-worker states to the typed core state machine and projected authoritative state, partial transcript, emergency state and broker health into the HUD store/provider.
- Added streaming output for Claude SSE and Kimi chat-completion deltas. All three providers now feed the existing sentence queue so TTS can begin before the full response completes.
- Added `llm_first_token` and `tts_first_audio` latency metrics alongside existing wake/STT/tool measurements.
- Added a declarative, permission-checked plugin layer and manifests for Chrome, VS Code, Spotify, TradingView, File Explorer and Windows Settings; packaged manifests are included in PyInstaller builds.
- Added spontaneous process-exit observation and failure-injection coverage for process crash, offline broker, provider timeout/fallback and TTS failure.
- Corrected capability descriptions so sensitive/admin/destructive confirmation boundaries are represented honestly.
- Final report: `docs/FINAL_AI_OS_REPORT.md`.
- Verification: 231 tests passed, 1 environment-only skip; `pip check` clean; packaged EXE smoke test passed.
- Added a full read-only process inventory (CPU, RAM, executable, parent/children and status), supervised restart, forced termination and owned-tree termination. Spontaneous exits remain event-observed.
- Added `AppManager` discovery across known apps, Start Menu and uninstall registry, ambiguity-safe resolution, open/close actions and exact-ID Winget search/install/upgrade/uninstall through the broker.
- Added event-fed `ContextEngine`, bounded network diagnostics, explicit non-polling clipboard access, HUD notifications, system/hardware inventory and low-frequency device/network change events.
- Structured logs now rotate and recursively redact secrets; the audit API records the complete action schema required by the brief.
- Added `ARCHITECTURE.md`, `SECURITY.md`, `PERMISSIONS.md`, `TOOLS.md`, `DEVELOPMENT.md`, `PERFORMANCE_REPORT.md` and `SECURITY_REPORT.md` based only on implemented modules.
- Current verification: 246 tests passed, 1 environment-only skip.
- Added a DPAPI-backed generic Credential Vault whose inventory never exposes values.
- Added confirmed broker-managed delayed Windows startup (`ONLOGON`, 30-second delay, `LIMITED` task execution).
- Reintroduced the required Command Center as a live 14-category HUD page while preserving Home and Registro.
- Replaced generic terminal execution with named `TerminalAgent`, `CommandValidator`, `ArgumentSanitizer` and `WorkingDirectoryGuard`; inline PowerShell/Python and unsafe Git commands fail closed.
- Integrated the transactional FileAgent into the skill registry and added retained plans, dry-run, rollback, metadata, compare, checksum and ZIP traversal-safe archive handling.
- Added distinct session/preference/task memory kinds, sensitive-content rejection and local vector similarity retrieval.
- Added bounded UI Automation action timeout/retry and complete skill action audit integration.
- Requirement-by-requirement evidence: `docs/REQUIREMENTS_MATRIX.md`.
- Current verification: 268 tests passed, 1 environment-only skip; `pip check` clean.

## IN PROGRESS

- Phase 0 detailed audit report and phased convergence of legacy top-level modules into shared `jarvis_core` services.
- Phase 4 permission coverage for every registered tool and parameter-sensitive risk classification (for example single-file versus massive file operations).
- Credential vault, named Terminal Agent validators, delayed Windows startup support and complete Command Center surfaces.

## REMAINING

- Controlled live UAC/broker IPC validation and installer packaging remain an environment/manual gate.
- Full Windows UI Automation and multi-monitor window management hardening.
- File operation planning/undo, expanded indexing, browser bridge hardening and screen-diff integration.
- Planner rollback/preconditions, recovery strategies, global cancellation and safe-mode enforcement across every executor.
- Live desktop, audio, multi-monitor and elevated-broker validation on the target hardware remains a manual gate.
- Final architecture, security and performance reports after the corresponding implementation phases exist.

## KNOWN ISSUES

- Several legacy top-level modules remain large and partially duplicate responsibilities now present under `jarvis_core`.
- `computer.py`, `tools.py` and `event_automation.py` still contain broad exception handlers; these need scoped remediation with regression tests.
- Git is not available in the current PATH; recoverability currently relies on timestamped ZIP checkpoints.
- Hardware/UI and elevated-operation validation require controlled live Windows checks and are not claimed by automated tests.

## TEST RESULTS

- Focused permissions/core/command regression: 23 passed.
- Full unittest regression after streaming voice/provider/HUD integration: 223 passed, 1 skipped, in 9.791 seconds.
- Dependency integrity: no broken requirements.
- Syntax compilation: `permission_engine.py`, `permission_manager.py`, `action_guard.py`, and `brain.py` passed.

## TRANCHE 10 - OPERABILITY, RECOVERY AND QUALITY

- Added loopback-only bounded Chrome DevTools tab fallback behind the authenticated browser bridge, without arbitrary DOM script execution.
- Expanded Companion with Trading Copilot, Coding Copilot and Do Not Disturb modes plus build, dependency, process and traceback signals.
- Added recoverable watchdog probes, hardware/audio/display topology events, runtime process/GPU telemetry and natural-language Explain mode.
- Added a shared typed error hierarchy and removed the silent failure loop from the legacy event automation worker.
- Added deterministic layered JSON configuration and configured Ruff, Black, mypy and pytest quality gates.
- Controlled Notepad UI Automation was attempted twice; the sandbox launched no window on the interactive desktop, so live GUI verification remains an explicit environment gate.
- Current verification: 280 passed, 1 environment-only DPAPI skip; Ruff, Black, scoped mypy and `pip check` clean.

## TRANCHE 11 - CENTRAL AI GATEWAY AND ARCHITECTURE GUARDS

- Centralized all OpenAI-compatible SDK construction in `llm_gateway.py`, retaining bounded per-purpose timeout/retry profiles and connection pooling.
- Added a deterministic, bounded and non-persistent `clipboard.summarize` skill for explicit clipboard requests.
- Removed remaining bare exception handlers from project code and added an AST regression test that rejects both bare handlers and SDK construction outside the gateway.
- Current full regression: 283 passed, 1 environment-only DPAPI skip.

## TRANCHE 12 - COMPLETE CONTROL SURFACES

- Added typed validated mouse/keyboard skills for absolute and relative multi-monitor movement, all click variants, drag, scroll, shortcuts and explicit key down/up.
- Expanded the broker allowlist for firewall profiles/program rules, existing scheduled tasks, device scans, Windows Update history/scan, Winget upgrade-all and power actions.
- Added structured TradingView DOM evidence ahead of visual chart analysis, filtering sensitive controls and treating page content as untrusted.
- Added selective graceful app closing, system pressure diagnosis, JARVIS-only memory trimming and validated Python virtual-environment creation.
- Added `docs/REPOSITORY_AUDIT.md` and architecture gates for bare exception handlers and centralized model SDK construction.
- Controlled elevated broker smoke reached the elevation boundary but no authenticated pipe appeared within 30 seconds in the managed runner; live UAC remains an explicit environment gate.
- Current full regression: 292 passed, 1 environment-only DPAPI skip; selected Ruff, scoped mypy and `pip check` clean.
- Expanded mypy from seven security-critical files to all 65 files in the modern `jarvis_*` architecture plus `llm_gateway.py`; the expanded gate passes without errors.

## FINAL TARGET-PC ACCEPTANCE

- Target-PC report `data/acceptance/acceptance-20260819-150926.json` passes Notepad write/save verification, Calculator UIA, File Explorer UIA, audio input/output discovery, display discovery and the elevated broker.
- The UAC broker passes authenticated system, driver and installed-software inventory and shuts down cleanly; fixed named-pipe ACL incompatibility was replaced by per-launch HMAC-authenticated loopback IPC.
- The active machine exposes one 1920x1080 monitor, so a second physical monitor is not testable there; deterministic virtual-screen, negative-coordinate and multi-monitor snap tests pass.
- Final source verification: 304 tests passed with one managed-environment DPAPI skip; scoped Black/Ruff, mypy (67 files) and `pip check` clean. The final packaged broker passed authenticated ping/stop under the real Windows identity; the normal EXE remained alive for the eight-second smoke test.
