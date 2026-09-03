import json
import queue
import re
from decision_layer import decide, resolve_control_intent
import sys
import threading
import time

import keyboard
from PySide6.QtCore import (
    QObject,
    QThread,
    Signal,
    Qt,
)
from PySide6.QtWidgets import QApplication

from settings_store import get_setting, set_setting
from jarvis_core.logging import redact
from personal_memory import (
    export_json as export_memory,
    learn_explicit,
    remember,
    search as search_memory,
    forget as forget_memory,
)
from automation_engine import add_after, add_daily, add_once, delete_routine, list_routines, set_enabled
from goal_manager import add_step, close_goal, complete_step, create_goal, list_goals
from skill_engine import create_skill, delete_skill, get_skill, list_skills
from permission_manager import profile as permission_profile, set_mode, activate_session, clear_session
from agent_state import recover_interrupted
from context_engine import update as update_context
from chrome_bridge import ensure_server as start_chrome_bridge
from async_engine import ENGINE as ASYNC_ENGINE
from jarvis_core.runtime import RUNTIME as CORE_RUNTIME
from jarvis_core.operational_followup import execute as execute_operational_followup, is_operational_followup
from jarvis_core.crash_report import install_crash_reporting
from jarvis_core.response_renderer import RESPONSE_RENDERER, TechnicalResult, message_indicates_failure
from jarvis_core.reference_resolution import consume_pending_proposal, record_assistant_turn, record_user_turn, resolve_reference
from jarvis_identity import IdentityService
from jarvis_voice.attention import AttentionController, AttentionState
from jarvis_expansion.routing import match_expansion_skill

domande_testo = queue.Queue(maxsize=128)
DEVELOPMENT_AUTO_CEO = True
_STARTUP_GREETING_LOCK = threading.Lock()
_STARTUP_GREETING_CLAIMED = False


def _reset_startup_greeting_gate():
    global _STARTUP_GREETING_CLAIMED
    with _STARTUP_GREETING_LOCK:
        _STARTUP_GREETING_CLAIMED = False


def _claim_startup_greeting():
    global _STARTUP_GREETING_CLAIMED
    with _STARTUP_GREETING_LOCK:
        if _STARTUP_GREETING_CLAIMED:
            return False
        _STARTUP_GREETING_CLAIMED = True
        return True


def _accoda_domanda(testo):
    """Accoda il comando più recente senza permettere accumuli illimitati."""
    valore = None if testo is None else str(testo).strip()
    if valore == "":
        return
    try:
        domande_testo.put_nowait(valore)
    except queue.Full:
        try:
            domande_testo.get_nowait()
        except queue.Empty:
            pass
        try:
            domande_testo.put_nowait(valore)
        except queue.Full:
            pass


def _identity_event(topic, payload):
    if topic in {"camera.started", "camera.stopped"}:
        camera_enabled = bool(get_setting("camera_enabled", True))
        camera_state = {
            **dict(payload or {}),
            "active": topic == "camera.started",
            # Webcam inattiva e webcam bloccata dalla privacy sono stati diversi.
            "enabled": camera_enabled,
            "privacy": not camera_enabled,
        }
        CORE_RUNTIME.state.set("camera", camera_state, source="identity")
    CORE_RUNTIME.events.publish(topic, payload, source="identity")


IDENTITY = IdentityService(event_sink=_identity_event)
FULL_PROFILE_PERMISSIONS = {
    "computer": "allow",
    "files_read": "allow",
    "files_write": "allow",
    "scripts": "allow",
    "admin": "allow",
    "install": "allow",
    "external_send": "allow",
    "destructive": "allow",
}
GUEST_PROFILE_PERMISSIONS = {
    "computer": "allow",
    "files_read": "allow",
    "files_write": "allow",
    "scripts": "deny",
    "admin": "deny",
    "install": "deny",
    "external_send": "deny",
    "destructive": "deny",
}

# Caricamento differito: l'HUD compare prima che Vosk, OpenAI e PyAutoGUI
# terminino l'inizializzazione nel thread di servizio.
aspetta_avvio = aspetta_jarvis = invia_comando_testo = recupera_frase_wake = None
ascolta = parla = richiedi_stop_voce = None
aggiungi_messaggio = chiedi_jarvis = reset_conversazione = None
interpreta_comando = conferma_azione = conferma_ultima_azione = None
_runtime_lock = threading.Lock()


def _load_runtime_components():
    global aspetta_avvio, aspetta_jarvis, invia_comando_testo, recupera_frase_wake
    global ascolta, parla, richiedi_stop_voce
    global aggiungi_messaggio, chiedi_jarvis, reset_conversazione
    global interpreta_comando, conferma_azione, conferma_ultima_azione
    if aspetta_avvio is not None:
        return
    with _runtime_lock:
        if aspetta_avvio is not None:
            return
        from wakeword import (
            aspetta_avvio as _avvio,
            aspetta_jarvis as _jarvis,
            invia_comando_testo as _invia,
            recupera_frase_wake as _recupera_wake,
        )
        from voice import (
            ascolta as _ascolta,
            parla as _parla,
            richiedi_stop_voce as _stop_voce,
            set_output_level_callback,
        )
        from ai import aggiungi_messaggio as _aggiungi, chiedi_jarvis as _chiedi, reset_conversazione as _reset
        from brain import (
            interpreta_comando as _interpreta,
            conferma_azione as _conferma,
            conferma_ultima_azione as _conferma_ultima,
        )

        aspetta_avvio, aspetta_jarvis, invia_comando_testo, recupera_frase_wake = _avvio, _jarvis, _invia, _recupera_wake
        ascolta, parla, richiedi_stop_voce = _ascolta, _parla, _stop_voce
        aggiungi_messaggio, chiedi_jarvis, reset_conversazione = _aggiungi, _chiedi, _reset
        interpreta_comando, conferma_azione, conferma_ultima_azione = _interpreta, _conferma, _conferma_ultima
        set_output_level_callback(
            lambda level: CORE_RUNTIME.events.publish("voice.output_level", {"level": level}, source="tts")
        )


VARIANTI_JARVIS = {"jarvis", "jarvi", "iarvis", "gervis", "jarves"}
FRASI_FINE_CONVERSAZIONE = {
    "ok",
    "okay",
    "okey",
    "okai",
    "okay stop",
    "ok stop",
    "stop",
    "basta",
    "va bene",
    "va bene grazie",
    "ok grazie",
    "okay grazie",
}


def contestualizza_risposta_companion(domanda, pending):
    """Attach one spontaneous turn to the normal router without changing displayed user text."""
    if not pending or not str(pending.get("message") or "").strip():
        return domanda
    return (
        "JARVIS ha appena iniziato spontaneamente questa conversazione dicendo: "
        f"{pending['message']}\n"
        f"Risposta dell'utente: {domanda}"
    )


def comando_modalita_companion(testo):
    normalized = re.sub(r"\s+", " ", str(testo).strip().lower())
    if (
        "esci dalla modalità focus" in normalized
        or "esci dalla modalita focus" in normalized
        or "puoi tornare a parlare" in normalized
    ):
        return "companion"
    if "modalità focus" in normalized or "modalita focus" in normalized or "non interrompermi" in normalized:
        return "focus"
    return None


def deve_allegare_contesto_operazione(riferito_al_contesto):
    """Independent deterministic commands must retain their local fast path."""
    return bool(riferito_al_contesto)


def _confirmation_intent(testo):
    """Classify only explicit confirmation/cancellation language."""
    value = re.sub(r"[\s,.;:!?]+", " ", str(testo or "").casefold()).strip()
    explicit = re.fullmatch(
        r"(?:conferma|confermo) azione ([a-f0-9]{8,64})(?: pin (.+))?",
        value,
        flags=re.IGNORECASE,
    )
    if explicit:
        return "confirm", explicit.group(1)
    explicit_cancel = re.fullmatch(r"(?:annulla|cancella) azione ([a-f0-9]{8,64})", value, flags=re.IGNORECASE)
    if explicit_cancel:
        return "cancel", explicit_cancel.group(1)
    if re.fullmatch(
        r"(?:confermo|conferma)(?: (?:esegui|procedi|fallo|autorizzo)\b.*)?",
        value,
        flags=re.IGNORECASE,
    ) or re.fullmatch(
        r"(?:si|sì|ok|okay|va bene|certo|procedi|esegui|fallo|autorizzo)(?: procedi)?",
        value,
        flags=re.IGNORECASE,
    ):
        return "confirm", None
    if re.fullmatch(
        r"(?:no|annulla|non farlo|non procedere|rifiuto|rifiuta|stop)",
        value,
        flags=re.IGNORECASE,
    ):
        return "cancel", None
    return None, None


