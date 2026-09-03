import os
import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil
import pyautogui
import pygetwindow as gw
import pyperclip
from recovery_manager import move_to_recovery
from jarvis_core.logging import redact

LOGGER = logging.getLogger(__name__)


# ============================================================
# CONFIGURAZIONE GENERALE
# ============================================================

# Spostando il mouse nell'angolo in alto a sinistra,
# PyAutoGUI genera un FailSafeException.
#
# È un'importante uscita di emergenza nel caso JARVIS
# inizi a muovere mouse/tastiera in modo indesiderato.
pyautogui.FAILSAFE = True

# Piccola pausa automatica dopo ogni comando PyAutoGUI.
pyautogui.PAUSE = 0.08


HOME = Path.home()

DESKTOP = HOME / "Desktop"
DOCUMENTS = HOME / "Documents"
DOWNLOADS = HOME / "Downloads"
PICTURES = HOME / "Pictures"


# ============================================================
# RISPOSTE STANDARD
# ============================================================

def ok(messaggio, dati=None):
    return {
        "successo": True,
        "messaggio": messaggio,
        "dati": dati
    }


def errore(messaggio, dettagli=None):
    return {
        "successo": False,
        "messaggio": messaggio,
        "errore": redact(dettagli) if isinstance(dettagli, (str, dict, list, tuple)) else dettagli
    }


# ============================================================
# PERCORSI
# ============================================================

def risolvi_percorso(percorso):

    if not percorso:
        return None

    percorso = str(percorso).strip()

    alias = {
        "desktop": DESKTOP,
        "scrivania": DESKTOP,

        "documenti": DOCUMENTS,
        "documents": DOCUMENTS,

        "download": DOWNLOADS,
        "downloads": DOWNLOADS,

        "immagini": PICTURES,
        "pictures": PICTURES,

        "home": HOME
    }

    chiave = percorso.lower()

    if chiave in alias:
        return alias[chiave]

    percorso = os.path.expandvars(percorso)
    percorso = os.path.expanduser(percorso)

    return Path(percorso)


# ============================================================
# APRI FILE / CARTELLE
# ============================================================

def apri_percorso(percorso):

    try:

        path = risolvi_percorso(percorso)

        if not path:
            return errore(
                "Non hai specificato cosa aprire."
            )

        if not path.exists():
            return errore(
                f"Il percorso {path} non esiste."
            )

        os.startfile(str(path))

        return ok(
            f"Ho aperto {path.name}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito ad aprire il percorso.",
            repr(e)
        )


def apri_percorso_con_programma(percorso, programma):
    """Open an existing file with a small, explicit application allow-list."""
    try:
        path = risolvi_percorso(percorso)
        if not path or not path.exists() or not path.is_file():
            return errore("Il file da aprire non esiste o non è un file.")
        application = str(programma or "").strip().casefold()
        executables = {"blocco note": "notepad.exe", "notepad": "notepad.exe"}
        executable = executables.get(application)
        if not executable:
            return errore("Per l'apertura con programma è supportato solo Blocco note.")
        process = subprocess.Popen([executable, str(path)])
        time.sleep(0.25)
        running = bool(process.poll() is None)
        if not running:
            return errore("Blocco note non risulta realmente aperto.")
        return ok(f"Ho aperto {path.name} con Blocco note.", {"path": str(path), "verified": True})
    except Exception as e:
        return errore("Non sono riuscito ad aprire il file con il programma richiesto.", repr(e))


# ============================================================
# CREA CARTELLA
# ============================================================

def crea_cartella(percorso):

    try:

        path = risolvi_percorso(percorso)

        if not path:
            return errore(
                "Non hai specificato il nome della cartella."
            )

        path.mkdir(
            parents=True,
            exist_ok=True
        )

        return ok(
            f"Cartella {path.name} pronta."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a creare la cartella.",
            repr(e)
        )


# ============================================================
# CREA FILE TESTO
# ============================================================

def crea_file(
    percorso,
    contenuto=""
):

    try:

        path = risolvi_percorso(percorso)

        if not path:
            return errore(
                "Non hai specificato il file da creare."
            )

        path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        # Per sicurezza non sovrascriviamo automaticamente.
        if path.exists():

            return errore(
                f"Il file {path.name} esiste già."
            )

        path.write_text(
            contenuto,
            encoding="utf-8"
        )

        return ok(
            f"Ho creato {path.name}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a creare il file.",
            repr(e)
        )


