import threading
import time

import numpy as np

from .faceprint import face_descriptor, match_face
from .store import BiometricStore
from .voiceprint import match_voice, voice_descriptor


class IdentityService:
    def __init__(self, store=None, event_sink=None):
        self.store = store or BiometricStore()
        self._camera_lock = threading.Lock()
        self._event_sink = event_sink

    def _emit(self, topic, payload=None):
        if self._event_sink:
            self._event_sink(topic, dict(payload or {}))

    def enroll_voice_samples(self, name, recordings, sample_rate=16000):
        templates = [voice_descriptor(row, sample_rate).tolist() for row in recordings]
        if len(templates) < 2:
            raise ValueError("servono almeno due campioni vocali")
        self.store.put_template(name, "voice", templates)
        return {"successo": True, "messaggio": f"Impronta vocale locale registrata per {name}.", "campioni": len(templates)}

    def recognize_voice_samples(self, recordings, sample_rate=16000, threshold=.88):
        profiles = self.store.templates("voice")
        if not profiles:
            raise RuntimeError("nessun profilo vocale registrato; prima registra la tua voce")
        descriptors = [voice_descriptor(row, sample_rate) for row in recordings]
        probe = np.mean(descriptors, axis=0)
        probe /= max(float(np.linalg.norm(probe)), 1e-8)
        return match_voice(probe, profiles, threshold=threshold)

    @staticmethod
    def record_audio(seconds=2.5, sample_rate=16000, device=None):
        import sounddevice as sd
        recording = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1,
                           dtype="float32", device=device)
        sd.wait()
        return recording.reshape(-1)

    def enroll_voice(self, name, device=None):
        return self.enroll_voice_samples(name, [self.record_audio(device=device) for _ in range(3)])

    def recognize_voice(self, device=None, threshold=.88):
        if not self.store.templates("voice"):
            raise RuntimeError("nessun profilo vocale registrato; prima registra la tua voce")
        return self.recognize_voice_samples([self.record_audio(device=device)], threshold=threshold)

    @staticmethod
    def _opencv():
        try:
            import cv2
            return cv2
        except ImportError as exc:
            raise RuntimeError("componente videocamera non installato") from exc

    def capture_faces(self, count=8, camera=0, timeout=12.0):
        from settings_store import get_setting
        if not bool(get_setting("camera_enabled", True)):
            raise RuntimeError("videocamera disattivata dal controllo privacy HUD")
        cv2 = self._opencv()
        with self._camera_lock:
            detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            stream = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
            if not stream.isOpened():
                raise RuntimeError("videocamera non disponibile")
            faces, deadline, last_capture = [], time.monotonic() + timeout, 0.0
            frame_index, fps_started = 0, time.monotonic()
            self._emit("camera.started", {"camera": int(camera), "purpose": "identity"})
            try:
                while len(faces) < count and time.monotonic() < deadline:
                    ok, frame = stream.read()
                    if not ok:
                        continue
                    frame_index += 1
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    found = detector.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=6, minSize=(90, 90))
                    if frame_index % 4 == 0:
                        height_px, width_px = frame.shape[:2]
                        preview_width = 480
                        preview = cv2.resize(frame, (preview_width, max(1, int(height_px * preview_width / width_px))))
                        encoded_ok, encoded = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                        if encoded_ok:
                            elapsed = max(.001, time.monotonic() - fps_started)
                            boxes = [(float(x)/width_px, float(y)/height_px, float(w)/width_px, float(h)/height_px)
                                     for x, y, w, h in found]
                            self._emit("camera.frame", {"encoded": encoded.tobytes(), "boxes": boxes,
                                                        "fps": frame_index / elapsed, "camera": int(camera)})
                    if len(found) != 1 or time.monotonic() - last_capture < .25:
                        continue
                    x, y, width, height = found[0]
                    faces.append(gray[y:y + height, x:x + width].copy())
                    last_capture = time.monotonic()
            finally:
                stream.release()
                self._emit("camera.stopped", {"camera": int(camera), "purpose": "identity"})
            if len(faces) < max(2, count // 2):
                raise RuntimeError("volto non rilevato con sufficiente stabilità")
            return faces

    def enroll_face_arrays(self, name, faces):
        templates = [face_descriptor(face).tolist() for face in faces]
        if len(templates) < 2:
            raise ValueError("servono almeno due immagini del volto")
        self.store.put_template(name, "face", templates)
        return {"successo": True, "messaggio": f"Profilo facciale locale registrato per {name}.", "campioni": len(templates)}

    def enroll_face(self, name, camera=0):
        return self.enroll_face_arrays(name, self.capture_faces(camera=camera))

    def create_profile_samples(self, name, faces, recordings, permissions, sample_rate=16000,
                               role="CEO", fallback_phrase="jarvis sono io"):
        face_templates = [face_descriptor(face).tolist() for face in faces]
        voice_templates = [voice_descriptor(row, sample_rate).tolist() for row in recordings]
        if len(face_templates) < 2 or len(voice_templates) < 2:
            raise ValueError("servono almeno due campioni validi per volto e voce")
        metadata = {"role": str(role or "USER").upper(), "permissions": dict(permissions or {}),
                    "fallback_phrase": str(fallback_phrase).strip().lower(), "complete": True}
        self.store.put_profile(name, face_templates, voice_templates, metadata)
        return {"successo": True, "messaggio": f"Profilo {metadata['role']} {name} salvato con volto, voce e permessi.",
                "nome": str(name), "ruolo": metadata["role"]}

    def create_profile(self, name, permissions, camera=0, device=None, role="CEO"):
        faces = self.capture_faces(camera=camera)
        recordings = [self.record_audio(device=device) for _ in range(3)]
        return self.create_profile_samples(name, faces, recordings, permissions, role=role)

    def profile(self, name):
        return self.store.profile(name)

    def recognize_face(self, camera=0, threshold=.91):
        profiles = self.store.templates("face")
        if not profiles:
            raise RuntimeError("nessun profilo facciale registrato; prima registra il tuo volto")
        descriptors = [face_descriptor(face) for face in self.capture_faces(count=3, camera=camera, timeout=6.0)]
        probe = np.mean(descriptors, axis=0)
        probe /= max(float(np.linalg.norm(probe)), 1e-8)
        return match_face(probe, profiles, threshold=threshold)

    def delete_profile(self, name):
        return self.store.delete(name)

    def status(self):
        faces, voices = self.store.templates("face"), self.store.templates("voice")
        try:
            import cv2
            camera_runtime = bool(cv2.data.haarcascades)
        except ImportError:
            camera_runtime = False
        try:
            import sounddevice as sd
            audio_inputs = sum(1 for row in sd.query_devices() if row.get("max_input_channels", 0) > 0)
        except Exception:
            audio_inputs = 0
        return {"profiles": sorted(set(faces) | set(voices)), "face_profiles": sorted(faces),
                "voice_profiles": sorted(voices), "local_only": True,
                "camera_runtime": camera_runtime, "audio_inputs": audio_inputs}
