"""Provider-neutral conversational routing for JARVIS."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

from llm_gateway import kimi_client

from settings_store import get_setting
from decision_layer import decide as decide_intent


@dataclass(frozen=True)
class RouteDecision:
    provider: str
    model: str
    task_kind: str
    reason: str


_CURRENT_INFO = ("oggi", "ieri", "adesso", "attuale", "ultime", "notizie", "meteo", "prezzo", "mercat", "borsa", "sport")
_CODING = ("codice", "python", "rust", "bug", "errore", "debug", "repository", "progetto", "funzione", "test")
_LONG_CONTEXT = ("documento", "pdf", "riassumi", "confronta", "analisi", "pianifica", "strategia", "ricerca")
_PLANNING = ("pianifica", "piano", "multi-step", "dipendenze", "strategia")
_VISION = ("schermo", "immagine", "screenshot", "grafico", "visivo", "fotografia")
_SUMMARIZATION = ("riassumi", "sintetizza", "documento lungo", "molti file")

_PROVIDER_ORDER = {
    "tool_execution": ("openai", "claude", "kimi"),
    "current_information": ("openai", "claude", "kimi"),
    "vision": ("openai", "claude", "kimi"),
    "coding": ("claude", "openai", "kimi"),
    "planning": ("claude", "kimi", "openai"),
    "summarization": ("kimi", "claude", "openai"),
    "long_context": ("kimi", "claude", "openai"),
    "conversation": ("openai", "claude", "kimi"),
}

_ROUTE_REASONS = {
    "tool_execution": "tool calling e controllo operativo",
    "current_information": "ricerca aggiornata e strumenti web",
    "vision": "percezione visiva e strumenti multimodali",
    "coding": "implementazione, revisione e debugging del codice",
    "planning": "pianificazione strutturata e analisi delle dipendenze",
    "summarization": "contesto esteso e sintesi documentale",
    "long_context": "contesto lungo e analisi strutturata",
    "conversation": "conversazione, voce e latenza interattiva",
}


def available_providers() -> set[str]:
    """Return configured providers only; secrets are never returned or logged."""
    providers = set()
    if os.getenv("OPENAI_API_KEY"):
        providers.add("openai")
    if os.getenv("ANTHROPIC_API_KEY"):
        providers.add("claude")
    if os.getenv("MOONSHOT_API_KEY") or os.getenv("KIMI_API_KEY"):
        providers.add("kimi")
    return providers


def classify_task(text: str) -> str:
    value = str(text or "").lower()
    # Summarization of a long document is a conversational workload even when
    # the Italian wording starts with the operational verb "analizza".
    if any(word in value for word in _SUMMARIZATION):
        return "summarization"
    intent = decide_intent(text)
    if intent.kind.value in {"operation", "composite", "control"}:
        return "tool_execution"
    if intent.kind.value == "capability":
        return "conversation"
    if any(word in value for word in _CURRENT_INFO):
        return "current_information"
    if any(word in value for word in _CODING):
        return "coding"
    if any(word in value for word in _VISION):
        return "vision"
    if any(word in value for word in _PLANNING):
        return "planning"
    if any(word in value for word in _LONG_CONTEXT):
        return "long_context"
    return "conversation"


def _models() -> dict[str, str]:
    claude_model = os.getenv("ANTHROPIC_MODEL") or get_setting("claude_model", "claude-haiku-4-5-20251001")
    return {"openai": str(get_setting("ai_model", "gpt-5.6-luna")), "claude": str(claude_model), "kimi": str(get_setting("kimi_model", "kimi-k3"))}


def decide_route(text: str, *, requires_tools: bool = False) -> RouteDecision:
    """Choose by task category, user preference, availability and safe fallbacks."""
    available = available_providers()
    preferred = str(get_setting("ai_provider", "auto")).strip().lower()
    kind = classify_task(text)
    if requires_tools:
        kind = "tool_execution"
        order, reason = _PROVIDER_ORDER[kind], _ROUTE_REASONS[kind]
    elif preferred in _models() and preferred != "auto":
        order, reason = (preferred, "openai", "claude", "kimi"), "provider scelto dall'utente"
    else:
        order, reason = _PROVIDER_ORDER[kind], _ROUTE_REASONS[kind]
    provider = next((item for item in order if item in available), "openai")
    return RouteDecision(provider, _models()[provider], kind, reason)


def fallback_routes(decision: RouteDecision) -> Iterable[RouteDecision]:
    for provider in _PROVIDER_ORDER.get(decision.task_kind, _PROVIDER_ORDER["conversation"]):
        if provider != decision.provider and provider in available_providers():
            yield RouteDecision(provider, _models()[provider], decision.task_kind, "fallback dopo errore provider")


def route_work_items(items: Iterable[dict]) -> list[tuple[dict, RouteDecision]]:
    """Assign independently described work items without exposing provider secrets."""
    routed = []
    for item in items:
        payload = dict(item)
        text = str(payload.get("description") or payload.get("prompt") or payload.get("task") or "")
        routed.append((payload, decide_route(text, requires_tools=bool(payload.get("requires_tools")))))
    return routed


def complete_non_openai(decision: RouteDecision, instructions: str, messages: list[dict]) -> str:
    return "".join(stream_non_openai(decision, instructions, messages))


def stream_non_openai(decision: RouteDecision, instructions: str, messages: list[dict]):
    """Yield text deltas from configured alternative providers with bounded calls."""
    if decision.provider == "kimi":
        client = kimi_client()
        response = client.chat.completions.create(model=decision.model, messages=[{"role": "system", "content": instructions}, *messages], max_completion_tokens=2048, extra_body={"reasoning_effort": str(get_setting("kimi_reasoning_effort", "low"))},stream=True)
        for chunk in response:
            text = str(chunk.choices[0].delta.content or "") if chunk.choices else ""
            if text: yield text
        return
    if decision.provider == "claude":
        body = json.dumps({"model": decision.model, "max_tokens": 2048, "system": instructions, "messages": messages,"stream":True}).encode("utf-8")
        request = Request("https://api.anthropic.com/v1/messages", data=body, headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=90) as response:
                for raw in response:
                    line=raw.decode("utf-8",errors="replace").strip()
                    if not line.startswith("data:"):continue
                    data=line[5:].strip()
                    if data=="[DONE]":break
                    payload=json.loads(data)
                    if payload.get("type")=="content_block_delta":
                        text=str((payload.get("delta") or {}).get("text") or "")
                        if text:yield text
        except URLError as exc:
            raise RuntimeError(f"Claude non raggiungibile: {exc.reason}") from exc
        return
    raise ValueError(f"Provider non supportato: {decision.provider}")
