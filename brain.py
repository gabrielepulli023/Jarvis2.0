import json
import re
import time

from dotenv import load_dotenv
from llm_gateway import openai_client
from settings_store import get_setting
from action_guard import cancel as cancel_action_guard
from action_guard import pending as pending_action_guard, risk_level, stage, take
from audit_log import record as audit_record
from productivity import crea_bozza_email, crea_evento_calendario
from vision import analizza_schermo, individua_elemento
from capability_registry import capability_report
from permission_manager import profile as permission_profile
from permission_manager import verify_pin
from script_engine import list_scripts, run_script, save_script
from system_extended import aggiorna_programma, connessioni_rete, crea_archivio_zip, estrai_archivio_zip, info_rete, installa_programma, programmi_installati, servizi_windows, spazio_cartella, stato_wifi
from event_automation import add_rule, list_rules, set_rule_enabled, delete_rule
from agent_state import add_step as agent_add_step, begin as agent_begin, finish as agent_finish, recent as recent_jobs, latest_resumable, get_job as get_agent_job, add_review as agent_add_review
from cognitive_core import plan_mission, review_mission
from decision_layer import decide, router_guidance
from automation_intelligence import policy_guidance
from mission_control import verified_success, verify_result
from recovery_manager import restore_last
from project_builder import create_project, list_projects, restore_project_version
from visual_agent import visual_task
from jarvis_core.reference_resolution import record_operational_action
from project_quality import inspect_project, test_project
from trading_analyst import analyze_trading_chart
from desktop_intelligence import inspect_ui, ui_focus, ui_invoke, ui_set_value
from performance_metrics import record_tool as record_tool_metric, report as performance_report
from chrome_bridge import chrome_action, chrome_snapshot
from adaptive_learning import approve_procedure, learned_report, simulate_procedure
from continuous_improvement import analyze_evaluations
from jarvis_core.logging import redact
from simulation_engine import simulate_action
from async_engine import ENGINE as ASYNC_ENGINE, report as async_report
from result_cache import get as cache_get, put as cache_put, clear as cache_clear
from model_selector import reasoning_options, select_model
from jarvis_core.runtime import RUNTIME as CORE_RUNTIME
from jarvis_expansion.routing import expansion_skill_names, litellm_arguments, match_expansion_skill, qdrant_arguments, secrets_arguments
from presentation_tools import crea_presentazione
from jarvis_integrations.brain_tools import (
    browser_agent_task,
    delegate_agent_task,
    integration_status,
    mem0_remember,
    mem0_search,
    ufo_agent_task,
    ui_tars_agent_task,
)


# ============================================================
# TOOL GIÀ ESISTENTI
# ============================================================

from tools import (
    apri_programma,
    chiudi_programma,
    apri_sito,
    cerca_google,
    imposta_volume,
    modifica_volume,
    imposta_muto
)


# ============================================================
# NUOVO MODULO COMPUTER
# ============================================================

from computer import (
    apri_percorso,
    apri_percorso_con_programma,
    crea_cartella,
    crea_file,
    leggi_file,
    rinomina,
    sposta,
    copia,
    elimina,
    cerca_file,

    screenshot,
    dimensione_schermo,
    posizione_mouse,
    muovi_mouse,
    clicca,
    doppio_click,
    click_destro,
    scroll,

    scrivi_testo,
    premi_tasto,
    scorciatoia,
    copia_selezione,
    incolla,
    leggi_clipboard,
    imposta_clipboard,

    elenco_finestre,
    porta_finestra_davanti,
    minimizza_finestra,
    massimizza_finestra,
    ripristina_finestra,
    chiudi_finestra,
    sposta_finestra,
    ridimensiona_finestra,
    finestra_attiva,
    cambia_finestra,

    info_sistema,
    processi_attivi,
    termina_processo,

    apri_task_manager,
    apri_esplora_file,
    apri_impostazioni,
    blocca_pc,
    spegni_pc,
    riavvia_pc,
    sospendi_pc,

    play_pause,
    traccia_successiva,
    traccia_precedente,

    mostra_desktop,
    apri_start,

    premi_esc,
    premi_inv,
    annulla,
    ripristina,
    seleziona_tutto,
    salva
)


# ============================================================
# OPENAI
# ============================================================

load_dotenv()


client = openai_client(profile="router")


# ============================================================
# MODELLO ROUTER
# ============================================================

MODELLO_ROUTER = "gpt-5.6-luna"


def _tool_permission_profile():
    return {"successo": True, "messaggio": "Profilo permessi caricato.", "dati": permission_profile()}


def _tool_list_scripts():
    rows = list_scripts()
    return {"successo": True, "messaggio": f"Trovati {len(rows)} script.", "dati": rows}


def _tool_add_event_rule(trigger_type, trigger_value, command):
    item = add_rule(trigger_type, trigger_value, command)
    return {"successo": True, "messaggio": f"Regola {item['id']} creata.", "dati": item}


def _tool_list_event_rules():
    rows = list_rules()
    return {"successo": True, "messaggio": f"Trovate {len(rows)} regole.", "dati": rows}


def _tool_set_event_rule_enabled(rule_id, enabled):
    ok = set_rule_enabled(rule_id, enabled)
    return {"successo": ok, "messaggio": "Regola aggiornata." if ok else "Regola non trovata."}


def _tool_delete_event_rule(rule_id):
    ok = delete_rule(rule_id)
    return {"successo": ok, "messaggio": "Regola eliminata." if ok else "Regola non trovata."}


def _tool_recent_jobs(limit):
    rows = recent_jobs(limit)
    return {"successo": True, "messaggio": f"Trovate {len(rows)} attività recenti.", "dati": rows}


def _tool_resume_mission():
    mission = latest_resumable()
    if not mission:
        return {"successo": False, "messaggio": "Non ci sono missioni da riprendere."}
    return {
        "successo": True,
        "messaggio": "Checkpoint caricato. Continua soltanto dai passaggi mancanti.",
        "dati": mission,
    }


def _tool_simulate_action(tool, arguments_json):
    try:
        arguments = json.loads(arguments_json or "{}")
    except Exception:
        return {"successo": False, "messaggio": "Argomenti della simulazione non validi."}
    return simulate_action(tool, arguments)


def _tool_clear_cache():
    count = cache_clear()
    return {"successo": True, "messaggio": f"Cache intelligente svuotata: {count} elementi."}


def _tool_list_projects():
    rows = list_projects()
    return {"successo": True, "messaggio": f"Trovati {len(rows)} progetti.", "dati": rows}


def _tool_context_state():
    return {
        "successo": True,
        "messaggio": "Contesto operativo caricato.",
        "dati": {
            **CORE_RUNTIME.context.snapshot(),
            "operational_result": CORE_RUNTIME.context.operational_context(),
        },
    }


# ============================================================
# NUMERO MASSIMO DI PASSAGGI
#
# Evita eventuali loop infiniti dell'agente.
# ============================================================

MAX_PASSAGGI = 24


def _router_effort(text):
    value = str(text or "").lower()
    build_markers = ("crea un bot", "costruisci un bot", "sviluppa", "genera codice", "progetto completo")
    if any(marker in value for marker in build_markers):
        return "medium"
    complex_markers = ("organizza", "pianifica", "analizza", "risolvi", "automatizza", "workflow", "progetto", "controlla tutto", " e ", " poi ")
    return "low" if any(marker in value for marker in complex_markers) else "minimal"


def _looks_action_request(text):
    return decide(text).needs_tools or match_expansion_skill(CORE_RUNTIME.skills, text) is not None or bool(re.match(
        r"^(?:per favore\s+)?(?:fammi|fai|usa|accedi|attiva|disattiva|crea|costruisci|sviluppa|apri|chiudi|avvia|lancia|"
        r"cattura|analizza|studia|converti|leggi|indicizza|cerca|trova|recupera|aggiungi|memorizza|conserva|invia|manda|modifica|genera|compila|riproduci|archivia|ordina|vai|scrivi|salva|sposta|copia|rinomina|elimina|rimuovi|installa|"
        r"aggiorna|scarica|controlla|gestisci|automatizza|configura|imposta|spegni|riavvia|"
        r"sospendi|blocca|premi|clicca|seleziona|mostra|nascondi)\b",
        str(text or "").strip(), flags=re.IGNORECASE,
    ))


def _with_active_window_context(text):
    value = str(text or "").strip()
    if not re.search(r"\b(?:cerca|riproduci|video|clicca|seleziona|risultato|pagina|menu|pulsante)\b", value, flags=re.IGNORECASE):
        return value
    active = finestra_attiva()
    if not active.get("successo"):
        return value
    title = str((active.get("dati") or {}).get("titolo") or "").strip()
    if not title:
        return value
    return f"Contesto verificato: la finestra attiva è '{title}'.\nRichiesta dell'utente: {value}"


# ============================================================
# TOOL SCHEMAS
# ============================================================



# ============================================================
# JARVIS EXPANSION ROUTER
# ============================================================

def _tool_expansion_call(skill, arguments_json="{}"):
    """Esegue una skill del Mega Expansion Pack tramite SkillRegistry."""
    skill_name = str(skill or "").strip()
    manifest = CORE_RUNTIME.skills.manifest(skill_name)
    if manifest is None or not str(manifest.entrypoint).startswith("jarvis_expansion:"):
        return {
            "successo": False,
            "messaggio": f"Skill espansione non autorizzata o sconosciuta: {skill_name}",
        }

    try:
        parsed = json.loads(str(arguments_json or "{}"))
    except Exception:
        return {
            "successo": False,
            "messaggio": "arguments_json deve contenere un oggetto JSON valido.",
            "dati": {"error": "invalid_tool_arguments", "invocation_not_started": True},
            "skill": skill_name,
        }
    if not isinstance(parsed, dict):
        return {
            "successo": False,
            "messaggio": "arguments_json deve rappresentare un oggetto JSON.",
            "dati": {"error": "invalid_tool_arguments", "invocation_not_started": True},
            "skill": skill_name,
        }

    if skill_name == "litellm.complete":
        unknown = set(parsed) - {"model", "prompt", "input", "max_tokens"}
        if unknown:
            return {"successo": False, "messaggio": "Argomenti LiteLLM non riconosciuti: " + ", ".join(sorted(unknown)),
                    "dati": {"error": "invalid_tool_arguments", "invocation_not_started": True, "unexpected_arguments": sorted(unknown)}, "skill": skill_name}
        if "input" in parsed:
            if "prompt" in parsed:
                return {"successo": False, "messaggio": "Usa un solo campo tra prompt e input per LiteLLM.",
                        "dati": {"error": "invalid_tool_arguments", "invocation_not_started": True}, "skill": skill_name}
            parsed["prompt"] = parsed.pop("input")

    # Confirmation metadata is owned by the central confirmation layer.  It
    # must never be accepted as ordinary model-supplied Expansion/MCP input.
    reserved_confirmation_keys = {"action_id", "confirmed", "_confirmed"}
    nested_mcp_arguments = parsed.get("arguments") if skill_name == "mcp.call" else None
    if reserved_confirmation_keys.intersection(parsed) or (
        isinstance(nested_mcp_arguments, dict)
        and reserved_confirmation_keys.intersection(nested_mcp_arguments)
    ):
        return {
            "successo": False,
            "messaggio": "Metadati di conferma non validi: usa la conferma utente dell'azione pendente.",
            "skill": skill_name,
        }

    result = CORE_RUNTIME.skills.execute(skill_name, **parsed)
    data = dict(getattr(result, "data", {}) or {})
    message = str(getattr(result, "message", "") or "")
    success = bool(getattr(result, "success", False))
    payload = {
        "successo": success,
        "messaggio": message or ("Skill espansione completata." if success else "Skill espansione non completata."),
        "dati": data,
        "skill": skill_name,
    }
    if data.get("requires_confirmation"):
        payload["richiede_conferma_skill"] = True
        payload["azione_id_skill"] = str(data.get("action_id") or "")
        payload["richiede_conferma"] = True
        payload["azione_id"] = str(data.get("action_id") or "")
        payload["rischio"] = str(data.get("risk") or getattr(manifest, "risk", "sensitive"))
        payload["stato"] = "pending_confirmation"
    return payload


def _tool_attempt_identity(nome_tool, argomenti):
    """Build a stable identity for retries of the same logical tool action."""
    normalized = dict(argomenti or {})
    if nome_tool == "expansion_call":
        skill = str(normalized.get("skill") or "")
        try:
            payload = json.loads(str(normalized.get("arguments_json") or "{}"))
        except (TypeError, ValueError):
            payload = {}
        if skill == "litellm.complete" and isinstance(payload, dict) and "input" in payload and "prompt" not in payload:
            payload["prompt"] = payload.pop("input")
        normalized = {"skill": skill, "arguments": payload}
    return nome_tool, json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)


def _tool_attempt_family(nome_tool, argomenti):
    if nome_tool == "expansion_call":
        return nome_tool, str((argomenti or {}).get("skill") or "")
    return nome_tool, ""


