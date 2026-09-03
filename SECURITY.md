# Security model

JARVIS uses least privilege. SAFE actions may run when their capability is enabled. SENSITIVE, ADMIN and DESTRUCTIVE actions are staged behind one-time user confirmation. FORBIDDEN actions cannot be confirmed. Safe Mode denies desktop control, writes, processes, browser automation and system settings.

The elevated broker listens on a per-launch authenticated endpoint bound exclusively to `127.0.0.1`. This loopback transport is used because Windows integrity-level ACLs rejected medium-to-high named-pipe connections on the target PC. Requests contain identity, timestamp, action, parameters, declared risk, confirmation and an HMAC signature using a DPAPI-protected installation secret. It rejects stale, replayed, tampered, unknown and incorrectly classified requests. It exposes an allowlist, never an arbitrary elevated shell or external-network listener.

Secrets belong in environment variables or DPAPI-backed storage. Structured logging and audit recursively redact password, authorization, token, secret and API-key fields and rotate bounded files. Screen capture is volatile; clipboard access is explicit and non-polling; indexed content excludes credential locations and secret assignments.

Residual risks include third-party UI changes, compromised same-user desktop sessions, provider outages and Windows accessibility boundaries. UAC elevation and read-only broker inventory were validated on the target PC; destructive operations still require an explicit one-time confirmation. Trading is advisory only.
