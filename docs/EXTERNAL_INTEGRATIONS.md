# Integrazioni agentiche esterne di JARVIS

Componenti collegati al core senza sostituire i percorsi nativi già stabili:

- **Microsoft UFO**: escalation per workflow Windows multi-step.
- **Browser Use**: workflow browser autonomi.
- **LangGraph**: orchestration `plan -> execute -> verify/fallback` tra backend agentici.
- **Mem0**: memoria secondaria opzionale; non sostituisce `jarvis_memory`.
- **Pipecat**: runtime/pipeline vocale opzionale; non sostituisce automaticamente wake word/STT/TTS attuali.
- **UI-TARS**: fallback visuale agentico tramite bridge Node.
- **OmniParser**: escluso intenzionalmente.

## Installazione

1. Chiudere JARVIS.
2. Eseguire `Prepara ambiente.cmd` se `.runtime-env` non esiste.
3. Eseguire `Installa integrazioni JARVIS.cmd`.
4. Per UFO, configurare `external_integrations/UFO/config/ufo/agents.yaml` e avviare `Avvia UFO per JARVIS.cmd`.
5. Per UI-TARS, configurare le variabili indicate sotto.
6. Riavviare JARVIS.
7. Usare `/integrations` per lo stato veloce o il tool `integration_status` con `deep=true` per verificare anche i sidecar.

## Strategia di routing

JARVIS continua a preferire i propri strumenti deterministici (UI Automation, Chrome DOM, file tools, ecc.). Gli agenti esterni sono usati per workflow lunghi o quando il percorso strutturato non basta.

```text
browser multi-step -> Browser Use -> UFO -> UI-TARS
Windows multi-step -> UFO -> UI-TARS
GUI esplicitamente visuale -> UI-TARS -> UFO
```

Quando LangGraph è disponibile, gestisce il tentativo dei backend candidati e il fallback. Se LangGraph non è installato, lo stesso fallback viene eseguito deterministicamente dal core JARVIS.

## Microsoft UFO

UFO è volutamente isolato dal runtime Python di JARVIS perché il repository Microsoft usa dipendenze con versioni diverse da quelle del progetto. L'installer:

- clona UFO in `external_integrations/UFO`;
- crea `external_integrations/UFO/.ufo-env` con Python 3.10;
- installa `UFO/requirements.txt` dentro quell'ambiente separato;
- crea `config/ufo/agents.yaml` dal template, se necessario.

JARVIS comunica con il server UFO tramite:

- `POST /api/dispatch`
- `GET /api/task_result/{task_name}`
- `GET /api/health`

Valori predefiniti JARVIS:

```text
ufo_base_url=http://127.0.0.1:5000
ufo_client_id=jarvis_windows
```

Dopo avere configurato il modello LLM di UFO, `Avvia UFO per JARVIS.cmd` apre server e client Windows con il client id `jarvis_windows`.

## Browser Use

Il backend è installato nel `.runtime-env` di JARVIS e usa, in ordine:

1. `BROWSER_USE_API_KEY`, se presente;
2. `OPENAI_API_KEY`;
3. `ANTHROPIC_API_KEY`.

`browser_use_max_steps` limita i passi di un workflow (25 di default, massimo 100).

## UI-TARS

Il bridge è in `external_integrations/ui_tars/ui_tars_bridge.mjs` e usa versioni pinning `1.2.3` di:

- `@ui-tars/sdk`
- `@ui-tars/operator-nut-js`

Richiede **Node.js 20+** e un endpoint modello UI-TARS compatibile. Il modello non è incluso nel progetto.

Configurare nell'ambiente:

```text
UI_TARS_BASE_URL=...
UI_TARS_API_KEY=...
UI_TARS_MODEL=...
```

## Mem0

Disabilitato di default (`mem0_enabled=false`) perché aggiunge un secondo livello di memoria persistente. Quando attivo:

- usa lo stesso `mem0_user_id` per separare le memorie del proprietario;
- non legge né scrive quando `privacy_mode=true` o `ai_memory=false`;
- rifiuta testo che sembra contenere password, token o API key;
- salva Qdrant e cronologia sotto la normale directory dati di JARVIS (`.../JARVIS/mem0/`) invece di una directory temporanea.

Per abilitarlo, impostare `mem0_enabled=true` nelle impostazioni JARVIS.

## Pipecat

Installato ma disabilitato di default (`pipecat_enabled=false`). L'adapter usa le API moderne:

- `Pipeline`
- `PipelineWorker`
- `PipelineParams`
- `WorkerRunner`

La pipeline voce attuale resta quella predefinita per evitare regressioni su wake word, VAD, ElevenLabs e barge-in. Pipecat è disponibile come runtime alternativo per una migrazione progressiva dei processori vocali senza cambiare il percorso stabile finché non viene esplicitamente attivato/testato.

## Sicurezza

Gli agenti esterni possono eseguire molte azioni da una singola istruzione. Per questo:

- `delegate_agent_task`, `browser_agent_task`, `ufo_agent_task` e `ui_tars_agent_task` sono classificati `sensitive` e richiedono conferma dal permission engine;
- l'adapter rifiuta task che chiedono password, passcode, OTP/2FA, codici di verifica, pagamenti/acquisti, bonifici o ordini finanziari;
- Mem0 rifiuta memorie che sembrano contenere segreti;
- i backend sono lazy: se una dipendenza o sidecar manca, JARVIS continua ad avviarsi e i percorsi nativi restano disponibili.

## Versioni pinning verificate per il patch

```text
browser-use[core]==0.13.8
langgraph==1.2.11
mem0ai==2.0.19
pipecat-ai==1.7.0
@ui-tars/sdk==1.2.3
@ui-tars/operator-nut-js==1.2.3
```
