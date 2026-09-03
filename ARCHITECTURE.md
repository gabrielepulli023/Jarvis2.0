# JARVIS architecture

```text
Voice / HUD / Automation / Companion
                 |
       Core EventBus + StateMachine
                 |
 Perception -> Planner -> Skill Registry
                 |
 Desktop | Browser | Files | Apps | Coding | System
                 |
       Verification + Recovery + Audit
                 |
 User process -- authenticated loopback IPC -- Privileged Broker
```

`jarvis_core` owns lifecycle, typed state, events, health, watchdog, process supervision, recovery and emergency cancellation. `jarvis_missions` persists task graphs, dependencies, evidence and rollback. `jarvis_skills` is the only capability registry and enforces permissions and declared risk before dispatch. `jarvis_perception` chooses DOM, UI Automation and vision in that order and verifies observed state changes.

`jarvis_apps`, `jarvis_files`, `jarvis_windows`, `jarvis_system`, `jarvis_developer` and the authenticated browser bridge provide domain operations. JSON-only manifests under `plugins/` compose existing skills without loading plugin code. Administrative mutations cross a per-launch HMAC-authenticated `127.0.0.1` broker endpoint; the main UI process is not elevated and no external interface is bound.

Long-running work is isolated in bounded queues, worker threads or the async engine. Events connect subsystems without introducing another bus. Runtime persistence lives below `data/`; secrets and transient screen/clipboard contents are excluded.