# ============================================================
# LEGGI FILE TESTO
# ============================================================

def leggi_file(
    percorso,
    max_caratteri=20000
):

    try:

        path = risolvi_percorso(percorso)

        if not path:
            return errore(
                "Non hai specificato il file."
            )

        if not path.exists():

            return errore(
                "Il file non esiste."
            )

        if not path.is_file():

            return errore(
                "Il percorso indicato non è un file."
            )

        testo = path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        if len(testo) > max_caratteri:

            testo = testo[
                :max_caratteri
            ]

        return ok(
            f"Ho letto {path.name}.",
            {
                "contenuto": testo,
                "percorso": str(path)
            }
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a leggere il file.",
            repr(e)
        )


# ============================================================
# RINOMINA
# ============================================================

def rinomina(
    percorso,
    nuovo_nome
):

    try:

        path = risolvi_percorso(percorso)

        if not path or not path.exists():

            return errore(
                "Il file o la cartella non esiste."
            )

        destinazione = (
            path.parent
            /
            nuovo_nome
        )

        if destinazione.exists():

            return errore(
                f"Esiste già qualcosa chiamato {nuovo_nome}."
            )

        nuovo = path.rename(
            destinazione
        )

        return ok(
            f"Ho rinominato {path.name} in {nuovo.name}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a rinominare l'elemento.",
            repr(e)
        )


# ============================================================
# SPOSTA FILE / CARTELLA
# ============================================================

def sposta(
    origine,
    destinazione
):

    try:

        src = risolvi_percorso(
            origine
        )

        dst = risolvi_percorso(
            destinazione
        )

        if not src or not src.exists():

            return errore(
                "Il file o la cartella di origine non esiste."
            )

        if not dst:

            return errore(
                "Destinazione non valida."
            )

        # Se destinazione è una cartella esistente,
        # conserva il nome originale.
        if dst.exists() and dst.is_dir():

            dst = (
                dst
                /
                src.name
            )

        if dst.exists():

            return errore(
                f"{dst.name} esiste già nella destinazione."
            )

        dst.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        nuovo = shutil.move(
            str(src),
            str(dst)
        )

        return ok(
            f"Ho spostato {src.name}.",
            {
                "nuovo_percorso": nuovo
            }
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a spostare l'elemento.",
            repr(e)
        )


# ============================================================
# COPIA FILE / CARTELLA
# ============================================================

def copia(
    origine,
    destinazione
):

    try:

        src = risolvi_percorso(
            origine
        )

        dst = risolvi_percorso(
            destinazione
        )

        if not src or not src.exists():

            return errore(
                "L'elemento da copiare non esiste."
            )

        if not dst:

            return errore(
                "Destinazione non valida."
            )

        if dst.exists() and dst.is_dir():

            dst = (
                dst
                /
                src.name
            )

        if dst.exists():

            return errore(
                f"{dst.name} esiste già."
            )

        dst.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if src.is_dir():

            shutil.copytree(
                src,
                dst
            )

        else:

            shutil.copy2(
                src,
                dst
            )

        return ok(
            f"Ho copiato {src.name}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a copiare l'elemento.",
            repr(e)
        )


# ============================================================
# ELIMINAZIONE
#
# IMPORTANTE:
# questa funzione NON elimina direttamente.
# Il router dovrà prima chiedere conferma.
# ============================================================

