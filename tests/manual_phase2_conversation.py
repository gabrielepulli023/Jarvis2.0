"""Manual Phase 2 checklist; hardware/UI execution is intentionally not automatic."""

CHECKLIST = (
    '1. Avvia JARVIS.\n'
    '2. "Apri Chrome" poi "Chiudilo": verificare Chrome.\n'
    '3. "Apri Chrome e Spotify" poi "Chiudilo": verificare richiesta Chrome/Spotify e nessuna azione casuale.\n'
    '4. Fai creare un file, poi "Aprilo": verificare il file corretto.\n'
    '5. Genera un markdown verificato, poi "Salvalo sul desktop".\n'
    '6. Prova "Perché?", "E poi?", "Continua" e "Fallo" dopo una proposta.\n'
    '7. Lascia scadere il contesto e prova "Aprilo": non deve riusare il vecchio artefatto.\n'
    '8. Controlla che non siano esposti segreti o dati biometrici.'
)


if __name__ == "__main__":
    print(CHECKLIST)
