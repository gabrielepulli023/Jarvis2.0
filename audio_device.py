"""Shared, defensive microphone selection for Windows audio hot-plugging."""

from contextlib import contextmanager

import sounddevice as sd

from settings_store import get_setting


_auto_selected_input_device = None
_last_input_device = None


def _configured_input(requested=None):
    value = requested if isinstance(requested, int) else get_setting("mic_device", None)
    if not isinstance(value, int):
        return None
    try:
        info = sd.query_devices(value)
    except Exception:
        return None
    return value if int(info.get("max_input_channels", 0)) > 0 else None


def _find_best_input_device():
    """Auto-detect the best available input device by testing audio levels."""
    try:
        import numpy as np
        import time
        
        devices = sd.query_devices()
        best_device = None
        best_rms = 0
        
        # Test first configured device if available
        configured = _configured_input()
        candidates = [configured] if configured is not None else []
        
        # Add common microphone indices
        for i in [3, 11, 1, 0]:
            if i not in candidates and i < len(devices):
                candidates.append(i)
        
        FREQUENZA = 16000
        FRAME_SAMPLES = int(FREQUENZA * 30 / 1000)
        
        for device in candidates:
            try:
                state = {"rms_values": []}
                
                def callback(indata, frames, time_info, status):
                    audio_np = np.frombuffer(bytes(indata), dtype=np.int16).astype(np.float32)
                    rms = float(np.sqrt(np.mean(audio_np**2)))
                    state["rms_values"].append(rms)
                
                with sd.RawInputStream(
                    samplerate=FREQUENZA,
                    blocksize=FRAME_SAMPLES,
                    dtype="int16",
                    channels=1,
                    callback=callback,
                    device=device,
                ):
                    time.sleep(0.3)
                
                if state["rms_values"]:
                    max_rms = max(state["rms_values"])
                    if max_rms > best_rms:
                        best_device = device
                        best_rms = max_rms
                        if best_rms > 500:
                            break
            
            except Exception:
                pass
        
        return best_device if best_rms > 100 else None
    
    except Exception:
        return None


@contextmanager
def input_stream(*, samplerate, blocksize, dtype, channels, callback, device=None):
    """Open the requested microphone, then degrade to the system default."""
    global _auto_selected_input_device, _last_input_device
    configured = _configured_input(device)
    
    # If configured device is None (default), try to find a better one
    if configured is None and device is None:
        auto_device = _configured_input(_auto_selected_input_device)
        if auto_device is None:
            auto_device = _find_best_input_device()
            _auto_selected_input_device = auto_device
        if auto_device is not None:
            print(f"[AUDIO] Auto-rilevato device {auto_device}")
            configured = auto_device
        else:
            print("[AUDIO] Auto-rilevamento fallito, usando default")
    
    candidates = [configured, None] if configured is not None else [None]
    last_error = None
    for dev in candidates:
        try:
            _last_input_device = dev
            with sd.RawInputStream(
                samplerate=samplerate,
                blocksize=blocksize,
                dtype=dtype,
                channels=channels,
                callback=callback,
                device=dev,
            ) as stream:
                yield stream
                return
        except (sd.PortAudioError, ValueError) as exc:
            last_error = exc
            if dev == _auto_selected_input_device:
                _auto_selected_input_device = None
    if last_error is not None:
        raise last_error


def get_last_input_device():
    """Return the last selected input device without opening another stream."""
    device = _last_input_device
    try:
        info = sd.query_devices(device, "input")
        return {
            "id": device,
            "name": str(info.get("name", "")),
            "default_samplerate": float(info.get("default_samplerate", 0)),
        }
    except Exception:
        return {"id": device, "name": None, "default_samplerate": None}
