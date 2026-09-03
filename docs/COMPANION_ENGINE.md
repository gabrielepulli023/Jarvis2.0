# Companion Engine

The Companion Engine is a capability of `CoreRuntime`, not a second application. It subscribes to the shared EventBus, records its snapshot in the shared StateManager, emits structured `companion.decision` events and sends approved speech through the existing interruptible `VoiceSessionEngine`.

Flow: local producer → typed event → detector → intervention candidate → confidence/score → mode → deduplication → interruption budget/voice collision check → silence, HUD-only or shared TTS.

Defaults are conservative: mode `normal`, Coding and Trading Copilots off, minimum confidence `0.70`, HUD threshold `0.60`, voice threshold `0.80`, duplicate cooldown 15 minutes and a two-message budget recovering at one message/hour. Persistent overrides are stored atomically in `data/companion/preferences.json`. Invalid persisted JSON falls back safely.

The implemented Coding slice consumes `test.failed` events containing a stable `signature` or `traceback`. Three equal failures within 15 minutes create one intervention. Subsequent identical events are suppressed by fingerprint/cooldown. The approved message is interruptible and its reason is retained as pending conversation context for the normal conversation router to consume.

Modes:

- `passive`: always silent.
- `normal` / `companion`: score policy applies.
- `focus`: non-critical candidates are at most HUD-only.

Voice/text commands handled before the operational router are: `Jarvis modalità focus`, `Jarvis non interrompermi`, `Jarvis esci dalla modalità focus`, and `Jarvis puoi tornare a parlare`.

Diagnostics are available through `CoreRuntime.diagnostics()["companion"]` and the HUD snapshot provider. Decision logs contain score, confidence, decision, reason, cooldown state, category and remaining budget; message payloads are not copied into decision logs.

Run focused tests with `.\.runtime-env\Scripts\python.exe -m unittest tests.test_companion -v` and the full regression command documented in `AGENTS.md`.
