import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from jarvis_identity.faceprint import face_descriptor, match_face
from jarvis_identity.service import IdentityService
from jarvis_identity.store import BiometricStore
from jarvis_identity.voiceprint import voice_descriptor
from jarvis_identity.crypto import protect, unprotect


class IdentityTests(unittest.TestCase):
    def test_store_is_atomic_and_deletes_profile(self):
        codec = {"protect": lambda value: b"ENC" + value[::-1],
                 "unprotect": lambda value: value[3:][::-1]}
        with patch("jarvis_identity.store.protect", codec["protect"]), patch("jarvis_identity.store.unprotect", codec["unprotect"]), tempfile.TemporaryDirectory() as folder:
            store = BiometricStore(Path(folder))
            store.put_template("Gabriel", "face", [[1.0, 0.0]])
            self.assertEqual(store.templates("face")["Gabriel"], [[1.0, 0.0]])
            self.assertFalse((Path(folder) / "profiles.tmp").exists())
            self.assertTrue(store.delete("Gabriel"))

    def test_face_descriptor_is_normalized_and_matches(self):
        grid = np.indices((96, 96)).sum(axis=0) % 17
        descriptor = face_descriptor(grid)
        self.assertEqual(descriptor.shape, (256,))
        self.assertAlmostEqual(float(np.linalg.norm(descriptor)), 1.0, places=5)
        result = match_face(descriptor, {"Gabriel": [descriptor.tolist()]})
        self.assertTrue(result["matched"])
        self.assertEqual(result["name"], "Gabriel")

    def test_voice_enrollment_and_recognition_without_raw_audio(self):
        rate = 16000
        time = np.arange(rate * 2, dtype=np.float32) / rate
        sample = (.7 * np.sin(2 * np.pi * 180 * time) + .2 * np.sin(2 * np.pi * 360 * time)).astype(np.float32)
        descriptor = voice_descriptor(sample, rate)
        self.assertEqual(descriptor.shape, (48,))
        codec = {"protect": lambda value: b"ENC" + value[::-1],
                 "unprotect": lambda value: value[3:][::-1]}
        with patch("jarvis_identity.store.protect", codec["protect"]), patch("jarvis_identity.store.unprotect", codec["unprotect"]), tempfile.TemporaryDirectory() as folder:
            service = IdentityService(BiometricStore(Path(folder)))
            service.enroll_voice_samples("Gabriel", [sample, sample * .8], rate)
            result = service.recognize_voice_samples([sample * .9], rate)
            self.assertTrue(result["matched"])
            self.assertEqual(result["name"], "Gabriel")
            payload = (Path(folder) / "profiles.json").read_bytes()
            self.assertNotIn(b"raw_audio", payload)
            self.assertNotIn(b"Gabriel", payload)

    def test_windows_dpapi_roundtrip_when_available(self):
        payload = b"jarvis-biometric-probe"
        try:
            encrypted = protect(payload)
        except OSError:
            self.skipTest("DPAPI non disponibile nel sandbox")
        self.assertNotEqual(encrypted, payload)
        self.assertEqual(unprotect(encrypted), payload)

    def test_complete_profile_persists_metadata_and_both_modalities(self):
        rate = 16000
        time = np.arange(rate, dtype=np.float32) / rate
        audio = np.sin(2 * np.pi * 190 * time).astype(np.float32)
        face = (np.indices((80, 80)).sum(axis=0) % 23).astype(np.uint8)
        codec = {"protect": lambda value: b"ENC" + value[::-1], "unprotect": lambda value: value[3:][::-1]}
        with patch("jarvis_identity.store.protect", codec["protect"]), patch("jarvis_identity.store.unprotect", codec["unprotect"]), tempfile.TemporaryDirectory() as folder:
            service = IdentityService(BiometricStore(Path(folder)))
            result = service.create_profile_samples("Gabriele", [face, face], [audio, audio],
                                                    {"computer": "allow", "admin": "allow"}, rate)
            self.assertTrue(result["successo"])
            profile = service.profile("Gabriele")
            self.assertTrue(profile["has_face"] and profile["has_voice"])
            self.assertEqual(profile["metadata"]["role"], "CEO")
            self.assertEqual(profile["metadata"]["fallback_phrase"], "jarvis sono io")

    def test_invalid_samples_fail_closed(self):
        with self.assertRaises(ValueError):
            voice_descriptor(np.zeros(1000), 16000)
        with self.assertRaises(ValueError):
            face_descriptor(np.zeros((10, 10)))

    def test_voice_descriptor_ignores_leading_silence(self):
        rate = 16000
        time = np.arange(rate, dtype=np.float32) / rate
        speech = np.sin(2 * np.pi * 210 * time).astype(np.float32)
        plain = voice_descriptor(speech, rate)
        padded = voice_descriptor(np.concatenate((np.zeros(rate), speech)), rate)
        self.assertGreater(float(np.dot(plain, padded)), .98)


if __name__ == "__main__":
    unittest.main()
