from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from typing import Any

RESULT_PREFIX = "JARVIS_BROWSER_RESULT="


def _final_result(history: Any) -> str:
    value = getattr(history, "final_result", None)
    if callable(value):
        try:
            final = value()
            if final:
                return str(final)
        except Exception:
            pass
    return str(history)


def _build_llm(model: str):
    if os.getenv("BROWSER_USE_API_KEY"):
        from browser_use import ChatBrowserUse

        kwargs = {"model": model} if model else {}
        return ChatBrowserUse(**kwargs)

    if os.getenv("OPENAI_API_KEY"):
        try:
            from browser_use import ChatOpenAI
        except ImportError:
            from browser_use.llm import ChatOpenAI
        return ChatOpenAI(model=model or "gpt-5-mini")

    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            from browser_use import ChatAnthropic
        except ImportError:
            from browser_use.llm import ChatAnthropic
        return ChatAnthropic(model=model or "claude-haiku-4-5-20251001")

    raise RuntimeError(
        "Manca BROWSER_USE_API_KEY, OPENAI_API_KEY o ANTHROPIC_API_KEY."
    )


async def _run(payload: dict[str, Any]) -> dict[str, Any]:
    from browser_use import Agent

    task = str(payload.get("task") or "").strip()
    if not task:
        raise ValueError("Task Browser Use vuoto")

    model = str(payload.get("model") or "").strip()
    max_steps = max(1, min(100, int(payload.get("max_steps") or 25)))
    agent = Agent(task=task, llm=_build_llm(model))
    try:
        history = await agent.run(max_steps=max_steps)
    except TypeError:
        history = await agent.run()

    final = _final_result(history)
    return {"success": True, "message": final, "data": {"final_result": final}}


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
        result = asyncio.run(_run(payload))
        print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except BaseException as exc:
        result = {
            "success": False,
            "message": f"Errore Browser Use sidecar: {exc}",
            "error_type": type(exc).__name__,
        }
        print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
        if os.getenv("JARVIS_DEBUG") == "1":
            traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
