"""Manual hardware acceptance checklist for Phase 1.

Run JARVIS normally, then perform the spoken steps below. This script is only
documentation and does not claim hardware validation.
"""

CHECKLIST = (
    "1. Avvia JARVIS.",
    "2. Pronuncia una frase ambientale non diretta a JARVIS: nessuna risposta.",
    "3. Pronuncia 'apri Chrome' come owner: verifica la selective attention.",
    "4. Apri una conversazione normale.",
    "5. Pronuncia 'Jarvis zitto': verifica MUTED e interruzione TTS.",
    "6. Pronuncia altri comandi senza wake word: devono essere ignorati.",
    "7. Pronuncia 'Jarvis': verifica uscita da MUTED e stato ENGAGED.",
)


if __name__ == "__main__":
    print("Phase 1 — test manuale microfono reale (non automatizzato):")
    print("\n".join(CHECKLIST))
