import unittest
from unittest.mock import patch

import numpy as np

from jarvis_voice.vad import HybridVAD, SileroVADProvider, create_hybrid_vad


class FakeProvider:
    def __init__(self, values, threshold=0.55):
        self.values = iter(values)
        self.threshold = threshold
        self.available = True

    def score(self, _frame):
        return next(self.values, 0.0)


class VadTests(unittest.TestCase):
    def test_silero_provider_loads_once_and_scores_speech(self):
        def model(_tensor, _rate):
            return np.float32(0.9)

        fake_torch = type("Torch", (), {"set_num_threads": lambda *_: None, "from_numpy": staticmethod(lambda x: x),
                                        "no_grad": staticmethod(lambda: __import__("contextlib").nullcontext())})
        fake_module = type("Silero", (), {"load_silero_vad": staticmethod(lambda: model)})
        provider = SileroVADProvider()
        with patch.dict("sys.modules", {"torch": fake_torch, "silero_vad": fake_module}):
            self.assertGreater(provider.score(b"\x00\x00" * 512), 0.8)
            self.assertGreater(provider.score(b"\x00\x00" * 512), 0.8)
        self.assertIsNotNone(provider._model)

    def test_silence_and_invalid_audio_are_safe(self):
        provider = SileroVADProvider()
        self.assertIsNone(provider.score(b""))
        self.assertIsNone(provider.score(b"\x00"))

    def test_missing_silero_falls_back_without_traceback(self):
        provider = SileroVADProvider()
        with patch.object(provider, "_load", return_value=False):
            hybrid = HybridVAD(provider, log=None)
            self.assertTrue(hybrid.decide(b"frame", True))
            self.assertFalse(hybrid.decide(b"frame", False))

    def test_inference_exception_falls_back(self):
        provider = FakeProvider([0.8])
        provider.score = lambda _frame: (_ for _ in ()).throw(RuntimeError("fault"))
        provider.available = False
        self.assertTrue(HybridVAD(provider, log=None).decide(b"frame", True))

    def test_hybrid_speech_and_short_pause_keep_audio_open(self):
        hybrid = HybridVAD(FakeProvider([0.8, 0.1, 0.1, 0.1, 0.8]), grace_ms=120, frame_ms=30, log=None)
        values = [hybrid.decide(b"frame", value) for value in [True, True, True, True, True]]
        self.assertEqual(values[0], True)
        self.assertEqual(values[-1], True)

    def test_sustained_noise_does_not_open_full_recording(self):
        hybrid = HybridVAD(FakeProvider([0.1] * 20), grace_ms=60, frame_ms=30, log=None)
        values = [hybrid.decide(b"frame", True) for _ in range(20)]
        self.assertLess(sum(values), 6)

    def test_disabled_provider_restores_legacy(self):
        settings = {"silero_enabled": False, "vad_provider": "silero"}
        hybrid = create_hybrid_vad(settings.get, sample_rate=16000, frame_ms=30)
        self.assertIsNone(hybrid.provider)
        self.assertTrue(hybrid.decide(b"frame", True))

    def test_different_sample_rate_is_carried_to_provider(self):
        provider = SileroVADProvider(sample_rate=8000)
        self.assertEqual(provider.sample_rate, 8000)

    def test_silero_probability_can_open_even_when_legacy_misses(self):
        hybrid = HybridVAD(FakeProvider([0.9]), log=None)
        self.assertTrue(hybrid.decide(b"frame", False))

    def test_fallback_message_is_emitted_once(self):
        provider = FakeProvider([None, None])
        provider.available = False
        messages = []
        hybrid = HybridVAD(provider, log=messages.append)
        hybrid.decide(b"frame", True)
        hybrid.decide(b"frame", True)
        self.assertEqual(messages, ["Silero VAD unavailable -> legacy fallback"])

    def test_threshold_and_provider_are_configurable(self):
        hybrid = create_hybrid_vad(
            {"silero_enabled": True, "vad_provider": "silero", "silero_threshold": 0.8,
             "silero_release_threshold": 0.4, "silero_grace_ms": 300}.get,
            sample_rate=16000,
            frame_ms=30,
        )
        self.assertEqual(hybrid.provider.threshold, 0.8)
        self.assertEqual(hybrid.release_threshold, 0.4)

    def test_stt_and_wakeword_modules_are_not_imported_by_vad(self):
        import inspect
        import wakeword
        self.assertNotIn("jarvis_voice.vad", inspect.getsource(wakeword))

    def test_barge_in_legacy_path_remains_independent(self):
        from voice import _barge_wake_word_detected
        self.assertTrue(callable(_barge_wake_word_detected))

    def test_shared_model_is_reused_across_provider_instances(self):
        first = SileroVADProvider()
        second = SileroVADProvider()
        marker = object()
        type(first)._shared_model = marker
        type(first)._shared_torch = object()
        try:
            self.assertTrue(second._load())
            self.assertIs(second._model, marker)
        finally:
            type(first)._shared_model = None
            type(first)._shared_torch = None

    def test_incomplete_chunk_is_buffered(self):
        provider = SileroVADProvider()
        provider._model = lambda tensor, rate: np.float32(0.8)
        provider._torch = type("Torch", (), {"from_numpy": staticmethod(lambda x: x),
                                             "no_grad": staticmethod(lambda: __import__("contextlib").nullcontext())})
        self.assertIsNone(provider.score(b"\x00\x00" * 100))
        self.assertIsNotNone(provider.score(b"\x00\x00" * 412))


if __name__ == "__main__":
    unittest.main()