def elimina(
    percorso,
    confermato=False
):

    try:

        if not confermato:

            return errore(
                "Questa operazione richiede conferma."
            )

        path = risolvi_percorso(
            percorso
        )

        if not path or not path.exists():

            return errore(
                "L'elemento non esiste."
            )

        # Protezioni basilari
        protetti_esatti = [Path("C:/"), HOME, DESKTOP, DOCUMENTS, DOWNLOADS, PICTURES]
        protetti_albero = [
            Path(os.environ.get("WINDIR", "C:/Windows")),
            Path(os.environ.get("ProgramFiles", "C:/Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
        ]

        path_resolved = path.resolve()

        for protetto in protetti_esatti:

            try:

                if (
                    path_resolved
                    ==
                    protetto.resolve()
                ):

                    return errore(
                        "Non posso eliminare questo percorso protetto."
                    )

            except OSError as exc:
                LOGGER.debug("Unable to resolve protected path %s: %s", protetto, exc)

        for protetto in protetti_albero:
            try:
                if path_resolved == protetto.resolve() or path_resolved.is_relative_to(protetto.resolve()):
                    return errore("Non posso eliminare elementi nelle cartelle di sistema protette.")
            except OSError as exc:
                LOGGER.debug("Unable to compare protected path %s: %s", protetto, exc)

        nome = path.name

        recovery_id = move_to_recovery(path)

        return ok(
            f"Ho spostato {nome} nel cestino recuperabile di JARVIS.",
            {"recovery_id": recovery_id}
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a eliminare l'elemento.",
            repr(e)
        )


# ============================================================
# CERCA FILE
# ============================================================

def cerca_file(
    nome,
    limite=20
):

    try:

        nome = nome.lower().strip()

        cartelle = [
            DESKTOP,
            DOCUMENTS,
            DOWNLOADS
        ]

        risultati = []

        for cartella in cartelle:

            if not cartella.exists():
                continue

            for elemento in cartella.rglob("*"):

                try:

                    if nome in elemento.name.lower():

                        risultati.append(
                            str(elemento)
                        )

                        if len(risultati) >= limite:

                            return ok(
                                f"Ho trovato {len(risultati)} risultati.",
                                risultati
                            )

                except (
                    PermissionError,
                    OSError
                ):

                    continue

        return ok(
            f"Ho trovato {len(risultati)} risultati.",
            risultati
        )

    except Exception as e:

        return errore(
            "Errore durante la ricerca.",
            repr(e)
        )


# ============================================================
# SCREENSHOT
# ============================================================

def screenshot(
    percorso=None
):

    try:

        if percorso:

            path = risolvi_percorso(
                percorso
            )

        else:

            cartella = (
                PICTURES
                /
                "Jarvis"
            )

            cartella.mkdir(
                parents=True,
                exist_ok=True
            )

            nome = datetime.now().strftime(
                "screenshot_%Y-%m-%d_%H-%M-%S.png"
            )

            path = (
                cartella
                /
                nome
            )

        path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        immagine = pyautogui.screenshot(
            str(path)
        )

        return ok(
            "Screenshot effettuato.",
            {
                "percorso": str(path),
                "larghezza": immagine.width,
                "altezza": immagine.height
            }
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a fare lo screenshot.",
            repr(e)
        )


# ============================================================
# DIMENSIONE SCHERMO
# ============================================================

def dimensione_schermo():

    try:

        larghezza, altezza = pyautogui.size()

        return ok(
            "Dimensioni schermo rilevate.",
            {
                "larghezza": larghezza,
                "altezza": altezza
            }
        )

    except Exception as e:

        return errore(
            "Non riesco a leggere le dimensioni dello schermo.",
            repr(e)
        )


# ============================================================
# POSIZIONE MOUSE
# ============================================================

def posizione_mouse():

    try:

        posizione = pyautogui.position()

        return ok(
            "Posizione mouse rilevata.",
            {
                "x": posizione.x,
                "y": posizione.y
            }
        )

    except Exception as e:

        return errore(
            "Non riesco a leggere la posizione del mouse.",
            repr(e)
        )


# ============================================================
# MUOVI MOUSE
# ============================================================

def muovi_mouse(
    x,
    y,
    durata=0.2
):

    try:

        pyautogui.moveTo(
            int(x),
            int(y),
            duration=float(durata)
        )

        return ok(
            f"Mouse spostato a {x}, {y}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a spostare il mouse.",
            repr(e)
        )


# ============================================================
# CLICK
# ============================================================

def clicca(
    x=None,
    y=None,
    bottone="left",
    click=1
):

    try:

        kwargs = {
            "button": bottone,
            "clicks": int(click),
            "interval": 0.12
        }

        if x is not None:
            kwargs["x"] = int(x)

        if y is not None:
            kwargs["y"] = int(y)

        pyautogui.click(
            **kwargs
        )

        return ok(
            "Click eseguito."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a cliccare.",
            repr(e)
        )


# ============================================================
# DOPPIO CLICK
# ============================================================

def doppio_click(
    x=None,
    y=None
):

    return clicca(
        x=x,
        y=y,
        bottone="left",
        click=2
    )


# ============================================================
# CLICK DESTRO
# ============================================================

def click_destro(
    x=None,
    y=None
):

    return clicca(
        x=x,
        y=y,
        bottone="right",
        click=1
    )


# ============================================================
# SCROLL
# ============================================================

def scroll(
    quantita
):

    try:

        pyautogui.scroll(
            int(quantita)
        )

        return ok(
            "Scroll eseguito."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a scorrere.",
            repr(e)
        )


# ============================================================
# SCRIVI TESTO
# ============================================================

def scrivi_testo(
    testo,
    intervallo=0.01
):

    try:

        # PyAutoGUI write() può essere poco affidabile
        # con alcuni caratteri Unicode/accentati.
        #
        # Per testo generico usiamo clipboard + Ctrl+V.

        pyperclip.copy(
            str(testo)
        )

        pyautogui.hotkey(
            "ctrl",
            "v"
        )

        return ok(
            "Testo inserito."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a scrivere il testo.",
            repr(e)
        )


# ============================================================
# PREMI TASTO
# ============================================================

def premi_tasto(
    tasto,
    volte=1
):

    try:

        pyautogui.press(
            tasto.lower(),
            presses=int(volte),
            interval=0.05
        )

        return ok(
            f"Tasto {tasto} premuto."
        )

    except Exception as e:

        return errore(
            f"Non sono riuscito a premere {tasto}.",
            repr(e)
        )


# ============================================================
# HOTKEY
# ============================================================

def scorciatoia(
    *tasti
):

    try:

        lista = [
            str(tasto).lower()
            for tasto in tasti
        ]

        pyautogui.hotkey(
            *lista
        )

        return ok(
            "Scorciatoia eseguita."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a eseguire la scorciatoia.",
            repr(e)
        )


# ============================================================
# COPIA
# ============================================================

def copia_selezione():

    try:

        pyautogui.hotkey(
            "ctrl",
            "c"
        )

        time.sleep(
            0.15
        )

        testo = pyperclip.paste()

        return ok(
            "Contenuto copiato.",
            {
                "clipboard": testo
            }
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a copiare.",
            repr(e)
        )


# ============================================================
# INCOLLA
# ============================================================

def incolla():

    try:

        pyautogui.hotkey(
            "ctrl",
            "v"
        )

        return ok(
            "Contenuto incollato."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a incollare.",
            repr(e)
        )


# ============================================================
# CLIPBOARD
# ============================================================

def leggi_clipboard():

    try:

        testo = pyperclip.paste()

        return ok(
            "Clipboard letta.",
            {
                "contenuto": testo
            }
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a leggere la clipboard.",
            repr(e)
        )


def imposta_clipboard(testo):

    try:

        pyperclip.copy(
            str(testo)
        )

        return ok(
            "Clipboard aggiornata."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito ad aggiornare la clipboard.",
            repr(e)
        )


# ============================================================
# FINESTRE
# ============================================================

def elenco_finestre():

    try:

        titoli = []

        for finestra in gw.getAllWindows():

            titolo = (
                finestra.title
                or
                ""
            ).strip()

            if titolo:
                titoli.append(
                    titolo
                )

        titoli = list(
            dict.fromkeys(
                titoli
            )
        )

        return ok(
            f"Ho trovato {len(titoli)} finestre.",
            titoli
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a leggere le finestre.",
            repr(e)
        )


# ============================================================
# TROVA FINESTRA
# ============================================================

def _trova_finestra(
    titolo
):

    titolo = titolo.lower().strip()

    finestre = gw.getAllWindows()

    for finestra in finestre:

        if titolo in (
            finestra.title
            or
            ""
        ).lower():

            return finestra

    return None


# ============================================================
# PORTA DAVANTI
# ============================================================

def porta_finestra_davanti(
    titolo
):

    try:

        finestra = _trova_finestra(
            titolo
        )

        if not finestra:

            return errore(
                f"Non trovo una finestra chiamata {titolo}."
            )

        if finestra.isMinimized:

            finestra.restore()

        finestra.activate()

        return ok(
            f"Ho portato davanti {finestra.title}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito ad attivare la finestra.",
            repr(e)
        )


# ============================================================
# MINIMIZZA
# ============================================================

def minimizza_finestra(
    titolo
):

    try:

        finestra = _trova_finestra(
            titolo
        )

        if not finestra:

            return errore(
                "Finestra non trovata."
            )

        finestra.minimize()

        return ok(
            f"Ho minimizzato {finestra.title}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a minimizzare la finestra.",
            repr(e)
        )


# ============================================================
# MASSIMIZZA
# ============================================================

def massimizza_finestra(
    titolo
):

    try:

        finestra = _trova_finestra(
            titolo
        )

        if not finestra:

            return errore(
                "Finestra non trovata."
            )

        finestra.maximize()

        return ok(
            f"Ho massimizzato {finestra.title}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a massimizzare la finestra.",
            repr(e)
        )


# ============================================================
# RIPRISTINA
# ============================================================

def ripristina_finestra(
    titolo
):

    try:

        finestra = _trova_finestra(
            titolo
        )

        if not finestra:

            return errore(
                "Finestra non trovata."
            )

        finestra.restore()

        return ok(
            f"Ho ripristinato {finestra.title}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a ripristinare la finestra.",
            repr(e)
        )


# ============================================================
# CHIUDI FINESTRA
# ============================================================

def chiudi_finestra(
    titolo
):

    try:

        finestra = _trova_finestra(
            titolo
        )

        if not finestra:

            return errore(
                "Finestra non trovata."
            )

        nome = finestra.title

        finestra.close()

        return ok(
            f"Ho chiuso {nome}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a chiudere la finestra.",
            repr(e)
        )


# ============================================================
# SPOSTA FINESTRA
# ============================================================

def sposta_finestra(
    titolo,
    x,
    y
):

    try:

        finestra = _trova_finestra(
            titolo
        )

        if not finestra:

            return errore(
                "Finestra non trovata."
            )

        finestra.moveTo(
            int(x),
            int(y)
        )

        return ok(
            f"Ho spostato {finestra.title}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a spostare la finestra.",
            repr(e)
        )


# ============================================================
# RIDIMENSIONA FINESTRA
# ============================================================

def ridimensiona_finestra(
    titolo,
    larghezza,
    altezza
):

    try:

        finestra = _trova_finestra(
            titolo
        )

        if not finestra:

            return errore(
                "Finestra non trovata."
            )

        finestra.resizeTo(
            int(larghezza),
            int(altezza)
        )

        return ok(
            f"Ho ridimensionato {finestra.title}."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a ridimensionare la finestra.",
            repr(e)
        )


# ============================================================
# FINESTRA ATTIVA
# ============================================================

def finestra_attiva():

    try:

        finestra = gw.getActiveWindow()

        if not finestra:

            return errore(
                "Non riesco a determinare la finestra attiva."
            )

        return ok(
            f"La finestra attiva è {finestra.title}.",
            {
                "titolo": finestra.title,
                "x": finestra.left,
                "y": finestra.top,
                "larghezza": finestra.width,
                "altezza": finestra.height
            }
        )

    except Exception as e:

        return errore(
            "Non riesco a leggere la finestra attiva.",
            repr(e)
        )


# ============================================================
# ALT TAB
# ============================================================

def cambia_finestra():

    try:

        pyautogui.hotkey(
            "alt",
            "tab"
        )

        return ok(
            "Ho cambiato finestra."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a cambiare finestra.",
            repr(e)
        )


# ============================================================
# INFO PC
# ============================================================

def info_sistema():

    try:

        cpu = psutil.cpu_percent(
            interval=0.3
        )

        memoria = psutil.virtual_memory()

        disco = psutil.disk_usage(
            str(
                Path.home().anchor
            )
        )

        avvio = datetime.fromtimestamp(
            psutil.boot_time()
        )

        dati = {

            "cpu_percento":
                round(cpu, 1),

            "ram_percento":
                memoria.percent,

            "ram_totale_gb":
                round(
                    memoria.total
                    /
                    (1024 ** 3),
                    2
                ),

            "ram_disponibile_gb":
                round(
                    memoria.available
                    /
                    (1024 ** 3),
                    2
                ),

            "disco_percento":
                disco.percent,

            "disco_libero_gb":
                round(
                    disco.free
                    /
                    (1024 ** 3),
                    2
                ),

            "avvio_pc":
                avvio.strftime(
                    "%d/%m/%Y %H:%M"
                )
        }

        messaggio = (
            f"CPU al {dati['cpu_percento']} percento, "
            f"RAM al {dati['ram_percento']} percento "
            f"e disco al {dati['disco_percento']} percento."
        )

        return ok(
            messaggio,
            dati
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a leggere lo stato del computer.",
            repr(e)
        )


# ============================================================
# PROCESSI
# ============================================================

def processi_attivi(
    limite=50
):

    try:

        processi = []

        for processo in psutil.process_iter(
            [
                "pid",
                "name",
                "memory_percent"
            ]
        ):

            try:

                info = processo.info

                processi.append(
                    {
                        "pid":
                            info[
                                "pid"
                            ],

                        "nome":
                            info[
                                "name"
                            ],

                        "memoria_percento":
                            round(
                                info.get(
                                    "memory_percent",
                                    0
                                ),
                                2
                            )
                    }
                )

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied
            ):

                continue

        processi.sort(
            key=lambda x: x[
                "memoria_percento"
            ],
            reverse=True
        )

        processi = processi[
            :int(limite)
        ]

        return ok(
            f"Ho trovato {len(processi)} processi principali.",
            processi
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a leggere i processi.",
            repr(e)
        )


# ============================================================
# TERMINA PROCESSO
#
# Richiede conferma.
# ============================================================

def termina_processo(
    nome,
    confermato=False
):

    if not confermato:

        return errore(
            "La chiusura forzata di un processo richiede conferma."
        )

    # Processi che non vogliamo far terminare
    # automaticamente.
    protetti = {
        "system",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "dwm.exe",
        "explorer.exe"
    }

    nome_lower = nome.lower().strip()

    if nome_lower in protetti:

        return errore(
            "Non posso terminare automaticamente questo processo di sistema."
        )

    trovati = 0

    try:

        for processo in psutil.process_iter(
            [
                "pid",
                "name"
            ]
        ):

            try:

                processo_nome = (
                    processo.info.get(
                        "name"
                    )
                    or
                    ""
                ).lower()

                if nome_lower in processo_nome:

                    processo.terminate()

                    trovati += 1

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied
            ):

                continue

        if trovati == 0:

            return errore(
                f"Non ho trovato processi chiamati {nome}."
            )

        return ok(
            f"Ho richiesto la chiusura di {trovati} processi."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a terminare il processo.",
            repr(e)
        )


