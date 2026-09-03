from __future__ import annotations
from dataclasses import dataclass
from .store import MemoryStore


@dataclass(frozen=True, slots=True)
class ContextItem:
    content: str
    kind: str
    score: float
    source: str


class ContextBuilder:
    """Selects relevant memory under a deterministic character budget."""

    def __init__(self, store: MemoryStore, max_chars: int = 6000, max_items: int = 20):
        self.store = store
        self.max_chars = max(256, int(max_chars))
        self.max_items = max(1, int(max_items))

    def build(self, query: str) -> list[ContextItem]:
        candidates = self.store.search(query, limit=self.max_items * 2)
        selected = []
        used = 0
        seen = set()
        for row in candidates:
            normalized = " ".join(row["content"].lower().split())
            if normalized in seen:
                continue
            remaining = self.max_chars - used
            if remaining <= 0:
                break
            content = row["content"][:remaining]
            if not content:
                break
            selected.append(ContextItem(content, row["kind"], row["score"], row["source"]))
            seen.add(normalized)
            used += len(content)
            if len(selected) >= self.max_items:
                break
        return selected

    def render(self, query: str) -> str:
        return "\n".join(
            f"- [{x.kind} | fonte={x.source} | score={x.score:.2f}] {x.content}" for x in self.build(query)
        )
