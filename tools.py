import os
import logging
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

import comtypes
import psutil
import pygetwindow as gw

from pycaw.pycaw import (
    AudioUtilities,
    IAudioEndpointVolume
)

from comtypes import CLSCTX_ALL
from jarvis_core.logging import redact

LOGGER = logging.getLogger(__name__)


def _chrome_extension_directory():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "chrome_extension"


def _avvia_chrome_controllato(percorso):
    """Avvia un profilo Chrome JARVIS con il bridge DOM locale già caricato."""
    from app_paths import data_path
    from chrome_bridge import ensure_server, write_extension_config

    # Chrome is a single-instance application. If a normal Chrome profile is
    # already running, a second invocation can ignore the extension and CDP
    # flags. Opening the OS application must still work independently.
    if _processo_presente("chrome.exe"):
        subprocess.Popen([percorso])
        return True

    extension = _chrome_extension_directory()
    try:
        if not extension.exists() or not ensure_server():
            # Chrome resta un'azione valida anche quando il bridge DOM non è
            # disponibile: il fallback deve essere riportato come riuscito.
            subprocess.Popen([percorso])
            return True
        write_extension_config(extension)
        profile = data_path("browser") / "chrome-profile"
        profile.mkdir(parents=True, exist_ok=True)
        subprocess.Popen([
            percorso,
            f"--user-data-dir={profile}",
            f"--disable-extensions-except={extension}",
            f"--load-extension={extension}",
            "--remote-debugging-port=9222",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "https://www.google.com",
        ])
        return True
    except Exception as exc:
        # Un errore dell'integrazione locale non deve impedire l'apertura
        # nativa del browser. Se anche il fallback fallisce, l'eccezione
        # arriva ad apri_programma e diventa un errore reale per l'utente.
        LOGGER.warning("Avvio Chrome controllato fallito; uso il fallback nativo: %s", redact(repr(exc)))
        subprocess.Popen([percorso])
        return True


def _processo_presente(nome_processo):
    target = str(nome_processo or "").casefold()
    if not target:
        return False
    try:
        for processo in psutil.process_iter(["name"]):
            try:
                nome = str((processo.info or {}).get("name") or "").casefold()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
            if nome == target:
                return True
    except (psutil.Error, OSError):
        return False
    return False


def _finestre_con_titolo(*titoli):
    """Restituisce finestre associate ai titoli indicati, senza duplicati."""
    richiesti = [str(titolo or "").casefold().strip() for titolo in titoli if str(titolo or "").strip()]
    finestre = []
    viste = set()

    def aggiungi(finestra):
        handle = getattr(finestra, "_hWnd", None)
        chiave = ("handle", handle) if isinstance(handle, int) else ("object", id(finestra))
        if chiave not in viste:
            viste.add(chiave)
            finestre.append(finestra)

    for titolo in richiesti:
        try:
            for finestra in gw.getWindowsWithTitle(titolo) or []:
                aggiungi(finestra)
        except Exception as exc:
            LOGGER.debug("Ricerca finestra %s non disponibile: %s", titolo, redact(repr(exc)))

    # Il titolo può variare, per esempio "Documento senza nome - Blocco note".
    if richiesti:
        try:
            for finestra in gw.getAllWindows() or []:
                titolo = str(getattr(finestra, "title", "") or "").casefold()
                if titolo and any(needle in titolo for needle in richiesti):
                    aggiungi(finestra)
        except Exception as exc:
            LOGGER.debug("Elenco finestre non disponibile: %s", redact(repr(exc)))
    return finestre


def _titoli_programma(nome):
    if nome in {"blocco note", "notepad"}:
        return ("blocco note", "notepad")
    if nome in {"chrome", "google chrome"}:
        return ("google chrome", "chrome")
    return (nome,)


def _programma_chiuso(nome, processo):
    return not _processo_presente(processo) and not _finestre_con_titolo(*_titoli_programma(nome))


def _attendi_chiusura(nome, processo, timeout=1.5):
    scadenza = time.monotonic() + timeout
    while time.monotonic() < scadenza:
        if _programma_chiuso(nome, processo):
            return True
        time.sleep(0.05)
    return _programma_chiuso(nome, processo)


# ============================================================
# PROGRAMMI CONOSCIUTI
# ============================================================

