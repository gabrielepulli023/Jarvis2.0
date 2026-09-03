from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    verified: bool
    confidence: float
    observation: str
    expected: str

    def as_dict(self) -> dict:
        return asdict(self)


class EvidenceEngine:
    """Builds independent, explicit proof from an action result."""

    def __init__(self):
        self._verifiers: dict[str, Callable[[dict, dict], Evidence]] = {}

    def register(self, action: str, verifier: Callable[[dict, dict], Evidence]) -> None:
        self._verifiers[action] = verifier

    def verify(self, action: str, expected: dict, result: dict) -> Evidence:
        if action in self._verifiers:
            return self._verifiers[action](expected, result)
        if not result.get("successo", result.get("success", False)):
            return Evidence(
                "action_result", False, 1.0, str(result.get("messaggio", result.get("error", "failed"))), str(expected)
            )
        path = result.get("percorso") or result.get("path")
        if path:
            exists = Path(str(path)).exists()
            return Evidence("filesystem", exists, 1.0, f"exists={exists}: {path}", str(expected))
        observed = result.get("observed")
        if observed is not None:
            matches = (
                all(observed.get(k) == v for k, v in expected.items())
                if isinstance(observed, dict)
                else observed == expected
            )
            return Evidence("state_observation", matches, 0.95, str(observed), str(expected))
        return Evidence("action_result", True, 0.65, str(result.get("messaggio", "success flag")), str(expected))


class ConfidenceEngine:
    def __init__(self, threshold: float = 0.7):
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between zero and one")
        self.threshold = threshold

    def score(self, evidence: list[Evidence]) -> float:
        if not evidence:
            return 0.0
        weights = [1.0 if item.verified else -1.0 for item in evidence]
        value = sum(item.confidence * weight for item, weight in zip(evidence, weights, strict=True)) / len(evidence)
        return max(0.0, min(1.0, value))

    def sufficient(self, evidence: list[Evidence]) -> bool:
        return all(x.verified for x in evidence) and self.score(evidence) >= self.threshold
