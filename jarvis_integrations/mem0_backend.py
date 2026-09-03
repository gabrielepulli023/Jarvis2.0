from __future__ import annotations

from typing import Any

from settings_store import get_setting
from app_paths import data_path

from .models import IntegrationResult
from .safety import contains_secret


class Mem0Backend:
    name = "mem0"

    def __init__(self, *, user_id: str):
        self.user_id = str(user_id)
        self._memory = None

    @staticmethod
    def available() -> bool:
        try:
            import mem0  # noqa: F401
            return True
        except Exception:
            return False

    def _get_memory(self):
        if self._memory is None:
            from mem0 import Memory

            # Mem0's default local Qdrant location is not tied to JARVIS data.
            # Keep both vectors and history under the normal JARVIS data directory
            # so memories survive restarts and packaged builds. `on_disk=True` is
            # explicit because local Qdrant otherwise may not persist collections.
            root = data_path("mem0", migrate=False)
            root.mkdir(parents=True, exist_ok=True)
            qdrant_path = root / "qdrant"
            qdrant_path.mkdir(parents=True, exist_ok=True)
            config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": "jarvis_memories",
                        "path": str(qdrant_path),
                        "on_disk": True,
                        "embedding_model_dims": 1536,
                    },
                },
                "history_db_path": str(root / "history.db"),
            }
            self._memory = Memory.from_config(config)
        return self._memory

    def health(self, *, deep: bool = False) -> IntegrationResult:
        if not self.available():
            return IntegrationResult.fail(self.name, "mem0ai non installato.")
        if not deep:
            return IntegrationResult.ok(self.name, "Mem0 installato")
        try:
            self._get_memory()
            return IntegrationResult.ok(self.name, "Mem0 inizializzato")
        except Exception as exc:
            return IntegrationResult.fail(self.name, f"Mem0 non inizializzabile: {exc}")

    def search(self, query: str, *, limit: int = 6) -> IntegrationResult:
        try:
            memory = self._get_memory()
            result = memory.search(str(query), filters={"user_id": self.user_id})
            if isinstance(result, dict) and isinstance(result.get("results"), list):
                result = {**result, "results": result["results"][: max(1, int(limit))]}
            return IntegrationResult.ok(self.name, "Memorie Mem0 recuperate.", result)
        except Exception as exc:
            return IntegrationResult.fail(self.name, f"Errore ricerca Mem0: {exc}")

    def add_turn(self, user_text: str, assistant_text: str) -> IntegrationResult:
        combined = f"{user_text}\n{assistant_text}"
        if contains_secret(combined):
            return IntegrationResult.fail(self.name, "Turno non memorizzato perché potrebbe contenere un segreto.")
        try:
            memory = self._get_memory()
            result = memory.add(
                [
                    {"role": "user", "content": str(user_text)},
                    {"role": "assistant", "content": str(assistant_text)},
                ],
                user_id=self.user_id,
                metadata={"source": "jarvis_conversation"},
            )
            return IntegrationResult.ok(self.name, "Turno salvato in Mem0.", result)
        except Exception as exc:
            return IntegrationResult.fail(self.name, f"Errore scrittura Mem0: {exc}")

    def add_fact(self, text: str) -> IntegrationResult:
        if contains_secret(text):
            return IntegrationResult.fail(self.name, "Memoria rifiutata perché potrebbe contenere un segreto.")
        try:
            result = self._get_memory().add(
                [{"role": "user", "content": str(text)}],
                user_id=self.user_id,
                metadata={"source": "jarvis_explicit"},
            )
            return IntegrationResult.ok(self.name, "Memoria aggiunta a Mem0.", result)
        except Exception as exc:
            return IntegrationResult.fail(self.name, f"Errore scrittura Mem0: {exc}")


def _extract_memories(data: Any) -> list[str]:
    rows = data.get("results", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    rendered: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            value = row.get("memory") or row.get("text") or row.get("content")
        else:
            value = row
        text = str(value or "").strip()
        if text:
            rendered.append(text)
    return rendered


def conversational_context(query: str, backend: "Mem0Backend | None" = None) -> str:
    if not bool(get_setting("ai_memory", True)) or bool(get_setting("privacy_mode", False)) or not bool(get_setting("mem0_enabled", False)):
        return ""
    try:
        service = backend
        if service is None:
            from .service import get_integration_service
            service = get_integration_service().mem0
        result = service.search(query, limit=6)
        if not result.success:
            return ""
        return "\n".join(f"- {item}" for item in _extract_memories(result.data))
    except Exception:
        return ""


def remember_conversation_turn(user_text: str, assistant_text: str, backend: "Mem0Backend | None" = None) -> None:
    if not bool(get_setting("ai_memory", True)) or bool(get_setting("privacy_mode", False)) or not bool(get_setting("mem0_enabled", False)):
        return
    try:
        service = backend
        if service is None:
            from .service import get_integration_service
            service = get_integration_service().mem0
        service.add_turn(user_text, assistant_text)
    except Exception:
        return
