# JARVIS AI OS — final engineering report

Date: 2026-08-18

## Delivered architecture

JARVIS now uses shared `jarvis_core` lifecycle, events, state, health, process supervision, recovery and emergency-stop services. Typed skills declare permissions, risk, timeout, retries and verification. Missions support preconditions, dry-run, user-wait states, evidence, bounded fallback and rollback. Windows control prefers Win32/UI Automation, browser control prefers the authenticated DOM bridge, and visual coordinates remain the last fallback.

The declarative plugin layer loads JSON manifests only; plugin files cannot import executable Python. It verifies that every contributed tool maps to an existing skill, cannot request permissions outside the plugin grant, and cannot downgrade the underlying risk. Shipped plugins: Chrome, VS Code, Spotify, TradingView (advisory only), File Explorer and Windows Settings.

## Security boundary

- SAFE actions may run autonomously when their capability is enabled.
- SENSITIVE, ADMIN and DESTRUCTIVE actions require a real, one-time confirmation.
- FORBIDDEN actions fail closed and cannot be confirmed.
- Administrative operations use an allowlisted elevated broker on a per-launch `127.0.0.1` endpoint with DPAPI credentials, HMAC request signing, caller binding, timestamps and replay protection; no external interface is exposed.
- Safe Mode centrally disables desktop control, writes, processes, browser automation and settings changes.
- Secrets are excluded from indexing/logging; browser payloads are bounded and redacted; screenshots remain volatile.
- Emergency stop cancels missions and async work, pauses automation, terminates managed processes, stops voice, releases input and returns the state machine to IDLE.
- Trading remains analysis-only. The system does not place orders, bypass UAC/security controls, steal credentials, evade access controls or silently perform destructive actions.

## Provider/API assignment

| Work category | Primary | Fallback order |
|---|---|---|
| Tool execution, current web information, vision, conversation | OpenAI | Claude, Kimi |
| Coding and debugging | Claude | OpenAI, Kimi |
| Planning and dependency analysis | Claude | Kimi, OpenAI |
| Summarization and long context | Kimi | Claude, OpenAI |

Each independent work item is classified separately. Only configured providers are selected; keys stay in environment variables and are never written to manifests or logs. User-selected provider preference takes precedence for non-tool conversational tasks.

## Verification

- Full automated regression: 310 passed, 1 environment-only DPAPI skip where applicable.
- ElevenLabs is the primary TTS provider when `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are configured. The provider uses `eleven_flash_v2_5`, internal voice defaults, PCM streaming, cancellation, bounded retry/timeout, cache, speech cost optimization and local edge-TTS fallback.
- Failure injection: process crash, broker offline, provider/API timeout with fallback and TTS failure all degrade without taking down the runtime.
- Dependency integrity: `pip check` reports no broken requirements.
- The deterministic `quality_gate.ps1` passes scoped Ruff and Black across the modern architecture, mypy across 67 files, unittest and `pip check`.
- Packaged executable: `dist/JARVIS/JARVIS.exe`, 18,430,007 bytes, SHA-256 `FB907C322818499DA31982D3F20E4FC06800DB5298BD68B71D3AFC94B14CF87A`.
- Package contains layered configuration and all seven plugin manifests, including the advisory football analyzer; it remained alive during an eight-second normal smoke test, and its minimal broker entrypoint completed authenticated ping/stop under the real Windows identity.
- Latest target-PC acceptance: audio input/output enumeration, a two-second volatile microphone sample, Notepad text/save, Calculator UIA, File Explorer UIA and authenticated broker inventory all passed. Multi-monitor was correctly marked `SKIP` because the machine exposes one monitor.
- Voice artifacts are present and validated: the Italian Vosk model is complete, and focused wake queue/audio health/streaming STT/barge-in/TTS shutdown tests pass.
- Recoverable source checkpoint: `backups/tranche15_tool_registry_acceptance_20260819.zip` (secrets, environments, runtime data, model and build outputs excluded).

## Manual gates and honest limits

Automated tests cannot prove microphone/speaker quality, wake-word behavior in a noisy room, all third-party UI layouts, every multi-monitor/DPI combination, network/provider availability, or elevated broker behavior under every Windows policy. `Esegui collaudo JARVIS.cmd` performs the safe desktop subset in the user's interactive session and records JSON evidence. In the managed runner, display/window discovery passed but PyAutoGUI's corner fail-safe correctly blocked input; UAC, audio and multi-monitor checks remain manual. External services remain limited by credentials, quotas, policies and outages. JARVIS deliberately does not gain unlimited authority: OS security boundaries and explicit destructive confirmations remain enforced.
