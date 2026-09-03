# JARVIS Maximum PC Edition

JARVIS è un assistente Windows modulare con voce, HUD Qt, Mission Control, memoria persistente, skill con permessi, computer-use verificato, laboratorio di sviluppo e automazioni persistenti.

## Avvio rapido

Requisiti: Windows 10/11, `uv`, microfono e Python 3.12. Non serve installare più versioni di Python.

1. Esegui `Prepara ambiente.cmd` una sola volta. Lo script individua automaticamente qualsiasi Python 3.12 installato da `uv` e crea `.runtime-env`.
2. Copia `.env.example` in `.env` e inserisci `OPENAI_API_KEY`.
3. Esegui `Avvia Jarvis.cmd`.

I dati runtime rimangono in `data/`. L’ambiente isolato è `.runtime-env`; non modificare il vecchio `venv` per eseguire JARVIS.

## Comandi diagnostici

- `/health` o `/status`: stato dei componenti controllati dal watchdog.
- `/doctor`: Python, dipendenze, directory dati, file critici e integrità SQLite.
- `/missions`, `/memory`, `/skills`, `/automations`: riepiloghi dei sottosistemi.
- `/logs`, `/performance`: disponibilità log e metriche.
- `/search testo`: ricerca unificata in memoria, missioni, skill, log e codice.

## Verifica

```powershell
.\.runtime-env\Scripts\python.exe -m unittest discover -s tests -v
.\.runtime-env\Scripts\python.exe -m pip check
```

Per un controllo grafico senza aprire finestre, imposta `QT_QPA_PLATFORM=offscreen` e istanzia `JarvisHUD` con lo stesso runtime.

## EXE Windows

La build portabile verificata si trova in `dist\JARVIS\JARVIS.exe`. La cartella `_internal` deve restare accanto all'eseguibile: per distribuire JARVIS copia l'intera cartella `dist\JARVIS`, non soltanto il file `.exe`.

Per ricrearla:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
```

## Architettura

- `jarvis_core`: lifecycle, configurazione, eventi, health, watchdog, processi e diagnostica.
- `jarvis_missions`: task graph, checkpoint, evidenze, executor e critic.
- `jarvis_memory`: memoria working/episodica/semantica/procedurale e knowledge graph.
- `jarvis_skills`: manifest, autorizzazioni, fallback e metriche delle capacità.
- `jarvis_perception`: osservazione DOM/UIA/vision e azioni con verifica post-condizione.
- `jarvis_voice`: sessione asincrona, priorità, barge-in, cache e sonde audio.
- `jarvis_developer`: analisi repository, LAB isolato, test, promozione e rollback.
- `jarvis_automation`: scheduler SQLite, trigger, retry, catene, idempotenza e storico.
- `jarvis_hud`: snapshot thread-safe per Mission Control, salute, log e prestazioni.

## Recupero

I checkpoint ZIP sono nella cartella `backups`. Le modifiche autonome al codice passano dal LAB e vengono promosse solo dopo test verdi; in caso di errore il servizio developer ripristina i file precedenti. I file eliminati tramite gli strumenti protetti usano inoltre il recovery store.

## Sicurezza

Non inserire segreti nel codice o nei log. `.env` è escluso dal controllo versione; condividi soltanto `.env.example`. Le skill dichiarano capacità e vengono autorizzate prima dell’esecuzione. Le operazioni desktop devono verificare lo stato osservato dopo ogni azione e le analisi finanziarie restano consultive.
