import asyncio
import json
import os
import shutil
import queue
import tempfile
import threading
import time
import wave
from pathlib import Path
from jarvis_voice import TTSCache
from jarvis_voice.elevenlabs import ElevenLabsError, ElevenLabsTTSProvider

import edge_tts
import numpy as np
import pygame
import webrtcvad
from dotenv import load_dotenv

from transcriber import StreamingTranscriber, trascrivi
from settings_store import get_setting
from app_paths import data_path
from performance_metrics import record_tool
from audio_device import input_stream
from jarvis_core.logging import redact
from audio_device import get_last_input_device
from jarvis_voice.vad import create_hybrid_vad

load_dotenv()


DEFAULT_VOICE = "it-IT-ElsaNeural"
FREQUENZA = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(FREQUENZA * FRAME_MS / 1000)
FRAME_ATTIVAZIONE = 6
AUDIO_QUEUE_LIMIT = 32
BARGE_START_GRACE = 0.45

if not pygame.mixer.get_init():
    pygame.mixer.init()

_mixer_device = None

_stop_voce = threading.Event()
_nuovo_testo = None
_lock_testo = threading.Lock()
_tts_cache = data_path("tts_cache")
_tts_cache.mkdir(parents=True, exist_ok=True)
_cache_manager = TTSCache(_tts_cache, max_entries=120, min_size=128)
_output_level_callback = None
_elevenlabs = ElevenLabsTTSProvider(_tts_cache)
_stt_diag_dir = Path("diagnostics")
_stt_diag_dir.mkdir(parents=True, exist_ok=True)
for _stt_diag_name in (
    "stt_normal.wav", "stt_post_barge.wav", "normal_raw.wav", "normal_stt.wav",
    "post_barge_raw.wav", "post_barge_stt.wav", "stt_report.json",
):
    try:
        (_stt_diag_dir / _stt_diag_name).unlink()
    except FileNotFoundError:
        pass
_stt_diag_phase = "normal_pending"
_stt_diag_lock = threading.Lock()
_stt_diag_events = {}


def set_output_level_callback(callback):
    global _output_level_callback
    _output_level_callback = callback


def _emit_output_level(value):
    callback = _output_level_callback
    if callback:
        try:
            callback(max(0.0, min(1.0, float(value))))
        except Exception:
            pass


def _decoded_tts_envelope(path, window_ms=25):
    """RMS envelope from the exact decoded audio sent to pygame, never persisted."""
    try:
        sound = pygame.mixer.Sound(path)
        raw = sound.get_raw()
        frequency, sample_format, channels = pygame.mixer.get_init()
        dtype = np.int16 if abs(sample_format) == 16 else np.int8
        values = np.frombuffer(raw, dtype=dtype).astype(np.float32)
        if channels > 1:
            values = values.reshape(-1, channels).mean(axis=1)
        peak = float(np.iinfo(dtype).max)
        size = max(1, int(frequency * window_ms / 1000))
        usable = len(values) // size * size
        if usable <= 0:
            return np.zeros(1, dtype=np.float32), window_ms
        chunks = values[:usable].reshape(-1, size) / peak
        envelope = np.sqrt(np.mean(np.square(chunks), axis=1))
        ceiling = max(float(np.percentile(envelope, 95)), 0.01)
        return np.clip(envelope / ceiling, 0.0, 1.0), window_ms
    except Exception:
        return np.zeros(1, dtype=np.float32), window_ms


def _vad():
    mode = max(0, min(3, int(get_setting("vad_mode", 3))))
    return webrtcvad.Vad(mode)


def _silence_frames():
    if bool(get_setting("silero_enabled", True)) and str(get_setting("vad_provider", "silero")).lower() == "silero":
        silence_ms = int(get_setting("silero_min_silence_ms", get_setting("silence_ms", 540)))
    else:
        silence_ms = int(get_setting("silence_ms", 540))
    silence_ms = max(300, silence_ms)
    if get_setting("performance_mode", True):
        silence_ms = min(silence_ms, 420)
    return max(10, int(round(silence_ms / FRAME_MS)))


def _speech_activation_frames():
    if bool(get_setting("silero_enabled", True)) and str(get_setting("vad_provider", "silero")).lower() == "silero":
        duration_ms = int(get_setting("silero_min_speech_ms", FRAME_ATTIVAZIONE * FRAME_MS))
        return max(1, int(round(max(1, duration_ms) / FRAME_MS)))
    return FRAME_ATTIVAZIONE


