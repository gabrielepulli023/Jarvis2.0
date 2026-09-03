"""Deprecated compatibility facade over the canonical runtime context."""


def _runtime():
    from jarvis_core.runtime import RUNTIME
    return RUNTIME


def current():
    return _runtime().context.snapshot()


def update(request=None, result=None, window=None, tool=None):
    from jarvis_core.reference_resolution import record_assistant_turn, record_operational_action, record_user_turn
    runtime = _runtime()
    if request:
        record_user_turn(runtime, request)
    if result:
        record_assistant_turn(runtime, result)
        record_operational_action(runtime, request or "", {"successo": True, "verification": {"status": "verified"}})
    if window:
        runtime.memory.working.set("conversation.active_window", str(window)[:500], ttl=300)
    if tool:
        runtime.memory.working.set("conversation.last_tool", str(tool)[:100], ttl=300)
    return current()


def clear():
    working = _runtime().memory.working
    for key in tuple(working.snapshot()):
        if str(key).startswith("conversation."):
            working.set(key, None, ttl=0)
    return True