def _confirmation_pin(testo):
    match = re.search(r"\bpin\s+(.+?)\s*$", str(testo or "").strip(), flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _conferma_breve_operazione_precedente(testo, ultimo_contesto=None):
    """True only for a short affirmative answer to a pending operational question."""
    if not isinstance(ultimo_contesto, dict) or not ultimo_contesto:
        return False
    value = re.sub(r"\s+", " ", str(testo or "").strip().lower())
    affirmative = bool(re.fullmatch(
        r"(?:s[iì]|si grazie|s[iì] grazie|ok|okay|va bene|certo|procedi|vai|fallo|fai pure|continua)",
        value,
        flags=re.IGNORECASE,
    ))
    intent, action_id = _confirmation_intent(testo)
    affirmative = affirmative or (intent == "confirm" and not action_id)
    if not affirmative:
        return False
    previous = " ".join(
        str(ultimo_contesto.get(key) or "")
        for key in ("status", "verification_status", "message", "tool", "skill")
    ).lower()
    pending_markers = (
        "vuoi che", "vuole che", "posso ", "procedo", "procedere", "confermi",
        "conferma", "preferisci", "devo ", "posso verificare", "vuoi procedere",
        "vuoi continuare", "recuperi subito", "completare il riassunto", "?",
    )
    return any(marker in previous for marker in pending_markers)


def deve_usare_router_operativo(testo, ultimo_contesto=None, cognitive_decision=None):
    """Use the shared decision policy for every input surface."""
    if cognitive_decision is not None:
        # A supplied canonical decision owns intent, tool eligibility and
        # clarification. Legacy matchers cannot upgrade a non-operational turn.
        if (
            cognitive_decision.needs_clarification
            or cognitive_decision.negated
            or not cognitive_decision.needs_tools
        ):
            return False
        return True
    # Expansion manifests are the authoritative trigger index.  This keeps a
    # technology-specific request on the operational path even when its wording
    # contains a generic verb such as "salva".  Explicit registered skills must
    # win before the generic previous-result detector.
    try:
        if match_expansion_skill(CORE_RUNTIME.skills, testo) is not None:
            return True
    except (AttributeError, TypeError, ValueError):
        pass
    if is_operational_followup(testo, ultimo_contesto):
        return True
    if _conferma_breve_operazione_precedente(testo, ultimo_contesto):
        return True
    has_context = isinstance(ultimo_contesto, dict) or ultimo_contesto is True
    return decide(testo, has_context=has_context).needs_tools


def _contesto_operativo_corrente():
    try:
        return CORE_RUNTIME.context.operational_context()
    except Exception:
        return None


def _testo_operativo_risolto(testo: str, reference) -> str:
    """Return the internal routing text without changing the user transcript."""
    if getattr(reference, "resolved", False) and getattr(reference, "reference_type", None) == "application":
        value = getattr(reference, "value", None)
        if isinstance(value, dict) and value.get("name"):
            if re.search(r"\bchiudi\w*\b", testo, re.I):
                return f"chiudi {value['name']}"
            if re.search(r"\bapri\w*\b", testo, re.I):
                return f"apri {value['name']}"
    return testo


def _prepare_cognitive_turn(original_text, resolved_text, reference=None, operational_context=None):
    """Build the one canonical decision shared by all turn consumers."""
    cognition = getattr(CORE_RUNTIME, "cognition", None)
    if cognition is None:
        return decide(resolved_text, has_context=bool(reference or operational_context))
    try:
        return cognition.decide(
            original_text,
            resolved_operational_text=resolved_text,
            reference=reference,
            operational_context=operational_context,
        )
    except Exception as exc:
        print("[WARN] cognitive decision degraded:", redact(repr(exc)))
        return decide(resolved_text, has_context=bool(reference or operational_context))


def _esegui_followup_operativo(testo, contesto):
    """Run a deterministic follow-up using only the real shared tools."""
    if not is_operational_followup(testo, contesto):
        return None
    from brain import esegui_tool

    def opener(path, application):
        if application:
            return esegui_tool("apri_percorso_con_programma", {"percorso": path, "programma": application})
        return esegui_tool("apri_percorso", {"percorso": path})

    result = execute_operational_followup(
        testo,
        contesto,
        writer=CORE_RUNTIME.write_text_file,
        opener=opener,
    )
    if result is None:
        return None
    handled, message, tool_result = result
    # Synthetic clarification responses have no real action to retain.  Every
    # result coming from writer/opener, including failures, invalidates older
    # reusable content through the normal operational context path.
    if isinstance(tool_result, dict) and "stato" not in tool_result:
        normalized_text = str(testo).casefold()
        action = "files.write" if any(marker in normalized_text for marker in ("salv", "esport", "scriv", "metti", "crea", "fall")) else "apri_percorso"
        try:
            CORE_RUNTIME.context.record_operational_result(action, tool_result, {})
        except Exception:
            pass
    return handled, message, False


class SingleActionAnnouncement:
    def __init__(self):
        self._claimed = False
        self._lock = threading.Lock()

    def claim(self):
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True


from hud_startup import StartupScreen  # noqa: E402 - keeps startup UI import lazy after runtime helpers
StartupScreen.__name__ = "MinimalStartupScreen"  # compatibilità del vecchio test pubblico; classe canonica invariata
class ConsoleStream(QObject):
    testo = Signal(str)

    def __init__(self, original):
        super().__init__()
        self.original = original

    def write(self, text):
        if self.original:
            try:
                self.original.write(text)
                self.original.flush()
            except Exception:
                pass
        self.testo.emit(str(text))

    def flush(self):
        if self.original:
            try:
                self.original.flush()
            except Exception:
                pass


def normalizza_testo(testo):
    if not testo:
        return ""
    testo = testo.lower().strip()
    testo = re.sub(r"[^\wàèéìòù]+", " ", testo, flags=re.UNICODE)
    return re.sub(r"\s+", " ", testo).strip()


def frase_sicurezza_valida(pronunciata, attesa="jarvis sono io"):
    """Fail closed: voiceprint and the complete configured phrase are both required."""
    expected = normalizza_testo(attesa)
    return bool(expected) and normalizza_testo(pronunciata) == expected


def richiesta_fine_conversazione(testo):
    return normalizza_testo(testo) in FRASI_FINE_CONVERSAZIONE


def interpreta_richiamo_jarvis(testo):
    testo_normale = normalizza_testo(testo)
    if not testo_normale:
        return None, None
    if testo_normale in VARIANTI_JARVIS:
        return "solo", None
    for variante in VARIANTI_JARVIS:
        prefisso = variante + " "
        if testo_normale.startswith(prefisso):
            resto = testo_normale[len(prefisso) :].strip()
            if resto:
                return "domanda", resto
    return None, None


def sembra_comando_pc(testo):
    testo = testo.lower().strip()
    parole = [
        "apri",
        "aprimi",
        "chiudi",
        "volume",
        "muto",
        "silenzia",
        "alza",
        "alzalo",
        "abbassa",
        "abbassalo",
        "cartella",
        "crea file",
        "sposta file",
        "copia file",
        "rinomina",
        "cerca file",
        "impostazioni",
        "bluetooth",
        "task manager",
        "gestione attività",
        "esplora file",
        "desktop",
        "menu start",
        "finestra",
        "minimizza",
        "massimizza",
        "porta davanti",
        "ridimensiona",
        "mouse",
        "tastiera",
        "webcam",
        "microfono",
        "fotocamera",
        "file",
        "applicazioni",
        "programmi",
        "accesso al computer",
        "accesso al pc",
        "controllare il computer",
        "controllare direttamente",
        "usare il computer",
        "clicca",
        "click",
        "doppio click",
        "scroll",
        "scorri",
        "scrivi",
        "incolla",
        "seleziona tutto",
        "premi invio",
        "premi esc",
        "ctrl",
        "salva il file",
        "screenshot",
        "cattura schermo",
        "metti in pausa",
        "riprendi la musica",
        "traccia successiva",
        "traccia precedente",
        "canzone successiva",
        "quanta ram",
        "quanto ram",
        "uso cpu",
        "uso ram",
        "processi attivi",
        "stato del pc",
        "lancia",
        "avvia chrome",
        "mostra desktop",
        "vai al desktop",
        "passa alla finestra",
        "massimizzalo",
        "minimizzalo",
        "chiudilo",
        "aprilo",
        "spostalo",
        "ridimensionalo",
        "copialo",
        "rinominalo",
        "scrivilo",
        "premilo",
        "cosa vedi",
        "guarda lo schermo",
        "analizza lo schermo",
        "leggi lo schermo",
        "trova il pulsante",
        "trova sullo schermo",
        "verifica sullo schermo",
        "cosa sai fare",
        "quali capacità",
        "quali capacita",
        "crea archivio",
        "crea zip",
        "estrai archivio",
        "estrai zip",
        "comprimi",
        "stato wifi",
        "connessioni di rete",
        "servizi windows",
        "programmi installati",
        "installa programma",
        "aggiorna programma",
        "script powershell",
        "script python",
        "esegui script",
        "automazione quando",
        "regola evento",
        "attività recenti",
        "attivita recenti",
        "ripristina ultima eliminazione",
        "spegni",
        "spegnere",
        "riavvia",
        "riavviare",
        "sospendi",
        "blocca il pc",
        "chrome",
        "browser",
        "scheda",
        "pagina web",
        "vai su",
        "naviga",
        "cerca su",
        "crea un bot",
        "crea il bot",
        "creami un bot",
        "costruisci un bot",
        "crea progetto",
        "crea un progetto",
        "sviluppa",
        "codice",
        "gestisci",
        "controlla",
        "automatizza",
        "configura",
        "modifica",
        "genera",
        "scarica",
        "disinstalla",
        "rimuovi",
        "manda",
        "invia",
        "compila",
        "riproduci",
        "video",
        "youtube",
        "risultato",
        "primo",
        "secondo",
        "terzo",
        "tradingview",
        "trading view",
        "analizza questo grafico",
        "grafico visibile",
        "candela",
        "candele",
        "timeframe",
        "temporale",
        "un ora",
        "1 ora",
        "sessanta minuti",
        "testa il progetto",
        "controlla il progetto",
        "correggi il progetto",
        "continua da dove",
    ]
    if any(parola in testo for parola in parole):
        return True
    # Intercetta anche ordini formulati liberamente. Le domande informative
    # continuano invece a passare al normale assistente conversazionale.
    return bool(
        re.match(
            r"^(?:per favore\s+)?(?:fammi|fai|usa|accedi|attiva|disattiva|crea|costruisci|sviluppa|apri|chiudi|avvia|"
            r"lancia|vai|scrivi|salva|sposta|copia|rinomina|elimina|rimuovi|"
            r"installa|aggiorna|scarica|controlla|gestisci|automatizza|configura|imposta|"
            r"spegni|riavvia|sospendi|blocca|premi|clicca|seleziona|mostra|nascondi)\b",
            testo,
            flags=re.IGNORECASE,
        )
    )


def richiede_controllo_visivo(testo):
    value = normalizza_testo(testo)
    markers = (
        "youtube",
        "video",
        "pagina",
        "sullo schermo",
        "clicca",
        "seleziona",
        "cerca",
        "primo risultato",
        "secondo risultato",
        "terzo risultato",
        "riproduci",
        "compila",
        "menu",
        "pulsante",
        "scheda",
        "browser",
        "grafico",
        "trading",
        "candela",
        "candele",
        "timeframe",
        "un ora",
        "1 ora",
        "sessanta minuti",
    )
    return any(marker in value for marker in markers)


def scheda_per_richiesta(testo):
    # Le schede contestuali sono selezioni manuali: la chat resta visibile.
    return "ASSISTENTE"
    t = normalizza_testo(testo)
    if any(
        x in t
        for x in ["impostazioni jarvis", "microfono", "voce jarvis", "wake word", "sensibilità", "avvio automatico"]
    ):
        return "IMPOSTAZIONI"
    if any(x in t for x in ["console", "log", "debug", "errore jarvis", "diagnostica"]):
        return "CONSOLE"
    if any(
        x in t
        for x in [
            "mercato",
            "mercati",
            "forex",
            "eur usd",
            "euro dollaro",
            "nasdaq",
            "nas100",
            "sp500",
            "s p 500",
            "dow jones",
            "oro",
            "xau",
            "fed",
            "bce",
            "inflazione",
            "calendario economico",
            "nfp",
            "cpi",
            "tassi",
        ]
    ):
        return "MERCATI"
    if sembra_comando_pc(t) or any(x in t for x in ["cpu", "ram", "gpu", "disco", "rete", "processi", "computer"]):
        return "SISTEMA"
    return "ASSISTENTE"


def preload_startup_components(status=None):
    """Prepare the critical path without an automatic identity gate."""
    raw_update = status or (lambda _text, _progress=None: None)

    def update(label, progress=None):
        try:
            raw_update(label, progress)
        except TypeError:
            # Compatibilità con i callback legacy che accettano solo il testo.
            raw_update(label)

    result = {"ready": False, "errors": []}
    stage_timeout = max(5.0, float(get_setting("startup_stage_timeout_seconds", 20.0)))
    update("Attivazione sessione CEO sviluppo", 2.0)
    result["identity"] = startup_identity_check()

    def run_bounded(operation):
        """Run optional startup work without allowing one adapter to freeze the HUD."""
        outcome = {"error": None}

        def target():
            try:
                operation()
            except Exception as exc:  # The caller records the structured startup failure.
                outcome["error"] = exc

        thread = threading.Thread(target=target, daemon=True, name="jarvis-startup-stage")
        thread.start()
        thread.join(timeout=stage_timeout)
        if thread.is_alive():
            return TimeoutError(f"fase di avvio oltre il limite di {stage_timeout:.1f}s")
        return outcome["error"]

    stages = (
        ("Avvio servizi principali", CORE_RUNTIME.start),
        ("Ripristino sessione", recover_interrupted),
        ("Connessione browser", start_chrome_bridge),
        ("Caricamento router e voce", _load_runtime_components),
    )
    for index, (label, operation) in enumerate(stages):
        update(label, 8.0 + index * 18.0)
        error = run_bounded(operation)
        if error is not None:
            result["errors"].append({"stage": label, "error": redact(repr(error))})
    update("Caricamento riconoscimento vocale", 88.0)

    def load_wake_model():
        from wakeword import carica_modello

        carica_modello()

    error = run_bounded(load_wake_model)
    if error is not None:
        result["errors"].append({"stage": "wake_model", "error": redact(repr(error))})
    try:
        CORE_RUNTIME.voice.start()
    except Exception as exc:
        result["errors"].append({"stage": "voice_queue", "error": redact(repr(exc))})
    critical = {"Avvio servizi principali", "Caricamento router e voce"}
    result["ready"] = not any(row["stage"] in critical for row in result["errors"])
    update("Sistema pronto" if result["ready"] else "Avvio degradato", 100.0)
    return result


def _shutdown_runtime():
    """Route every Qt exit through the shared, idempotent runtime shutdown."""
    CORE_RUNTIME.stop()


def _is_development_identity_command(text):
    """Recognize legacy identity commands without invoking identity services."""
    lower = normalizza_testo(text)
    biometric_lower = re.sub(r"\bvolte\b", "volto", lower)
    if biometric_lower in {"jarvis sono io", "sono io", "chi vedi", "chi sta parlando"}:
        return True
    if "biometric" in lower or "riconoscimento facciale" in lower or "riconoscimento vocale" in lower:
        return True
    if "stato identit" in lower or "profili biometrici" in lower:
        return True
    if "accesso ceo" in lower or "profilo ceo" in lower:
        return True
    if re.search(r"\b(?:crea|registra|memorizza|elimina|cancella)\b.*\bprofil", lower):
        return True
    if re.search(r"\b(?:registra|memorizza)\b.*\b(?:mio volto|mia voce)", biometric_lower):
        return True
    return any(
        marker in biometric_lower
        for marker in ("riconosci il mio volto", "riconoscimi dal volto", "mio volto", "mia voce")
    )


def startup_identity_check(_identity_service=None):
    """Create the temporary development owner session without biometric I/O.

    The optional argument is retained only for compatibility with older
    callers. IdentityService and persisted biometric profiles are deliberately
    not consulted while ``DEVELOPMENT_AUTO_CEO`` is enabled.
    """
    clear_session()
    activate_session("OWNER", "CEO", FULL_PROFILE_PERMISSIONS, "development_auto_ceo")
    result = {
        "role": "CEO",
        "name": "OWNER",
        "authenticated": True,
        "method": "development_auto_ceo",
        "confidence": 1.0,
        "status": "authenticated",
    }
    CORE_RUNTIME.state.set("identity", result, source="identity")
    return result


class JarvisWorker(QThread):
    attivato = Signal()
    mostra_hud = Signal()
    minimizza_hud = Signal()
    trascrizione = Signal(str)
    risposta = Signal(str)
    stato_assistente = Signal(str)
    apri_scheda_signal = Signal(str)
    market_news_signal = Signal(str)
    arresto = Signal()
    errore = Signal(str)
    stato_modulo = Signal(str, bool)
    richiedi_pin = Signal()
    toggle_tastiera_compatta = Signal()

    def __init__(self):
        super().__init__()
        self.stato_assistente.connect(self._sync_core_state)
        self.running = True
        self.jarvis_avviato = False
        self.sessione_attiva = False
        self.conversazione_vocale_attiva = False
        self.richiesta_fine = False
        self.forza_ascolto = False
        self.sta_parlando = False
        self.lock_stato = threading.Lock()
        self.domanda_interruzione = None
        self.interrompi_ascolto = threading.Event()
        self.scheda_corrente_domanda = "ASSISTENTE"
        self.ultimo_contesto_pc = None
        self.active_task_id = None
        self._cycle_sequence = 0
        self._active_cycle_id = None
        self._cycle_trace = []
        self._ambient_speaker = None
        self.attention = AttentionController(CORE_RUNTIME.state)

    def _sync_core_state(self, state):
        from jarvis_core.state_machine import JarvisState

        mapping = {
            "standby": JarvisState.IDLE,
            "idle": JarvisState.IDLE,
            "listening": JarvisState.LISTENING,
            "user": JarvisState.TRANSCRIBING,
            "thinking": JarvisState.UNDERSTANDING,
            "planning": JarvisState.PLANNING,
            "waiting_confirmation": JarvisState.WAITING_PERMISSION,
            "executing": JarvisState.EXECUTING,
            "verifying": JarvisState.VERIFYING,
            "recovering": JarvisState.RECOVERING,
            "speaking": JarvisState.SPEAKING,
            "error": JarvisState.ERROR,
        }
        target = mapping.get(str(state).lower())
        if target is not None:
            CORE_RUNTIME.state_machine.advance(target, source="voice_worker")

    def set_sta_parlando(self, valore):
        with self.lock_stato:
            self.sta_parlando = valore

    def _cycle_transition(self, state):
        with self.lock_stato:
            cycle_id = self._active_cycle_id
            if cycle_id is None:
                return
            row = {"cycle": cycle_id, "state": str(state), "at": time.monotonic()}
            self._cycle_trace.append(row)
            self._cycle_trace = self._cycle_trace[-300:]
        print(f"[CYCLE {cycle_id}] {state}")

    def _begin_cycle(self, wake_detected=False):
        with self.lock_stato:
            self._cycle_sequence += 1
            self._active_cycle_id = self._cycle_sequence
        self._cycle_transition("STANDBY")
        if wake_detected:
            self._cycle_transition("WAKE_DETECTED")

    def _finish_cycle(self):
        self._cycle_transition("AUDIO_RELEASED")
        self._cycle_transition("BACK_TO_STANDBY")
        with self.lock_stato:
            self._active_cycle_id = None

    def _recover_cycle_exception(self, exc):
        print(f"\n[ERROR] ERRORE CICLO: {redact(repr(exc))}")
        self._cycle_transition("ERROR_RECOVERED")
        self.domanda_interruzione = None
        self.interrompi_ascolto.clear()
        self.set_sta_parlando(False)
        if self.active_task_id:
            ASYNC_ENGINE.cancel(self.active_task_id)
            self.active_task_id = None

    def minimizza_da_tastiera(self):
        if self.sessione_attiva:
            self.minimizza_hud.emit()

    def attiva_da_tastiera(self):
        if self.jarvis_avviato:
            self.mostra_hud.emit()
            return
        invia_comando_testo("tastiera")

    def tastiera_compatta_da_hotkey(self):
        self.toggle_tastiera_compatta.emit()

    def ricevi_testo(self, testo):
        if not testo:
            return
        testo = testo.strip()
        if not testo:
            return
        print("\n⌨️ TESTO:", testo)

        if testo.lower() in ["nuova conversazione", "reset conversazione", "dimentica conversazione"]:
            reset_conversazione()
            self.risposta.emit("Conversazione resettata.")
            return

        with self.lock_stato:
            parlando = self.sta_parlando

        if parlando:
            self.domanda_interruzione = testo
            CORE_RUNTIME.voice.interrupt(testo)
            return

        _accoda_domanda(testo)
        if self.conversazione_vocale_attiva:
            self.interrompi_ascolto.set()
            return
        if self.jarvis_avviato:
            invia_comando_testo("domanda_testo")

    def stop(self):
        if not self.running:
            return
        print("\n🛑 Arresto JARVIS...")
        self.running = False
        self.jarvis_avviato = False
        self.sessione_attiva = False
        self.conversazione_vocale_attiva = False
        self.forza_ascolto = False
        self.interrompi_ascolto.set()
        if self.active_task_id:
            ASYNC_ENGINE.cancel(self.active_task_id)
        richiedi_stop_voce()
        invia_comando_testo("stop")
        _accoda_domanda(None)
        self.requestInterruption()

    def emergency_stop(self):
        """Abort active work without closing the HUD or the assistant loop."""
        self.interrompi_ascolto.set()
        if self.active_task_id:
            ASYNC_ENGINE.cancel(self.active_task_id)
            self.active_task_id = None
        CORE_RUNTIME.emergency.trigger("global_shortcut")
        self.stato_assistente.emit("idle")

    def interpreta_interruzione(self, testo):
        if not testo:
            return None
        tipo, resto = interpreta_richiamo_jarvis(testo)
        if tipo == "solo":
            print("\n⚡ JARVIS richiamato durante la risposta")
            return "__JARVIS__"
        if tipo == "domanda":
            print("\n⚡ JARVIS + NUOVA DOMANDA:", resto)
            return resto
        return testo.strip()

    def parla_controllato(self, testo, interrompibile=True, *, already_rendered=False, request=""):
        if not testo or not self.running:
            return None
        if already_rendered:
            spoken_text = str(testo)
        else:
            rendered = RESPONSE_RENDERER.render(
                TechnicalResult(True, str(testo)),
                request=request,
                technical_mode=bool(get_setting("technical_mode", False)),
            )
            spoken_text = rendered.spoken_response
        print("\nJARVIS:", spoken_text)
        self.stato_assistente.emit("speaking")
        self._cycle_transition("TTS_START")
        self.set_sta_parlando(True)
        self.stato_modulo.emit("TTS", True)
        try:
            risultato = CORE_RUNTIME.voice.speak_wait(spoken_text, interruptible=interrompibile)
        except Exception as exc:
            print("\n[ERROR] ERRORE VOCE:", redact(repr(exc)))
            self.stato_modulo.emit("TTS", False)
            risultato = None
        finally:
            self.set_sta_parlando(False)
            self._cycle_transition("TTS_END")

        if isinstance(risultato, str) and risultato.startswith("__TESTO__:"):
            nuova = risultato[len("__TESTO__:") :].strip()
            return self.interpreta_interruzione(nuova) if nuova else None
        if isinstance(risultato, str) and risultato.strip():
            return self.interpreta_interruzione(risultato)
        if self.domanda_interruzione:
            nuova = self.domanda_interruzione
            self.domanda_interruzione = None
            return self.interpreta_interruzione(nuova)
        return None

    def chiudi_conversazione_vocale(self):
        self.richiesta_fine = True
        self.conversazione_vocale_attiva = False
        self.forza_ascolto = False
        self.risposta.emit("Va bene.")
        self.parla_controllato("Va bene.", interrompibile=False)
        self.stato_assistente.emit("standby")

    def risposta_ai(self, domanda, cognitive_decision=None):
        # Defense in depth: an operational utterance must never reach the
        # conversational provider, even if a routing exception occurs.
        if deve_usare_router_operativo(domanda, _contesto_operativo_corrente(), cognitive_decision):
            message = "Non ho eseguito alcuna azione: la richiesta operativa deve essere gestita da uno strumento verificabile."
            self._risposta_locale(message)
            return None
        print("\n💬 Invio domanda all'AI...")
        nuova_domanda = None
        phrase_queue = queue.Queue()
        producer_error = []
        
        # [DIAG_MAIN] Contatore frasi
        phrase_count = [0]  # wrap in list to allow mutation in nested function
        start_time = time.perf_counter()

        def produce_response():
            full = ""
            try:
                for phrase in chiedi_jarvis(domanda, cognitive_decision=cognitive_decision):
                    if not self.running:
                        break
                    if not phrase:
                        continue
                    phrase_count[0] += 1
                    full = (full + " " + phrase).strip()
                    self.risposta.emit(full)
                    if self.scheda_corrente_domanda == "MERCATI":
                        self.market_news_signal.emit(full)
                    elapsed = time.perf_counter() - start_time
                    print(f"\n[DIAG] AI FRASE {phrase_count[0]} ricevuta (t={elapsed:.2f}s): {repr(phrase[:60])}")
                    phrase_queue.put(phrase)
            except Exception as exc:
                producer_error.append(exc)
            finally:
                phrase_queue.put(None)

        try:
            self.stato_modulo.emit("AI", True)
            producer = threading.Thread(target=produce_response, daemon=True, name="jarvis-ai-stream")
            producer.start()
            parla_call_num = [0]  # Counter for parla calls
            risposta_voce = []
            while self.running:
                frase = phrase_queue.get()
                if frase is None:
                    break
                elapsed = time.perf_counter() - start_time
                risposta_voce.append(frase)
                print(f"\n[DIAG] AI FRASE ACCUMULATA #{len(risposta_voce)} (t={elapsed:.2f}s): {repr(frase[:60])}")
            if self.running and risposta_voce:
                testo_voce = " ".join(risposta_voce).strip()
                parla_call_num[0] = 1
                elapsed = time.perf_counter() - start_time
                print(f"\n[DIAG] PARLA() CALL #1 (risposta completa, {len(risposta_voce)} frasi, t={elapsed:.2f}s): {repr(testo_voce[:60])}")
                nuova = self.parla_controllato(testo_voce, request=domanda)
                if nuova:
                    nuova_domanda = nuova
            if producer_error:
                raise producer_error[0]
        except Exception as exc:
            print("\n[ERROR] ERRORE AI:", redact(repr(exc)))
            self.stato_modulo.emit("AI", False)
            messaggio = "Si è verificato un errore durante la risposta."
            self.risposta.emit(messaggio)
            nuova = self.parla_controllato(messaggio)
            if nuova:
                nuova_domanda = nuova

        if not nuova_domanda:
            self.stato_assistente.emit("listening" if self.conversazione_vocale_attiva else "standby")
        return nuova_domanda

    def _risposta_locale(self, message):
        rendered = self._presenta_risultato(message)
        record_assistant_turn(CORE_RUNTIME, rendered.display_response)
        self.parla_controllato(rendered.spoken_response, already_rendered=True)

    def _presenta_risultato(self, message, *, request="", success=True, verification_status=None, data=None):
        """Present one operational result through the shared speech/HUD renderer."""
        rendered = RESPONSE_RENDERER.render(
            TechnicalResult(
                success=bool(success) and not message_indicates_failure(message),
                message=str(message or ""),
                verification_status=verification_status,
                data=dict(data or {}),
            ),
            request=request,
            technical_mode=bool(get_setting("technical_mode", False)),
        )
        self.risposta.emit(rendered.display_response)
        return rendered
        self.stato_assistente.emit("listening" if self.conversazione_vocale_attiva else "standby")

    @staticmethod
    def _annuncio_per_azione(nome_tool, argomenti):
        nome = str((argomenti or {}).get("nome") or "").strip()
        query = str((argomenti or {}).get("query") or "").strip()
        annunci = {
            "apri_programma": f"Certo, sto aprendo {nome}." if nome else "Certo, apro il programma.",
            "apri_sito": f"Va bene, apro {nome}." if nome else "Va bene, apro il sito.",
            "cerca_google": f"Cerco subito {query}." if query else "Cerco subito.",
            "chiudi_programma": f"Va bene, sto chiudendo {nome}." if nome else "Va bene, chiudo il programma.",
            "visual_task": "Certo, me ne occupo subito.",
            "analizza_schermo": "Va bene, osservo lo schermo.",
            "analyze_trading_chart": "Certo, analizzo il grafico visibile.",
            "crea_progetto": "Va bene, preparo il progetto.",
            "spegni_pc": "Va bene, preparo lo spegnimento.",
            "riavvia_pc": "Va bene, preparo il riavvio.",
        }
        return annunci.get(nome_tool, "Certo, me ne occupo subito.")

    def _gestisci_conferma_operativa(self, domanda):
        intent, action_id = _confirmation_intent(domanda)
        if intent not in {"confirm", "cancel"}:
            return False
        from brain import (
            annulla_azione,
            conferma_azione,
            conferma_ultima_azione,
            messaggio_risultato_operativo,
            pending_confirmation_actions,
        )

        pending = pending_confirmation_actions()
        normalized = re.sub(r"[\s,.;:!?]+", " ", str(domanda or "").casefold()).strip()
        if intent == "confirm" and not pending and not action_id and normalized == "procedi" and is_operational_followup(
            domanda, _contesto_operativo_corrente()
        ):
            return False
        if intent == "confirm":
            pin = _confirmation_pin(domanda) if action_id else None
            result = conferma_azione(action_id, pin) if action_id else conferma_ultima_azione()
            message = messaggio_risultato_operativo(result) if result.get("successo") else str(
                result.get("messaggio") or "Conferma non eseguita."
            )
        else:
            result = annulla_azione(action_id)
            message = str(result.get("messaggio") or "Annullamento non eseguito.")
        self._risposta_locale(message)
        return True

    def _comando_memoria_o_conferma(self, domanda):
        confirmation_handled = self._gestisci_conferma_operativa(domanda)
        if confirmation_handled:
            return True
        text = str(domanda or "").strip()
        lower = text.lower()
        if lower in {"modalità tecnica", "modalita tecnica", "attiva modalità tecnica", "attiva modalita tecnica"}:
            set_setting("technical_mode", True)
            self._risposta_locale("Modalità tecnica attiva.")
            return True
        if lower in {"disattiva modalità tecnica", "disattiva modalita tecnica", "esci dalla modalità tecnica", "esci dalla modalita tecnica"}:
            set_setting("technical_mode", False)
            self._risposta_locale("Modalità normale attiva.")
            return True
        if is_operational_followup(text, _contesto_operativo_corrente()) and lower in {"procedi", "conferma", "confermo", "sì procedi", "si procedi"}:
            return False
        if DEVELOPMENT_AUTO_CEO and _is_development_identity_command(text):
            self._risposta_locale(
                "Modalita sviluppo attiva: sessione OWNER/CEO automatica. "
                "Profili e riconoscimento biometrico sono disabilitati."
            )
            return True
        biometric_lower = re.sub(r"\bvolte\b", "volto", lower)
        if lower in {"attiva riconoscimento biometrico", "attiva identità biometrica", "attiva identita biometrica"}:
            set_setting("biometric_identity_enabled", True)
            self._risposta_locale("Riconoscimento biometrico locale attivato.")
            return True
        if lower in {
            "disattiva riconoscimento biometrico",
            "disattiva identità biometrica",
            "disattiva identita biometrica",
        }:
            set_setting("biometric_identity_enabled", False)
            self._risposta_locale(
                "Riconoscimento biometrico disattivato. I profili restano cifrati finché non chiedi di eliminarli."
            )
            return True
        if lower in {"stato identità", "stato identita", "profili biometrici"}:
            status = IDENTITY.status()
            profiles = ", ".join(status["profiles"]) or "nessuno"
            role = CORE_RUNTIME.state.get("identity", {}).get("role", "GUEST")
            self._risposta_locale(f"Profili biometrici locali: {profiles}. Sessione attuale: {role}.")
            return True
        if lower in {"riprova accesso ceo", "accedi al profilo ceo", "verifica accesso ceo"}:
            result = startup_identity_check()
            if result.get("authenticated"):
                self._risposta_locale(f"Bentornato {result['name']}. Profilo CEO personale attivo.")
            elif result.get("status") == "setup_required":
                self._risposta_locale(
                    "Il profilo CEO non è ancora registrato. Di': registra il mio volto come Gabriele."
                )
            else:
                self._risposta_locale("Accesso CEO non riuscito. Sessione ospite mantenuta.")
            return True
        if lower in {"crea profilo", "crea un profilo", "crea e salva profilo", "registra profilo"}:
            self._risposta_locale("Indica il nome. Per esempio: crea profilo CEO Gabriele con permessi completi.")
            return True
        profile_match = re.fullmatch(
            r"(?:crea|registra)(?: e salva)? (?:un |il )?profilo(?: personale)?(?: (?:da )?ceo)?(?: nome)?\s+(.+?)(?:\s+con permessi\s+(completi|standard|limitati))?",
            text,
            flags=re.IGNORECASE,
        )
        if profile_match:
            profile_name = profile_match.group(1).strip()
            preset = (profile_match.group(2) or "completi").lower()
            permissions = dict(FULL_PROFILE_PERMISSIONS)
            if preset in {"standard", "limitati"}:
                permissions.update(
                    {
                        "scripts": "deny",
                        "admin": "deny",
                        "install": "deny",
                        "external_send": "deny",
                        "destructive": "deny",
                    }
                )
            try:
                self.risposta.emit(
                    "Guarda la webcam. Subito dopo pronuncia Jarvis, sono io per tre volte, con voce naturale."
                )
                result = IDENTITY.create_profile(
                    profile_name,
                    permissions,
                    camera=int(get_setting("face_camera", 0)),
                    device=get_setting("mic_device", None),
                    role="CEO",
                )
                set_setting("ceo_profile_name", profile_name)
                set_setting("startup_face_login", True)
                set_setting("biometric_identity_enabled", True)
                activate_session(profile_name, "CEO", permissions, "windows_dpapi+face+voice_enrollment")
                CORE_RUNTIME.state.set(
                    "identity",
                    {
                        "role": "CEO",
                        "name": profile_name,
                        "authenticated": True,
                        "method": "windows_dpapi+face+voice_enrollment",
                        "confidence": 1.0,
                        "status": "authenticated",
                    },
                    source="identity",
                )
                self._risposta_locale(result["messaggio"] + " Accesso con volto e frase vocale di riserva attivati.")
            except Exception as exc:
                self._risposta_locale(f"Creazione del profilo non riuscita: {redact(str(exc))}.")
            return True
        if biometric_lower in {"jarvis sono io", "sono io"}:
            try:
                self.risposta.emit("Verifico la tua impronta vocale.")
                match = IDENTITY.recognize_voice(
                    device=get_setting("mic_device", None), threshold=float(get_setting("voice_match_threshold", 0.88))
                )
                stored = IDENTITY.profile(match.get("name")) if match.get("matched") else None
                metadata = (stored or {}).get("metadata", {})
                phrase_ok = frase_sicurezza_valida(text, metadata.get("fallback_phrase", "jarvis sono io"))
                if not match.get("matched") or not stored or not phrase_ok:
                    raise RuntimeError("voce o frase di sicurezza non riconosciuta")
                activate_session(
                    match["name"],
                    metadata.get("role", "USER"),
                    metadata.get("permissions") or GUEST_PROFILE_PERMISSIONS,
                    "windows_dpapi+voice_phrase",
                )
                CORE_RUNTIME.state.set(
                    "identity",
                    {
                        "role": metadata.get("role", "USER"),
                        "name": match["name"],
                        "authenticated": True,
                        "method": "windows_dpapi+voice_phrase",
                        "confidence": match["score"],
                        "status": "authenticated",
                    },
                    source="identity",
                )
                self._risposta_locale(
                    f"Voce verificata. Bentornato {match['name']}, profilo {metadata.get('role', 'USER')} attivo."
                )
            except Exception as exc:
                self._risposta_locale(f"Accesso vocale non riuscito: {redact(str(exc))}.")
            return True
        biometric_request = any(
            marker in biometric_lower
            for marker in ("mio volto", "dal volto", "chi vedi", "mia voce", "dalla voce", "chi sta parlando")
        )
        if biometric_request and not bool(get_setting("biometric_identity_enabled", True)):
            self._risposta_locale("Il riconoscimento biometrico è disattivato nelle impostazioni.")
            return True
        wants_face = any(marker in biometric_lower for marker in ("mio volto", "dal volto", "chi vedi"))
        wants_voice = any(marker in biometric_lower for marker in ("mia voce", "dalla voce", "chi sta parlando"))
        is_recognition = any(
            marker in biometric_lower for marker in ("riconosci", "riconoscimi", "chi vedi", "chi sta parlando")
        )
        if is_recognition and wants_face and wants_voice:
            messages = []
            try:
                face = IDENTITY.recognize_face(
                    camera=int(get_setting("face_camera", 0)),
                    threshold=float(get_setting("face_match_threshold", 0.91)),
                )
                messages.append(
                    f"volto: {face['name']} con confidenza {face['score']:.0%}"
                    if face["matched"]
                    else "volto non riconosciuto"
                )
                owner = str(get_setting("ceo_profile_name", "Gabriele"))
                if face["matched"] and str(face.get("name", "")).casefold() == owner.casefold():
                    CORE_RUNTIME.state.set(
                        "identity",
                        {
                            "role": "CEO",
                            "name": face["name"],
                            "authenticated": True,
                            "method": "windows_dpapi+face",
                            "confidence": face["score"],
                            "status": "authenticated",
                        },
                        source="identity",
                    )
            except Exception as exc:
                messages.append(f"volto non disponibile, {redact(str(exc))}")
            try:
                self.risposta.emit("Ora parla normalmente per qualche secondo.")
                voice = IDENTITY.recognize_voice(
                    device=get_setting("mic_device", None), threshold=float(get_setting("voice_match_threshold", 0.88))
                )
                messages.append(
                    f"voce: {voice['name']} con confidenza {voice['score']:.0%}"
                    if voice["matched"]
                    else "voce non riconosciuta"
                )
            except Exception as exc:
                messages.append(f"voce non disponibile, {redact(str(exc))}")
            self._risposta_locale("Verifica identità completata. " + "; ".join(messages) + ".")
            return True
        match = re.fullmatch(r"(?:registra|memorizza) (?:il )?mio volto(?: come)?\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            try:
                self.stato_assistente.emit("thinking")
                profile_name = match.group(1).strip()
                result = IDENTITY.enroll_face(profile_name, camera=int(get_setting("face_camera", 0)))
                set_setting("ceo_profile_name", profile_name)
                set_setting("startup_face_login", True)
                CORE_RUNTIME.state.set(
                    "identity",
                    {
                        "role": "CEO",
                        "name": profile_name,
                        "authenticated": True,
                        "method": "windows_dpapi+face_enrollment",
                        "confidence": 1.0,
                        "status": "authenticated",
                    },
                    source="identity",
                )
                self._risposta_locale(
                    result["messaggio"] + " Profilo CEO attivo e verifica automatica abilitata all'avvio."
                )
            except Exception as exc:
                self._risposta_locale(f"Registrazione del volto non riuscita: {redact(str(exc))}.")
            return True
        if biometric_lower in {"riconosci il mio volto", "riconoscimi dal volto", "chi vedi"}:
            try:
                result = IDENTITY.recognize_face(
                    camera=int(get_setting("face_camera", 0)),
                    threshold=float(get_setting("face_match_threshold", 0.91)),
                )
                owner = str(get_setting("ceo_profile_name", "Gabriele"))
                if result["matched"] and str(result.get("name", "")).casefold() == owner.casefold():
                    CORE_RUNTIME.state.set(
                        "identity",
                        {
                            "role": "CEO",
                            "name": result["name"],
                            "authenticated": True,
                            "method": "windows_dpapi+face",
                            "confidence": result["score"],
                            "status": "authenticated",
                        },
                        source="identity",
                    )
                message = (
                    f"Ti riconosco come {result['name']}, confidenza {result['score']:.0%}."
                    if result["matched"]
                    else "Non riconosco con sufficiente confidenza il volto rilevato."
                )
                self._risposta_locale(message)
            except Exception as exc:
                self._risposta_locale(f"Riconoscimento facciale non disponibile: {redact(str(exc))}.")
            return True
        match = re.fullmatch(r"(?:registra|memorizza) (?:la )?mia voce(?: come)?\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            try:
                self.risposta.emit("Pronuncia la stessa frase tre volte, una per ogni campione.")
                result = IDENTITY.enroll_voice(match.group(1).strip(), device=get_setting("mic_device", None))
                set_setting("wake_speaker_lock", True)
                self._risposta_locale(result["messaggio"])
            except Exception as exc:
                self._risposta_locale(f"Registrazione della voce non riuscita: {redact(str(exc))}.")
            return True
        if lower in {"riconosci la mia voce", "chi sta parlando", "riconoscimi dalla voce"}:
            try:
                self.risposta.emit("Parla normalmente per qualche secondo.")
                result = IDENTITY.recognize_voice(
                    device=get_setting("mic_device", None), threshold=float(get_setting("voice_match_threshold", 0.88))
                )
                message = (
                    f"La voce corrisponde a {result['name']}, confidenza {result['score']:.0%}."
                    if result["matched"]
                    else "La voce non corrisponde con sufficiente confidenza a un profilo locale."
                )
                self._risposta_locale(message)
            except Exception as exc:
                self._risposta_locale(f"Riconoscimento vocale non disponibile: {redact(str(exc))}.")
            return True
        match = re.fullmatch(r"(?:elimina|cancella) profilo biometrico\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            removed = IDENTITY.delete_profile(match.group(1))
            self._risposta_locale("Profilo biometrico eliminato." if removed else "Profilo biometrico non trovato.")
            return True
        if lower in {"attiva modalità privata", "attiva modalita privata", "modalità privata", "modalita privata"}:
            set_setting("privacy_mode", True)
            reset_conversazione()
            self._risposta_locale("Modalità privata attiva. Questa sessione non verrà memorizzata.")
            return True
        if lower in {
            "disattiva modalità privata",
            "disattiva modalita privata",
            "termina modalità privata",
            "termina modalita privata",
        }:
            set_setting("privacy_mode", False)
            self._risposta_locale("Modalità privata disattivata.")
            return True
        if lower.startswith("ricorda che "):
            result = remember(text[11:].strip(), category="user_fact")
            self._risposta_locale(result["messaggio"])
            return True
        if lower in {"cosa ricordi", "cosa ricordi di me", "mostra memoria", "mostra la memoria"}:
            rows = search_memory(limit=12)
            if not rows:
                message = "Non ho ancora memorie personali salvate."
            else:
                message = "Ricordo: " + "; ".join(f"numero {row['id']}: {row['content']}" for row in rows)
            self._risposta_locale(message)
            return True
        if lower in {"esporta memoria", "esporta la memoria", "crea backup memoria"}:
            path = export_memory()
            self._risposta_locale(f"Memoria esportata in {path}.")
            return True
        if lower in {"attiva modalità proattiva", "attiva modalita proattiva"}:
            set_setting("proactive_enabled", True)
            self._risposta_locale("Modalità proattiva attivata.")
            return True
        if lower in {"disattiva modalità proattiva", "disattiva modalita proattiva"}:
            set_setting("proactive_enabled", False)
            self._risposta_locale("Modalità proattiva disattivata.")
            return True
        mode_commands = {
            "modalità osservazione": "observe",
            "modalita osservazione": "observe",
            "modalità assistita": "assisted",
            "modalita assistita": "assisted",
            "modalità autonoma": "autonomous",
            "modalita autonoma": "autonomous",
        }
        if lower in mode_commands:
            mode = set_mode(mode_commands[lower])
            self._risposta_locale(f"Modalità {mode} attivata.")
            return True
        if lower in {"mostra permessi", "quali permessi hai", "profilo autorizzazioni"}:
            data = permission_profile()
            self._risposta_locale(
                f"Modalità {data['mode']}. Permessi: " + "; ".join(f"{k} {v}" for k, v in data["categories"].items())
            )
            return True
        if lower in {"imposta pin sicurezza", "cambia pin sicurezza"}:
            self._risposta_locale("Il PIN è stato rimosso. JARVIS opera già in modalità autonoma.")
            return True
        if lower in {"attiva visione", "attiva la visione"}:
            set_setting("vision_enabled", True)
            self._risposta_locale("Visione dello schermo attivata.")
            return True
        match = re.fullmatch(r"crea competenza\s+(.+?)\s*:\s*(.+)", text, flags=re.IGNORECASE)
        if match:
            try:
                skill = create_skill(match.group(1), match.group(2).split(";"))
                self._risposta_locale(f"Competenza {skill['name']} salvata con {len(skill['commands'])} passaggi.")
            except ValueError:
                self._risposta_locale("Per creare una competenza indica nome e passaggi separati da punto e virgola.")
            return True
        if lower in {"mostra competenze", "elenca competenze", "quali competenze ho"}:
            skills = list_skills()
            message = (
                "Non hai ancora competenze personalizzate."
                if not skills
                else "; ".join(f"{s['name']}, {len(s['commands'])} passaggi" for s in skills)
            )
            self._risposta_locale(message)
            return True
        match = re.fullmatch(r"esegui competenza\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            skill = get_skill(match.group(1))
            if not skill:
                self._risposta_locale("Non trovo quella competenza.")
            else:
                for command in skill["commands"]:
                    _accoda_domanda(command)
                self._risposta_locale(f"Avvio la competenza {skill['name']}.")
            return True
        match = re.fullmatch(r"elimina competenza\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            self._risposta_locale(
                "Competenza eliminata." if delete_skill(match.group(1)) else "Non trovo quella competenza."
            )
            return True
        if lower in {"disattiva visione", "disattiva la visione"}:
            set_setting("vision_enabled", False)
            self._risposta_locale("Visione dello schermo disattivata.")
            return True
        match = re.fullmatch(r"(?:dimentica|cancella memoria)\s+(\d+)", lower)
        if match:
            self._risposta_locale(forget_memory(int(match.group(1)))["messaggio"])
            return True
        match = re.fullmatch(r"conferma azione\s+([a-f0-9]{8})(?:\s+pin\s+(.+))?", lower)
        if match:
            self._risposta_locale("Le conferme non sono più necessarie: le azioni vengono eseguite direttamente.")
            return True
        match = re.fullmatch(r"(?:confermo|conferma|procedi|sì procedi|si procedi)(?:\s+pin\s+(.+))?", lower)
        if match:
            self._risposta_locale("Non ci sono conferme in attesa: la modalità autonoma è attiva.")
            return True
        match = re.fullmatch(r"ogni giorno alle\s+(\d{1,2}:\d{2})\s+(.+)", lower)
        if match:
            try:
                routine = add_daily(match.group(1).zfill(5), text[text.lower().find(match.group(2)) :])
                self._risposta_locale(f"Routine {routine['id']} salvata per le {routine['time']}.")
            except ValueError:
                self._risposta_locale("Orario non valido. Usa il formato ore e minuti, per esempio 08:30.")
            return True
        match = re.fullmatch(r"tra\s+(\d+)\s+minut[oi]\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            routine = add_after(int(match.group(1)), match.group(2))
            self._risposta_locale(f"Operazione programmata per le {routine['run_at'][11:16]}.")
            return True
        match = re.fullmatch(r"(?:oggi\s+)?alle\s+(\d{1,2}:\d{2})\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            from datetime import datetime, timedelta

            try:
                hour, minute = (int(x) for x in match.group(1).split(":"))
                when = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
                if when < datetime.now():
                    when += timedelta(days=1)
                routine = add_once(when, match.group(2))
                self._risposta_locale(f"Operazione programmata per le {routine['run_at'][11:16]}.")
            except ValueError:
                self._risposta_locale("Orario non valido.")
            return True
        if lower in {"mostra routine", "elenca routine", "quali automazioni ho"}:
            routines = list_routines()
            message = (
                "Nessuna routine salvata."
                if not routines
                else "; ".join(
                    f"{item['id']} alle {item.get('time') or item.get('run_at', '')[11:16]}: {item['command']} ({'attiva' if item.get('enabled') else 'conclusa o in pausa'})"
                    for item in routines
                )
            )
            self._risposta_locale(message)
            return True
        match = re.fullmatch(r"(?:disattiva|metti in pausa) routine\s+(r\d+)", lower)
        if match:
            ok = set_enabled(match.group(1), False)
            self._risposta_locale("Routine messa in pausa." if ok else "Non trovo quella routine.")
            return True
        match = re.fullmatch(r"(?:attiva|riattiva) routine\s+(r\d+)", lower)
        if match:
            ok = set_enabled(match.group(1), True)
            self._risposta_locale("Routine attivata." if ok else "Non trovo quella routine.")
            return True
        match = re.fullmatch(r"(?:elimina|cancella) routine\s+(r\d+)", lower)
        if match:
            ok = delete_routine(match.group(1))
            self._risposta_locale("Routine eliminata." if ok else "Non trovo quella routine.")
            return True
        if lower.startswith("crea obiettivo "):
            goal = create_goal(text[len("crea obiettivo ") :])
            self._risposta_locale(f"Obiettivo {goal['id']} creato. Ora puoi aggiungere i passi.")
            return True
        if lower in {"mostra obiettivi", "elenca obiettivi", "quali obiettivi ho"}:
            goals = list_goals(active_only=False)
            message = (
                "Non hai obiettivi salvati."
                if not goals
                else "; ".join(
                    f"{g['id']}: {g['title']} ({g['status']}, {sum(1 for s in g.get('steps', []) if s.get('done'))}/{len(g.get('steps', []))} passi)"
                    for g in goals
                )
            )
            self._risposta_locale(message)
            return True
        match = re.fullmatch(r"aggiungi passo\s+(g\d+)\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            goal = add_step(match.group(1).lower(), match.group(2))
            self._risposta_locale("Passo aggiunto." if goal else "Non trovo quell'obiettivo.")
            return True
        match = re.fullmatch(r"completa passo\s+(g\d+)\s+(\d+)", lower)
        if match:
            goal = complete_step(match.group(1), int(match.group(2)))
            self._risposta_locale("Passo completato." if goal else "Obiettivo o numero del passo non valido.")
            return True
        match = re.fullmatch(r"(?:completa|chiudi) obiettivo\s+(g\d+)", lower)
        if match:
            goal = close_goal(match.group(1))
            self._risposta_locale("Obiettivo completato." if goal else "Non trovo quell'obiettivo.")
            return True
        return False

    def processa_domanda(self, domanda):
        domanda_corrente = domanda
        record_user_turn(CORE_RUNTIME, domanda_corrente)
        # CONTROL is resolved before memory, routing or cloud calls.  Muted
        # accepts only the explicit wake word; all other speech is discarded.
        tipo_wake, _ = interpreta_richiamo_jarvis(domanda_corrente)
        if self.attention.state is AttentionState.MUTED:
            if tipo_wake in {"solo", "domanda"}:
                self.attention.wake_from_mute()
                if tipo_wake == "solo":
                    return
                domanda_corrente = interpreta_richiamo_jarvis(domanda_corrente)[1]
            else:
                return
        control = resolve_control_intent(
            domanda_corrente,
            addressed=True,
            conversation_open=self.conversazione_vocale_attiva,
        )
        if control and control.name == "mute":
            self.attention.mute()
            self.conversazione_vocale_attiva = False
            self.forza_ascolto = False
            self.interrompi_ascolto.set()
            CORE_RUNTIME.voice.interrupt()
            CORE_RUNTIME.voice.cancel_pending()
            richiedi_stop_voce()
            self.stato_assistente.emit("standby")
            return
        pending_companion = CORE_RUNTIME.companion.consume_pending_context()
        while domanda_corrente and self.running:
            domanda_corrente = domanda_corrente.strip()
            domanda_con_contesto = contestualizza_risposta_companion(domanda_corrente, pending_companion)
            pending_companion = None

            if get_setting("ai_memory", True):
                learn_explicit(domanda_corrente)

            contesto_operativo = _contesto_operativo_corrente()
            if (
                self.conversazione_vocale_attiva
                and richiesta_fine_conversazione(domanda_corrente)
                and not is_operational_followup(domanda_corrente, contesto_operativo)
            ):
                self.chiudi_conversazione_vocale()
                return

            companion_mode = comando_modalita_companion(domanda_corrente)
            if companion_mode:
                CORE_RUNTIME.companion.set_mode(companion_mode)
                self._risposta_locale(
                    "Modalità focus attiva." if companion_mode == "focus" else "Modalità Companion attiva."
                )
                return

            if self._comando_memoria_o_conferma(domanda_corrente):
                return

            original_user_text = domanda_corrente
            reference = resolve_reference(CORE_RUNTIME, original_user_text)
            if reference.needs_clarification:
                candidates = " o ".join(str(item) for item in reference.alternatives)
                self._risposta_locale(f"Quale intendi: {candidates}?")
                return
            resolved_text = _testo_operativo_risolto(original_user_text, reference)
            domanda_con_contesto = contestualizza_risposta_companion(resolved_text, pending_companion)
            if reference.resolved and reference.reference_type in {"assistant_proposal", "conversational entity/topic"}:
                domanda_con_contesto = (
                    f"Contesto conversazionale rilevante: {reference.value}\n"
                    f"Nuova richiesta dell'utente: {original_user_text}"
                )
                if reference.reference_type == "assistant_proposal":
                    consume_pending_proposal(CORE_RUNTIME)

            self.scheda_corrente_domanda = scheda_per_richiesta(original_user_text)
            self.apri_scheda_signal.emit(self.scheda_corrente_domanda)
            self.trascrizione.emit(original_user_text)
            self.stato_assistente.emit("thinking")

            print("\n======================================")
            print("TU:", original_user_text)
            print("SCHEDA:", self.scheda_corrente_domanda)
            print("======================================")

            cognitive_decision = _prepare_cognitive_turn(
                original_user_text, resolved_text, reference, contesto_operativo
            )
            usa_brain = deve_usare_router_operativo(
                resolved_text, contesto_operativo, cognitive_decision
            )
            print("🧠 Controllo PC:", usa_brain)

            if usa_brain:
                annunci_in_corso = []
                ha_annunciato = False

                def annuncia_azione(
                    nome_tool,
                    argomenti,
                ):
                    # Non annunciare l'azione prima di averla eseguita: un
                    # "sto facendo" prematuro faceva sembrare riusciti tool
                    # che poi fallivano. Lo stato resta visibile nell'HUD; la
                    # voce viene emessa una sola volta, dopo la verifica.
                    _ = nome_tool, argomenti
                    self.stato_modulo.emit("Controllo PC", True)

                try:
                    self.stato_modulo.emit("Controllo PC", True)
                    domanda_router = domanda_con_contesto
                    conferma_operativa = _conferma_breve_operazione_precedente(
                        domanda_corrente, contesto_operativo
                    )
                    explicit_expansion = False
                    try:
                        explicit_expansion = match_expansion_skill(CORE_RUNTIME.skills, domanda_corrente) is not None
                    except (AttributeError, TypeError, ValueError):
                        pass
                    riferito_al_contesto = (not explicit_expansion) and (
                        is_operational_followup(domanda_corrente, contesto_operativo)
                        or bool(
                            re.search(
                                r"\b(?:continua|poi|ora|quello|quella|questo|questa|terzo|secondo|primo|"
                                r"candela|candele|timeframe|grafico|video|risultato)\b",
                                domanda_corrente,
                                flags=re.IGNORECASE,
                            )
                        )
                    )
                    if contesto_operativo and deve_allegare_contesto_operazione(riferito_al_contesto):
                        istruzione_followup = (
                            "\nLa risposta dell'utente conferma il seguito operativo precedente. "
                            "Continua ora l'operazione usando i tool necessari e restituisci il risultato reale; "
                            "non limitarti a dire che procederai.\n"
                            if conferma_operativa else "\n"
                        )
                        domanda_router = (
                            "Contesto strutturato dell'ultima operazione sul PC, ancora fresco e verificato: "
                            f"{json.dumps(contesto_operativo, ensure_ascii=False)}\n"
                            f"{istruzione_followup}"
                        f"Nuova richiesta dell'utente: {resolved_text}"
                        )
                    followup_result = _esegui_followup_operativo(domanda_corrente, contesto_operativo)
                    if followup_result is not None:
                        comando, risposta_comando, minimizza = followup_result
                    else:
                        if richiede_controllo_visivo(domanda_router):
                            # Libera lo schermo prima che il ciclo visivo acquisisca
                            # il primo frame. L'orb resta disponibile per ripristinare.
                            self.minimizza_hud.emit()
                            time.sleep(0.4)
                        if get_setting("async_engine_enabled", True):
                            self.active_task_id, operation_future = ASYNC_ENGINE.submit(
                                "ai",
                                interpreta_comando,
                                domanda_router,
                                on_before_action=annuncia_azione,
                                cognitive_decision=cognitive_decision,
                                priority=2,
                                timeout=900,
                                label="missione-operativa",
                            )
                            while self.running and not operation_future.done():
                                time.sleep(0.025)
                            if not self.running:
                                ASYNC_ENGINE.cancel(self.active_task_id)
                                return
                            comando, risposta_comando, minimizza = operation_future.result()
                            self.active_task_id = None
                        else:
                            comando, risposta_comando, minimizza = interpreta_comando(
                                domanda_router,
                                on_before_action=annuncia_azione,
                                cognitive_decision=cognitive_decision,
                            )
                except Exception as exc:
                    print("\n[ERROR] ERRORE BRAIN:", redact(repr(exc)))
                    self.stato_modulo.emit("Controllo PC", False)
                    comando, risposta_comando, minimizza = False, None, False

                if comando:
                    for thread in annunci_in_corso:
                        thread.join(timeout=8.0)
                    self.ultimo_contesto_pc = (
                        f"Richiesta: {domanda_corrente}. " f"Esito: {risposta_comando or 'operazione completata'}"
                    )
                    aggiungi_messaggio("user", domanda_corrente)
                    if risposta_comando:
                        update_context(request=domanda_corrente, result=risposta_comando)
                        aggiungi_messaggio("assistant", risposta_comando)
                    if risposta_comando:
                        rendered = self._presenta_risultato(
                            risposta_comando,
                            request=domanda_corrente,
                            success=True,
                        )
                        finale_breve = len(risposta_comando) < 120 and not any(
                            parola in risposta_comando.lower()
                            for parola in ("errore", "non posso", "non ho", "conferma", "attenzione")
                        )
                        nuova = None if ha_annunciato and finale_breve else self.parla_controllato(
                            rendered.spoken_response,
                            already_rendered=True,
                        )
                        if nuova == "__JARVIS__":
                            self.forza_ascolto = True
                            self.stato_assistente.emit("listening")
                            return
                        if nuova:
                            domanda_corrente = nuova
                            continue
                    if minimizza:
                        self.minimizza_hud.emit()
                    self.stato_assistente.emit("listening" if self.conversazione_vocale_attiva else "standby")
                    return

            nuova_domanda = self.risposta_ai(domanda_con_contesto, cognitive_decision)
            if nuova_domanda == "__JARVIS__":
                self.forza_ascolto = True
                self.stato_assistente.emit("listening")
                return
            if nuova_domanda:
                domanda_corrente = nuova_domanda
                continue
            return

    def avvia_sessione(self):
        self.jarvis_avviato = True
        self.sessione_attiva = True
        self.attivato.emit()
        self.stato_assistente.emit("standby")

    def prendi_testo_coda(self):
        try:
            testo = domande_testo.get_nowait()
        except queue.Empty:
            return None
        if testo is None:
            return None
        return testo.strip()

    def _voice_started(self):
        self.stato_assistente.emit("user")

    def _voice_ended(self):
        self.stato_assistente.emit("thinking")

    def _owner_speaker_from_audio(self, pcm16, sample_rate=16000):
        """Resolve speaker identity from the just-captured, volatile phrase."""
        if not bool(get_setting("biometric_identity_enabled", True)):
            return None
        if not pcm16 or len(pcm16) < int(sample_rate * 0.45) * 2:
            return None
        try:
            import numpy as np

            samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
            status = IDENTITY.status()
            if not status.get("voice_profiles"):
                return None
            result = IDENTITY.recognize_voice_samples(
                [samples],
                sample_rate=sample_rate,
                threshold=float(get_setting("voice_match_threshold", 0.88)),
            )
            if not result.get("matched") or not result.get("name"):
                return None
            owner_name = str(get_setting("ceo_profile_name", "")).strip().casefold()
            return str(result["name"]).strip().casefold() == owner_name if owner_name else None
        except (RuntimeError, ValueError, OSError, TypeError):
            return None

    def _capture_ambient_speaker(self, pcm16):
        self._ambient_speaker = self._owner_speaker_from_audio(pcm16)

    def ciclo_conversazione_vocale(self, richiesta_iniziale=None):
        # La console Windows può usare CP1252: l'emoji rende il ciclo
        # inutilizzabile prima ancora di entrare nel loop vocale.
        print("\n[OK] CONVERSAZIONE CONTINUA ATTIVA")
        print('Di\' "ok", "okay" o "va bene" per uscire.')
        self.conversazione_vocale_attiva = True
        self.richiesta_fine = False
        self.attention.enter_conversation()

        if richiesta_iniziale:
            try:
                self._cycle_transition("STT_DONE")
                self._cycle_transition("PROCESSING")
                self.processa_domanda(richiesta_iniziale)
            except Exception as exc:
                self._recover_cycle_exception(exc)
            self._finish_cycle()

        while self.running and self.conversazione_vocale_attiva:
            if self._active_cycle_id is None:
                self._begin_cycle()
            if self.forza_ascolto:
                self.forza_ascolto = False
                print("\n[VOICE] Pronto per la nuova domanda")

            domanda_testo = self.prendi_testo_coda()
            if domanda_testo:
                try:
                    self._cycle_transition("STT_DONE")
                    self._cycle_transition("PROCESSING")
                    self.processa_domanda(domanda_testo)
                except Exception as exc:
                    self._recover_cycle_exception(exc)
                self._finish_cycle()
                if self.richiesta_fine:
                    break
                continue

            self.interrompi_ascolto.clear()
            self.stato_assistente.emit("listening")
            self._cycle_transition("LISTENING")
            print("\n[LISTENING] In ascolto...")
            stt_started = time.perf_counter()
            domanda = ascolta(
                timeout_inizio=None,
                stop_event=self.interrompi_ascolto,
                on_voice_start=self._voice_started,
                on_voice_end=self._voice_ended,
                on_partial=lambda text: CORE_RUNTIME.events.publish("voice.partial", {"text": text}, source="stt"),
                on_interrupt=lambda text: self.emergency_stop(),
            )
            try:
                from performance_metrics import record_tool

                record_tool("stt", domanda is not None, int((time.perf_counter() - stt_started) * 1000))
            except OSError:
                pass
            self.stato_modulo.emit("Microfono", domanda is not None or self.running)

            if not domanda:
                domanda_testo = self.prendi_testo_coda()
                if domanda_testo:
                    self._cycle_transition("STT_DONE")
                    try:
                        self._cycle_transition("PROCESSING")
                        self.processa_domanda(domanda_testo)
                    except Exception as exc:
                        self._recover_cycle_exception(exc)
                    self._finish_cycle()
                    if self.richiesta_fine:
                        break
                continue

            self._cycle_transition("STT_DONE")
            try:
                self._cycle_transition("PROCESSING")
                self.processa_domanda(domanda)
            except Exception as exc:
                self._recover_cycle_exception(exc)
            self._finish_cycle()
            if self.richiesta_fine:
                break
            # La sessione resta aperta finché l'utente non pronuncia una
            # frase di chiusura esplicita. Al termine torna alla sola wake word.

        self.conversazione_vocale_attiva = False
        self.richiesta_fine = False
        self.forza_ascolto = False
        self.attention.disengage()
        self.stato_assistente.emit("standby")
        print('\n[STANDBY] Di\' "Jarvis" per riprendere.')

    def run(self):
        _load_runtime_components()
        self.jarvis_avviato = True
        self.sessione_attiva = True
        saluto = "Sistema pronto. Come posso aiutarti oggi?"
        if _claim_startup_greeting():
            self.risposta.emit(saluto)
            self.parla_controllato(saluto, interrompibile=False)
        else:
            print("\n[STARTUP] Saluto iniziale duplicato ignorato.")
        self.risposta.emit("Standby. Pronuncia JARVIS per iniziare.")
        self.stato_assistente.emit("standby")
        standby_error_count = 0
        last_standby_error = None
        last_standby_report = 0.0

        while self.running and self.jarvis_avviato:
            if self.forza_ascolto:
                self.forza_ascolto = False
                self._begin_cycle(wake_detected=True)
                self.ciclo_conversazione_vocale()
                continue

            domanda_pendente = self.prendi_testo_coda()
            if domanda_pendente:
                self.processa_domanda(domanda_pendente)
                continue

            # Optional always-listening standby: STT remains local-only until
            # selective attention has enough evidence to address JARVIS.
            selective = bool(get_setting("continuous_listening", True)) and not bool(
                get_setting("wake_word_only_standby", True)
            ) and self.attention.state is not AttentionState.MUTED
            if selective:
                self.stato_assistente.emit("standby")
                self._ambient_speaker = None
                try:
                    ambient = ascolta(
                        timeout_inizio=3.0,
                        allow_cloud=False,
                        on_audio=self._capture_ambient_speaker,
                    )
                except Exception as exc:
                    print("\n[WARN] selective listening degradato:", redact(repr(exc)))
                    ambient = None
                if ambient:
                    wake_kind, wake_request = interpreta_richiamo_jarvis(ambient)
                    has_context = bool(self.conversazione_vocale_attiva or self.ultimo_contesto_pc)
                    attention = self.attention.accepts(
                        ambient,
                        conversation_open=self.conversazione_vocale_attiva,
                        owner_speaker=self._ambient_speaker,
                        has_context=has_context,
                        activity_relevant=False,
                    )
                    CORE_RUNTIME.events.publish(
                        "voice.attention_decision",
                        {"addressed": attention.addressed, "confidence": round(attention.confidence, 3),
                         "reasons": attention.reasons, "state": self.attention.state.value},
                        source="voice_attention",
                    )
                    if attention.addressed:
                        self.attention.engage()
                        if wake_kind == "solo":
                            self._begin_cycle(wake_detected=True)
                            self.ciclo_conversazione_vocale()
                        elif wake_kind == "domanda":
                            self._begin_cycle(wake_detected=True)
                            self.ciclo_conversazione_vocale(richiesta_iniziale=wake_request)
                        else:
                            self._begin_cycle()
                            try:
                                self.processa_domanda(ambient)
                            finally:
                                self._finish_cycle()
                continue

            self.stato_assistente.emit("standby")
            try:
                self.stato_modulo.emit("Wake Word", True)
                wake_started = time.perf_counter()
                evento = aspetta_jarvis()
                standby_error_count = 0
                try:
                    from performance_metrics import record_tool

                    record_tool("wake_word", evento == "jarvis", int((time.perf_counter() - wake_started) * 1000))
                except OSError:
                    pass
            except Exception as exc:
                standby_error_count += 1
                error_text = redact(repr(exc))
                now = time.monotonic()
                if error_text != last_standby_error or now - last_standby_report >= 30.0:
                    print("\n[ERROR] ERRORE STANDBY:", error_text)
                    last_standby_error = error_text
                    last_standby_report = now
                self.stato_modulo.emit("Wake Word", False)
                delay = min(5.0, 0.5 * (2 ** min(standby_error_count - 1, 4)))
                deadline = time.monotonic() + delay
                while self.running and time.monotonic() < deadline:
                    time.sleep(max(0.0, min(0.1, deadline - time.monotonic())))
                continue

            if evento == "stop":
                break
            if evento == "tastiera":
                self.mostra_hud.emit()
                continue
            if evento == "testo":
                domanda = self.prendi_testo_coda()
                if domanda:
                    self.processa_domanda(domanda)
                continue
            if evento == "jarvis":
                self.attention.wake_from_mute()
                self._begin_cycle(wake_detected=True)
                wake_phrase = recupera_frase_wake() if recupera_frase_wake else None
                wake_kind, wake_request = interpreta_richiamo_jarvis(wake_phrase or "Jarvis")
                self.ciclo_conversazione_vocale(
                    richiesta_iniziale=wake_request if wake_kind == "domanda" else None
                )
                continue

        self.arresto.emit()


def main():
    install_crash_reporting()
    if "--broker" in sys.argv:
        from jarvis_broker.server import serve_forever

        address = None
        tcp_port = None
        if "--broker-address" in sys.argv:
            index = sys.argv.index("--broker-address")
            if index + 1 < len(sys.argv):
                address = sys.argv[index + 1]
        if "--broker-tcp-port" in sys.argv:
            index = sys.argv.index("--broker-tcp-port")
            if index + 1 < len(sys.argv):
                tcp_port = int(sys.argv[index + 1])
        serve_forever(address or r"\\.\pipe\JarvisPrivilegedBroker", tcp_port=tcp_port)
        return 0
    # Qt must not receive the application-specific flag. RuntimeMode already
    # captured it during core initialization.
    qt_argv = [value for value in sys.argv if value != "--safe"]
    app = QApplication(qt_argv)
    app.setQuitOnLastWindowClosed(False)

    # La schermata di preload è una superficie autonoma e opaca; l'HUD resta
    # nascosto fino al completamento per evitare doppie Orb o flicker.
    from hud import JarvisHUD
    from hud_ui import StartupView

    hud = JarvisHUD()
    app.aboutToQuit.connect(_shutdown_runtime)
    hud.setWindowOpacity(1.0)
    app.processEvents()
    startup = StartupView()
    startup.setAttribute(Qt.WA_TranslucentBackground, True)
    startup.minimize_requested.connect(startup.showMinimized)
    startup.close_requested.connect(startup.close)
    screen = app.primaryScreen()
    if screen is not None:
        startup.setGeometry(screen.availableGeometry())
    startup.showFullScreen()
    app.processEvents()

    preload_state = {"label": "Preparazione sistemi essenziali", "progress": 0.0, "result": None}
    preload_lock = threading.Lock()

    def set_preload_status(label, progress=None):
        with preload_lock:
            preload_state["label"] = label
            if progress is not None:
                preload_state["progress"] = float(progress)

    def run_preload():
        result = preload_startup_components(set_preload_status)
        with preload_lock:
            preload_state["result"] = result

    preload_thread = threading.Thread(target=run_preload, daemon=True, name="jarvis-startup-preloader")
    preload_thread.start()

    while preload_thread.is_alive():
        with preload_lock:
            label = preload_state["label"]
            progress = preload_state["progress"]
        startup.set_status(label)
        startup.set_progress(progress)
        app.processEvents()
        preload_thread.join(timeout=0.02)
    with preload_lock:
        preload_result = preload_state["result"] or {
            "ready": False,
            "errors": [{"stage": "preload", "error": "unknown"}],
        }
    if preload_result["errors"]:
        CORE_RUNTIME.logger.warning("startup.preload_degraded", extra={"errors": preload_result["errors"]})

    startup.set_status("SISTEMA PRONTO" if preload_result.get("ready") else "AVVIO DEGRADATO")
    startup.set_progress(100.0)
    app.processEvents()

    startup.set_status("CARICAMENTO HUD OPERATIVO")
    app.processEvents()
    # Renderizza l'HUD solo dopo il preavvio: chiudi la startup prima di
    # mostrare la Home per mantenere una singola superficie visibile.
    startup.close()
    app.processEvents()
    hud.show_initial()
    hud.raise_()
    app.processEvents()
    worker = JarvisWorker()
    _reset_startup_greeting_gate()

    # Console: copia stdout/stderr nella scheda CONSOLE senza perdere il terminale.
    stdout_proxy = ConsoleStream(sys.__stdout__)
    stderr_proxy = ConsoleStream(sys.__stderr__)
    stdout_proxy.testo.connect(hud.append_console)
    stderr_proxy.testo.connect(hud.append_console)
    sys.stdout = stdout_proxy
    sys.stderr = stderr_proxy

    worker.attivato.connect(hud.attiva)
    worker.mostra_hud.connect(hud.attiva)
    worker.minimizza_hud.connect(hud.showMinimized)
    worker.trascrizione.connect(hud.aggiorna_trascrizione)
    worker.risposta.connect(hud.aggiorna_risposta)
    worker.stato_assistente.connect(hud.set_stato_assistente)
    worker.apri_scheda_signal.connect(hud.apri_scheda)
    worker.market_news_signal.connect(hud.aggiorna_news_mercati)
    worker.stato_modulo.connect(hud.set_modulo)
    worker.richiedi_pin.connect(hud.imposta_pin_sicurezza)
    worker.toggle_tastiera_compatta.connect(hud.toggle_compact_keyboard)
    hud.messaggio_inviato.connect(worker.ricevi_testo)
    hud.routine_comando.connect(worker.ricevi_testo)
    hud.event_comando.connect(worker.ricevi_testo)
    _automation_unsubscribe = CORE_RUNTIME.events.subscribe(
        "automation.command",
        lambda event: hud.event_comando.emit(str(event.payload.get("command") or "")),
    )
    hud.chiudi_programma.connect(worker.stop)
    hud.chiudi_programma.connect(app.quit)
    worker.arresto.connect(app.quit)

    keyboard.add_hotkey("ctrl+alt+j", worker.attiva_da_tastiera)
    keyboard.add_hotkey("ctrl+alt+shift+j", worker.emergency_stop, suppress=True)
    keyboard.add_hotkey("ctrl+alt+q", worker.stop)
    keyboard.add_hotkey("esc", worker.minimizza_da_tastiera)
    keyboard.add_hotkey("ctrl+m", worker.tastiera_compatta_da_hotkey)

    worker.start()

    print("\n======================================")
    print("            JARVIS ONLINE")
    print("======================================")
    print('Standby: pronuncia "Jarvis" per iniziare')
    print('Interrompi risposta: "Jarvis"')
    print('Fine conversazione: "Va bene / Okai / Ok / Okay / Stop"')
    print("CTRL + ALT + J = mostra HUD")
    print("ESC = minimizza")
    print("CTRL + M = tastiera compatta quando minimizzato")
    print("CTRL + ALT + Q = arresta")
    print("======================================\n")

    codice = app.exec()

    try:
        keyboard.unhook_all_hotkeys()
    except Exception:
        pass
    try:
        hud.shutdown_services()
    except Exception:
        pass
    worker.stop()
    worker.wait(2000)
    ASYNC_ENGINE.shutdown()
    _shutdown_runtime()
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    sys.exit(codice)


if __name__ == "__main__":
    main()
