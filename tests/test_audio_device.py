import unittest
from unittest.mock import MagicMock, patch

import audio_device


class AudioDeviceTests(unittest.TestCase):
    def test_explicit_valid_microphone_is_forwarded_to_raw_stream(self):
        stream = MagicMock()
        stream.__enter__.return_value = stream
        with (
            patch.object(audio_device.sd, "query_devices", return_value={"max_input_channels": 1}),
            patch.object(audio_device.sd, "RawInputStream", return_value=stream) as raw,
        ):
            with audio_device.input_stream(
                samplerate=16000,
                blocksize=2000,
                dtype="int16",
                channels=1,
                callback=lambda *_: None,
                device=7,
            ):
                pass
        self.assertEqual(raw.call_args.kwargs["device"], 7)

    def test_invalid_explicit_microphone_falls_back_to_default(self):
        stream = MagicMock()
        stream.__enter__.return_value = stream
        with (
            patch.object(audio_device.sd, "query_devices", side_effect=ValueError("missing")),
            patch.object(audio_device.sd, "RawInputStream", return_value=stream) as raw,
        ):
            with audio_device.input_stream(
                samplerate=16000,
                blocksize=2000,
                dtype="int16",
                channels=1,
                callback=lambda *_: None,
                device=99,
            ):
                pass
        self.assertIsNone(raw.call_args.kwargs["device"])

    def test_auto_selected_microphone_is_reused_without_probe(self):
        audio_device._auto_selected_input_device = None
        stream = MagicMock()
        stream.__enter__.return_value = stream
        with (
            patch.object(audio_device, "_find_best_input_device", return_value=3) as probe,
            patch.object(audio_device.sd, "query_devices", return_value={"max_input_channels": 1}),
            patch.object(audio_device.sd, "RawInputStream", return_value=stream) as raw,
        ):
            for _ in range(2):
                with audio_device.input_stream(
                    samplerate=16000,
                    blocksize=480,
                    dtype="int16",
                    channels=1,
                    callback=lambda *_: None,
                    device=None,
                ):
                    pass
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(raw.call_args.kwargs["device"], 3)


if __name__ == "__main__":
    unittest.main()
