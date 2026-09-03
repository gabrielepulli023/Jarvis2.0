import os
import re
import threading
import time
from datetime import datetime

from dotenv import load_dotenv
from llm_gateway import openai_client
from settings_store import get_setting
from personal_memory import context as memory_context, recent_episodes, record_episode
from jarvis_memory import ContextBuilder,MemoryStore
from app_paths import data_path
from model_selector import reasoning_options
from provider_router import decide_route, fallback_routes, stream_non_openai
from performance_metrics import record_tool
from decision_layer import decide as decide_intent, router_guidance
from jarvis_core.logging import redact
from jarvis_core.runtime import RUNTIME as CORE_RUNTIME
from jarvis_core.reference_resolution import compact_current_context, record_assistant_turn, record_user_turn
from jarvis_integrations.mem0_backend import conversational_context as mem0_context, remember_conversation_turn

_ranked_memory = ContextBuilder(MemoryStore(data_path("jarvis_memory.db")))


# ============================================================
# CONFIGURAZIONE
# ============================================================

load_dotenv()


client = openai_client(profile="interactive")


# ============================================================
# MODELLO
# ============================================================

MODELLO = "gpt-5.6-luna"


# ============================================================
# MEMORIA CONVERSAZIONE
# ============================================================

_lock_memoria = threading.Lock()


cronologia = []


MAX_MESSAGGI = 24


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
Sei JARVIS, un assistente personale intelligente installato
sul computer Windows dell'utente.

JARVIS include un sottosistema operativo locale separato che controlla
realmente Windows, programmi, browser, mouse, tastiera e file. Non affermare
che JARVIS non possa controllare il computer o non abbia accesso a questi
strumenti. Gli ordini operativi vengono intercettati ed eseguiti dal router
locale; nelle domande sulle capacità descrivi questa integrazione correttamente.

Parla sempre in italiano.

Mantieni il contesto della conversazione.

Se l'utente fa una domanda collegata al messaggio precedente,
come:

perché?
come mai?
e poi?
quale?
quello di prima?
cosa intendi?
e invece quello?
quindi?

devi capire automaticamente il riferimento usando ciò che è
stato detto nei turni precedenti.

Hai accesso alla ricerca web.

Usa la ricerca web quando la risposta può dipendere da
informazioni aggiornate o recenti.

Devi usare il web soprattutto per:

ultime notizie
mercati finanziari
Forex
EUR/USD
azioni
indici
criptovalute
prezzi attuali
notizie economiche
politica attuale
geopolitica
risultati sportivi
meteo
aziende
prodotti attuali
eventi recenti
persone pubbliche
informazioni che contengono riferimenti come:
oggi
ieri
adesso
attualmente
ultime
recente
live

Quando parli di mercati finanziari:

verifica le informazioni sul web;
distingui fatti da interpretazioni;
indica date e orari quando sono importanti;
spiega quali notizie possono influenzare il mercato;
non inventare prezzi o eventi;
se i dati non sono sufficientemente recenti, dillo chiaramente.

Le risposte devono essere naturali e adatte a essere pronunciate
ad alta voce.

Evita risposte inutilmente lunghe, a meno che l'utente non chieda
una spiegazione dettagliata.

Non usare URL completi nella risposta parlata.
""".strip()


# ============================================================
# REGOLE DI FORMATTAZIONE
# ============================================================

FORMATTING_RULES = """
Non usare Markdown.

Non usare asterischi.

Non usare doppio asterisco.

Non usare hashtag.

Non usare backtick.

Non usare tabelle.

Non usare titoli Markdown.

Non usare trattini o pallini per creare elenchi.

Non usare simboli decorativi.

Scrivi sempre in testo semplice.

La risposta deve essere pensata principalmente per essere
pronunciata ad alta voce da un sintetizzatore vocale.

Non scrivere:

**S&P 500:** 7.709 punti, **-0,18%**

Scrivi invece:

S&P 500: 7.709 punti, in calo dello 0,18 percento.

Non scrivere:

- S&P 500
- Nasdaq
- Dow Jones

Scrivi invece:

L'S&P 500 è...
Il Nasdaq è...
Il Dow Jones è...

Quando devi presentare più elementi, usa frasi brevi e naturali.

Per percentuali positive o negative, quando possibile usa
espressioni naturali come:

