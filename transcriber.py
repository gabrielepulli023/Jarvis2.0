from dotenv import load_dotenv
import json
import re
from llm_gateway import openai_client
from jarvis_core.logging import redact
from settings_store import get_setting
from transcript_repair import stt_context_prompt

load_dotenv()

client = openai_client(profile="transcription")


class StreamingTranscriber:
    """Shared local Vosk stream with partial hypotheses and interrupt detection."""
    INTERRUPTS = ("jarvis fermati", "jarvis annulla", "lascia stare", "annulla", "fermati", "stop")

    def __init__(self, recognizer=None, on_partial=None, on_interrupt=None,on_error=None):
        if recognizer is None:
            from vosk import KaldiRecognizer
            from wakeword import SAMPLE_RATE, carica_modello
            recognizer = KaldiRecognizer(carica_modello(), SAMPLE_RATE)
        self.recognizer = recognizer; self.on_partial = on_partial; self.on_interrupt = on_interrupt;self.on_error=on_error
        self._partial = ""; self._final = []; self.interrupted = False;self.errors=[]

    @staticmethod
    def _normalized(text): return re.sub(r"\s+", " ", str(text or "").casefold()).strip()

    @staticmethod
    def _join_final_fragments(fragments):
        """Join Vosk final chunks without inventing spaces inside words.

        Vosk can finalize an audio block in the middle of a word. A plain
        ``" ".join`` turns ``pronunc`` + ``iare`` into ``pronunc iare``.
        Only a bounded Italian vocabulary is eligible for fusion; ordinary
        adjacent words remain separated, so this cannot collapse a sentence
        arbitrarily.
        """
        vocabulary = {
            "andare", "aprire", "ascoltare", "avviare", "controllare", "correggere",
            "dire", "disattivare", "eliminare", "eseguire", "impostazioni", "inserire",
            "lanciare", "mettere", "parlare", "pronunciare", "rispondere", "sistemare",
            "spegnere", "verificare", "visualizzare", "continuare", "calcolatrice",
        }
        result = []
        for fragment in fragments:
            tokens = str(fragment or "").split()
            for token in tokens:
                if result and (result[-1] + token) in vocabulary:
                    result[-1] += token
                else:
                    result.append(token)
        return " ".join(result)

    def feed(self, audio: bytes) -> str:
        try:
            complete = bool(self.recognizer.AcceptWaveform(audio))
            payload = json.loads(self.recognizer.Result() if complete else self.recognizer.PartialResult())
            if not isinstance(payload,dict):raise ValueError("Risultato STT non valido")
        except (RuntimeError,ValueError,TypeError,json.JSONDecodeError) as exc:
            self._record_error(exc);return ""
        text = self._normalized(payload.get("text" if complete else "partial", ""))
        if complete and text: self._final.append(text)
        if text and text != self._partial:
            self._partial = text
            if self.on_partial: self.on_partial(text)
            if any(text == phrase or text.endswith(" " + phrase) for phrase in self.INTERRUPTS):
                self.interrupted = True
                if self.on_interrupt: self.on_interrupt(text)
        return text

    def finish(self) -> str:
        try:
            payload = json.loads(self.recognizer.FinalResult())
            if not isinstance(payload,dict):raise ValueError("Risultato STT finale non valido")
        except (RuntimeError,ValueError,TypeError,json.JSONDecodeError) as exc:
            self._record_error(exc);return self._normalized(self._join_final_fragments(self._final) or self._partial)
        text = self._normalized(payload.get("text", ""))
        if text: self._final.append(text)
        return self._normalized(self._join_final_fragments(self._final) or self._partial)

    def _record_error(self,exc):
        row=redact(f"{type(exc).__name__}: {exc}");self.errors.append(row);self.errors=self.errors[-20:]
        if self.on_error:self.on_error(row)


def trascrivi(file_audio):

    with open(file_audio, "rb") as audio:

        kwargs = {
            "model": "gpt-4o-mini-transcribe",
            "file": audio,
            "language": str(get_setting("stt_language", "it") or "it"),
            "prompt": stt_context_prompt(),
        }
        risultato = client.audio.transcriptions.create(**kwargs)

    return risultato.text
