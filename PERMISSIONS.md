# Permissions and risk

| Risk | Behavior | Examples |
|---|---|---|
| SAFE | Runs when the capability is granted | list windows, read system status |
| SENSITIVE | One-time confirmation | read clipboard, close applications |
| ADMIN | One-time confirmation plus broker | Winget install/uninstall, services |
| DESTRUCTIVE | Explicit one-time confirmation and rollback when possible | massive deletion, forced process tree termination |
| FORBIDDEN | Always denied | bypassing controls, self-escalation |

Capabilities are `READ_SCREEN`, `CONTROL_MOUSE`, `CONTROL_KEYBOARD`, `READ_FILES`, `WRITE_FILES`, `PROCESS_CONTROL`, `NETWORK`, `BROWSER_CONTROL` and `SYSTEM_SETTINGS`. Plugin permissions must contain every tool permission and may never lower the underlying skill risk.