def _record_tool_result(nome_tool, argomenti, risultato, failures, pending, unverified, successes, schema_errors=None):
    """Let a correlated successful retry supersede its prior failed attempt."""
    identity = _tool_attempt_identity(nome_tool, argomenti)
    family = _tool_attempt_family(nome_tool, argomenti)
    schema_errors = schema_errors if schema_errors is not None else []
    if risultato.get("successo") and not risultato.get("richiede_conferma"):
        successes.append({"identity": identity, "result": dict(risultato)})
        failures[:] = [row for row in failures if row["identity"] != identity]
        unverified[:] = [row for row in unverified if row["identity"] != identity]
        schema_errors[:] = [row for row in schema_errors if row["family"] != family]
        if isinstance(risultato.get("verification"), dict) and risultato["verification"].get("status") == "verified":
            return
        unverified.append({"identity": identity, "message": str(
            risultato["verification"].get("evidence") if isinstance(risultato.get("verification"), dict) else f"{nome_tool} non verificato"
        ).strip()[:500]})
        return
    if risultato.get("richiede_conferma"):
        pending.append(str(risultato.get("messaggio") or "conferma richiesta").strip()[:500])
        return
    if not risultato.get("successo"):
        data = risultato.get("dati") if isinstance(risultato.get("dati"), dict) else {}
        if data.get("error") == "invalid_tool_arguments" or data.get("invocation_not_started"):
            schema_errors.append({"family": family, "message": str(risultato.get("messaggio") or "Argomenti tool non validi.").strip()[:500]})
            return
        failures.append({"identity": identity, "message": str(risultato.get("messaggio") or f"{nome_tool} non riuscito.").strip()[:500]})
        return
    if not isinstance(risultato.get("verification"), dict) or risultato["verification"].get("status") != "verified":
        unverified.append({"identity": identity, "message": str(
            risultato["verification"].get("evidence") if isinstance(risultato.get("verification"), dict) else f"{nome_tool} non verificato"
        ).strip()[:500]})