# ============================================================
# GESTIONE ATTIVITÀ
# ============================================================

def apri_task_manager():

    try:

        subprocess.Popen(
            [
                "taskmgr"
            ]
        )

        return ok(
            "Ho aperto Gestione attività."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito ad aprire Gestione attività.",
            repr(e)
        )


# ============================================================
# ESPLORA FILE
# ============================================================

def apri_esplora_file():

    try:

        subprocess.Popen(
            [
                "explorer.exe"
            ]
        )

        return ok(
            "Ho aperto Esplora file."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito ad aprire Esplora file.",
            repr(e)
        )


# ============================================================
# IMPOSTAZIONI WINDOWS
# ============================================================

def apri_impostazioni(
    pagina=None
):

    try:

        pagine = {

            "bluetooth":
                "ms-settings:bluetooth",

            "wifi":
                "ms-settings:network-wifi",

            "rete":
                "ms-settings:network",

            "audio":
                "ms-settings:sound",

            "schermo":
                "ms-settings:display",

            "display":
                "ms-settings:display",

            "batteria":
                "ms-settings:batterysaver",

            "windows update":
                "ms-settings:windowsupdate",

            "aggiornamenti":
                "ms-settings:windowsupdate",

            "app":
                "ms-settings:appsfeatures",

            "privacy":
                "ms-settings:privacy"
        }

        if not pagina:

            uri = "ms-settings:"

        else:

            uri = pagine.get(
                pagina.lower().strip(),
                "ms-settings:"
            )

        os.startfile(
            uri
        )

        return ok(
            "Ho aperto le impostazioni."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito ad aprire le impostazioni.",
            repr(e)
        )