in rialzo dello 0,5 percento
in calo dello 0,3 percento

invece di leggere simboli come +0,5% o -0,3%.
""".strip()


# ============================================================
# LIMITA CRONOLOGIA
# ============================================================

def limita_cronologia():

    global cronologia


    if len(cronologia) > MAX_MESSAGGI:

        cronologia = cronologia[
            -MAX_MESSAGGI:
        ]


# ============================================================
# RESET CONVERSAZIONE
# ============================================================

def reset_conversazione():

    global cronologia


    with _lock_memoria:

        cronologia = []


    print()
    print(
        "🧠 Conversazione resettata"
    )


# ============================================================
# AGGIUNGI MESSAGGIO
# ============================================================

def aggiungi_messaggio(
    ruolo,
    testo
):

    if not testo or get_setting("privacy_mode", False):

        return


    with _lock_memoria:

        cronologia.append(
            {
                "role": ruolo,
                "content": testo
            }
        )


        limita_cronologia()


# ============================================================
# COSTRUISCE INPUT CONVERSAZIONE
# ============================================================

def costruisci_input():

    if get_setting("privacy_mode", False):
        return []

    with _lock_memoria:

        return list(
            cronologia
        )


# ============================================================
# PULIZIA TESTO
# ============================================================

def pulisci_testo_voce(
    testo
):

    if not testo:

        return ""


    # ========================================================
    # MARKDOWN
    # ========================================================

    testo = testo.replace(
        "**",
        ""
    )

    testo = testo.replace(
        "__",
        ""
    )

    testo = testo.replace(
        "`",
        ""
    )

    testo = testo.replace(
        "#",
        ""
    )


    # ========================================================
    # ELENCHI
    # ========================================================

    testo = re.sub(
        r"(?m)^\s*[-•]\s*",
        "",
        testo
    )


    testo = re.sub(
        r"(?m)^\s*\d+[\.\)]\s*",
        "",
        testo
    )


    # ========================================================
    # LINK MARKDOWN
    #
    # [testo](url) -> testo
    # ========================================================

    testo = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        testo
    )


    # ========================================================
    # PERCENTUALI NEGATIVE
    #
    # -0,18% -> in calo dello 0,18 percento
    # ========================================================

    testo = re.sub(
        r"(?<!\w)-\s*(\d+(?:[.,]\d+)?)\s*%",
        r"in calo dello \1 percento",
        testo
    )


    # ========================================================
    # PERCENTUALI POSITIVE
    #
    # +0,18% -> in rialzo dello 0,18 percento
    # ========================================================

    testo = re.sub(
        r"\+\s*(\d+(?:[.,]\d+)?)\s*%",
        r"in rialzo dello \1 percento",
        testo
    )


    # ========================================================
    # PERCENTUALI NORMALI
    #
    # 40% -> 40 percento
    # ========================================================

    testo = re.sub(
        r"(\d+(?:[.,]\d+)?)\s*%",
        r"\1 percento",
        testo
    )


    # ========================================================
    # SPAZI MULTIPLI
    # ========================================================

    testo = re.sub(
        r"[ \t]+",
        " ",
        testo
    )


    # ========================================================
    # TROPPE RIGHE VUOTE
    # ========================================================

    testo = re.sub(
        r"\n{3,}",
        "\n\n",
        testo
    )


    return testo.strip()


# ============================================================
# CONTROLLA SE BUFFER HA UNA FRASE PRONUNCIABILE
# ============================================================

def frase_pronta(
    buffer
):

    if not buffer:

        return False


    # Frase conclusa normalmente
    if any(
        simbolo in buffer
        for simbolo in [
            ".",
            "!",
            "?"
        ]
    ):

        return True


    # Evita di aspettare troppo se il modello
    # genera una frase molto lunga senza punteggiatura.
    if len(buffer) >= 120:

        return True


    return False


# ============================================================
# CHIEDI A JARVIS
# ============================================================

def _diagnostic_mode_enabled():
    return str(os.getenv("JARVIS_DIAGNOSTIC_MODE", "")).strip().lower() in {"1", "true", "yes", "on"}


def chiedi_jarvis(domanda, cognitive_decision=None):

    if not domanda:

        return

    if _diagnostic_mode_enabled():
        response = openai_client(profile="interactive").responses.create(
            model=str(get_setting("ai_model", MODELLO)),
            input=str(domanda),
            text={"verbosity": str(get_setting("ai_verbosity", "low"))},
        )
        text = getattr(response, "output_text", "") or ""
        if not text:
            for item in getattr(response, "output", []) or []:
                if getattr(item, "type", "") == "message":
                    for content in getattr(item, "content", []) or []:
                        if getattr(content, "type", "") == "output_text":
                            text = getattr(content, "text", "") or ""
                            break
        cleaned = pulisci_testo_voce(text).strip()
        if cleaned:
            yield cleaned
        return

    if not bool(get_setting("ai_memory", True)):
        reset_conversazione()


    # ========================================================
    # MEMORIZZA DOMANDA
    # ========================================================

    aggiungi_messaggio(
        "user",
        domanda
    )
    record_user_turn(CORE_RUNTIME, domanda)


    # ========================================================
    # DATA E ORA ATTUALI
    # ========================================================

    ora = datetime.now().astimezone()


    contesto_temporale = (
        "\n\n"
        +
        "Data e ora locale attuale: "
        +
        ora.strftime(
            "%d/%m/%Y %H:%M %Z"
        )
        +
        "."
    )


    # ========================================================
    # ISTRUZIONI COMPLETE
    # ========================================================

    instructions = (
        SYSTEM_PROMPT
        +
        "\n\n"
        +
        FORMATTING_RULES
        +
        contesto_temporale
    )
    if cognitive_decision is None:
        cognitive_decision = decide_intent(domanda)
    instructions += "\n\n" + router_guidance(cognitive_decision)
    compact_context = compact_current_context(CORE_RUNTIME)
    if compact_context:
        instructions += "\n\nContesto immediato canonico (volatile):\n" + compact_context
    memories = memory_context()
    if memories:
        instructions += "\n\nMemoria personale approvata dall'utente:\n" + memories
    ranked_memories = _ranked_memory.render(str(domanda)) if get_setting("ai_memory", True) else ""
    if ranked_memories:
        instructions += "\n\nMemoria pertinente selezionata automaticamente:\n" + ranked_memories
    episodes = recent_episodes(3) if get_setting("ai_memory", True) else []
    if episodes:
        instructions += "\n\nEpisodi recenti utili al contesto:\n" + "\n".join(
            f"Utente: {e['user_text']}\nJARVIS: {e['assistant_text']}" for e in episodes
        )
    external_memories = mem0_context(str(domanda))
    if external_memories:
        instructions += "\n\nMemoria Mem0 pertinente (secondaria):\n" + external_memories


    # ========================================================
    # INPUT CON CONTESTO
    # ========================================================

    input_conversazione = costruisci_input()


    # ========================================================
    # RISPOSTA
    # ========================================================

    risposta_completa = ""

    buffer_voce = ""


    try:
        llm_started=time.perf_counter();first_token_recorded=False

        print()
        print(
            "🌐 JARVIS AI ONLINE"
        )


        # Il provider e' scelto per tipo di lavoro. I provider alternativi
        # ricevono solo la conversazione, mai gli strumenti operativi/web.
        decision = decide_route(domanda, cognitive_decision=cognitive_decision)
        if decision.provider != "openai":
            provider_error = None
            candidates=[decision,*fallback_routes(decision)]
            for candidate in candidates:
                if candidate.provider=="openai":decision=candidate;break
                received=""
                try:
                    for delta in stream_non_openai(candidate,instructions,input_conversazione):
                        if not first_token_recorded:
                            record_tool("llm_first_token",True,int((time.perf_counter()-llm_started)*1000));first_token_recorded=True
                        received+=delta;risposta_completa+=delta;buffer_voce+=delta
                        if frase_pronta(buffer_voce):
                            frase=pulisci_testo_voce(buffer_voce)
                            if frase:yield frase
                            buffer_voce=""
                    decision=candidate
                    if received:break
                except Exception as exc:
                    provider_error=exc
                    if received:break
                    risposta_completa="";buffer_voce=""
            if not risposta_completa and decision.provider != "openai":
                raise RuntimeError("Nessun provider AI configurato e raggiungibile.") from provider_error
            if risposta_completa:
                if buffer_voce.strip():
                    frase = pulisci_testo_voce(buffer_voce)
                    if frase:
                        yield frase
                return

        # ====================================================
        # RESPONSES API + WEB SEARCH
        # ====================================================

        effort = "low" if any(x in str(domanda).lower() for x in ("analizza", "pianifica", "confronta", "risolvi", "strategia", "progetto")) else "minimal"
        model = decision.model
        web_tools = [
            {
                "type": "web_search",
                "search_context_size": "medium",
                "user_location": {
                    "type": "approximate",
                    "country": "IT",
                    "timezone": "Europe/Rome"
                }
            }
        ]
        request = dict(model=model, instructions=instructions, input=input_conversazione,
            text={
                "verbosity": str(get_setting("ai_verbosity", "low"))
            },
            tools=web_tools,

            tool_choice="auto", stream=True)
        reasoning = reasoning_options(model, effort, tools=web_tools)
        if reasoning is not None:
            request["reasoning"] = reasoning
        stream = client.responses.create(**request)


        # ====================================================
        # STREAM
        # ====================================================

        for evento in stream:


            tipo = getattr(
                evento,
                "type",
                ""
            )


            # =================================================
            # WEB SEARCH INIZIATA
            # =================================================

            if tipo == "response.web_search_call.in_progress":

                print()
                print(
                    "🌐 Ricerca sul web..."
                )


            # =================================================
            # WEB SEARCH ATTIVA
            # =================================================

            elif tipo == "response.web_search_call.searching":

                print(
                    "🔎 Cerco informazioni aggiornate..."
                )


            # =================================================
            # WEB SEARCH COMPLETATA
            # =================================================

            elif tipo == "response.web_search_call.completed":

                print(
                    "✅ Ricerca web completata"
                )


            # =================================================
            # TESTO IN STREAMING
            # =================================================

            elif tipo == "response.output_text.delta":


                testo = getattr(
                    evento,
                    "delta",
                    ""
                )


                if not testo:

                    continue

                if not first_token_recorded:
                    record_tool("llm_first_token",True,int((time.perf_counter()-llm_started)*1000));first_token_recorded=True


                # =============================================
                # RISPOSTA COMPLETA ORIGINALE
                # =============================================

                risposta_completa += testo


                # =============================================
                # BUFFER VOCE
                # =============================================

                buffer_voce += testo


                # =============================================
                # TERMINALE PULITO
                # =============================================

                testo_terminale = pulisci_testo_voce(
                    testo
                )


                if testo_terminale:

                    print(
                        testo_terminale,
                        end="",
                        flush=True
                    )


                # =============================================
                # MANDA FRASE A ISABELLA
                # =============================================

                if frase_pronta(
                    buffer_voce
                ):


                    frase = pulisci_testo_voce(
                        buffer_voce
                    )


                    if frase:

                        yield frase


                    buffer_voce = ""


        # ====================================================
        # PEZZO FINALE
        # ====================================================

        if buffer_voce.strip():


            frase_finale = pulisci_testo_voce(
                buffer_voce
            )


            if frase_finale:

                yield frase_finale

        if not risposta_completa.strip():
            # Alcuni gateway possono chiudere uno stream vuoto senza
            # sollevare eccezioni. Non lasciare il percorso UI/voce senza
            # alcun evento: comunica il degrado in modo esplicito.
            yield "Non ho ricevuto una risposta dal motore AI. Riprova tra poco."


    except Exception as errore:

        print()
        print()
        print(
            "❌ ERRORE AI / WEB:"
        )

        print(redact(repr(errore)))


        raise


    finally:

        # ====================================================
        # MEMORIZZA RISPOSTA PULITA
        # ====================================================

        if risposta_completa.strip():


            risposta_memoria = pulisci_testo_voce(
                risposta_completa
            )


            aggiungi_messaggio(
                "assistant",
                risposta_memoria
            )
            record_assistant_turn(CORE_RUNTIME, risposta_memoria)
            if get_setting("ai_memory", True):
                record_episode(domanda, risposta_memoria)
                _ranked_memory.store.remember(
                    f"Utente: {domanda}\nAssistente: {risposta_memoria}",
                    kind="episodic", source="conversation", importance=.5,
                )
                remember_conversation_turn(domanda, risposta_memoria)
