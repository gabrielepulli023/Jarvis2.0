# Tool system

Every registered skill declares name, version, description, intents, permissions, entrypoint, risk, timeout, retries, fallbacks and verification strategy. The runtime exposes structured tools for windows/UIA, browser DOM, files/indexing, processes, applications/Winget, network, clipboard, notifications, system information, developer LAB operations and TradingView observation.

Use `RUNTIME.skills.list()` for the authoritative inventory and `RUNTIME.skills.metrics()` for execution statistics. Sensitive calls first return a one-time `action_id`; execution occurs only through `SkillRegistry.confirm(action_id)`. Existing structured tools take precedence over terminal commands.