def _speech_preroll_frames():
    if bool(get_setting("silero_enabled", True)) and str(get_setting("vad_provider", "silero")).lower() == "silero":
        duration_ms = int(get_setting("silero_preroll_ms", FRAME_ATTIVAZIONE * FRAME_MS))
        return max(1, int(round(max(1, duration_ms) / FRAME_MS)))
    return FRAME_ATTIVAZIONE


def _mic_device():
    value = get_setting("mic_device", None)
    return value if isinstance(value, int) else None


def _mic_sensitivity():
    """Moltiplicatore della sensibilita: 100 mantiene il comportamento storico."""
    value = max(50, min(200, int(get_setting("mic_sensitivity", 100))))
    return value / 100.0


def _transcribe_with_fallback(file_audio, local_text):
    """Prefer remote STT when available, but never discard local Vosk text."""

    fallback = str(local_text or "").strip()
    try:
        remote = str(trascrivi(file_audio) or "").strip()
    except Exception as exc:
        print("[WARN] Trascrizione OpenAI non disponibile; uso Vosk locale:", redact(repr(exc)))
        return fallback, None
    return remote or fallback, remote or None


def _ensure_output_device():
    """Applica l'uscita SDL scelta, lasciando il dispositivo predefinito come fallback."""
    global _mixer_device
    selected = get_setting("output_device", None)
    selected = str(selected).strip() if selected else None
    if pygame.mixer.get_init() and selected == _mixer_device:
        return
    try:
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        pygame.mixer.init(devicename=selected)
        _mixer_device = selected
    except Exception as exc:
        print("\nERRORE USCITA AUDIO:", redact(repr(exc)))
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        _mixer_device = None


def _safe_callback(callback):
    if callback:
        try:
            callback()
        except Exception:
            pass


def richiedi_stop_voce(nuovo_testo=None):
    global _nuovo_testo
    if nuovo_testo:
        with _lock_testo:
            _nuovo_testo = nuovo_testo
    _stop_voce.set()
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass


def recupera_nuovo_testo():
    global _nuovo_testo
    with _lock_testo:
        testo = _nuovo_testo
        _nuovo_testo = None
    return testo


