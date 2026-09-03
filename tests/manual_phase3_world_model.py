"""Manual Phase 3 checklist; intentionally performs no hardware actions."""

CHECKLIST = (
    "Avvia JARVIS e chiedi il contesto corrente.",
    "Apri e chiudi Chrome manualmente; verifica che il process snapshot corregga running/focused.",
    "Esegui 'Apri Spotify' e poi 'Chiudilo'; verifica le belief dopo ogni risultato verificato.",
    "Crea un artifact tramite JARVIS e verifica solo path/recent, mai il contenuto completo.",
    "Apri una UI osservabile e verifica source/confidence DOM/UIA senza forzare un observer.",
)


if __name__ == "__main__":
    print("Phase 3 manual checklist (non eseguita automaticamente):")
    for index, item in enumerate(CHECKLIST, 1):
        print(f"{index}. {item}")