APPS = {

    "chrome": {
        "percorsi": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ],
        "processo": "chrome.exe"
    },

    "google chrome": {
        "percorsi": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ],
        "processo": "chrome.exe"
    },

    "spotify": {
        "percorsi": [
            os.path.expandvars(
                r"%APPDATA%\Spotify\Spotify.exe"
            )
        ],
        "processo": "Spotify.exe"
    },

    "discord": {
        "percorsi": [
            os.path.expandvars(
                r"%LOCALAPPDATA%\Discord\Update.exe"
            )
        ],
        "processo": "Discord.exe"
    },

    "visual studio code": {
        "percorsi": [
            os.path.expandvars(
                r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
            )
        ],
        "processo": "Code.exe"
    },

    "vscode": {
        "percorsi": [
            os.path.expandvars(
                r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
            )
        ],
        "processo": "Code.exe"
    },

    "vs code": {
        "percorsi": [
            os.path.expandvars(
                r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"
            )
        ],
        "processo": "Code.exe"
    },

    "blocco note": {
        "percorsi": [
            "notepad.exe"
        ],
        "processo": "notepad.exe"
    },

    "notepad": {
        "percorsi": [
            "notepad.exe"
        ],
        "processo": "notepad.exe"
    },

    "calcolatrice": {
        "percorsi": [
            "calc.exe"
        ],
        "processo": "CalculatorApp.exe"
    }
}


# ============================================================
# SITI CONOSCIUTI
# ============================================================

SITI = {

    "youtube":
        "https://www.youtube.com",

    "google":
        "https://www.google.com",

    "github":
        "https://github.com",

    "chatgpt":
        "https://chatgpt.com",

    "openai":
        "https://openai.com",

    "gmail":
        "https://mail.google.com",

    "tradingview":
        "https://www.tradingview.com/chart/",

    "trading view":
        "https://www.tradingview.com/chart/"
}


# ============================================================
# NORMALIZZA NOME
# ============================================================

def normalizza_nome(nome):

    return nome.lower().strip()


def _trova_collegamento_menu_start(nome):
    """Trova applicazioni realmente installate senza eseguire testo arbitrario."""
    richiesto = normalizza_nome(nome).removesuffix(".exe")
    roots = (
        Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")),
        Path(os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs")),
    )
    exact = []
    partial = []
    for root in roots:
        if not root.exists():
            continue
        try:
            shortcuts = root.rglob("*.lnk")
            for shortcut in shortcuts:
                key = normalizza_nome(shortcut.stem).removesuffix(".exe")
                if key == richiesto:
                    exact.append(shortcut)
                elif richiesto and richiesto in key:
                    partial.append(shortcut)
        except OSError:
            continue
    matches = exact or partial
    return matches[0] if len(matches) == 1 else None


# ============================================================
# APRI PROGRAMMA
# ============================================================

def apri_programma(nome):

    nome = normalizza_nome(
        nome
    )

    # Nomi di servizi web pronunciati con "apri" usano il browser nativo.
    # Questo fast path non dipende dall'estensione DOM di Chrome.
    if nome in SITI:
        return apri_sito(nome)


    if nome not in APPS:
        shortcut = _trova_collegamento_menu_start(nome)
        if shortcut is None:
            return (False, f"Non trovo un programma installato chiamato {nome}.")
        try:
            os.startfile(str(shortcut))
            return (True, f"Ho aperto {shortcut.stem}.")
        except OSError as errore:
            LOGGER.warning("Apertura collegamento Start fallita: %r", errore)
            return (False, f"Ho trovato {shortcut.stem}, ma Windows non è riuscito ad aprirlo.")


    dati = APPS[nome]


    for percorso in dati["percorsi"]:

        try:

            # =================================================
            # ESEGUIBILE WINDOWS DIRETTO
            # =================================================

            if "\\" not in percorso:

                subprocess.Popen(
                    percorso
                )

                if nome in {"blocco note", "notepad"}:
                    scadenza = time.monotonic() + 3.0
                    while time.monotonic() < scadenza:
                        processo_presente = any(
                            (proc.info.get("name") or "").casefold() == "notepad.exe"
                            for proc in psutil.process_iter(["name"])
                        )
                        finestre = gw.getWindowsWithTitle("Blocco note") or gw.getWindowsWithTitle("Notepad")
                        if finestre and all(getattr(window, "isMinimized", False) for window in finestre):
                            try:
                                finestre[0].restore()
                                finestre[0].activate()
                            except Exception as exc:
                                LOGGER.warning("Ripristino finestra Blocco note fallito: %r", exc)
                        finestra_presente = bool(finestre and any(not getattr(window, "isMinimized", False) for window in finestre))
                        if processo_presente and finestra_presente:
                            break
                        time.sleep(0.05)
                    else:
                        LOGGER.error("Blocco note avviato ma non verificato: processo=%s finestra=%s", processo_presente, finestra_presente)
                        return (False, "Blocco note non risulta realmente aperto.")

                return (
                    True,
                    f"Ho aperto {nome}."
                )


            # =================================================
            # PERCORSO COMPLETO
            # =================================================

            if os.path.exists(
                percorso
            ):

                if nome == "discord":

                    subprocess.Popen([
                        percorso,
                        "--processStart",
                        "Discord.exe"
                    ])

                else:
                    if nome in {"chrome", "google chrome"}:
                        if not _avvia_chrome_controllato(percorso):
                            return (
                                False,
                                "Chrome non è stato avviato."
                            )
                    else:
                        subprocess.Popen([percorso])


                return (
                    True,
                    f"Ho aperto {nome}."
                )


        except Exception as errore:

            print()
            print(
                "Errore apertura programma:"
            )

            print(
                redact(repr(errore))
            )


    return (
        False,
        f"Non riesco a trovare {nome} sul computer."
    )


# ============================================================
# CHIUDI PROGRAMMA
# ============================================================

def chiudi_programma(nome):

    nome = normalizza_nome(
        nome
    )


    if nome not in APPS:

        return (
            False,
            f"Non conosco ancora il programma {nome}."
        )


    processo = APPS[nome][
        "processo"
    ]


    try:
        finestre = _finestre_con_titolo(*_titoli_programma(nome))
        if not _processo_presente(processo) and not finestre:
            return (
                False,
                f"{nome} non sembra essere aperto."
            )

        # Prima chiediamo alla finestra di chiudersi normalmente, così i dati
        # possono essere salvati e il processo non resta bloccato in background.
        for finestra in finestre:
            try:
                finestra.close()
            except Exception as exc:
                LOGGER.debug("Chiusura finestra %s fallita: %s", nome, redact(repr(exc)))

        if _attendi_chiusura(nome, processo):
            return (
                True,
                f"Ho chiuso {nome} e ho verificato che non sia più aperto."
            )

        # Fallback per applicazioni che ignorano WM_CLOSE o hanno finestre
        # senza titolo riconoscibile. Il risultato viene verificato dopo.
        risultato = subprocess.run(
            [
                "taskkill",
                "/F",
                "/T",
                "/IM",
                processo
            ],
            capture_output=True,
            text=True,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            )
        )

        if risultato.returncode == 0 and _attendi_chiusura(nome, processo):
            return (
                True,
                f"Ho chiuso {nome} e ho verificato che non sia più aperto."
            )

        dettaglio = (risultato.stderr or risultato.stdout or "").strip()
        return (
            False,
            f"Non sono riuscito a chiudere {nome}: Windows non conferma la chiusura."
            + (f" {dettaglio[:180]}" if dettaglio else "")
        )


    except Exception as errore:

        print()
        print(
            "Errore chiusura programma:"
        )

        print(
            redact(repr(errore))
        )


        return (
            False,
            f"Non sono riuscito a chiudere {nome}."
        )