# ============================================================
# BLOCCA PC
# ============================================================

def blocca_pc(
    confermato=False
):

    if not confermato:

        return errore(
            "Il blocco del computer richiede conferma."
        )

    try:

        subprocess.run(
            [
                "rundll32.exe",
                "user32.dll,LockWorkStation"
            ]
        )

        return ok(
            "Computer bloccato."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a bloccare il computer.",
            repr(e)
        )


# ============================================================
# SPEGNI PC
# ============================================================

def spegni_pc(
    confermato=False
):

    if not confermato:

        return errore(
            "Lo spegnimento richiede conferma esplicita."
        )

    try:

        subprocess.Popen(
            [
                "shutdown",
                "/s",
                "/t",
                "0"
            ]
        )

        return ok(
            "Sto spegnendo il computer."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a spegnere il computer.",
            repr(e)
        )


# ============================================================
# RIAVVIA PC
# ============================================================

def riavvia_pc(
    confermato=False
):

    if not confermato:

        return errore(
            "Il riavvio richiede conferma esplicita."
        )

    try:

        subprocess.Popen(
            [
                "shutdown",
                "/r",
                "/t",
                "0"
            ]
        )

        return ok(
            "Sto riavviando il computer."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a riavviare il computer.",
            repr(e)
        )


# ============================================================
# SOSPENSIONE
# ============================================================

