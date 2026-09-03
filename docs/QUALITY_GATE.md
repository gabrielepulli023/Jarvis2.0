# Quality gate ripetibile

Il gate ufficiale del repository è `quality_gate.ps1`. Deve essere eseguito dalla root del progetto con l'ambiente `.runtime-env` preparato:

```powershell
.\quality_gate.ps1
```

Esegue, nello stesso ordine:

1. la suite `unittest` completa;
2. `pip check`;
3. Ruff;
4. Black in modalità `--check`;
5. mypy sull'architettura moderna.

Le esclusioni sono centralizzate in `pyproject.toml`, così cache, ambienti virtuali, build, runtime data e directory temporanee non possono alterare il risultato del gate.

Per un controllo statico rapido durante lo sviluppo:

```powershell
.\quality_gate.ps1 -SkipTests
```

Il gate non sostituisce il collaudo hardware/UI interattivo in `Esegui collaudo JARVIS.cmd`.

## Stato certificato attuale

Ultima esecuzione locale verificata il 19 agosto 2026: 310 test superati, `pip check` superato, Ruff superato, Black superato e mypy superato su 67 file. L'accettazione target-PC ha inoltre superato audio input/output, campione microfono volatile, Notepad, Calculator, File Explorer e broker autenticato. La suite non certifica da sola wake word in ambienti rumorosi, provider esterni, ogni combinazione DPI/multi-monitor o stabilità di lunga durata.

La catena vocale ha inoltre superato 14 test mirati su wake queue, presenza del modello Vosk italiano, salute audio, STT streaming, barge-in, priorità TTS e shutdown.

## Blocco per parlante

JARVIS supporta `wake_speaker_lock`. Dopo il comando `registra la mia voce come <nome>`, il blocco viene attivato automaticamente. Da quel momento il wake word viene accettato solo se l'impronta vocale locale cifrata corrisponde al profilo; l'audio resta volatile e il testo non viene inoltrato allo STT quando la verifica fallisce. Senza un profilo vocale il sistema rifiuta la verifica invece di accettare indiscriminatamente qualsiasi parlante.