# ============================================================
# APRI SITO
# ============================================================

def apri_sito(nome):

    nome = normalizza_nome(
        nome
    )


    if nome not in SITI:

        return (
            False,
            f"Non conosco il sito {nome}."
        )


    try:

        aperto = webbrowser.open(
            SITI[nome]
        )

        if aperto is False:
            return (
                False,
                f"Non sono riuscito ad aprire {nome}."
            )

        return (
            True,
            f"Ho aperto {nome}."
        )


    except Exception as errore:

        print(
            "Errore apertura sito:",
            redact(str(errore))
        )


        return (
            False,
            f"Non sono riuscito ad aprire {nome}."
        )


# ============================================================
# GOOGLE
# ============================================================

def cerca_google(query):

    query = query.strip()


    if not query:

        return (
            False,
            "Non hai specificato cosa cercare."
        )


    url = (
        "https://www.google.com/search?q="
        +
        quote_plus(
            query
        )
    )


    try:

        aperto = webbrowser.open(
            url
        )

        if aperto is False:
            return (
                False,
                "Non sono riuscito ad aprire la ricerca."
            )

        return (
            True,
            f"Sto cercando {query} su Google."
        )


    except Exception:

        return (
            False,
            "Non sono riuscito ad aprire la ricerca."
        )


# ============================================================
# OTTIENI INTERFACCIA VOLUME WINDOWS
# ============================================================

def _ottieni_volume():

    dispositivo = AudioUtilities.GetSpeakers()


    try:

        return dispositivo.EndpointVolume

    except Exception:

        interfaccia = dispositivo.Activate(
            IAudioEndpointVolume._iid_,
            CLSCTX_ALL,
            None
        )


        return interfaccia.QueryInterface(
            IAudioEndpointVolume
        )


# ============================================================
# IMPOSTA VOLUME
# ============================================================

