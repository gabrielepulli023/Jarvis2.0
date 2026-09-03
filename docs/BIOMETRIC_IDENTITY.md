# Identità biometrica locale

JARVIS supporta riconoscimento del volto e della voce come funzioni di presenza e personalizzazione. Non sostituiscono PIN, conferme o credenziali per operazioni ad alto rischio.

## Comandi

- `Registra il mio volto come Gabriel`
- `Riconosci il mio volto`
- `Registra la mia voce come Gabriel`
- `Riconosci la mia voce`
- `Stato identità`
- `Elimina profilo biometrico Gabriel`
- `Disattiva riconoscimento biometrico`

La registrazione del volto richiede una sola persona davanti alla webcam e raccoglie più campioni per ridurre falsi riconoscimenti. La voce richiede tre campioni di circa 2,5 secondi.

## Privacy e sicurezza

- foto e audio grezzi non vengono salvati;
- vengono conservati soltanto descrittori numerici derivati;
- su Windows il database è cifrato con DPAPI e può essere decifrato soltanto dallo stesso account;
- il riconoscimento funziona localmente e non invia dati biometrici a servizi remoti;
- errori, dispositivi assenti e campioni insufficienti falliscono in modo chiuso senza arrestare JARVIS.

I profili sono conservati nella directory dati locale di JARVIS, sotto `identity/profiles.json` (contenuto cifrato su Windows).

## Accesso CEO all'avvio

Dopo `Registra il mio volto come Gabriele`, JARVIS salva Gabriele come proprietario CEO e abilita la verifica automatica. Agli avvii successivi la schermata iniziale mostra `Verifica identità CEO`, acquisisce più frame e attiva la sessione personale soltanto se coincidono sia l'account Windows/DPAPI sia il volto configurato. Senza profilo non apre la webcam e resta disponibile la configurazione. Il comando `Riprova accesso CEO` ripete il controllo durante la sessione.

Il comando consigliato completo è `Crea profilo CEO Gabriele con permessi completi`. JARVIS registra in modo atomico nome, ruolo, preset permessi, più campioni del volto e tre campioni vocali della frase `Jarvis, sono io`. Se il volto fallisce all'avvio, la sessione resta ospite con le categorie sensibili negate; pronunciando la frase di riserva JARVIS verifica l'impronta del parlante e ripristina esclusivamente i permessi cifrati nel profilo riconosciuto.
