from __future__ import annotations
import re
from pathlib import Path
import pyperclip
from PIL import Image, ImageGrab
from jarvis_core.logging import redact


class ClipboardManager:
    """On-demand clipboard access; it never polls or persists clipboard contents."""

    def __init__(self, allowed_roots=()):
        self.allowed_roots = tuple(Path(item).resolve() for item in allowed_roots)

    def inspect(self, max_chars: int = 100000) -> dict:
        try:
            value = ImageGrab.grabclipboard()
        except OSError:
            value = None
        if isinstance(value, Image.Image):
            return {"kind": "image", "width": value.width, "height": value.height, "mode": value.mode}
        if isinstance(value, list):
            return {"kind": "files", "files": [str(Path(item)) for item in value[:1000]]}
        try:
            text = pyperclip.paste()
        except pyperclip.PyperclipException as exc:
            return {"kind": "unavailable", "error": redact(str(exc))}
        return {
            "kind": "text" if text else "empty",
            "text": str(text)[: max(1, min(int(max_chars), 1000000))],
            "truncated": len(str(text)) > max_chars,
        }

    def write_text(self, text: str) -> dict:
        value = str(text)
        if len(value) > 1000000:
            return {"success": False, "message": "Testo clipboard troppo grande."}
        try:
            pyperclip.copy(value)
        except pyperclip.PyperclipException as exc:
            return {"success": False, "message": redact(str(exc))}
        return {"success": True, "message": "Testo copiato negli appunti.", "data": {"characters": len(value)}}

    def summarize(self, max_sentences: int = 5, max_chars: int = 12000) -> dict:
        """Create a deterministic, non-persistent summary after an explicit request."""
        snapshot = self.inspect(max_chars=max_chars)
        if snapshot.get("kind") != "text":
            return {
                "success": False,
                "message": "Gli appunti non contengono testo riassumibile.",
                "data": {"kind": snapshot.get("kind", "unknown")},
            }
        text = re.sub(r"\s+", " ", str(snapshot.get("text") or "")).strip()
        if not text:
            return {"success": False, "message": "Gli appunti sono vuoti."}
        sentence_limit = max(1, min(int(max_sentences), 12))
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        selected = sentences[:sentence_limit]
        summary = " ".join(selected)
        if len(sentences) > sentence_limit or snapshot.get("truncated"):
            summary = summary.rstrip() + "…"
        return {
            "success": True,
            "message": summary,
            "data": {
                "characters_read": len(text),
                "sentences_returned": len(selected),
                "source_truncated": bool(snapshot.get("truncated")),
                "persistent": False,
            },
        }

    def save_image(self, path: str) -> dict:
        target = Path(path).resolve()
        if not self.allowed_roots or not any(
            target == root or target.is_relative_to(root) for root in self.allowed_roots
        ):
            return {"success": False, "message": "Destinazione clipboard fuori dalle cartelle consentite."}
        try:
            value = ImageGrab.grabclipboard()
        except OSError as exc:
            return {"success": False, "message": redact(str(exc))}
        if not isinstance(value, Image.Image):
            return {"success": False, "message": "La clipboard non contiene un'immagine."}
        target.parent.mkdir(parents=True, exist_ok=True)
        value.save(target)
        return {
            "success": True,
            "message": "Immagine clipboard salvata.",
            "data": {"path": str(target), "width": value.width, "height": value.height},
        }
