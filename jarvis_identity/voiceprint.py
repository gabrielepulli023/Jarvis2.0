import numpy as np


def voice_descriptor(samples, sample_rate=16000):
    signal = np.asarray(samples, dtype=np.float32).reshape(-1)
    if signal.size < int(sample_rate * 0.45):
        raise ValueError("campione vocale troppo breve")
    signal -= float(signal.mean())
    peak = float(np.max(np.abs(signal)))
    if peak < 1e-4:
        raise ValueError("campione vocale silenzioso")
    signal /= peak
    # Scarta finestre quasi silenziose per ridurre la dipendenza da ambiente e pause.
    activity_frame = max(1, int(sample_rate * .020))
    usable = signal[:signal.size - (signal.size % activity_frame)]
    chunks = usable.reshape(-1, activity_frame)
    rms = np.sqrt(np.mean(chunks * chunks, axis=1))
    active = chunks[rms >= max(.025, float(np.percentile(rms, 55)) * .55)]
    if active.shape[0] < 8:
        raise ValueError("voce attiva insufficiente")
    signal = active.reshape(-1)
    frame, hop = int(sample_rate * .025), int(sample_rate * .010)
    frames = np.lib.stride_tricks.sliding_window_view(signal, frame)[::hop]
    windowed = frames * np.hanning(frame).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(windowed, axis=1)) ** 2
    log_energy = np.stack([np.log1p(part.mean(axis=1)) for part in np.array_split(spectrum[:, 1:], 24, axis=1)], axis=1)
    descriptor = np.concatenate((log_energy.mean(axis=0), log_energy.std(axis=0)))
    norm = float(np.linalg.norm(descriptor))
    if norm <= 1e-8:
        raise ValueError("impossibile estrarre l'impronta vocale")
    return (descriptor / norm).astype(np.float32)


def match_voice(descriptor, profiles, threshold=.88):
    probe = np.asarray(descriptor, dtype=np.float32)
    best_name, best_score = None, -1.0
    for name, templates in profiles.items():
        for template in templates:
            candidate = np.asarray(template, dtype=np.float32)
            if candidate.shape == probe.shape:
                score = float(np.dot(probe, candidate) / max(np.linalg.norm(probe) * np.linalg.norm(candidate), 1e-8))
                if score > best_score:
                    best_name, best_score = name, score
    matched = best_score >= threshold
    return {"name": best_name if matched else None, "score": max(0.0, best_score), "matched": matched}