def sospendi_pc(
    confermato=False
):

    if not confermato:

        return errore(
            "La sospensione richiede conferma."
        )

    try:

        subprocess.Popen(
            [
                "rundll32.exe",
                "powrprof.dll,SetSuspendState",
                "0,1,0"
            ]
        )

        return ok(
            "Sto sospendendo il computer."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a sospendere il computer.",
            repr(e)
        )


# ============================================================
# COMANDI MEDIA
# ============================================================

def play_pause():

    try:

        pyautogui.press(
            "playpause"
        )

        return ok(
            "Play o pausa eseguito."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a controllare la riproduzione.",
            repr(e)
        )


def traccia_successiva():

    try:

        pyautogui.press(
            "nexttrack"
        )

        return ok(
            "Sono passato alla traccia successiva."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a cambiare traccia.",
            repr(e)
        )


def traccia_precedente():

    try:

        pyautogui.press(
            "prevtrack"
        )

        return ok(
            "Sono tornato alla traccia precedente."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a cambiare traccia.",
            repr(e)
        )


# ============================================================
# DESKTOP
# ============================================================

def mostra_desktop():

    try:

        pyautogui.hotkey(
            "win",
            "d"
        )

        return ok(
            "Desktop visualizzato."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito a mostrare il Desktop.",
            repr(e)
        )


