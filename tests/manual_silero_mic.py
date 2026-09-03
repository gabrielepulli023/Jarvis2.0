"""Bounded manual smoke test: capture one existing microphone stream once."""

import time

import sounddevice as sd

from jarvis_voice.vad import SileroVADProvider


def main():
    frames = []

    def callback(indata, _frames, _time_info, _status):
        frames.append(bytes(indata))

    provider = SileroVADProvider()
    with sd.RawInputStream(samplerate=16_000, blocksize=512, dtype="int16", channels=1, callback=callback):
        time.sleep(3.0)
    scores = [provider.score(frame) for frame in frames]
    scores = [score for score in scores if score is not None]
    print({"frames": len(frames), "scores": len(scores), "max_probability": max(scores) if scores else None,
           "model_available": provider.available, "error": provider.error})


if __name__ == "__main__":
    main()
