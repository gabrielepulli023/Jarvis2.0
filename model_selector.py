from settings_store import get_setting


def select_model(task_type, complexity="simple"):
    primary = str(get_setting("ai_model", "gpt-5.6-luna"))
    fast = str(get_setting("fast_model", "gpt-5-mini"))
    vision = str(get_setting("vision_model", primary))
    if task_type == "vision":
        return vision
    if task_type in {"router", "critic"} and complexity == "simple":
        return fast
    return primary


def reasoning_options(model, effort, tools=None):
    """Build a reasoning argument only for model families that accept it."""
    name = str(model or "").strip().lower()
    if not (name.startswith("gpt-5") or name.startswith(("o1", "o3", "o4"))):
        return None
    value = str(effort or "minimal").strip().lower()
    # gpt-5.6-luna intentionally uses the newer Responses effort vocabulary:
    # unlike gpt-5-mini it rejects ``minimal`` with HTTP 400. Keep this
    # normalization centralized so router, critic and vision cannot diverge.
    if name == "gpt-5.6-luna" and value == "minimal":
        value = "none"
    elif value == "none":
        value = "minimal"
    if value not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
        value = "low"
    tool_types = {str(tool.get("type", "")) for tool in (tools or ()) if isinstance(tool, dict)}
    # Responses API does not accept web_search with minimal reasoning.
    if "web_search" in tool_types and value in {"none", "minimal"}:
        value = "low"
    return {"effort": value}