def imposta_volume(percentuale):

    try:

        percentuale = int(
            percentuale
        )


        percentuale = max(
            0,
            min(
                100,
                percentuale
            )
        )


    except (TypeError, ValueError):

        return (
            False,
            "Il valore del volume non è valido."
        )


    comtypes.CoInitialize()


    try:

        volume = _ottieni_volume()


        # Se imposto un volume maggiore di 0
        # tolgo automaticamente il muto.
        if percentuale > 0:

            volume.SetMute(
                0,
                None
            )


        volume.SetMasterVolumeLevelScalar(
            percentuale / 100.0,
            None
        )


        valore_reale = int(
            round(
                volume.GetMasterVolumeLevelScalar()
                *
                100
            )
        )


        print(
            f"Volume Windows: {valore_reale}%"
        )


        return (
            True,
            f"Volume impostato al {valore_reale} percento."
        )


    except Exception as errore:

        print()
        print(
            "Errore volume:"
        )

        print(
            redact(repr(errore))
        )


        return (
            False,
            "Non sono riuscito a modificare il volume."
        )


    finally:

        try:

            comtypes.CoUninitialize()

        except (OSError, RuntimeError) as exc:
            LOGGER.debug("COM audio cleanup failed: %s", exc)


# ============================================================
# CAMBIA VOLUME RELATIVAMENTE
# ============================================================

def modifica_volume(variazione):

    try:

        variazione = int(
            variazione
        )

    except (TypeError, ValueError):

        return (
            False,
            "La variazione del volume non è valida."
        )


    comtypes.CoInitialize()


    try:

        volume = _ottieni_volume()


        volume_attuale = (
            volume.GetMasterVolumeLevelScalar()
            *
            100
        )


        nuovo_volume = int(
            round(
                volume_attuale
                +
                variazione
            )
        )


        nuovo_volume = max(
            0,
            min(
                100,
                nuovo_volume
            )
        )


        if nuovo_volume > 0:

            volume.SetMute(
                0,
                None
            )


        volume.SetMasterVolumeLevelScalar(
            nuovo_volume / 100.0,
            None
        )


        if variazione > 0:

            messaggio = (
                f"Ho alzato il volume al "
                f"{nuovo_volume} percento."
            )

        else:

            messaggio = (
                f"Ho abbassato il volume al "
                f"{nuovo_volume} percento."
            )


        return (
            True,
            messaggio
        )


    except Exception as errore:

        print()
        print(
            "Errore modifica volume:"
        )

        print(
            redact(repr(errore))
        )


        return (
            False,
            "Non sono riuscito a modificare il volume."
        )


    finally:

        try:

            comtypes.CoUninitialize()

        except (OSError, RuntimeError) as exc:
            LOGGER.debug("COM audio cleanup failed: %s", exc)


# ============================================================
# MUTO / AUDIO ATTIVO
# ============================================================

def imposta_muto(attivo):

    comtypes.CoInitialize()


    try:

        volume = _ottieni_volume()


        if attivo:

            volume.SetMute(
                1,
                None
            )

            return (
                True,
                "Audio disattivato."
            )


        volume.SetMute(
            0,
            None
        )


        return (
            True,
            "Audio riattivato."
        )


    except Exception as errore:

        print()
        print(
            "Errore muto:"
        )

        print(
            redact(repr(errore))
        )


        return (
            False,
            "Non sono riuscito a modificare lo stato dell'audio."
        )


    finally:

        try:

            comtypes.CoUninitialize()

        except (OSError, RuntimeError) as exc:
            LOGGER.debug("COM audio cleanup failed: %s", exc)


# ============================================================
# CERCA FILE
# ============================================================

def cerca_file(nome):

    nome = nome.lower().strip()


    if not nome:

        return (
            False,
            "Non hai specificato cosa cercare."
        )


    cartelle = [

        Path.home() / "Desktop",

        Path.home() / "Documents",

        Path.home() / "Downloads"
    ]


    risultati = []


    for cartella in cartelle:

        if not cartella.exists():

            continue


        try:

            for elemento in cartella.rglob(
                "*"
            ):

                if nome in elemento.name.lower():

                    risultati.append(
                        elemento
                    )


                    if len(risultati) >= 10:

                        break


        except (
            PermissionError,
            OSError
        ):

            pass


        if len(risultati) >= 10:

            break


    if not risultati:

        return (
            False,
            f"Non ho trovato niente chiamato {nome}."
        )


    primo = risultati[0]


    try:

        if primo.is_dir():

            os.startfile(
                primo
            )

        else:

            os.startfile(
                primo.parent
            )

    except OSError as exc:
        LOGGER.warning("Unable to open search result %s: %s", primo, exc)


    return (
        True,
        f"Ho trovato {primo.name}."
    )
