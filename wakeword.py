import json
import queue
import threading
from collections import deque
from pathlib import Path

from vosk import Model, KaldiRecognizer

from settings_store import get_setting
from audio_device import input_stream
from permission_manager import session_profile

MODEL_PATH = Path(__file__).resolve().parent / "model-it"
SAMPLE_RATE = 16000
BLOCK_SIZE = 2000

model = None
_model_lock = threading.Lock()
# Limita la latenza: in caso di CPU occupata manteniamo solo audio recente.
audio_queue = queue.Queue(maxsize=24)
command_queue = queue.Queue()
_recent_audio = deque(maxlen=24)
_speaker_verifier = None
_speaker_lock = threading.Lock()
_last_wake_text = None


def set_speaker_verifier(verifier):
    """Install a volatile speaker gate; it receives one PCM buffer."""
    global _speaker_verifier
    with _speaker_lock:
        _speaker_verifier = verifier


def _verify_speaker():
    with _speaker_lock:
        verifier = _speaker_verifier
    if verifier is None:
        return True
    chunks = list(_recent_audio)
    if not chunks:
        return False
    try:
        return bool(verifier(b"".join(chunks), SAMPLE_RATE))
    except (RuntimeError, ValueError, OSError):
        return False


def _default_speaker_verifier(payload, sample_rate):
    from settings_store import get_setting

    active_session = session_profile()
    if active_session and active_session.get("method") == "development_auto_ceo":
        return True
    if not bool(get_setting("wake_speaker_lock", False)):
        return True
    import numpy as np
    from jarvis_identity import IdentityService

    samples = np.frombuffer(payload, dtype=np.int16).astype(np.float32) / 32768.0
    result = IdentityService().recognize_voice_samples([samples], sample_rate=sample_rate, threshold=.88)
    return bool(result.get("matched"))


set_speaker_verifier(_default_speaker_verifier)


def carica_modello():
    global model
    if model is None:
        with _model_lock:
            if model is None:
                print("\nCaricamento riconoscimento vocale...")
                if not MODEL_PATH.is_dir():
                    raise FileNotFoundError(f"Modello Vosk non trovato: {MODEL_PATH}")
                model = Model(str(MODEL_PATH))
                print("Riconoscimento vocale pronto.")
    return model


def _mic_device():
    value = get_setting("mic_device", None)
    return value if isinstance(value, int) else None


def callback(indata, frames, time_info, status):
    if status and not (getattr(status, "input_overflow", False) or getattr(status, "output_underflow", False)):
        print("Audio:", status)
    payload = bytes(indata)
    _recent_audio.append(payload)
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


def invia_comando_testo(comando):
    command_queue.put(str(comando).lower().strip())


def pulisci_audio():
    _recent_audio.clear()
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


def recupera_frase_wake():
    """Return and clear the complete local phrase that triggered wake word."""
    global _last_wake_text
    with _speaker_lock:
        value = _last_wake_text
        _last_wake_text = None
    return value


def leggi_comando():
    try:
        return command_queue.get_nowait()
    except queue.Empty:
        return None


def aspetta_avvio():
    pulisci_audio()
    print('\n🟡 In attesa di "Avvia"...')
    print("CTRL + ALT + J = apri JARVIS")
    print("CTRL + ALT + Q = arresto\n")

    grammatica = json.dumps(["avvia", "avvio", "[unk]"])
    riconoscitore = KaldiRecognizer(carica_modello(), SAMPLE_RATE, grammatica)

    with input_stream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        dtype="int16",
        channels=1,
        callback=callback,
        device=_mic_device(),
    ):
        while True:
            comando = leggi_comando()
            if comando == "stop":
                return "stop"
            if comando == "tastiera":
                return "tastiera"

            try:
                dati = audio_queue.get(timeout=0.08)
            except queue.Empty:
                continue

            if riconoscitore.AcceptWaveform(dati):
                testo = json.loads(riconoscitore.Result()).get("text", "").lower().strip()
                if testo:
                    print("Sentito:", testo)
                if "avvia" in testo or "avvio" in testo:
                    print("\n⚡ AVVIO RILEVATO")
                    return "voce"
            # I risultati parziali sono troppo instabili in presenza di TV,
            # musica o parole straniere: il wake word viene accettato solo
            # dopo una frase finalizzata.


def contiene_jarvis(testo):
    testo = (testo or "").lower()
    return any(x in testo for x in ["jarvis", "jarvi", "iarvis", "gervis", "jarves"])


def aspetta_jarvis():
    global _last_wake_text
    pulisci_audio()
    print('\n🟢 Standby. Di\' "Jarvis"...')

    grammatica = json.dumps(["jarvis", "jarvi", "iarvis", "gervis", "jarves", "[unk]"])
    riconoscitore = KaldiRecognizer(carica_modello(), SAMPLE_RATE, grammatica)

    with input_stream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        dtype="int16",
        channels=1,
        callback=callback,
        device=_mic_device(),
    ):
        while True:
            comando = leggi_comando()
            if comando == "stop":
                return "stop"
            if comando == "tastiera":
                return "tastiera"
            if comando == "domanda_testo":
                return "testo"

            try:
                dati = audio_queue.get(timeout=0.08)
            except queue.Empty:
                continue

            if riconoscitore.AcceptWaveform(dati):
                testo = json.loads(riconoscitore.Result()).get("text", "").lower().strip()
                if contiene_jarvis(testo):
                    print("\n🎤 JARVIS")
                    if _verify_speaker():
                        with _speaker_lock:
                            _last_wake_text = testo
                        return "jarvis"
                    print("Voce non autorizzata: comando ignorato.")
            # Evita falsi risvegli da ipotesi parziali del modello Vosk.


def aspetta_attivazione():
    return aspetta_avvio()
