CAPABILITIES = {
    "presentations": "Creazione nativa di file PowerPoint PPTX sul Desktop",
    "biometric_identity": "Registrazione e riconoscimento locale di volto e voce con profili cifrati",
    "computer": "Controllo di programmi, finestre, mouse, tastiera, file e sistema Windows",
    "vision": "Agente visivo continuo: screenshot dopo ogni azione, comprensione UI, mouse, tastiera e verifica del risultato",
    "voice": "Conversazione vocale continua, wake word e interruzione della voce",
    "memory": "Fatti personali, preferenze, episodi ed esportazione",
    "planning": "Obiettivi persistenti con passi e stato di avanzamento",
    "automation": "Routine giornaliere e operazioni programmate",
    "productivity": "Bozze email, calendario e creazione di file",
    "web": "Ricerca web e apertura di siti",
    "monitoring": "Stato sistema, mercati e avvisi proattivi locali",
    "security": "Policy di rischio centralizzata, conferme reali, audit e recupero delle operazioni reversibili",
    "scripts": "Script Python e PowerShell salvati, analizzati, tracciati e limitati da timeout",
    "windows_advanced": "Rete, Wi-Fi, servizi, programmi installati, ZIP e winget",
    "event_automation": "Regole su file, processi, CPU e spazio disco",
    "recovery": "Cestino JARVIS recuperabile e ripristino delle eliminazioni",
    "permissions": "Azioni sicure autonome; conferma esplicita per operazioni sensibili, amministrative o distruttive",
    "agent_state": "Attività persistenti, passaggi, esiti e recupero delle interruzioni",
    "cognitive_core": "Pianificatore, esecutore e critico indipendente con correzione iterativa delle missioni",
    "desktop_intelligence": "DOM Chrome, accessibilità Windows, visione e coordinate in fallback progressivo",
    "adaptive_learning": "Apprendimento di procedure ricorrenti da missioni completate senza dati sensibili",
    "simulation": "Simulazione preventiva di impatto, reversibilità e percorsi protetti",
    "telemetry": "Metriche locali su velocità, successi e fallimenti di ogni strumento",
    "async_runtime": "Corsie concorrenti per AI, visione, automazione, I/O e voce con cancellazione e timeout",
    "privacy": "Sessioni private senza memoria, episodi, cronologia o cache vocale",
    "project_sandbox": "Test dei progetti su copie temporanee isolate e versioni ripristinabili",
    "external_agents": "Orchestrazione opzionale di Browser Use, Microsoft UFO e UI-TARS con fallback e conferme",
    "langgraph": "Workflow agentici multi-step con routing e fallback tramite LangGraph",
    "mem0": "Memoria secondaria opzionale Mem0, disattivata in privacy mode",
    "pipecat": "Pipeline vocale Pipecat opzionale predisposta per migrazione progressiva",
}


CAPABILITY_CONDITIONS = {
    "ai_remota": "Risposte AI, trascrizione OpenAI e alcuni servizi esterni richiedono chiave API e rete disponibili",
    "browser": "Azioni web avanzate richiedono Chrome avviato e una pagina accessibile; il fallback apre comunque il browser nativo",
    "windows": "Mouse, tastiera, finestre, microfono e fotocamera dipendono dai permessi e dall'hardware presenti",
    "winget": "Installazione e aggiornamento dipendono da winget, rete e autorizzazioni Windows",
    "external_agents": "Browser Use/LangGraph/Mem0/Pipecat richiedono dipendenze opzionali; UFO richiede server e device client; UI-TARS richiede Node 20+ e un endpoint modello configurato",
}


CAPABILITY_LIMITS = (
    "non invia email: prepara solo bozze locali",
    "non esegue ordini finanziari, acquisti o pagamenti",
    "non gestisce password, OTP o dati sensibili nei moduli web",
    "non aggira permessi, antivirus, blocchi di sicurezza o credenziali",
    "non esegue codice appena creato senza una richiesta esplicita",
)


def capability_report():
    data = {
        "disponibili": CAPABILITIES,
        "condizionate": CAPABILITY_CONDITIONS,
        "non_disponibili": list(CAPABILITY_LIMITS),
    }
    message = (
        "Disponibili: "
        + "; ".join(f"{key}: {value}" for key, value in CAPABILITIES.items())
        + ". Condizionate: "
        + "; ".join(f"{key}: {value}" for key, value in CAPABILITY_CONDITIONS.items())
        + ". Limiti: "
        + "; ".join(CAPABILITY_LIMITS)
        + "."
    )
    return {"successo": True, "messaggio": message, "dati": data}
