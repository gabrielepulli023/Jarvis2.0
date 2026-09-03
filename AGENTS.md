# JARVIS engineering guide

- Target: Windows 10/11, Python 3.12 in `.runtime-env`; entry point `main.py` (`Avvia Jarvis.cmd`).
- Tests: `.\.runtime-env\Scripts\python.exe -m unittest discover -s tests -v`; dependencies: `python -m pip check`.
- Shared architecture: `jarvis_core` owns config, structured logs, events, state, processes, health and lifecycle. Missions, memory, skills, perception, voice, developer, automation, HUD and Companion extend these services; do not create parallel buses, memory stores, TTS or chat stacks.
- Critical path: start → HUD → wake word → STT → intent/action or AI → response → TTS. Preserve it at every checkpoint.
- Companion is silence-first, uses the shared voice queue, and must degrade without crashing the critical path. Trading analysis is advisory only; never execute orders.
- Persist runtime data below `data/`; never log secrets or persist sensitive screenshots. Private operation must avoid persistent learning.
- Changes must be integrated, tested and verified before being marked complete. No production placeholders, weakened assertions, swallowed errors or false completion. Add regression tests for significant bugs.
- Use bounded queues/history, timeouts, cancellation and deterministic shutdown. Verify malformed input, failure isolation, deduplication, cooldown and event storms where relevant.
- Preserve user changes. Before a major phase create a recoverable ZIP in `backups/` excluding environments/build outputs; record baseline and checkpoint names in `docs/IMPLEMENTATION_STATUS.md`.
- Verification hierarchy: focused tests → full unittest regression → `pip check` → manual hardware/UI checks when available. Clearly separate verified, partial and environment-blocked work.