# ============================================================
# START MENU
# ============================================================

def apri_start():

    try:

        pyautogui.press(
            "win"
        )

        return ok(
            "Menu Start aperto."
        )

    except Exception as e:

        return errore(
            "Non sono riuscito ad aprire Start.",
            repr(e)
        )


# ============================================================
# ESC
# ============================================================

def premi_esc():

    return premi_tasto(
        "esc"
    )


# ============================================================
# INVIO
# ============================================================

def premi_inv():

    return premi_tasto(
        "enter"
    )


# ============================================================
# CTRL Z
# ============================================================

def annulla():

    return scorciatoia(
        "ctrl",
        "z"
    )


# ============================================================
# CTRL Y
# ============================================================

def ripristina():

    return scorciatoia(
        "ctrl",
        "y"
    )


# ============================================================
# CTRL A
# ============================================================

def seleziona_tutto():

    return scorciatoia(
        "ctrl",
        "a"
    )


# ============================================================
# CTRL S
# ============================================================

def salva():

    return scorciatoia(
        "ctrl",
        "s"
    )


# ============================================================
# TEST MODULO
# ============================================================

if __name__ == "__main__":

    print()
    print("======================================")
    print("       JARVIS COMPUTER MODULE")
    print("======================================")
    print()

    risultato = info_sistema()

    print(
        risultato
    )

    print()

    print(
        "Modulo computer.py caricato correttamente."
    )

    print()
