"""Compatibility adapters for the identity/startup event API.

The production startup surface is ``hud_ui.startup_view.StartupView``.  This
module intentionally contains no second renderer; the legacy public symbols
delegate to the canonical surface so older integrations keep working.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from hud_ui.startup_view import StartupView
from jarvis_core.logging import redact


class StartupEventBridge(QObject):
    """Forward runtime events into the Qt thread without owning UI state."""

    received = Signal(str, dict)

    def forward(self, event):
        self.received.emit(str(event.topic), dict(event.payload or {}))


class IdentityPreview(QWidget):
    """Volatile camera data adapter retained for identity integrations.

    The production launcher does not open the camera during startup.  If an
    older identity flow supplies a frame, it remains in RAM only and is never
    written to disk.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame = QPixmap()
        self._boxes = []
        self._fps = None
        self._camera = None
        self._active = False
        self._timer = QTimer(self)
        self._timer.stop()
        self.hide()

    def set_camera_active(self, active, camera=None):
        self._active = bool(active)
        if camera is not None:
            self._camera = camera
        if not self._active:
            self._frame = QPixmap()
            self._boxes = []
            self._fps = None

    def set_frame(self, encoded, boxes=None, fps=None, camera=None):
        pixmap = QPixmap()
        if not encoded or not pixmap.loadFromData(bytes(encoded)):
            return
        self._frame = pixmap
        self._boxes = [tuple(row) for row in (boxes or ()) if isinstance(row, (list, tuple)) and len(row) == 4]
        self._fps = float(fps) if isinstance(fps, (int, float)) else None
        if camera is not None:
            self._camera = camera
        self._active = True

    def closeEvent(self, event):  # noqa: N802 - Qt API
        self._timer.stop()
        self.set_camera_active(False)
        super().closeEvent(event)


class StartupScreen(StartupView):
    """Backward-compatible identity gate backed by the canonical startup view."""

    def __init__(self):
        super().__init__()
        self._stage = "booting"
        self._identity = {"status": "loading", "authenticated": False}
        self._camera_active = False
        self._camera_index = None
        self.preview = IdentityPreview(self)

        # Compatibility labels are hidden by design; StartupView owns the
        # only pixels shown to the user.
        self.logo = self._compat_label("J A R V I S")
        self.system_line = self._compat_label("AI OPERATING SYSTEM")
        self.state = self._compat_label(self.status)
        self.clock = self._compat_label("")
        self.date = self._compat_label("")
        self.camera_title = self._compat_label("VISION INPUT // CAMERA")
        self.privacy = self._compat_label("CAMERA NON ATTIVA // NESSUN FRAME MEMORIZZATO")
        self.identity_state = self._compat_label("PREPARAZIONE SISTEMI")
        self.identity_detail = self._compat_label("Inizializzazione dei servizi locali")
        self.profile_title = self._compat_label("USER IDENTITY // ACCESS PROFILE")
        self.profile_data = self._compat_label("STATO\nINIZIALIZZAZIONE")
        self.permissions_title = self._compat_label("SESSION PERMISSIONS")
        self.permissions_data = self._compat_label("NESSUNA SESSIONE ATTIVA")
        self.command = self._compat_label("IDENTITY CORE // INIZIALIZZAZIONE")
        self.stage_line = self._compat_label("BOOT > PROFILE > SESSION > HUD")
        self.runtime_rail = self._compat_label("PROFILE LOADING // CAMERA STANDBY // FRAME STORAGE OFF")

    def _compat_label(self, text):
        label = QLabel(str(text), self)
        label.hide()
        return label

    def set_status(self, text):
        super().set_status(text)
        self.state.setText(self.status)

    def set_stage(self, stage, title, detail="", accent="#d8d8da", privacy=None):
        self._stage = str(stage)
        self.identity_state.setText(str(title).upper())
        self.identity_detail.setText(str(detail))
        if privacy is not None:
            self.privacy.setText(str(privacy).upper())
        self.command.setText(str(title).upper())
        self.update()

    def identity_state_text(self):
        return self.identity_state.text()

    def show_identity_result(self, result):
        result = dict(result or {})
        self._identity = result
        self._camera_active = False
        self.preview.set_camera_active(False)
        status = str(result.get("status") or "unavailable")
        if result.get("authenticated"):
            name = str(result.get("name") or "UTENTE").upper()
            role = str(result.get("role") or "USER").upper()
            self.set_stage(
                "authenticated",
                "IDENTITA' VERIFICATA",
                f"{name} // PROFILO {role}",
                "#d8d8da",
                "CAMERA RILASCIATA // FRAME ELIMINATO DALLA MEMORIA",
            )
        elif status == "setup_required":
            self.set_stage(
                "setup_required",
                "PROFILO NON CONFIGURATO",
                "Nessun profilo biometrico locale salvato.",
                "#d8d8da",
                "CAMERA NON APERTA // PRIVACY PROTETTA",
            )
        elif status == "rejected":
            self.set_stage(
                "rejected",
                "ACCESSO OSPITE LIMITATO",
                "Fallback vocale disponibile nell'HUD.",
                "#d8d8da",
                "CAMERA RILASCIATA // FALLBACK VOCALE DISPONIBILE",
            )
        elif status == "disabled":
            self.set_stage(
                "disabled",
                "BIOMETRIA DISATTIVATA",
                "Sessione ospite con autorizzazioni limitate.",
                "#d8d8da",
                "CAMERA DISABILITATA DALLE IMPOSTAZIONI PRIVACY",
            )
        else:
            error = redact(str(result.get("error") or "Verifica biometrica non disponibile"))
            self.set_stage(
                "error",
                "VERIFICA NON DISPONIBILE",
                f"{error}. Sessione ospite limitata.",
                "#d8d8da",
                "CAMERA RILASCIATA // NESSUN FRAME MEMORIZZATO",
            )

    def handle_runtime_event(self, topic, payload):
        payload = dict(payload or {})
        if topic == "camera.started":
            camera = payload.get("camera", 0)
            self._camera_active = True
            self._camera_index = camera
            self.preview.set_camera_active(True, camera)
            self.set_stage(
                "scanning",
                "SCANSIONE IDENTITA'",
                "Mantieni il volto visibile e guarda verso la videocamera.",
                "#d8d8da",
                f"CAM {int(camera) + 1:02d} LIVE // FRAME SOLO IN MEMORIA",
            )
        elif topic == "camera.frame":
            self.preview.set_frame(payload.get("encoded"), payload.get("boxes"), payload.get("fps"), payload.get("camera", 0))
        elif topic == "camera.stopped":
            self._camera_active = False
            self.preview.set_camera_active(False, payload.get("camera", 0))
            if self._stage == "scanning":
                self.set_stage(
                    "verifying",
                    "VERIFICA IDENTITA'",
                    "Confronto locale dell'impronta biometrica in corso.",
                    "#d8d8da",
                    "CAMERA RILASCIATA // FRAME ELIMINATO DALLA MEMORIA",
                )


MinimalStartupScreen = StartupScreen