async def _genera_audio_async(testo, file_output):
    voice = str(get_setting("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE)
    rate = int(get_setting("voice_rate", 0))
    volume = int(get_setting("voice_volume", 0))
    pitch = max(-20, min(20, int(get_setting("voice_pitch", -2))))
    comunicatore = edge_tts.Communicate(
        text=testo,
        voice=voice,
        rate=f"{rate:+d}%",
        volume=f"{volume:+d}%",
        pitch=f"{pitch:+d}Hz",
    )
    await comunicatore.save(file_output)


def genera_audio(testo, file_output, mood="normal", cancel=None, on_audio=None):
    """Generate ElevenLabs audio, falling back to the existing local edge player."""
    if _elevenlabs.configured:

        def first_audio(latency):
            record_tool("tts_first_audio", True, latency)

        try:
            _elevenlabs.synthesize(
                testo,
                Path(file_output),
                mood=mood,
                first_audio=first_audio,
                cancel=cancel,
                on_audio=on_audio,
            )
            return "elevenlabs"
        except ElevenLabsError as exc:
            print(f"\n[VOICE] {redact(str(exc))}; uso il fallback locale.")
        except asyncio.CancelledError:
            raise
    voice = str(get_setting("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE)
    signature = (
        f"{voice}|{get_setting('voice_rate', -4)}|{get_setting('voice_volume', 0)}|"
        f"{get_setting('voice_pitch', -2)}|{testo}"
    )
    private = bool(get_setting("privacy_mode", False))
    if not private and _cache_manager.restore(signature, Path(file_output)):
        return
    asyncio.run(_genera_audio_async(testo, file_output))
    if private:
        return
    try:
        _cache_manager.store(signature, Path(file_output))
    except OSError:
        pass
    return "fallback"


def calcola_rms(dati):
    audio = np.frombuffer(dati, dtype=np.int16).astype(np.float32)
    if len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio**2)))


def salva_wav(nome_file, frames):
    with wave.open(nome_file, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(FREQUENZA)
        wf.writeframes(b"".join(frames))


def _barge_wake_word_detected(recognizer, frame):
    """Accetta solo un risultato Vosk finalizzato che contiene la wake word."""
    try:
        if not recognizer.AcceptWaveform(frame):
            return False
        result = json.loads(recognizer.Result())
        from wakeword import contiene_jarvis

        return contiene_jarvis(result.get("text", ""))
    except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _diag_audio(label, started):
    print(f"[DIAG_AUDIO] {label} t=+{time.perf_counter() - started:.3f}s")


def _claim_stt_diagnostic():
    global _stt_diag_phase
    with _stt_diag_lock:
        if _stt_diag_phase == "normal_pending":
            _stt_diag_phase = "normal_done"
            return "normal"
        if _stt_diag_phase == "post_pending":
            _stt_diag_phase = "post_done"
            return "post_barge"
    return None


def _mark_post_barge_diagnostic():
    global _stt_diag_phase
    with _stt_diag_lock:
        if (_stt_diag_dir / "stt_normal.wav").exists():
            _stt_diag_phase = "post_pending"


def _mark_diag_event(name):
    with _stt_diag_lock:
        _stt_diag_events[name] = time.perf_counter()


def _write_stt_diagnostic(label, frames, raw_frames, raw_times, stream_open, stream_closed,
                          first_frame, voice_time, first_above, local_text, openai_text,
                          frame_count):
    global _stt_diag_phase
    try:
        if not label or not frames:
            return
        _stt_diag_dir.mkdir(parents=True, exist_ok=True)
        raw_values = np.frombuffer(b"".join(raw_frames), dtype=np.int16).astype(np.float32)
        values = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32)
        rms_values = []
        for frame in frames:
            rms_values.append(calcola_rms(frame))
        rms = np.asarray(rms_values, dtype=np.float32)
        threshold = max(250.0, 550.0 / _mic_sensitivity())
        first_non_silent = next((i for i, value in enumerate(rms) if value > threshold), None)
        target = _stt_diag_dir / ("normal_stt.wav" if label == "normal" else "post_barge_stt.wav")
        raw_target = _stt_diag_dir / ("normal_raw.wav" if label == "normal" else "post_barge_raw.wav")
        salva_wav(str(raw_target), raw_frames)
        salva_wav(str(target), frames)
        device = get_last_input_device()
        report_path = _stt_diag_dir / "stt_report.json"
        report = {}
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                report = {}
        with _stt_diag_lock:
            events = dict(_stt_diag_events)
        frame_rms_first_2s = []
        for index, frame in enumerate(raw_frames[: int(FREQUENZA * 2 / (FREQUENZA * FRAME_MS / 1000))]):
            frame_rms_first_2s.append({"frame": index + 1, "rms": round(calcola_rms(frame), 2)})
        expected_gap = FRAME_MS / 1000
        gaps = []
        for previous, current in zip(raw_times, raw_times[1:], strict=False):
            delta = current - previous
            if delta > expected_gap * 1.5:
                gaps.append(round(delta, 4))
        row = {
        "device": device,
        "sample_rate": FREQUENZA,
        "channels": 1,
        "frame_count_callback": frame_count,
        "frame_count_raw": len(raw_frames),
        "frame_count_wav": len(frames),
        "discarded_before_vad_frames": max(0, len(raw_frames) - len(frames)),
        "discarded_before_vad_s": round(max(0, len(raw_frames) - len(frames)) * FRAME_MS / 1000, 4),
        "raw_bytes_audio": int(len(raw_values) * 2),
        "raw_duration_s": round(len(raw_values) / FREQUENZA, 4),
        "bytes_audio": int(len(values) * 2),
        "duration_s": round(len(values) / FREQUENZA, 4),
        "rms_min": round(float(rms.min()), 2),
        "rms_mean": round(float(rms.mean()), 2),
        "rms_max": round(float(rms.max()), 2),
        "clipping_samples": int(np.count_nonzero(np.abs(values) >= 32767)),
        "initial_silence_s": round((first_non_silent or 0) * FRAME_MS / 1000, 4),
        "first_above_threshold": first_above,
        "stream_open_monotonic": stream_open,
        "first_frame_monotonic": first_frame,
        "voice_detected_monotonic": voice_time,
        "stream_closed_monotonic": stream_closed,
        "mixer_stop_monotonic": events.get("mixer_stop"),
        "mixer_unload_monotonic": events.get("mixer_unload"),
        "barge_stream_closed_monotonic": events.get("barge_stream_closed"),
        "rms_first_2s": frame_rms_first_2s,
        "audio_callback_gaps_s": gaps,
        "vosk_text": local_text,
        "openai_text": openai_text,
        }
        report[label] = row
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if label == "post_barge":
            normal = report.get("normal", {})
            def normalize(value):
                return " ".join(str(value or "").casefold().split())
            failed = (
                normalize(normal.get("vosk_text")) != normalize(local_text)
                or normalize(normal.get("openai_text")) != normalize(openai_text)
            )
            with _stt_diag_lock:
                _stt_diag_phase = "normal_pending"
            if failed:
                failure_dir = _stt_diag_dir / f"failure_{time.strftime('%Y%m%d-%H%M%S')}"
                failure_dir.mkdir(parents=True, exist_ok=True)
                for item in ("normal_raw.wav", "normal_stt.wav", "post_barge_raw.wav", "post_barge_stt.wav", "stt_report.json"):
                    source = _stt_diag_dir / item
                    if source.exists():
                        shutil.copy2(source, failure_dir / item)
                    else:
                        print(f"[DIAG_STT] file diagnostico assente, copia saltata: {source}")
    except Exception as exc:
        print(f"[DIAG_STT] diagnostica fallita: {type(exc).__name__}: {exc}")


def ascolta_barge_in(stop_listener, barge_started, risultato):
    from vosk import KaldiRecognizer
    from wakeword import carica_modello

    grammatica = json.dumps(["jarvis", "jarvi", "iarvis", "gervis", "jarves", "[unk]"])
    riconoscitore_wake = KaldiRecognizer(carica_modello(), FREQUENZA, grammatica)
    audio_queue = queue.Queue(maxsize=AUDIO_QUEUE_LIMIT)
    
    # [DIAG] Inizio barge-in
    barge_in_start = time.perf_counter()
    print(f"\n[DIAG_BARGE] Inizio thread barge-in at {barge_in_start:.2f}")

    def callback(indata, frames, time_info, status):
        payload = bytes(indata)
        try:
            audio_queue.put_nowait(payload)
        except queue.Full:
            try:
                audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                audio_queue.put_nowait(payload)
            except queue.Full:
                pass

    pre_buffer = []
    iniziato = False
    inizio = time.time()
    inizio_barge = None

    try:
        with input_stream(
            samplerate=FREQUENZA,
            blocksize=FRAME_SAMPLES,
            dtype="int16",
            channels=1,
            callback=callback,
            device=_mic_device(),
        ):
            _diag_audio("stream barge-in aperto", barge_in_start)
            while True:
                if stop_listener.is_set() and not iniziato:
                    break
                if iniziato and inizio_barge and (time.time() - inizio_barge) > 15:
                    break
                try:
                    frame = audio_queue.get(timeout=0.05)
                except queue.Empty:
                    continue

                tempo = time.time() - inizio
                if tempo < BARGE_START_GRACE:
                    continue

                if not iniziato:
                    pre_buffer.append(frame)
                    if len(pre_buffer) > 10:
                        pre_buffer.pop(0)
                if not iniziato:
                    if _barge_wake_word_detected(riconoscitore_wake, frame):
                        iniziato = True
                        inizio_barge = time.time()
                        barge_started.set()
                        rilevamento_time = time.perf_counter() - barge_in_start
                        print(f"\n🎙 Wake word 'Jarvis' rilevata (t=+{rilevamento_time:.2f}s)")
                        _diag_audio("wake word barge-in rilevata", barge_in_start)
                        try:
                            pygame.mixer.music.stop()
                            _mark_diag_event("mixer_stop")
                            _diag_audio("mixer stop", barge_in_start)
                        except Exception:
                            pass
                        # La richiesta va acquisita dal normale ascolta(), con
                        # stream, VAD e transcriber nuovi.
                        risultato["testo"] = "jarvis"
                        _mark_post_barge_diagnostic()
                        break
        _mark_diag_event("barge_stream_closed")
        _diag_audio("stream barge-in chiuso", barge_in_start)
    except Exception as exc:
        print("\n❌ ERRORE BARGE-IN:", redact(repr(exc)))


def parla(testo, interrompibile=True, mood="normal"):
    if not testo:
        return None

    tts_started = time.perf_counter()
    _stop_voce.clear()
    recupera_nuovo_testo()
    _ensure_output_device()

    temp = tempfile.NamedTemporaryFile(prefix="jarvis_", suffix=".mp3", delete=False)
    file_audio = temp.name
    temp.close()

    stop_listener = threading.Event()
    barge_started = threading.Event()
    risultato_barge = {"testo": None}
    thread_barge = None

    # [DIAG_PARLA] Inizio parla()
    print(f"\n[DIAG_PARLA] INIZIO parla() at {tts_started:.2f}: {repr(testo[:50])}")

    try:
        # Il listener parte prima della richiesta edge-tts: in questo modo
        # l'utente puo interrompere anche mentre l'MP3 e ancora in generazione.
        try:
            genera_audio(
                testo,
                file_audio,
                mood=mood,
                cancel=_stop_voce,
                on_audio=None,
            )
            gen_time = time.perf_counter()
            print(f"[DIAG_PARLA] Audio generato in {(gen_time - tts_started):.2f}s")
        except asyncio.CancelledError:
            stop_listener.set()
            return None

        testo_nuovo = recupera_nuovo_testo()
        if testo_nuovo:
            stop_listener.set()
            return "__TESTO__:" + testo_nuovo

        if barge_started.is_set():
            thread_barge.join(timeout=12.0)
            stop_listener.set()
            return risultato_barge.get("testo")

        if _stop_voce.is_set():
            stop_listener.set()
            return None

        pygame.mixer.music.load(file_audio)
        output_envelope, envelope_ms = _decoded_tts_envelope(file_audio)
        play_start = time.perf_counter()
        pygame.mixer.music.play()
        print(f"[DEBUG TTS] Playback iniziato at {play_start:.2f} (generazione+setup: {(play_start - tts_started):.2f}s)")
        # Il microfono per il barge-in si apre solo quando l'audio è realmente
        # in riproduzione: evita catture durante la generazione TTS e riduce
        # falsi interrupt dovuti a rumori nella fase di preparazione.
        if interrompibile:
            thread_barge = threading.Thread(
                target=ascolta_barge_in,
                args=(stop_listener, barge_started, risultato_barge),
                daemon=True,
            )
            thread_barge.start()
            print("[DEBUG TTS] Barge-in thread avviato")
        record_tool("tts_first_audio", True, int((time.perf_counter() - tts_started) * 1000))
        
        stall_time = None
        last_pos = -1
        
        while pygame.mixer.music.get_busy():
            try:
                position = max(0, pygame.mixer.music.get_pos())
                envelope_index = min(len(output_envelope) - 1, position // envelope_ms)
                _emit_output_level(float(output_envelope[envelope_index]))
                
                # Rilevare stalli (posizione non cambia per >0.5s)
                now = time.perf_counter()
                if position == last_pos:
                    if stall_time is None:
                        stall_time = now
                    elif (now - stall_time) > 0.5:
                        print(f"[DEBUG TTS] STALLO RILEVATO: pos={position}, stall_duration={(now - stall_time):.2f}s")
                else:
                    stall_time = None
                    last_pos = position
                
                testo_nuovo = recupera_nuovo_testo()
                if testo_nuovo:
                    pygame.mixer.music.stop()
                    stop_listener.set()
                    return "__TESTO__:" + testo_nuovo

                if _stop_voce.is_set():
                    pygame.mixer.music.stop()
                    stop_listener.set()
                    break
                time.sleep(0.01)
            except Exception as e:
                print(f"[DEBUG TTS] Errore loop playback: {e}")
                break
        
        play_duration = time.perf_counter() - play_start
        print(f"[DEBUG TTS] Playback terminato in {play_duration:.2f}s")

        if thread_barge and barge_started.is_set():
            print("\n⏳ Acquisisco la nuova richiesta...")
            thread_barge.join(timeout=12.0)
            stop_listener.set()
        else:
            stop_listener.set()
            if thread_barge:
                thread_barge.join(timeout=0.8)

        testo_barge = risultato_barge.get("testo")
        if testo_barge:
            return testo_barge

        testo_nuovo = recupera_nuovo_testo()
        if testo_nuovo:
            return "__TESTO__:" + testo_nuovo
        return None

    except Exception as exc:
        print("\n❌ ERRORE VOCE:", redact(repr(exc)))
        return None
    finally:
        _emit_output_level(0.0)
        stop_listener.set()
        try:
            pygame.mixer.music.stop()
            _diag_audio("mixer stop/finally", tts_started)
            pygame.mixer.music.unload()
            _mark_diag_event("mixer_unload")
            _diag_audio("mixer unload", tts_started)
        except Exception:
            pass
        time.sleep(0.03)
        try:
            if os.path.exists(file_audio):
                os.remove(file_audio)
        except Exception:
            pass


def voice_status():
    """Return non-secret provider status for HUD/diagnostics."""
    return {
        "provider": "ElevenLabs" if _elevenlabs.configured else "local-fallback",
        "status": _elevenlabs.status,
        **_elevenlabs.metrics.snapshot(),
    }


def ascolta(
    timeout_inizio=6.0, stop_event=None, on_voice_start=None, on_voice_end=None, on_partial=None, on_interrupt=None,
    *, allow_cloud=True,
):
    stt_started = time.perf_counter()
    diag_label = _claim_stt_diagnostic()
    stream_open = None
    first_frame = None
    voice_time = None
    first_above = None
    openai_text = None
    stream_closed = None
    raw_frames = []
    raw_times = []
    print("\n🎤 Ti ascolto...")
    device = _mic_device()
    print(f"[DEBUG STT] Dispositivo: {device}")
    vad = _vad()
    hybrid_vad = create_hybrid_vad(get_setting, sample_rate=FREQUENZA, frame_ms=FRAME_MS)
    audio_queue = queue.Queue(maxsize=AUDIO_QUEUE_LIMIT)
    audio_frame_count = 0

    def callback(indata, frames, time_info, status):
        nonlocal audio_frame_count
        if status and not (getattr(status, "input_overflow", False) or getattr(status, "output_underflow", False)):
            print("Microfono:", status)
        payload = bytes(indata)
        raw_frames.append(payload)
        raw_times.append(time.perf_counter())
        audio_frame_count += 1
        try:
            audio_queue.put_nowait(payload)
        except queue.Full:
            try:
                audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                audio_queue.put_nowait(payload)
            except queue.Full:
                pass

    frames_audio = []
    pre_buffer = []
    voce_consecutiva = 0
    silenzio_consecutivo = 0
    iniziato = False
    rumori = []
    inizio = time.time()
    inizio_voce = None
    max_frase = 30.0
    streaming = None
    if get_setting("local_streaming_stt", True):
        try:
            streaming = StreamingTranscriber(on_partial=on_partial, on_interrupt=on_interrupt)
            print("[DEBUG STT] Vosk StreamingTranscriber creato")
        except Exception as exc:
            print("\nSTT locale degradato:", redact(repr(exc)))
            print("[DEBUG STT] Fallback a OpenAI abilitato")

    try:
        with input_stream(
            samplerate=FREQUENZA,
            blocksize=FRAME_SAMPLES,
            dtype="int16",
            channels=1,
            callback=callback,
            device=_mic_device(),
        ):
            stream_open = time.perf_counter()
            _diag_audio("nuovo stream STT aperto", stt_started)
            while True:
                if stop_event is not None and stop_event.is_set():
                    print("\n⌨️ Ascolto interrotto")
                    return None

                if not iniziato and timeout_inizio is not None and (time.time() - inizio) > timeout_inizio:
                    return None

                if iniziato and inizio_voce and (time.time() - inizio_voce) > max_frase:
                    print("\n🔴 Limite durata frase")
                    break

                try:
                    frame = audio_queue.get(timeout=0.08)
                except queue.Empty:
                    continue

                if audio_frame_count == 1:
                    first_frame = time.perf_counter()
                    _diag_audio("primo frame STT ricevuto", stt_started)

                try:
                    voce = vad.is_speech(frame, FREQUENZA)
                except Exception:
                    voce = False

                # Il solo VAD tende a classificare musica, TV e rumori impulsivi
                # come voce.  Usa la stessa soglia adattiva del barge-in.
                rms = calcola_rms(frame)
                # Calibrate only on frames that VAD classifies as silence.
                # Including the user's first words (or the tail of TTS) in
                # the noise average can raise the threshold above speech.
                if time.time() - inizio < 0.75 and not voce:
                    rumori.append(rms)
                rumore = sum(rumori) / len(rumori) if rumori else 300
                soglia = max(250, max(550, rumore * 2.2) / _mic_sensitivity())
                if first_above is None and rms > soglia:
                    first_above = {
                        "frame": audio_frame_count,
                        "elapsed_s": round(time.perf_counter() - stt_started, 4),
                        "rms": round(rms, 2),
                        "threshold": round(soglia, 2),
                    }
                if get_setting("noise_reduction", True):
                    voce = voce and rms > soglia
                voce = hybrid_vad.decide(frame, voce)

                if not iniziato:
                    pre_buffer.append(frame)
                    if len(pre_buffer) > _speech_preroll_frames():
                        pre_buffer.pop(0)
                    voce_consecutiva = voce_consecutiva + 1 if voce else 0
                    if voce_consecutiva >= _speech_activation_frames():
                        iniziato = True
                        inizio_voce = time.time()
                        voice_time = time.perf_counter()
                        _safe_callback(on_voice_start)
                        print("\n🟢 Voce rilevata")
                        _diag_audio("voce rilevata da VAD", stt_started)
                        print(f"[DIAG_STT] frame={audio_frame_count} rms={rms:.0f} soglia={soglia:.0f}")
                        frames_audio.extend(pre_buffer)
                        if streaming:
                            for buffered in pre_buffer:
                                streaming.feed(buffered)
                        pre_buffer = []
                else:
                    frames_audio.append(frame)
                    if streaming:
                        streaming.feed(frame)
                        if streaming.interrupted:
                            return None
                    silenzio_consecutivo = 0 if voce else silenzio_consecutivo + 1
                    if silenzio_consecutivo >= _silence_frames():
                        print("\n🔴 Fine richiesta")
                        print(f"[DIAG_STT] fine registrazione frame={audio_frame_count} audio_frame={len(frames_audio)}")
                        _safe_callback(on_voice_end)
                        break

        stream_closed = time.perf_counter()
        if not frames_audio:
            print("[DEBUG STT] NESSUN AUDIO RILEVATO")
            return None

        local_text = streaming.finish() if streaming else ""
        print(f"[DEBUG STT] Risultato Vosk: {repr(local_text)}")
        _diag_audio("testo Vosk pronto", stt_started)
        
        if local_text and get_setting("prefer_local_stt", True):
            print("\nTU:", local_text)
            _write_stt_diagnostic(diag_label, frames_audio, raw_frames, raw_times, stream_open, stream_closed, first_frame, voice_time,
                                  first_above, local_text, None, audio_frame_count)
            return local_text

        if not allow_cloud:
            # Ambient standby is local-only by policy; no audio file is created.
            testo = str(local_text or "").strip()
            if not testo:
                return None
            print("\nTU (locale):", testo)
            return testo

        temp = tempfile.NamedTemporaryFile(prefix="jarvis_input_", suffix=".wav", delete=False)
        file_audio = temp.name
        temp.close()
        salva_wav(file_audio, frames_audio)
        
        audio_size = Path(file_audio).stat().st_size
        print(f"[DEBUG STT] File audio salvato: {audio_size} bytes")

        print("\n🧠 Trascrizione OpenAI...")
        try:
            testo, openai_text = _transcribe_with_fallback(file_audio, local_text)
            print(f"[DEBUG STT] Risultato OpenAI: {repr(openai_text)}")
            if openai_text is None and testo:
                print(f"[DEBUG STT] Vosk fallback: {repr(testo)}")
            _diag_audio("testo OpenAI pronto", stt_started)
        finally:
            try:
                os.remove(file_audio)
            except OSError:
                pass
        
        if not testo:
            _write_stt_diagnostic(diag_label, frames_audio, raw_frames, raw_times, stream_open, stream_closed, first_frame, voice_time,
                                  first_above, local_text, openai_text, audio_frame_count)
            return None
        testo = testo.strip()
        if not testo:
            _write_stt_diagnostic(diag_label, frames_audio, raw_frames, raw_times, stream_open, stream_closed, first_frame, voice_time,
                                  first_above, local_text, openai_text, audio_frame_count)
            return None
        print("\nTU:", testo)
        _write_stt_diagnostic(diag_label, frames_audio, raw_frames, raw_times, stream_open, stream_closed, first_frame, voice_time,
                              first_above, local_text, openai_text, audio_frame_count)
        return testo

    except Exception as exc:
        _safe_callback(on_voice_end)
        print("\n❌ ERRORE MICROFONO:", redact(repr(exc)))
        return None
