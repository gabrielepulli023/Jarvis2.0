"""Compatibility facade for the canonical core cognitive module."""

from jarvis_core.cognitive_core import (
    CognitiveDecision,
    Decision,
    IntentKind,
    Strategy,
    UnifiedCognitiveCore,
    mission_required,
    plan_mission,
    review_mission,
)

__all__ = [
    "CognitiveDecision", "Decision", "IntentKind", "Strategy",
    "UnifiedCognitiveCore", "mission_required", "plan_mission", "review_mission",
]