TOOLS = [

    # ========================================================
    # PROGRAMMI
    # ========================================================

    {
        "type": "function",
        "name": "apri_programma",
        "description": (
            "Apre un'applicazione installata su Windows. "
            "Esempi: Chrome, Spotify, Discord, Visual Studio Code, "
            "Blocco Note, Calcolatrice."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "nome": {
                    "type": "string"
                }
            },
            "required": ["nome"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "chiudi_programma",
        "description": (
            "Chiude normalmente un programma conosciuto."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "nome": {
                    "type": "string"
                }
            },
            "required": ["nome"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "apri_sito",
        "description": (
            "Apre un sito conosciuto come YouTube, Google, GitHub, "
            "ChatGPT, OpenAI o Gmail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "nome": {
                    "type": "string"
                }
            },
            "required": ["nome"],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # GOOGLE
    # ========================================================

    {
        "type": "function",
        "name": "cerca_google",
        "description": (
            "Apre nel browser una ricerca Google."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string"
                }
            },
            "required": ["query"],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # VOLUME
    # ========================================================

    {
        "type": "function",
        "name": "imposta_volume",
        "description": (
            "Imposta il volume Windows a una percentuale esatta."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "percentuale": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100
                }
            },
            "required": ["percentuale"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "modifica_volume",
        "description": (
            "Aumenta o diminuisce il volume rispetto al livello attuale. "
            "Usa valori positivi per aumentare e negativi per diminuire. "
            "Se l'utente dice 'un po'', usa circa 10 punti."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "variazione": {
                    "type": "integer",
                    "minimum": -100,
                    "maximum": 100
                }
            },
            "required": ["variazione"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "imposta_muto",
        "description": (
            "Attiva o disattiva il muto dell'audio Windows."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "attivo": {
                    "type": "boolean"
                }
            },
            "required": ["attivo"],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # FILE E CARTELLE
    # ========================================================

    {
        "type": "function",
        "name": "apri_percorso",
        "description": (
            "Apre un file o una cartella esistente."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "percorso": {
                    "type": "string"
                }
            },
            "required": ["percorso"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "apri_percorso_con_programma",
        "description": "Apre un file esistente con Blocco note, verificando che il processo sia realmente attivo.",
        "parameters": {
            "type": "object",
            "properties": {
                "percorso": {"type": "string"},
                "programma": {"type": "string"}
            },
            "required": ["percorso", "programma"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "crea_cartella",
        "description": (
            "Crea una nuova cartella. "
            "Può usare percorsi Windows completi."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "percorso": {
                    "type": "string"
                }
            },
            "required": ["percorso"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "crea_file",
        "description": (
            "Crea un nuovo file di testo senza sovrascrivere file esistenti."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "percorso": {
                    "type": "string"
                },
                "contenuto": {
                    "type": "string"
                }
            },
            "required": [
                "percorso",
                "contenuto"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "leggi_file",
        "description": (
            "Legge il contenuto di un file di testo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "percorso": {
                    "type": "string"
                }
            },
            "required": ["percorso"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "rinomina",
        "description": (
            "Rinomina un file o una cartella esistente."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "percorso": {
                    "type": "string"
                },
                "nuovo_nome": {
                    "type": "string"
                }
            },
            "required": [
                "percorso",
                "nuovo_nome"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "sposta",
        "description": (
            "Sposta un file o una cartella in un'altra posizione."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "origine": {
                    "type": "string"
                },
                "destinazione": {
                    "type": "string"
                }
            },
            "required": [
                "origine",
                "destinazione"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "copia",
        "description": (
            "Copia un file o una cartella."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "origine": {
                    "type": "string"
                },
                "destinazione": {
                    "type": "string"
                }
            },
            "required": [
                "origine",
                "destinazione"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "cerca_file",
        "description": (
            "Cerca file o cartelle nel Desktop, Documenti e Download."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "nome": {
                    "type": "string"
                }
            },
            "required": ["nome"],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # SCREENSHOT
    # ========================================================

    {
        "type": "function",
        "name": "screenshot",
        "description": (
            "Cattura uno screenshot dello schermo e lo salva sul computer."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # SCHERMO / MOUSE
    # ========================================================

    {
        "type": "function",
        "name": "dimensione_schermo",
        "description": (
            "Restituisce larghezza e altezza dello schermo."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "posizione_mouse",
        "description": (
            "Restituisce le coordinate attuali del mouse."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "muovi_mouse",
        "description": (
            "Muove il puntatore del mouse a coordinate precise."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer"
                },
                "y": {
                    "type": "integer"
                }
            },
            "required": [
                "x",
                "y"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "clicca",
        "description": (
            "Esegue un singolo click sinistro. "
            "Se non vengono fornite coordinate clicca nella posizione corrente."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": [
                        "integer",
                        "null"
                    ]
                },
                "y": {
                    "type": [
                        "integer",
                        "null"
                    ]
                }
            },
            "required": [
                "x",
                "y"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "doppio_click",
        "description": (
            "Esegue un doppio click sinistro."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": [
                        "integer",
                        "null"
                    ]
                },
                "y": {
                    "type": [
                        "integer",
                        "null"
                    ]
                }
            },
            "required": [
                "x",
                "y"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "click_destro",
        "description": (
            "Esegue un click con il tasto destro."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": [
                        "integer",
                        "null"
                    ]
                },
                "y": {
                    "type": [
                        "integer",
                        "null"
                    ]
                }
            },
            "required": [
                "x",
                "y"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "scroll",
        "description": (
            "Scorre la pagina. Valore positivo verso l'alto, "
            "negativo verso il basso."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "quantita": {
                    "type": "integer"
                }
            },
            "required": ["quantita"],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # TASTIERA
    # ========================================================

    {
        "type": "function",
        "name": "scrivi_testo",
        "description": (
            "Scrive o incolla del testo nel campo attualmente selezionato."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "testo": {
                    "type": "string"
                }
            },
            "required": ["testo"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "premi_tasto",
        "description": (
            "Preme uno specifico tasto della tastiera."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasto": {
                    "type": "string"
                },
                "volte": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20
                }
            },
            "required": [
                "tasto",
                "volte"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "scorciatoia",
        "description": (
            "Esegue una combinazione di tasti, per esempio ctrl+s, "
            "ctrl+shift+esc oppure alt+f4."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasti": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "minItems": 2,
                    "maxItems": 5
                }
            },
            "required": ["tasti"],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # CLIPBOARD
    # ========================================================

    {
        "type": "function",
        "name": "copia_selezione",
        "description": (
            "Copia negli appunti il testo o elemento attualmente selezionato."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "incolla",
        "description": (
            "Incolla il contenuto corrente degli appunti."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "leggi_clipboard",
        "description": (
            "Legge il testo presente negli appunti Windows."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "imposta_clipboard",
        "description": (
            "Inserisce del testo negli appunti Windows."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "testo": {
                    "type": "string"
                }
            },
            "required": ["testo"],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # FINESTRE
    # ========================================================

    {
        "type": "function",
        "name": "elenco_finestre",
        "description": (
            "Restituisce le finestre aperte attualmente."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "porta_finestra_davanti",
        "description": (
            "Porta in primo piano una finestra usando parte del titolo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titolo": {
                    "type": "string"
                }
            },
            "required": ["titolo"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "minimizza_finestra",
        "description": (
            "Minimizza una finestra."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titolo": {
                    "type": "string"
                }
            },
            "required": ["titolo"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "massimizza_finestra",
        "description": (
            "Massimizza una finestra."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titolo": {
                    "type": "string"
                }
            },
            "required": ["titolo"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "ripristina_finestra",
        "description": (
            "Ripristina una finestra minimizzata o massimizzata."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titolo": {
                    "type": "string"
                }
            },
            "required": ["titolo"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "chiudi_finestra",
        "description": (
            "Chiude normalmente una finestra. "
            "Non usarlo se potrebbe causare perdita evidente di dati "
            "non salvati senza che l'utente abbia richiesto chiaramente "
            "la chiusura."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titolo": {
                    "type": "string"
                }
            },
            "required": ["titolo"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "sposta_finestra",
        "description": (
            "Sposta una finestra a coordinate specifiche."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titolo": {
                    "type": "string"
                },
                "x": {
                    "type": "integer"
                },
                "y": {
                    "type": "integer"
                }
            },
            "required": [
                "titolo",
                "x",
                "y"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "ridimensiona_finestra",
        "description": (
            "Ridimensiona una finestra."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "titolo": {
                    "type": "string"
                },
                "larghezza": {
                    "type": "integer",
                    "minimum": 100
                },
                "altezza": {
                    "type": "integer",
                    "minimum": 100
                }
            },
            "required": [
                "titolo",
                "larghezza",
                "altezza"
            ],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "finestra_attiva",
        "description": (
            "Restituisce informazioni sulla finestra attualmente attiva."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "cambia_finestra",
        "description": (
            "Esegue Alt+Tab per passare alla finestra successiva."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # SISTEMA
    # ========================================================

    {
        "type": "function",
        "name": "info_sistema",
        "description": (
            "Legge utilizzo CPU, RAM, disco e informazioni generali sul PC."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "processi_attivi",
        "description": (
            "Elenca i principali processi attualmente attivi."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limite": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100
                }
            },
            "required": ["limite"],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "apri_task_manager",
        "description": (
            "Apre Gestione attività di Windows."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "apri_esplora_file",
        "description": (
            "Apre Esplora file."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "apri_impostazioni",
        "description": (
            "Apre Impostazioni Windows, eventualmente direttamente "
            "nella sezione richiesta: bluetooth, wifi, rete, audio, "
            "schermo, batteria, aggiornamenti, app o privacy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pagina": {
                    "type": [
                        "string",
                        "null"
                    ]
                }
            },
            "required": ["pagina"],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # MEDIA
    # ========================================================

    {
        "type": "function",
        "name": "play_pause",
        "description": (
            "Mette in pausa o riprende il contenuto multimediale."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "traccia_successiva",
        "description": (
            "Passa alla traccia multimediale successiva."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "traccia_precedente",
        "description": (
            "Passa alla traccia multimediale precedente."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },


    # ========================================================
    # COMANDI WINDOWS COMUNI
    # ========================================================

    {
        "type": "function",
        "name": "mostra_desktop",
        "description": (
            "Mostra il desktop usando Win+D."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "apri_start",
        "description": (
            "Apre il menu Start."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "premi_esc",
        "description": (
            "Preme Escape."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "premi_inv",
        "description": (
            "Preme Invio."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "annulla",
        "description": (
            "Esegue Ctrl+Z."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "ripristina",
        "description": (
            "Esegue Ctrl+Y."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "seleziona_tutto",
        "description": (
            "Esegue Ctrl+A."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    },

    {
        "type": "function",
        "name": "salva",
        "description": (
            "Salva il documento o file corrente con Ctrl+S."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    }
]

TOOLS.extend([
    {"type":"function","name":"crea_presentazione","description":"Crea e salva realmente una presentazione PowerPoint .pptx sul Desktop. Usalo quando l'utente dice crea, prepara, genera, salva o anche installa una presentazione.","parameters":{"type":"object","properties":{"titolo":{"type":"string"},"diapositive":{"type":"array","minItems":1,"maxItems":40,"items":{"type":"object","properties":{"titolo":{"type":"string"},"contenuto":{"type":"array","items":{"type":"string"},"maxItems":12}},"required":["titolo","contenuto"],"additionalProperties":False}},"nome_file":{"type":"string"}},"required":["titolo","diapositive","nome_file"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"elimina","description":"Sposta un file o una cartella nel cestino recuperabile di JARVIS.","parameters":{"type":"object","properties":{"percorso":{"type":"string"}},"required":["percorso"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"termina_processo","description":"Termina un processo per nome.","parameters":{"type":"object","properties":{"nome":{"type":"string"}},"required":["nome"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"blocca_pc","description":"Blocca la sessione Windows.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True},
    {"type":"function","name":"spegni_pc","description":"Spegne il computer direttamente.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True},
    {"type":"function","name":"riavvia_pc","description":"Riavvia il computer direttamente.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True},
    {"type":"function","name":"sospendi_pc","description":"Sospende il computer direttamente.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True},
    {"type":"function","name":"crea_bozza_email","description":"Crea una bozza email locale e la apre nel client predefinito; non invia nulla.","parameters":{"type":"object","properties":{"destinatario":{"type":"string"},"oggetto":{"type":"string"},"corpo":{"type":"string"},"apri":{"type":"boolean"}},"required":["destinatario","oggetto","corpo","apri"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"crea_evento_calendario","description":"Crea un invito calendario ICS locale. Le date sono ISO YYYY-MM-DDTHH:MM.","parameters":{"type":"object","properties":{"titolo":{"type":"string"},"inizio_iso":{"type":"string"},"fine_iso":{"type":"string"},"descrizione":{"type":"string"},"luogo":{"type":"string"},"apri":{"type":"boolean"}},"required":["titolo","inizio_iso","fine_iso","descrizione","luogo","apri"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"analizza_schermo","description":"Guarda lo schermo corrente per descriverlo, leggere errori o verificare il risultato di un'azione.","parameters":{"type":"object","properties":{"domanda":{"type":"string"}},"required":["domanda"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"individua_elemento","description":"Individua un elemento visibile e restituisce coordinate stimate, senza cliccare.","parameters":{"type":"object","properties":{"elemento":{"type":"string"}},"required":["elemento"],"additionalProperties":False},"strict":True},
    {"type":"function","name":"capability_report","description":"Elenca le capacità e i moduli attualmente disponibili in JARVIS.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"permission_profile","description":"Mostra modalità di autonomia e permessi correnti senza rivelare il PIN.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"save_script","description":"Salva uno script Python o PowerShell dopo analisi di sicurezza; non lo esegue.","parameters":{"type":"object","properties":{"name":{"type":"string"},"language":{"type":"string","enum":["python","powershell"]},"code":{"type":"string"}},"required":["name","language","code"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"list_scripts","description":"Elenca gli script salvati.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"run_script","description":"Esegue autonomamente uno script salvato con timeout e audit.","parameters":{"type":"object","properties":{"name":{"type":"string"},"arguments":{"type":"array","items":{"type":"string"}},"timeout":{"type":"integer","minimum":1,"maximum":300}},"required":["name","arguments","timeout"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"info_rete","description":"Mostra interfacce e indirizzi di rete locali.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"connessioni_rete","description":"Elenca connessioni di rete attive.","parameters":{"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":100}},"required":["limit"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"servizi_windows","description":"Elenca e filtra i servizi Windows senza modificarli.","parameters":{"type":"object","properties":{"filtro":{"type":"string"}},"required":["filtro"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"crea_archivio_zip","description":"Crea un archivio ZIP da un file o cartella.","parameters":{"type":"object","properties":{"sorgente":{"type":"string"},"destinazione":{"type":"string"}},"required":["sorgente","destinazione"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"estrai_archivio_zip","description":"Estrae in sicurezza un archivio ZIP.","parameters":{"type":"object","properties":{"archivio":{"type":"string"},"destinazione":{"type":"string"}},"required":["archivio","destinazione"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"spazio_cartella","description":"Calcola la dimensione totale di una cartella o file.","parameters":{"type":"object","properties":{"percorso":{"type":"string"}},"required":["percorso"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"add_event_rule","description":"Crea un'automazione condizionale. Tipi: file_created, process_started, cpu_above, disk_above.","parameters":{"type":"object","properties":{"trigger_type":{"type":"string","enum":["file_created","process_started","cpu_above","disk_above"]},"trigger_value":{"type":"string"},"command":{"type":"string"}},"required":["trigger_type","trigger_value","command"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"list_event_rules","description":"Elenca le automazioni condizionali.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"set_event_rule_enabled","description":"Attiva o disattiva una regola evento.","parameters":{"type":"object","properties":{"rule_id":{"type":"string"},"enabled":{"type":"boolean"}},"required":["rule_id","enabled"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"delete_event_rule","description":"Elimina una regola evento.","parameters":{"type":"object","properties":{"rule_id":{"type":"string"}},"required":["rule_id"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"recent_agent_jobs","description":"Mostra attività agentiche recenti, passaggi ed esiti.","parameters":{"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":50}},"required":["limit"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"resume_mission","description":"Carica l'ultima missione interrotta o non verificata con piano, checkpoint e prove. Dopo averla caricata continua soltanto i passaggi mancanti.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"inspect_ui","description":"Legge la finestra attiva tramite Windows UI Automation e restituisce pulsanti, campi, menu e controlli con nomi e ID strutturati. Preferiscilo agli screenshot.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"ui_invoke","description":"Attiva un pulsante, menu, opzione o controllo tramite nome o AutomationId, senza coordinate.","parameters":{"type":"object","properties":{"target":{"type":"string"}},"required":["target"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"ui_focus","description":"Porta il focus su un controllo strutturato tramite nome o AutomationId.","parameters":{"type":"object","properties":{"target":{"type":"string"}},"required":["target"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"ui_set_value","description":"Imposta il testo o valore di un campo tramite Windows UI Automation senza usare appunti o coordinate.","parameters":{"type":"object","properties":{"target":{"type":"string"},"value":{"type":"string"}},"required":["target","value"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"performance_report","description":"Mostra velocità media, tasso di successo e fallimenti reali degli strumenti di JARVIS.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"chrome_snapshot","description":"Legge DOM, URL, testo e controlli della scheda Chrome attiva tramite l'estensione locale. Preferiscilo alla visione per pagine web.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"chrome_action","description":"Agisce sul DOM della scheda Chrome e richiede poi chrome_snapshot per verificare. Non può compilare campi sensibili.","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["click_text","click_selector","set_value","focus","navigate","scroll"]},"target":{"type":"string"},"value":{"type":"string"}},"required":["action","target","value"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"simulate_action","description":"Simula senza eseguire un'azione, controllando impatto, reversibilità e percorsi protetti.","parameters":{"type":"object","properties":{"tool":{"type":"string"},"arguments_json":{"type":"string"}},"required":["tool","arguments_json"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"learned_procedures","description":"Mostra procedure ricorrenti apprese dalle missioni completate e quelle pronte a diventare skill.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"simulate_procedure","description":"Simula una procedura appresa senza eseguire alcuna azione.","parameters":{"type":"object","properties":{"signature":{"type":"string"}},"required":["signature"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"approve_procedure","description":"Approva esplicitamente una procedura appresa dopo la simulazione; non la esegue automaticamente.","parameters":{"type":"object","properties":{"signature":{"type":"string"},"approved_by":{"type":"string"}},"required":["signature","approved_by"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"evaluation_trends","description":"Analizza le ultime valutazioni real-world e segnala regressioni prima di un aggiornamento.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"async_runtime_report","description":"Mostra corsie, attività concorrenti, durate e stato del motore asincrono.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"clear_smart_cache","description":"Svuota la cache intelligente di osservazioni e letture non mutanti.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"restore_project_version","description":"Annulla l'ultimo aggiornamento di un progetto JARVIS ripristinando lo snapshot precedente.","parameters":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"restore_last_deleted","description":"Ripristina l'ultimo file o cartella spostato nel cestino recuperabile di JARVIS.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"stato_wifi","description":"Mostra lo stato dettagliato del Wi-Fi Windows.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"programmi_installati","description":"Elenca o cerca programmi installati tramite winget.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"installa_programma","description":"Installa autonomamente un pacchetto winget per ID.","parameters":{"type":"object","properties":{"package_id":{"type":"string"}},"required":["package_id"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"aggiorna_programma","description":"Aggiorna autonomamente un pacchetto winget per ID.","parameters":{"type":"object","properties":{"package_id":{"type":"string"}},"required":["package_id"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"create_project","description":"Crea o aggiorna un progetto software multi-file completo, per esempio bot, automazione, sito o applicazione. Genera file realmente utilizzabili ma non esegue automaticamente il codice.","parameters":{"type":"object","properties":{"name":{"type":"string"},"project_type":{"type":"string"},"description":{"type":"string"},"files":{"type":"array","minItems":1,"maxItems":40,"items":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False}},"overwrite":{"type":"boolean"}},"required":["name","project_type","description","files","overwrite"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"list_projects","description":"Elenca i progetti software creati da JARVIS e i relativi percorsi.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"visual_task","description":"Controlla qualunque interfaccia visibile in ciclo chiuso: osserva un nuovo screenshot, esegue una singola azione con mouse o tastiera e verifica, ripetendo fino all'obiettivo. Usalo per browser, YouTube e programmi quando il risultato dipende da ciò che appare sullo schermo.","parameters":{"type":"object","properties":{"task":{"type":"string"},"max_steps":{"type":"integer","minimum":1,"maximum":30}},"required":["task","max_steps"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"context_state","description":"Recupera il contesto operativo persistente dell'ultima attività, utile per frasi come continua, quello di prima o il terzo risultato.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"analyze_trading_chart","description":"Analizza in modo specializzato il grafico TradingView visibile: trend, struttura, livelli e scenari senza eseguire operazioni finanziarie.","parameters":{"type":"object","properties":{"question":{"type":"string"}},"required":["question"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"inspect_project","description":"Ispeziona staticamente un progetto creato da JARVIS e rileva errori Python e JSON senza eseguirlo.","parameters":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"test_project","description":"Esegue autonomamente i test unittest di un progetto creato da JARVIS.","parameters":{"type":"object","properties":{"name":{"type":"string"},"timeout":{"type":"integer","minimum":5,"maximum":300}},"required":["name","timeout"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"integration_status","description":"Controlla lo stato delle integrazioni opzionali Browser Use, Microsoft UFO, LangGraph, Mem0, Pipecat e UI-TARS. Usa deep=true solo per verificare anche i sidecar di rete.","parameters":{"type":"object","properties":{"deep":{"type":"boolean"}},"required":["deep"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"delegate_agent_task","description":"Delega un workflow GUI o browser lungo a un agente esterno con routing e fallback. Usalo solo quando gli strumenti nativi strutturati non sono adatti a completare in modo robusto un obiettivo multi-step.","parameters":{"type":"object","properties":{"task":{"type":"string"},"preferred_backend":{"type":"string","enum":["auto","browser_use","ufo","ui_tars"]},"max_steps":{"type":"integer","minimum":1,"maximum":100}},"required":["task","preferred_backend","max_steps"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"browser_agent_task","description":"Esegue un workflow browser multi-step con Browser Use. Non usarlo per semplici letture/click se chrome_snapshot/chrome_action bastano.","parameters":{"type":"object","properties":{"task":{"type":"string"},"max_steps":{"type":"integer","minimum":1,"maximum":100}},"required":["task","max_steps"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"ufo_agent_task","description":"Esegue un workflow Windows multi-step tramite Microsoft UFO. Preferisci prima UI Automation e strumenti JARVIS deterministici per azioni semplici.","parameters":{"type":"object","properties":{"task":{"type":"string"}},"required":["task"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"ui_tars_agent_task","description":"Esegue un workflow GUI tramite visione UI-TARS. È un fallback visuale per interfacce che non espongono controlli strutturati.","parameters":{"type":"object","properties":{"task":{"type":"string"}},"required":["task"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"mem0_search","description":"Cerca nella memoria secondaria Mem0 quando è abilitata.","parameters":{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":20}},"required":["query","limit"],"additionalProperties":False},"strict":True}
    ,{"type":"function","name":"mem0_remember","description":"Aggiunge esplicitamente una memoria a Mem0 quando il backend è abilitato. Non usare per segreti, password, token o OTP.","parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"],"additionalProperties":False},"strict":True}
])


# ============================================================
# MAPPA FUNZIONI
# ============================================================



# Ponte generico verso le skill del Mega Expansion Pack.
TOOLS.append({
    "type": "function",
    "name": "expansion_call",
    "description": (
        "Esegue realmente una skill avanzata del Mega Expansion Pack registrata in JARVIS. "
        "Usalo quando l'utente chiede esplicitamente MCP/FastMCP, DXcam, Docling, MarkItDown, "
        "Crawl4AI, Screenpipe, Watchdog, Qdrant, Ruff, Silero VAD, Home Assistant, ESPHome, "
        "LiteLLM, Ollama, llama.cpp, OpenHands, SearXNG o Keyring. Non limitarti a dire che "
        "l'azione e partita: devi chiamare questo tool e controllarne il risultato. "
        "In arguments_json passa SEMPRE un oggetto JSON serializzato. Per litellm.complete sono obbligatori "
        "model e prompt, mentre max_tokens è opzionale: non usare {} se questi dati sono richiesti."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "enum": sorted(expansion_skill_names(CORE_RUNTIME.skills))
            },
            "arguments_json": {
                "type": "string",
                "description": "JSON degli argomenti della skill. litellm.complete richiede model e prompt; max_tokens è opzionale."
            }
        },
        "required": ["skill", "arguments_json"],
        "additionalProperties": False
    },
    "strict": True
})


FUNZIONI = {
    "expansion_call": _tool_expansion_call,


    "crea_presentazione": crea_presentazione,

    "permission_profile": _tool_permission_profile,
    "save_script": save_script,
    "list_scripts": _tool_list_scripts,
    "run_script": run_script,
    "info_rete": info_rete,
    "connessioni_rete": connessioni_rete,
    "servizi_windows": servizi_windows,
    "crea_archivio_zip": crea_archivio_zip,
    "estrai_archivio_zip": estrai_archivio_zip,
    "spazio_cartella": spazio_cartella,
    "add_event_rule": _tool_add_event_rule,
    "list_event_rules": _tool_list_event_rules,
    "set_event_rule_enabled": _tool_set_event_rule_enabled,
    "delete_event_rule": _tool_delete_event_rule,
    "recent_agent_jobs": _tool_recent_jobs,
    "resume_mission": _tool_resume_mission,
    "inspect_ui": inspect_ui,
    "ui_invoke": ui_invoke,
    "ui_focus": ui_focus,
    "ui_set_value": ui_set_value,
    "performance_report": performance_report,
    "chrome_snapshot": chrome_snapshot,
    "chrome_action": chrome_action,
    "simulate_action": _tool_simulate_action,
    "learned_procedures": learned_report,
    "simulate_procedure": simulate_procedure,
    "approve_procedure": approve_procedure,
    "evaluation_trends": lambda: {"successo": True, "messaggio": "Analisi delle valutazioni disponibile.", "dati": analyze_evaluations()},
    "async_runtime_report": async_report,
    "clear_smart_cache": _tool_clear_cache,
    "restore_project_version": restore_project_version,
    "restore_last_deleted": restore_last,
    "stato_wifi": stato_wifi,
    "programmi_installati": programmi_installati,
    "installa_programma": installa_programma,
    "aggiorna_programma": aggiorna_programma,
    "create_project": create_project,
    "list_projects": _tool_list_projects,
    "visual_task": visual_task,
    "context_state": _tool_context_state,
    "analyze_trading_chart": analyze_trading_chart,
    "inspect_project": inspect_project,
    "test_project": test_project,
    "integration_status": integration_status,
    "delegate_agent_task": delegate_agent_task,
    "browser_agent_task": browser_agent_task,
    "ufo_agent_task": ufo_agent_task,
    "ui_tars_agent_task": ui_tars_agent_task,
    "mem0_search": mem0_search,
    "mem0_remember": mem0_remember,

    "analizza_schermo": analizza_schermo,
    "individua_elemento": individua_elemento,
    "capability_report": capability_report,

    "apri_programma":
        apri_programma,

    "chiudi_programma":
        chiudi_programma,

    "apri_sito":
        apri_sito,

    "cerca_google":
        cerca_google,

    "imposta_volume":
        imposta_volume,

    "modifica_volume":
        modifica_volume,

    "imposta_muto":
        imposta_muto,


    "apri_percorso":
        apri_percorso,

    "apri_percorso_con_programma":
        apri_percorso_con_programma,

    "crea_cartella":
        crea_cartella,

    "crea_file":
        crea_file,

    "leggi_file":
        leggi_file,

    "rinomina":
        rinomina,

    "sposta":
        sposta,

    "copia":
        copia,

    "elimina":
        elimina,

    "cerca_file":
        cerca_file,


    "screenshot":
        screenshot,

    "dimensione_schermo":
        dimensione_schermo,

    "posizione_mouse":
        posizione_mouse,

    "muovi_mouse":
        muovi_mouse,

    "clicca":
        clicca,

    "doppio_click":
        doppio_click,

    "click_destro":
        click_destro,

    "scroll":
        scroll,

    "scrivi_testo":
        scrivi_testo,

    "premi_tasto":
        premi_tasto,

    "scorciatoia":
        scorciatoia,

    "copia_selezione":
        copia_selezione,

    "incolla":
        incolla,

    "leggi_clipboard":
        leggi_clipboard,

    "imposta_clipboard":
        imposta_clipboard,


    "elenco_finestre":
        elenco_finestre,

    "porta_finestra_davanti":
        porta_finestra_davanti,

    "minimizza_finestra":
        minimizza_finestra,

    "massimizza_finestra":
        massimizza_finestra,

    "ripristina_finestra":
        ripristina_finestra,

    "chiudi_finestra":
        chiudi_finestra,

    "sposta_finestra":
        sposta_finestra,

    "ridimensiona_finestra":
        ridimensiona_finestra,

    "finestra_attiva":
        finestra_attiva,

    "cambia_finestra":
        cambia_finestra,


    "info_sistema":
        info_sistema,

    "processi_attivi":
        processi_attivi,

    "termina_processo":
        termina_processo,

    "apri_task_manager":
        apri_task_manager,

    "apri_esplora_file":
        apri_esplora_file,

    "apri_impostazioni":
        apri_impostazioni,

    "blocca_pc": blocca_pc,
    "spegni_pc": spegni_pc,
    "riavvia_pc": riavvia_pc,
    "sospendi_pc": sospendi_pc,
    "crea_bozza_email": crea_bozza_email,
    "crea_evento_calendario": crea_evento_calendario,


    "play_pause":
        play_pause,

    "traccia_successiva":
        traccia_successiva,

    "traccia_precedente":
        traccia_precedente,


    "mostra_desktop":
        mostra_desktop,

    "apri_start":
        apri_start,

    "premi_esc":
        premi_esc,

    "premi_inv":
        premi_inv,

    "annulla":
        annulla,

    "ripristina":
        ripristina,

    "seleziona_tutto":
        seleziona_tutto,

    "salva":
        salva
}


# ============================================================
# ESEGUI TOOL
# ============================================================

_CONFIRMATION_SENTINEL = object()


def _record_operational_tool_result(nome, argomenti, risultato):
    """Make the real tool payload available to a subsequent operational turn."""
    # Asking for the context must not replace the result that it is inspecting.
    if nome == "context_state":
        return
    try:
        CORE_RUNTIME.context.record_operational_result(nome, risultato, argomenti)
        record_operational_action(
            CORE_RUNTIME,
            request=argomenti.get("request") if isinstance(argomenti, dict) else None,
            result=risultato,
            tool=nome,
            arguments=argomenti,
        )
    except Exception as exc:
        # Context retention is a convenience; it must never break the critical
        # tool path or turn a real result into a false failure.
        print("OPERATIONAL CONTEXT ERROR:", redact(repr(exc)))

def esegui_tool(
    nome,
    argomenti
):

    argomenti = dict(argomenti or {})
    # Identity check prevents a model/tool payload from forging confirmation with
    # JSON such as {"_confirmed": true}.
    confirmed = argomenti.pop("_confirmed", None) is _CONFIRMATION_SENTINEL
    level = risk_level(nome)
    if level == "denied":
        audit_record("permission_denied", tool=nome, arguments=argomenti)
        risultato = {"successo": False, "messaggio": "Azione bloccata dal profilo di autorizzazione corrente."}
        _record_operational_tool_result(nome, argomenti, risultato)
        return risultato
    if level != "safe" and not confirmed:
        action_id = stage(nome, argomenti, risk=level)
        audit_record("confirmation_requested", tool=nome, arguments=argomenti, action_id=action_id, risk=level)
        pin_hint = " e inserisci il PIN dalla modalità testo" if permission_profile().get("pin") else ""
        risultato = {
            "successo": False,
            "richiede_conferma": True,
            "azione_id": action_id,
            "rischio": level,
            "messaggio": f"Conferma richiesta. Di': conferma azione {action_id}{pin_hint}",
        }
        _record_operational_tool_result(nome, argomenti, risultato)
        return risultato
    if nome in {"elimina", "termina_processo", "spegni_pc", "riavvia_pc", "sospendi_pc", "blocca_pc", "run_script", "test_project", "installa_programma", "aggiorna_programma"}:
        argomenti["confermato"] = True

    funzione = FUNZIONI.get(
        nome
    )


    if funzione is None:
        risultato = {
            "successo": False,
            "messaggio": (
                f"Tool sconosciuto: {nome}"
            )
        }
        _record_operational_tool_result(nome, argomenti, risultato)
        return risultato


    cache_ttls = {
        "inspect_ui": 0.6, "chrome_snapshot": 0.5, "finestra_attiva": 0.5,
        "elenco_finestre": 1.0, "info_sistema": 3.0, "processi_attivi": 2.0,
        "info_rete": 5.0, "connessioni_rete": 5.0, "programmi_installati": 20.0,
        "stato_wifi": 3.0, "performance_report": 1.0, "async_runtime_report": 0.5,
        "integration_status": 3.0, "mem0_search": 2.0,
    }
    cache_key = json.dumps([nome, argomenti], ensure_ascii=False, sort_keys=True, default=str)
    if get_setting("smart_cache_enabled", True) and nome in cache_ttls:
        cached = cache_get(cache_key)
        if cached is not None:
            cached["cache_hit"] = True
            _record_operational_tool_result(nome, argomenti, cached)
            return cached

    try:

        metric_started = time.perf_counter()
        audit_record("tool_started", tool=nome, arguments=argomenti, risk=level)
        def invoke_tool():
            if nome == "scorciatoia":
                return funzione(*argomenti.get("tasti", []))
            return funzione(**argomenti)

        vision_tools = {"visual_task", "analizza_schermo", "individua_elemento", "analyze_trading_chart"}
        automation_tools = {
            "clicca", "doppio_click", "click_destro", "muovi_mouse", "scroll", "scrivi_testo",
            "premi_tasto", "scorciatoia", "ui_invoke", "ui_focus", "ui_set_value", "chrome_action",
            "apri_programma", "chiudi_programma", "spegni_pc", "riavvia_pc", "sospendi_pc",
            "delegate_agent_task", "browser_agent_task", "ufo_agent_task", "ui_tars_agent_task",
        }
        lane = "vision" if nome in vision_tools else ("automation" if nome in automation_tools else "io")
        long_agent_tools = {"delegate_agent_task", "browser_agent_task", "ufo_agent_task", "ui_tars_agent_task"}
        timeout = 900 if nome in long_agent_tools else (240 if lane == "vision" else (320 if nome in {"run_script", "test_project", "installa_programma", "aggiorna_programma"} else 60))
        if nome == "expansion_call":
            expansion_skill = str(argomenti.get("skill") or "")
            if expansion_skill in {"documents.docling", "openhands.run"}:
                timeout = 1800
            elif expansion_skill in {"documents.markitdown", "web.crawl4ai", "ollama.chat", "llamacpp.chat", "ruff.check", "mcp.call"}:
                timeout = 360
            else:
                timeout = 120
        if get_setting("async_engine_enabled", True):
            _task_id, future = ASYNC_ENGINE.submit(lane, invoke_tool, timeout=timeout, label=f"tool:{nome}")
            risultato = future.result(timeout=timeout)
        else:
            risultato = invoke_tool()


        # tools.py usa ancora tuple
        # (successo, messaggio)

        if isinstance(
            risultato,
            tuple
        ):

            successo = (
                risultato[0]
                if len(risultato) > 0
                else False
            )

            messaggio = (
                risultato[1]
                if len(risultato) > 1
                else ""
            )


            risultato_normalizzato = {
                "successo": successo,
                "messaggio": messaggio
            }


        # computer.py restituisce già dict

        elif isinstance(
            risultato,
            dict
        ):
            risultato_normalizzato = risultato
        else:
            risultato_normalizzato = {
                "successo": True,
                "messaggio": str(risultato)
            }

        # Ogni tool restituisce una prova standardizzata al mission layer.
        # Il modello può continuare solo conoscendo lo stato verificato.
        risultato_normalizzato.setdefault(
            "verification",
            verify_result(nome, argomenti, risultato_normalizzato),
        )

        audit_record("tool_completed", tool=nome, result=risultato_normalizzato)
        _record_operational_tool_result(nome, argomenti, risultato_normalizzato)
        if get_setting("smart_cache_enabled", True) and nome in cache_ttls and risultato_normalizzato.get("successo"):
            cache_put(cache_key, risultato_normalizzato, cache_ttls[nome])
        record_tool_metric(nome, bool(risultato_normalizzato.get("successo")), int((time.perf_counter() - metric_started) * 1000))
        return risultato_normalizzato


    except Exception as e:
        try:
            record_tool_metric(nome, False, int((time.perf_counter() - metric_started) * 1000))
        except Exception:
            pass
        safe_error = redact(repr(e))
        audit_record("tool_failed", tool=nome, error=safe_error)
        risultato = {
            "successo": False,
            "messaggio": (
                f"Errore eseguendo {nome}."
            ),
            "errore": safe_error
        }
        _record_operational_tool_result(nome, argomenti, risultato)
        return risultato


def pending_confirmation_actions():
    """Return all live confirmations from both permission-backed stores."""
    actions = []
    for pending_id, row in pending_action_guard().items():
        item = dict(row)
        item.update({"action_id": str(pending_id), "source": "action_guard"})
        actions.append(item)
    for pending_id, row in CORE_RUNTIME.skills.pending().items():
        item = dict(row)
        item.update({"action_id": str(pending_id), "source": "skill_registry", "tool": "expansion_call"})
        actions.append(item)
    return sorted(actions, key=lambda item: float(item.get("created", 0)))


def _normalize_confirmed_skill_result(skill, arguments, result):
    data = dict(getattr(result, "data", {}) or {})
    payload = {
        "successo": bool(getattr(result, "success", False)),
        "messaggio": str(getattr(result, "message", "") or ""),
        "dati": data,
        "skill": str(skill),
    }
    tool_arguments = {
        "skill": str(skill),
        "arguments_json": json.dumps(dict(arguments or {}), ensure_ascii=False),
    }
    payload["verification"] = verify_result("expansion_call", tool_arguments, payload)
    audit_record("tool_completed", tool="expansion_call", result=payload)
    _record_operational_tool_result("expansion_call", tool_arguments, payload)
    return payload


def messaggio_risultato_operativo(risultato):
    """Render a user-facing message from a real, verified tool result."""
    value = dict(risultato or {})
    if not value.get("successo"):
        return str(value.get("messaggio") or "Operazione non riuscita.")
    verification = value.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "verified":
        return "Non posso confermare l'operazione: il risultato non è verificato."
    skill = str(value.get("skill") or "")
    if skill in {"qdrant.add", "qdrant.search"}:
        return _qdrant_result_message(skill, value)
    if skill == "ruff.check":
        data = value.get("dati") if isinstance(value.get("dati"), dict) else {}
        output = "\n".join(
            str(data.get(key) or "").strip()
            for key in ("stdout", "stderr")
            if str(data.get(key) or "").strip()
        ).strip()
        if output:
            return f"Controllo Ruff completato. Output:\n{output[:6000]}"
        return "Controllo Ruff completato: nessun problema rilevato."
    if skill == "mcp.call":
        data = value.get("dati") if isinstance(value.get("dati"), dict) else {}
        backend_result = data.get("result", data)
        if isinstance(backend_result, dict):
            backend_result = backend_result.get("structuredContent", backend_result)
            if isinstance(backend_result, dict) and set(backend_result) == {"result"}:
                backend_result = backend_result["result"]
        if isinstance(backend_result, (dict, list, tuple)):
            rendered = json.dumps(backend_result, ensure_ascii=False, default=str)
        else:
            rendered = str(backend_result)
        return f"Risultato MCP: {rendered}"
    return str(value.get("messaggio") or "Operazione completata.")


def conferma_azione(action_id, pin=None):
    profile_data = permission_profile()
    if profile_data.get("pin") and not verify_pin(pin):
        return {"successo": False, "messaggio": "PIN di sicurezza richiesto o non valido."}
    normalized_id = str(action_id or "").strip().lower()
    if not normalized_id:
        return {"successo": False, "messaggio": "Identificativo di conferma mancante."}

    action = take(normalized_id)
    if action:
        original_arguments = dict(action.get("arguments") or {})
        _stampa_tool_inizio(action["tool"], original_arguments)
        arguments = dict(original_arguments)
        arguments["_confirmed"] = _CONFIRMATION_SENTINEL
        result = esegui_tool(action["tool"], arguments)
        _stampa_tool_risultato(action["tool"], result)
        return result

    pending = CORE_RUNTIME.skills.pending().get(normalized_id)
    if pending:
        skill = str(pending.get("name") or pending.get("skill") or "")
        original_arguments = dict(pending.get("arguments") or {})
        tool_arguments = {
            "skill": skill,
            "arguments_json": json.dumps(original_arguments, ensure_ascii=False),
        }
        _stampa_tool_inizio("expansion_call", tool_arguments)
        result = CORE_RUNTIME.skills.confirm(normalized_id)
        normalized = _normalize_confirmed_skill_result(skill, original_arguments, result)
        _stampa_tool_risultato("expansion_call", normalized)
        return normalized

    return {"successo": False, "messaggio": "Conferma scaduta o inesistente."}


def conferma_ultima_azione(pin=None):
    actions = pending_confirmation_actions()
    if not actions:
        return {"successo": False, "messaggio": "Non ci sono azioni in attesa di conferma."}
    if len(actions) > 1:
        labels = ", ".join(
            f"{row['action_id']} ({row.get('skill') or row.get('tool') or 'azione'})" for row in actions
        )
        return {
            "successo": False,
            "messaggio": f"Ci sono piu azioni in attesa. Indica l'action_id da confermare: {labels}.",
            "richiede_selezione": True,
        }
    return conferma_azione(actions[0]["action_id"], pin)


def annulla_azione(action_id=None):
    """Cancel one pending action without executing it."""
    actions = pending_confirmation_actions()
    normalized_id = str(action_id or "").strip().lower()
    if normalized_id:
        selected = next((row for row in actions if row["action_id"].lower() == normalized_id), None)
        if selected is None:
            return {"successo": False, "messaggio": "Azione in attesa non trovata o scaduta."}
    elif len(actions) > 1:
        labels = ", ".join(
            f"{row['action_id']} ({row.get('skill') or row.get('tool') or 'azione'})" for row in actions
        )
        return {
            "successo": False,
            "messaggio": f"Ci sono piu azioni in attesa. Indica l'action_id da annullare: {labels}.",
            "richiede_selezione": True,
        }
    elif not actions:
        return {"successo": False, "messaggio": "Non ci sono azioni in attesa di conferma."}
    else:
        selected = actions[0]

    if selected.get("source") == "action_guard":
        removed = cancel_action_guard(selected["action_id"])
    else:
        removed = CORE_RUNTIME.skills.cancel(selected["action_id"])
    if removed is None:
        return {"successo": False, "messaggio": "Azione in attesa non trovata o scaduta."}
    message = "Azione annullata."
    audit_record("confirmation_cancelled", action_id=selected["action_id"], tool=selected.get("tool"), skill=selected.get("skill"))
    _record_operational_tool_result(
        str(selected.get("tool") or "expansion_call"),
        dict(selected.get("arguments") or {}),
        {"successo": False, "messaggio": message, "azione_id": selected["action_id"]},
    )
    return {"successo": True, "messaggio": message, "azione_id": selected["action_id"]}


# ============================================================
# CAPISCE SE MINIMIZZARE HUD
# ============================================================

def tool_richiede_minimizzazione(
    nome_tool,
    risultato
):

    if not risultato.get(
        "successo",
        False
    ):

        return False


    tool_minimizza = {
        "apri_programma",
        "apri_sito",
        "apri_percorso",
        "apri_task_manager",
        "apri_esplora_file",
        "apri_impostazioni"
        ,"visual_task"
        ,"delegate_agent_task", "browser_agent_task", "ufo_agent_task", "ui_tars_agent_task"
    }


    return nome_tool in tool_minimizza


# ============================================================
# SYSTEM PROMPT ROUTER
# ============================================================

ISTRUZIONI = """
Sei il sistema di controllo del computer di JARVIS.

Sei realmente collegato agli strumenti Windows elencati in questa richiesta.
Non dichiarare mai di non poter controllare il computer, mouse, tastiera,
programmi, browser o file. Quando l'utente impartisce un ordine operativo,
usa gli strumenti disponibili; se manca un dato indispensabile, chiedi solo
quel dato. Se uno strumento fallisce, riferisci il suo errore reale senza
trasformarlo in una generica dichiarazione di impossibilità.

Il tuo compito NON è fare conversazione generale.

Quando la richiesta nomina una delle espansioni avanzate installate in JARVIS
(DXcam, Docling, MarkItDown, Crawl4AI, Screenpipe, MCP/FastMCP, Watchdog,
Qdrant, Ruff, Silero VAD, Home Assistant, ESPHome, LiteLLM, Ollama, llama.cpp,
OpenHands, SearXNG o Keyring), usa expansion_call con la skill appropriata.
Non rispondere mai che una di queste operazioni e stata eseguita se non hai
ricevuto successo=true/successo=true dal relativo tool.
Esempi:
- "cattura lo schermo con DXcam" -> skill "screen.dxcam.capture", arguments_json "{}"
- "leggi X.pdf con Docling" -> skill "documents.docling", arguments_json con path
- "studia https://... con Crawl4AI" -> skill "web.crawl4ai", arguments_json con url
- "mostra gli ultimi file cambiati" -> skill "watchdog.recent"


Devi capire se la richiesta dell'utente richiede azioni
sul computer Windows usando gli strumenti disponibili.

Puoi usare più strumenti consecutivamente.

Esempi:

"Apri Chrome e massimizzalo"

può richiedere:
1. apri_programma
2. elenco_finestre oppure porta_finestra_davanti
3. massimizza_finestra

"Apri Spotify e metti il volume al 30 percento"

può richiedere:
1. apri_programma
2. imposta_volume

"Crea sul Desktop una cartella Progetto CRF e aprila"

può richiedere:
1. crea_cartella
2. apri_percorso

"Apri Blocco Note e scrivi ciao"

può richiedere:
1. apri_programma
2. scrivi_testo

Puoi utilizzare il risultato di un tool per decidere
quale tool usare dopo.

Quando un'azione dipende dalla finestra appena aperta,
usa eventualmente elenco_finestre per conoscere il titolo reale.

Il campo successo e il campo verification restituiti da uno strumento sono
vincolanti: se indicano errore o risultato non verificato, non dire mai "Fatto"
e non descrivere l'azione come completata.

Per interagire con un'app prova sempre questa gerarchia: prima inspect_ui e
i controlli ui_invoke/ui_set_value; poi strumenti diretti; usa visual_task
soltanto se l'app non espone controlli accessibili. Mouse e coordinate sono
l'ultima risorsa. Dopo un'azione strutturata richiama inspect_ui per verificare.
Per Chrome usa prima chrome_snapshot e chrome_action: il DOM è più affidabile
dell'accessibilità e della visione. Dopo chrome_action richiama chrome_snapshot.

Per workflow lunghi o interfacce che gli strumenti nativi non riescono a gestire
in modo robusto puoi usare gli agenti esterni. browser_agent_task è specializzato
nel browser; ufo_agent_task nei workflow Windows; ui_tars_agent_task è il fallback
visuale. delegate_agent_task usa LangGraph per routing e fallback tra questi backend.
Non delegare una semplice azione se inspect_ui, chrome_action o uno strumento diretto
la possono eseguire e verificare deterministicamente. Gli agenti esterni non devono
gestire password, OTP, pagamenti, acquisti o ordini finanziari.

Non inventare coordinate del mouse quando non puoi conoscerle.

Quando serve puoi vedere davvero lo schermo con analizza_schermo.
Usalo per leggere errori, comprendere interfacce nuove e verificare
il risultato di azioni importanti. Per trovare una posizione usa
individua_elemento e poi, solo se la confidenza e adeguata, muovi_mouse
o clicca. Non interagire con pagamenti, password, OTP o ordini finanziari.

Quando la richiesta richiede comprendere e manipolare un'interfaccia visibile
per più passaggi, preferisci visual_task invece di concatenare coordinate
ipotetiche. Esempi: cercare un canale su YouTube e riprodurre il terzo video,
usare menu di un'app sconosciuta, compilare campi non sensibili, verificare che
un pulsante abbia prodotto l'effetto richiesto. Scrivi nel campo task l'intero
obiettivo finale e il contesto utile; non spezzarlo in singoli clic.

Non usare mouse e click casualmente se non conosci le coordinate.

Le azioni distruttive o critiche come:

- eliminazione di file;
- spegnimento del computer;
- riavvio;
- sospensione;
- chiusura forzata di processi;
- comandi amministrativi arbitrari.

sono classificate dal permission engine e, quando la policy lo richiede,
devono attendere la conferma esplicita dell'utente prima dell'esecuzione.
Verifica con particolare attenzione il bersaglio prima di chiamarle.

Per attivita complesse procedi per passi ordinati. Dopo ogni strumento
controlla il risultato prima di continuare e non dichiarare riuscita
un'azione se il risultato segnala un errore. Se fallisce, osserva lo stato,
prova una strategia alternativa sicura e verifica nuovamente il risultato.
Quando l'esito non e verificabile dai dati del tool, usa analizza_schermo.

Se l'utente chiede di creare, costruire o sviluppare un bot, un programma,
un sito o un'automazione, non limitarti a spiegare come fare: usa
create_project per generare davvero una struttura multi-file completa.
Includi almeno un README con istruzioni di avvio e i file delle dipendenze
quando necessari. Dopo la creazione usa apri_percorso sul percorso restituito,
salvo che l'utente abbia chiesto di non aprirlo.

Per richieste composte completa tutti i passaggi nell'ordine richiesto.
Non fermarti dopo la prima azione se nella frase sono presenti "e", "poi" o
un risultato finale ancora non raggiunto. Verifica sempre l'ultimo passaggio.

Per un grafico TradingView usa analyze_trading_chart, non la descrizione visiva
generica. Non eseguire mai ordini finanziari come conseguenza dell'analisi.
Per "continua", "quello di prima" o riferimenti ambigui usa context_state.
Quando crei software, usa inspect_project e test_project per validarlo e
correggilo autonomamente se i test falliscono prima di dichiararlo funzionante.

Se la richiesta è solamente una normale domanda,
una spiegazione, una conversazione oppure una richiesta
di informazioni che non richiede controllo del computer,
NON usare strumenti.

In quel caso termina senza chiamare alcun tool.

Se hai usato uno o più strumenti, alla fine produci
una conferma molto breve e naturale in italiano.

Non usare Markdown.
Non usare asterischi.
Non descrivere tecnicamente i tool utilizzati.

Esempio finale:
"Fatto. Ho aperto Chrome e l'ho massimizzato."
""".strip()

ISTRUZIONI += "\n\n" + policy_guidance()


# ============================================================
# INTERPRETA COMANDO
# ============================================================

def _notifica_prima_azione(callback, nome_tool, argomenti):
    if not callback:
        return
    if nome_tool == "apri_programma" and str((argomenti or {}).get("nome") or "").casefold() in {"blocco note", "notepad"}:
        return
    try:
        callback(nome_tool, dict(argomenti or {}))
    except Exception as exc:
        print("PRE-ACTION CALLBACK ERROR:", redact(repr(exc)))


def _qdrant_search_rows(risultato):
    """Extract backend-returned Qdrant payloads without inventing content."""
    data = risultato.get("dati") if isinstance(risultato, dict) else {}
    points = data.get("points") if isinstance(data, dict) else []
    if not isinstance(points, list):
        return []
    rows = []
    for point in points[:8]:
        if not isinstance(point, dict):
            continue
        payload = point.get("payload") if isinstance(point.get("payload"), dict) else {}
        text = str(payload.get("text") or payload.get("content") or "").strip()
        if not text:
            continue
        row = {"text": text}
        score = point.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            row["score"] = round(float(score), 4)
        if point.get("id") is not None:
            row["id"] = str(point["id"])
        metadata = {key: value for key, value in payload.items() if key not in {"text", "content"}}
        if metadata:
            row["metadata"] = metadata
        rows.append(row)
    return rows


def _qdrant_result_message(skill, risultato):
    if skill == "qdrant.add":
        return "Memoria aggiunta a Qdrant."
    data = risultato.get("dati") if isinstance(risultato, dict) else {}
    points = data.get("points") if isinstance(data, dict) else []
    if not isinstance(points, list) or not points:
        return "Non ho trovato risultati in Qdrant."
    rows = _qdrant_search_rows(risultato)
    if not rows:
        return "Qdrant ha restituito risultati senza un testo leggibile."
    excerpts = []
    for row in rows[:5]:
        text = row["text"]
        if len(text) > 700:
            text = text[:697].rstrip() + "..."
        suffix = f" (score {row['score']:.4f})" if "score" in row else ""
        excerpts.append(f"{text}{suffix}")
    return "Ho trovato in Qdrant: " + " | ".join(excerpts)


def _stampa_tool_inizio(nome_tool, argomenti):
    display_arguments = dict(argomenti or {})
    expansion_skill = ""
    if nome_tool == "expansion_call":
        try:
            parsed = json.loads(str(display_arguments.get("arguments_json") or "{}"))
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            expansion_skill = str(display_arguments.get("skill") or "")
            display_arguments = {"skill": expansion_skill, "arguments": parsed}
    display_arguments = redact(display_arguments)
    if expansion_skill == "secrets.store" and isinstance(display_arguments.get("arguments"), dict):
        # Keep the diagnostic shape useful while ensuring the real credential
        # value never appears in console output.
        display_arguments["arguments"]["secret"] = "***REDACTED***"
    print()
    print("======================================")
    print("TOOL:", nome_tool)
    print("ARGOMENTI:", display_arguments)


def _stampa_tool_risultato(nome_tool, risultato):
    value = dict(risultato or {})
    console_result = {
        "successo": value.get("successo"),
        "messaggio": str(value.get("messaggio") or "")[:500],
    }
    if value.get("skill"):
        console_result["skill"] = str(value["skill"])
    if value.get("errore"):
        console_result["errore"] = str(value["errore"])[:500]
    if value.get("richiede_conferma"):
        console_result["richiede_conferma"] = True
    if value.get("azione_id"):
        console_result["azione_id"] = str(value["azione_id"])
    if value.get("rischio"):
        console_result["rischio"] = str(value["rischio"])
    verification = value.get("verification")
    if isinstance(verification, dict):
        console_result["verification"] = {
            "status": verification.get("status"),
            "strength": verification.get("strength"),
            "evidence": str(verification.get("evidence") or "")[:500],
        }
    data = value.get("dati")
    if isinstance(data, dict):
        console_result["dati_keys"] = sorted(map(str, data.keys()))[:30]
        skill = str(value.get("skill") or "")
        if nome_tool == "expansion_call" and skill == "qdrant.add":
            console_result["dati"] = redact(
                {key: data.get(key) for key in ("id", "collection", "verified", "verification_evidence") if key in data}
            )
        elif nome_tool == "expansion_call" and skill == "qdrant.search":
            console_result["dati"] = redact(
                {
                    "collection": data.get("collection"),
                    "verified": data.get("verified"),
                    "points": _qdrant_search_rows(value)[:5],
                }
            )
    print("RISULTATO:", redact(console_result))
    print("======================================")


def _sequenza_comandi_locale(value):
    """Riconosce le concatenazioni operative comuni senza affidarsi al modello."""
    import re

    patterns = (
        (
            r"^(?:apri|aprimi|avvia|lancia)\s+(.+?)\s+(?:e\s+)?(?:poi\s+)?(?:vai|naviga)\s+(?:su|a)\s+(.+)$",
            lambda match: [
                ("apri_programma", {"nome": match.group(1).strip()}),
                ("apri_sito", {"nome": match.group(2).strip()}),
            ],
        ),
        (
            r"^(?:apri|aprimi|avvia|lancia)\s+(.+?)\s+(?:e\s+)?(?:poi\s+)?(?:scrivi|digita)\s+(.+)$",
            lambda match: [
                ("apri_programma", {"nome": match.group(1).strip()}),
                ("scrivi_testo", {"testo": match.group(2).strip()}),
            ],
        ),
    )
    for pattern, build in patterns:
        match = re.fullmatch(pattern, value, flags=re.IGNORECASE)
        if match:
            return build(match)
    return None


def _richiesta_capacita_operativa(value):
    import re

    normalized = " ".join(str(value or "").casefold().split())
    if re.match(
        r"^(?:puoi|potresti|riesci a)\s+(?:aprire|aprirmi|chiudere|avviare|lanciare|cliccare|"
        r"scrivere|digitare|eliminare|spostare|rinominare|spegnere|riavviare|sospendere)\b",
        normalized,
    ):
        return False
    capability_phrases = (
        "cosa sai fare", "cosa puoi fare", "quali capacità", "quali capacita",
        "puoi controllare il computer", "puoi controllare direttamente",
        "hai accesso al computer", "hai accesso al mio computer",
        "sei in grado di controllare", "puoi usare mouse", "puoi usare il mouse",
        "puoi usare tastiera", "puoi usare la tastiera",
    )
    return any(phrase in normalized for phrase in capability_phrases) or bool(
        re.search(r"\b(?:puoi|riesci|sei in grado)\b.*\b(?:computer|pc|windows|mouse|tastiera|file|chrome)\b", normalized)
    )


def _interpreta_watchdog_locale(value, on_before_action=None):
    """Route natural filesystem-monitor commands to the core-owned registry."""
    import re

    text = " ".join(str(value or "").strip().split())
    lower = text.casefold()
    if any(phrase in lower for phrase in ("quali cartelle stai monitorando", "elenca monitoraggi", "monitoraggi attivi")):
        result = CORE_RUNTIME.skills.execute("watchdog.list")
        rows = list((result.data or {}).get("watchers", []))
        return True, "Nessuna cartella è attualmente monitorata." if not rows else "Monitoraggi attivi: " + "; ".join(row["path"] for row in rows), False
    if not any(marker in lower for marker in ("monitor", "tieni d'occhio", "tieni d’occhio", "avvisami quando")):
        return None

    if re.search(r"(?:ferma|smetti|interrompi)\s+(?:tutti|ogni)\s+monitor", lower) or "ferma tutti i monitoraggi" in lower:
        result = CORE_RUNTIME.skills.execute("watchdog.stop", all_watchers=True)
        return True, result.message, False

    path_match = re.search(r"([A-Za-z]:[\\/].*?)(?=\s+(?:e|quando|poi|avvisami|che)\s+|[.!?]|$)", text)
    path = path_match.group(1).strip().rstrip(".,;:") if path_match else None
    if re.search(r"(?:smetti|ferma|interrompi|non\s+monitorare)", lower):
        if not path:
            return True, "Indica la cartella da smettere di monitorare.", False
        result = CORE_RUNTIME.skills.execute("watchdog.stop", path=path)
        return True, result.message, False
    if not path:
        return True, "Indica il percorso completo della cartella da monitorare.", False

    events = []
    if re.search(r"creat|nuov|aggiunt", lower): events.append("created")
    if re.search(r"modificat|cambi|aggiorn", lower): events.append("modified")
    if re.search(r"eliminat|cancellat|rimoss", lower): events.append("deleted")
    if re.search(r"spostat|rinominat", lower): events.append("moved")
    if not events:
        events = ["created", "modified", "deleted", "moved"]
    result = CORE_RUNTIME.skills.execute("watchdog.start", path=path, events=events, recursive=False)
    if not result.success:
        return True, result.message, False
    return True, result.message, False


def _interpreta_expansion_deterministica(testo, on_before_action=None):
    """Execute requests whose registered Expansion skill and payload are unambiguous."""
    match = match_expansion_skill(CORE_RUNTIME.skills, testo)
    if match is None or match["skill"] not in {"qdrant.add", "qdrant.search", "secrets.store", "secrets.delete", "litellm.complete"}:
        return None
    skill = str(match["skill"])
    if skill.startswith("qdrant."):
        arguments = qdrant_arguments(skill, testo)
    elif skill.startswith("secrets."):
        arguments = secrets_arguments(skill, testo)
    else:
        arguments = litellm_arguments(testo)
    if arguments is None:
        if skill == "secrets.store":
            return True, "Indica servizio, username e segreto da salvare nel Keyring.", False
        if skill == "secrets.delete":
            return True, "Indica servizio e username della credenziale da eliminare.", False
        if skill == "litellm.complete":
            return True, "Indica il modello e il prompt da inviare a LiteLLM.", False
        action = "memorizzare" if skill == "qdrant.add" else "cercare"
        return True, f"Indica il testo da {action} con Qdrant.", False
    payload = {
        "skill": skill,
        "arguments_json": json.dumps(arguments, ensure_ascii=False),
    }
    _notifica_prima_azione(on_before_action, "expansion_call", payload)
    _stampa_tool_inizio("expansion_call", payload)
    result = esegui_tool("expansion_call", payload)
    _stampa_tool_risultato("expansion_call", result)
    if result.get("richiede_conferma"):
        return True, f"Non ho eseguito l'operazione: {result.get('messaggio') or 'conferma utente richiesta.'}", False
    if not result.get("successo"):
        return True, str(result.get("messaggio") or "L'operazione Expansion non è riuscita."), False
    if not verified_success(result):
        return True, "Non posso confermare l'operazione: il risultato Expansion non è verificato.", False
    if skill == "litellm.complete":
        data = result.get("dati") if isinstance(result.get("dati"), dict) else {}
        return True, str(data.get("text") or result.get("messaggio") or "LiteLLM ha restituito una risposta vuota."), False
    return True, _qdrant_result_message(skill, result), False


def _interpreta_comando_locale(testo, on_before_action=None):
    """Percorso immediato per comandi semplici e non ambigui."""
    import re
    from app_paths import data_path
    watchdog_result = _interpreta_watchdog_locale(testo, on_before_action)
    if watchdog_result is not None:
        return watchdog_result
    from transcript_repair import repair_transcript
    repair = repair_transcript(testo)
    if repair.raw_transcript and repair.normalized_transcript != repair.raw_transcript:
        print(
            f"[STT REPAIR] STT RAW: {repair.raw_transcript} | NORMALIZED: "
            f"{repair.normalized_transcript} | REASON: {repair.reason} | "
            f"CONFIDENCE: {repair.confidence:.2f}"
        )
        audit_record(
            "transcript_repair",
            raw_transcript=repair.raw_transcript,
            normalized_transcript=repair.normalized_transcript,
            reason=repair.reason,
            confidence=round(repair.confidence, 3),
        )
    if repair.clarification:
        return True, "Vuoi " + " o ".join(repair.clarification) + "?", False
    value = re.sub(r"[\s.!?,;:]+$", "", repair.normalized_transcript or str(testo or "").strip())
    capability_request = _richiesta_capacita_operativa(value)
    value = re.sub(r"^(?:jarvis[\s,;:]+)?(?:per favore\s+)?", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:puoi|potresti)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+per favore$", "", value, flags=re.IGNORECASE)
    lower = value.lower()
    if capability_request:
        return (
            True,
            "Sì. Sono collegato agli strumenti locali di JARVIS: posso controllare finestre, mouse e tastiera, "
            "aprire e chiudere programmi, usare Chrome e le pagine web, leggere e organizzare file, eseguire "
            "automazioni, gestire impostazioni Windows, creare file e progetti, analizzare lo schermo e il "
            "grafico TradingView, gestire memoria, obiettivi e routine. Posso inoltre usare, se installati e "
            "configurati, Browser Use, Microsoft UFO e UI-TARS per workflow agentici più lunghi. Limiti: non invio email, non eseguo "
            "ordini o pagamenti, non inserisco password o OTP, non aggiro permessi di sicurezza e non dichiaro "
            "completata un'azione se Windows non la conferma. Le azioni sensibili richiedono conferma esplicita.",
            False,
        )
    if lower in {"/health", "/status", "esegui diagnostica completa", "jarvis esegui diagnostica completa"}:
        diagnostics = CORE_RUNTIME.diagnostics()
        health = diagnostics["health"]
        if not health:
            message = "Diagnostica disponibile, ma nessun componente ha ancora pubblicato il proprio stato."
        else:
            summary = ", ".join(f"{name}: {row['status']}" for name, row in sorted(health.items()))
            message = f"Diagnostica completata. {summary}."
        return True, message, False
    if lower == "/doctor":
        result = CORE_RUNTIME.doctor.run()
        summary = result["summary"]
        return True, f"Diagnostica {result['status']}: {summary['total']} controlli, {summary['failed']} falliti, {summary['degraded']} degradati.", False
    if lower in {"/evaluation", "/evaluations", "analizza le valutazioni", "controlla le regressioni", "analizza le regressioni"}:
        from continuous_improvement import analyze_evaluations
        trend = analyze_evaluations()
        status = trend.get("status", "NO_DATA")
        considered = trend.get("reports_considered", 0)
        regressions = trend.get("regressions", [])
        if status == "NO_DATA":
            return True, "Non ci sono ancora abbastanza valutazioni reali per calcolare un trend.", False
        if regressions:
            details = "; ".join(str(row.get("message", row.get("id", "scenario"))) for row in regressions[:3])
            return True, f"Trend {status}: {len(regressions)} regressioni su {considered} report. {details}", False
        return True, f"Trend {status}: nessuna regressione rilevata su {considered} report. Il sistema è stabile.", False
    if lower in {"/integrations", "/integrazioni"}:
        status = integration_status(False)
        data = status.get("dati", {})
        summary = ", ".join(f"{name}: {'OK' if row.get('successo') else 'OFF'}" for name, row in sorted(data.items()))
        return True, f"Stato integrazioni: {summary}.", False
    if lower == "/missions":
        missions = CORE_RUNTIME.mission_store.recent(20)
        return True, f"Missioni registrate: {len(missions)}.", False
    if lower in {"/explain","perché stai facendo questo","perche stai facendo questo","perché lo stai facendo","perche lo stai facendo"}:
        explanation=CORE_RUNTIME.missions.explain()
        return True,explanation["message"],False
    if lower == "/memory":
        memories = CORE_RUNTIME.memory.search(limit=20)
        return True, f"Memorie attive trovate: {len(memories)}.", False
    if lower.startswith("/search "):
        results = CORE_RUNTIME.search.search(value.split(" ",1)[1],limit=20)
        top = "; ".join(f"{row['source']}: {row['title']}" for row in results[:5])
        return True, f"Risultati trovati: {len(results)}. {top}".strip(), False
    if lower == "/skills":
        skills=CORE_RUNTIME.skills.list()
        return True,f"Skill registrate: {len(skills)}. "+", ".join(row["name"] for row in skills),False
    if lower == "/automations":
        report = CORE_RUNTIME.automation.report()
        runs = sum(row["count"] for row in report["runs"].values())
        return True, f"Automazioni registrate: {report['automations']}. Esecuzioni storiche: {runs}.", False
    if lower == "/performance":
        from performance_metrics import report
        metrics = report()["dati"]
        measured = sum(1 for value in metrics.values() if isinstance(value, dict))
        return True, f"Metriche disponibili per {measured} componenti.", False
    if lower == "/logs":
        log_path = data_path("logs") / "jarvis.jsonl"
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        return True, f"Log runtime disponibili: {len(lines)} eventi.", False
    sequence = _sequenza_comandi_locale(value)
    if sequence:
        messages = []
        minimize = False
        for tool_name, arguments in sequence:
            _notifica_prima_azione(on_before_action, tool_name, arguments)
            result = esegui_tool(tool_name, arguments)
            messages.append(str(result.get("messaggio") or ""))
            minimize = minimize or tool_richiede_minimizzazione(tool_name, result)
            if not result.get("successo"):
                return True, messages[-1] or "Operazione non riuscita.", minimize
        return True, " ".join(message for message in messages if message).strip() or "Fatto.", minimize
    direct = {
        "mostra desktop": ("mostra_desktop", {}),
        "mostra il desktop": ("mostra_desktop", {}),
        "vai al desktop": ("mostra_desktop", {}),
        "apri task manager": ("apri_task_manager", {}),
        "apri gestione attività": ("apri_task_manager", {}),
        "apri esplora file": ("apri_esplora_file", {}),
        "apri le impostazioni": ("apri_impostazioni", {}),
        "apri impostazioni": ("apri_impostazioni", {}),
        "apri le impostazioni di windows": ("apri_impostazioni", {}),
        "apri impostazioni windows": ("apri_impostazioni", {}),
        "metti in muto": ("imposta_muto", {"attivo": True}),
        "togli il muto": ("imposta_muto", {"attivo": False}),
        "spegni il pc": ("spegni_pc", {}),
        "spegni pc": ("spegni_pc", {}),
        "spegni il computer": ("spegni_pc", {}),
        "riavvia il pc": ("riavvia_pc", {}),
        "riavvia pc": ("riavvia_pc", {}),
        "riavvia il computer": ("riavvia_pc", {}),
        "sospendi il pc": ("sospendi_pc", {}),
        "sospendi pc": ("sospendi_pc", {}),
        "blocca il pc": ("blocca_pc", {}),
    }
    command = direct.get(lower)
    if not command:
        match = re.fullmatch(r"(?:imposta (?:il )?volume|volume) (?:al |a )?(\d{1,3})(?: percento|%)?", lower)
        if match and 0 <= int(match.group(1)) <= 100:
            command = ("imposta_volume", {"percentuale": int(match.group(1))})
    if not command:
        match = re.fullmatch(r"(?:apri|aprimi|aprire|avvia|avviare|lancia|lanciare)\s+([^,;]+)", value, flags=re.IGNORECASE)
        if match and not re.search(r"\s+(?:e|poi|quindi)\s+", match.group(1), flags=re.IGNORECASE):
            target = re.sub(r"^(?:il|lo|la|l'|un|una)\s*", "", match.group(1).strip(), flags=re.IGNORECASE)
            command = ("apri_programma", {"nome": target})
    if not command:
        match = re.fullmatch(r"(?:scrivi|digita)\s+(.+)", value, flags=re.IGNORECASE)
        if match:
            testo = match.group(1).strip()
            active = finestra_attiva()
            active_title = str((active.get("dati") or {}).get("titolo") or "").casefold() if isinstance(active, dict) else ""
            if "blocco note" not in active_title and "notepad" not in active_title:
                focus_result = porta_finestra_davanti("Blocco note")
                if not focus_result.get("successo"):
                    return True, "Non ho scritto: Blocco note non è disponibile per la verifica.", False
            _notifica_prima_azione(on_before_action, "scrivi_testo", {"testo": testo})
            write_result = esegui_tool("scrivi_testo", {"testo": testo})
            if not write_result.get("successo"):
                return True, str(write_result.get("messaggio") or "Non sono riuscito a scrivere il testo."), False
            esegui_tool("seleziona_tutto", {})
            copied = esegui_tool("copia_selezione", {})
            clipboard = str((copied.get("dati") or {}).get("clipboard") or "") if isinstance(copied, dict) else ""
            esegui_tool("premi_tasto", {"tasto": "end"})
            if testo not in clipboard:
                return True, "Non confermo la scrittura: il testo non è stato verificato in Blocco note.", False
            return True, "Ho scritto e verificato il testo in Blocco note.", False
    if not command:
        match = re.fullmatch(r"(?:vai|naviga)\s+(?:su|a)\s+(.+)", value, flags=re.IGNORECASE)
        if match:
            command = ("apri_sito", {"nome": match.group(1).strip()})
    if not command:
        match = re.fullmatch(r"cerca su google\s+(.+)", value, flags=re.IGNORECASE)
        if match:
            command = ("cerca_google", {"query": match.group(1).strip()})
    if not command:
        match = re.fullmatch(r"(?:chiudi|termina)\s+(.+)", value, flags=re.IGNORECASE)
        if match:
            command = ("chiudi_programma", {"nome": match.group(1).strip()})
    if not command:
        return None
    tool_name, arguments = command
    _notifica_prima_azione(on_before_action, tool_name, arguments)
    result = esegui_tool(tool_name, arguments)
    message = str(result.get("messaggio") or ("Fatto." if result.get("successo") else "Operazione non riuscita."))
    return True, message, tool_richiede_minimizzazione(tool_name, result)

def interpreta_comando(
    testo,
    on_before_action=None,
    cognitive_decision=None,
):

    """
    Restituisce:

    comando, risposta, minimizza

    Se è una normale domanda:

    False, None, False

    Se ha eseguito azioni sul PC:

    True, "Fatto...", True/False
    """


    if not testo:

        return (
            False,
            None,
            False
        )

    # Il percorso deterministico locale è una garanzia funzionale, non solo
    # un'ottimizzazione: disattivare performance_mode non deve far perdere
    # comandi semplici (apri, chiudi, volume, navigazione, sequenze).
    # The canonical decision is the policy gate, not a post-hoc annotation.
    # Safety/permission/confirmation checks still run in the executors below.
    if cognitive_decision is None:
        cognitive_decision = CORE_RUNTIME.cognition.decide(testo)
    if (
        cognitive_decision.needs_clarification
        or cognitive_decision.negated
        or not cognitive_decision.needs_tools
    ):
        return False, None, False

    fast_result = _interpreta_comando_locale(testo, on_before_action)
    if fast_result is not None:
        return fast_result
    expansion_result = _interpreta_expansion_deterministica(testo, on_before_action)
    if expansion_result is not None:
        return expansion_result

    router_input = _with_active_window_context(testo)
    mission_mode = bool(get_setting("cognitive_mission_mode", True) and cognitive_decision.mission_required)
    mission_plan = None
    orchestrator = getattr(CORE_RUNTIME, "orchestrator", None)
    orchestration_run_id = None
    if mission_mode:
        mission_plan = plan_mission(
            client,
            str(get_setting("ai_model", MODELLO_ROUTER)),
            testo,
            json.dumps(CORE_RUNTIME.context.snapshot(), ensure_ascii=False),
        )
        if orchestrator is not None:
            orchestration_run_id = orchestrator.begin(testo, mission_plan)
        router_input = (
            f"{router_input}\n\nPIANO DI MISSION CONTROL (adattabile):\n"
            f"{json.dumps(mission_plan, ensure_ascii=False)}\n"
            "CATALOGO CAPABILITY DISPONIBILI (dal registry, scegli solo ciò che serve):\n"
            f"{orchestrator.planning_context(testo, mission_plan) if orchestrator is not None else '{}'}\n"
            "Esegui il piano, raccogli prove e non concludere prima dei criteri di successo."
        )


    # ========================================================
    # PRIMA RICHIESTA
    # ========================================================

    reasoning_effort = _router_effort(testo)

    try:

        router_model = select_model("router", "complex" if mission_mode else "simple")
        request = {"model": router_model, "instructions": ISTRUZIONI, "input": router_guidance(cognitive_decision) + "\n" + router_input,
                   "tools": TOOLS, "parallel_tool_calls": False}
        reasoning = reasoning_options(router_model, reasoning_effort)
        if reasoning is not None:
            request["reasoning"] = reasoning
        try:
            risposta = client.responses.create(**request)
        except Exception as first_error:
            # Provider/model deployments can expose a newer effort vocabulary
            # before the local capability table is updated. Retry once without
            # the optional reasoning field so a harmless router incompatibility
            # can never prevent an otherwise valid computer command.
            if "reasoning" not in request:
                raise
            retry_request = dict(request)
            retry_request.pop("reasoning", None)
            audit_record("router_reasoning_retry", model=router_model, error=redact(repr(first_error)))
            risposta = client.responses.create(**retry_request)


    except Exception as e:

        print()
        print(
            "❌ ERRORE ROUTER:"
        )

        print(redact(repr(e)))


        if _looks_action_request(testo):
            return (
                True,
                "Non ho eseguito il comando perché il motore operativo non è raggiungibile. Riprova tra poco.",
                False,
            )

        # Solo le vere domande conversazionali passano ad ai.py.
        return (
            False,
            None,
            False
        )


    # ========================================================
    # STATO AGENTE
    # ========================================================

    ha_usato_tool = False
    job_id = None

    minimizza_hud = False
    review_rounds = 0
    critic_complete = None
    tool_failures = []
    tool_pending = []
    tool_unverified = []
    tool_successes = []
    tool_schema_errors = []


    # Manteniamo gli output restituiti dal modello.
    # Nella Responses API il ciclo dei tool deve conservare anche l'input
    # originale. Senza questa riga, dopo la prima azione il modello perdeva
    # i passaggi successivi (es. apriva Chrome ma dimenticava YouTube).
    input_successivo = [
        {"role": "user", "content": router_input}
    ]
    input_successivo.extend(
        risposta.output
    )


    # ========================================================
    # LOOP MULTI-AZIONE
    # ========================================================

    for _passaggio in range(
        MAX_PASSAGGI
    ):


        chiamate = []


        for elemento in risposta.output:

            if getattr(
                elemento,
                "type",
                None
            ) == "function_call":

                chiamate.append(
                    elemento
                )


        # ====================================================
        # NESSUNA FUNCTION CALL
        # ====================================================

        if not chiamate:


            # Mai usato tool?
            # Allora è una domanda normale
            # e deve andare ad ai.py.

            if not ha_usato_tool:

                print()
                print(
                "ROUTER: domanda normale"
                )


                if _looks_action_request(testo):
                    return (
                        True,
                        "Non ho eseguito alcuna azione: il comando non è stato associato con sicurezza a uno strumento.",
                        False,
                    )
                return (False, None, False)


            # =================================================
            # TOOL USATI -> RISPOSTA FINALE
            # =================================================

            testo_finale = getattr(
                risposta,
                "output_text",
                ""
            ).strip()


            if not testo_finale:

                testo_finale = (
                    "Fatto."
                )

            # Nelle missioni complesse un secondo modello, senza accesso agli
            # strumenti, controlla piano e prove. Se trova lacune restituiamo
            # il feedback all'esecutore e il ciclo riparte automaticamente.
            if mission_mode and job_id:
                mission = get_agent_job(job_id) or {}
                review = review_mission(
                    client,
                    str(get_setting("ai_model", MODELLO_ROUTER)),
                    testo,
                    mission.get("plan") or mission_plan or {},
                    mission.get("steps", []),
                    testo_finale,
                )
                agent_add_review(job_id, review)
                min_confidence = float(get_setting("critic_min_confidence", 0.65))
                max_review_rounds = max(0, min(int(get_setting("critic_max_rounds", 2)), 4))
                critic_complete = bool(review.get("complete")) and float(review.get("confidence", 0)) >= min_confidence
                if not critic_complete and review_rounds < max_review_rounds:
                    review_rounds += 1
                    feedback = {
                        "critic_round": review_rounds,
                        "missing": review.get("missing", []),
                        "next_action": review.get("next_action", ""),
                    }
                    input_successivo.append({
                        "role": "user",
                        "content": (
                            "REVISIONE INDIPENDENTE: la missione non è ancora dimostrata completa. "
                            f"{json.dumps(feedback, ensure_ascii=False)} "
                            "Continua con gli strumenti necessari, correggi le lacune e raccogli nuove prove."
                        ),
                    })
                    try:
                        risposta = client.responses.create(
                            model=select_model("router", "complex"),
                            instructions=ISTRUZIONI,
                            input=input_successivo,
                            tools=TOOLS,
                            parallel_tool_calls=False,
                            reasoning={"effort": "medium"},
                        )
                        input_successivo.extend(risposta.output)
                        continue
                    except Exception as exc:
                        audit_record("critic_recovery_failed", job_id=job_id, error=redact(repr(exc)))
                if critic_complete:
                    testo_finale = str(review.get("summary") or testo_finale)
                else:
                    testo_finale = "La missione resta aperta: il controllo indipendente non ha trovato prove sufficienti per dichiararla completata."

            # Il testo finale del modello non può trasformare un risultato
            # negativo in una conferma positiva. Restituiamo sempre l'errore
            # effettivamente prodotto dal tool.
            if tool_failures:
                dettagli = "; ".join(dict.fromkeys(row["message"] for row in tool_failures))
                testo_finale = f"Non ho completato l'operazione. {dettagli}"
            elif tool_schema_errors:
                dettagli = "; ".join(dict.fromkeys(row["message"] for row in tool_schema_errors))
                testo_finale = f"Gli argomenti della chiamata non sono validi. {dettagli}"
            elif tool_pending:
                dettagli = "; ".join(dict.fromkeys(tool_pending))
                testo_finale = f"Non ho eseguito l'operazione: {dettagli}"
            elif tool_unverified:
                dettagli = "; ".join(dict.fromkeys(row["message"] for row in tool_unverified))
                testo_finale = f"Non posso confermare l'operazione: {dettagli}"

            litellm_success = next(
                (
                    row["result"] for row in reversed(tool_successes)
                    if row["result"].get("skill") == "litellm.complete"
                    and isinstance(row["result"].get("dati"), dict)
                    and row["result"]["dati"].get("text")
                ),
                None,
            )
            if litellm_success is not None and not tool_failures and not tool_pending and not tool_unverified:
                testo_finale = str(litellm_success["dati"]["text"])


            print()
            print(
                "AGENTE COMPLETATO:"
            )

            print(
                testo_finale
            )

            if job_id:
                requested_status = (
                    "completed"
                    if critic_complete is not False and not tool_failures and not tool_schema_errors and not tool_pending and not tool_unverified
                    else "needs_attention"
                )
                verified_status = agent_finish(job_id, requested_status, testo_finale)
                if verified_status == "needs_attention" and not (tool_failures or tool_schema_errors or tool_pending or tool_unverified):
                    testo_finale = "La missione non è conclusa: resta almeno un errore operativo da risolvere."
                elif verified_status == "needs_verification" and not (tool_failures or tool_schema_errors or tool_pending or tool_unverified):
                    testo_finale = "Ho completato le azioni, ma il risultato finale richiede ancora una verifica indipendente."


            if orchestration_run_id and orchestrator is not None:
                orchestration_status = (
                    "completed"
                    if critic_complete is not False
                    and not tool_failures
                    and not tool_schema_errors
                    and not tool_pending
                    and not tool_unverified
                    else "needs_attention"
                )
                orchestrator.finish(orchestration_run_id, orchestration_status, testo_finale)

            return (
                True,
                testo_finale,
                minimizza_hud
            )


        # ====================================================
        # ESEGUI TUTTE LE CHIAMATE DEL TURNO
        # ====================================================

        outputs_tool = []


        for chiamata in chiamate:


            ha_usato_tool = True
            if job_id is None:
                job_id = agent_begin(testo, mission_plan)


            nome_tool = chiamata.name


            try:

                argomenti = json.loads(
                    chiamata.arguments
                )


            except Exception:

                argomenti = {}


            _stampa_tool_inizio(nome_tool, argomenti)


            # =================================================
            # ESECUZIONE
            # =================================================

            _notifica_prima_azione(on_before_action, nome_tool, argomenti)
            risultato = esegui_tool(
                nome_tool,
                argomenti
            )
            if (
                not risultato.get("successo")
                and not risultato.get("richiede_conferma")
                and nome_tool in {"analizza_schermo", "individua_elemento", "info_rete", "connessioni_rete", "servizi_windows", "programmi_installati"}
            ):
                audit_record("tool_retry", tool=nome_tool, arguments=argomenti)
                risultato = esegui_tool(nome_tool, argomenti)
            _record_tool_result(
                nome_tool, argomenti, risultato, tool_failures, tool_pending, tool_unverified, tool_successes, tool_schema_errors
            )
            if orchestration_run_id and orchestrator is not None:
                orchestrator.observe(
                    orchestration_run_id, nome_tool, argomenti, risultato
                )
            agent_add_step(job_id, nome_tool, argomenti, risultato)


            _stampa_tool_risultato(nome_tool, risultato)


            # =================================================
            # MINIMIZZAZIONE HUD
            # =================================================

            if tool_richiede_minimizzazione(
                nome_tool,
                risultato
            ):

                minimizza_hud = True


            # =================================================
            # OUTPUT PER IL MODELLO
            # =================================================

            outputs_tool.append(
                {
                    "type": "function_call_output",
                    "call_id": chiamata.call_id,
                    "output": json.dumps(
                        risultato,
                        ensure_ascii=False
                    )
                }
            )

            # A pending confirmation closes this turn.  Do not ask the model
            # for another response: it could manufacture a second call with
            # confirmed/action_id metadata and create a new pending action.
            if risultato.get("richiede_conferma"):
                break


        # ====================================================
        # PASSAGGIO SUCCESSIVO
        #
        # Manteniamo output precedente +
        # risultati delle funzioni.
        # ====================================================

        input_successivo.extend(
            outputs_tool
        )

        if orchestration_run_id and orchestrator is not None:
            recovery_instruction = orchestrator.recovery_instruction(orchestration_run_id)
            if recovery_instruction:
                input_successivo.append({"role": "user", "content": recovery_instruction})

        if tool_pending:
            dettagli = "; ".join(dict.fromkeys(tool_pending))
            testo_finale = f"Non ho eseguito l'operazione: {dettagli}"
            print()
            print("AGENTE IN ATTESA DI CONFERMA:")
            print(testo_finale)
            if job_id:
                agent_finish(job_id, "needs_attention", testo_finale)
            if orchestration_run_id and orchestrator is not None:
                orchestrator.finish(orchestration_run_id, "needs_attention", testo_finale)
            return True, testo_finale, minimizza_hud


        try:

            router_model = select_model("router", "complex" if mission_mode else "simple")
            request = {"model": router_model, "instructions": ISTRUZIONI, "input": input_successivo,
                       "tools": TOOLS, "parallel_tool_calls": False}
            reasoning = reasoning_options(router_model, reasoning_effort)
            if reasoning is not None:
                request["reasoning"] = reasoning
            risposta = client.responses.create(**request)


        except Exception as e:


            print()
            print(
                "❌ ERRORE DURANTE CATENA TOOL:"
            )

            print(redact(repr(e)))


            if ha_usato_tool:

                if job_id:
                    agent_finish(job_id, "partial", "Catena interrotta da un errore del router.")

                if tool_failures:
                    dettagli = "; ".join(dict.fromkeys(row["message"] for row in tool_failures))
                    if orchestration_run_id and orchestrator is not None:
                        orchestrator.finish(orchestration_run_id, "needs_attention", dettagli)
                    return (
                        True,
                        f"La richiesta non è completata. {dettagli}",
                        minimizza_hud
                    )

                if orchestration_run_id and orchestrator is not None:
                    orchestrator.finish(orchestration_run_id, "needs_attention", "Catena interrotta da un errore del router.")
                return (
                    True,
                    (
                        "Ho eseguito parte della richiesta, "
                        "ma non sono riuscito a completarla."
                    ),
                    minimizza_hud
                )


            return (
                False,
                None,
                False
            )


        # Aggiungiamo anche i nuovi output
        # alla cronologia del workflow.

        input_successivo.extend(
            risposta.output
        )


    # ========================================================
    # LIMITE PASSAGGI
    # ========================================================

    print()
    print(
        "⚠️ Limite massimo di azioni raggiunto."
    )


    if ha_usato_tool:

        if job_id:
            agent_finish(job_id, "limit_reached", "Limite massimo di passaggi raggiunto.")

        if tool_failures:
            dettagli = "; ".join(dict.fromkeys(row["message"] for row in tool_failures))
            if orchestration_run_id and orchestrator is not None:
                orchestrator.finish(orchestration_run_id, "limit_reached", dettagli)
            return True, f"La richiesta non è completata. {dettagli}", minimizza_hud
        if orchestration_run_id and orchestrator is not None:
            orchestrator.finish(orchestration_run_id, "limit_reached", "Limite massimo di passaggi raggiunto.")
        return (
            True,
            (
                "Ho eseguito le operazioni possibili, "
                "ma ho raggiunto il limite massimo di passaggi."
            ),
            minimizza_hud
        )


    return (
        False,
        None,
        False
    )
