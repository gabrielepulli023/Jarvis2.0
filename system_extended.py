import os
import shutil
import socket
import subprocess
import zipfile
from pathlib import Path

import psutil
from jarvis_core.logging import redact


def info_rete():
    adapters = {}
    for name, addresses in psutil.net_if_addrs().items():
        adapters[name] = [a.address for a in addresses if a.address]
    return {"successo": True, "messaggio": f"Host {socket.gethostname()}, {len(adapters)} interfacce rilevate.", "dati": adapters}


def connessioni_rete(limit=30):
    rows = []
    try:
        for item in psutil.net_connections(kind="inet")[:max(1, min(int(limit), 100))]:
            rows.append({"locale": str(item.laddr), "remoto": str(item.raddr), "stato": item.status, "pid": item.pid})
        return {"successo": True, "messaggio": f"Rilevate {len(rows)} connessioni.", "dati": rows}
    except Exception as exc:
        return {"successo": False, "messaggio": "Impossibile leggere tutte le connessioni.", "errore": redact(repr(exc))}


def servizi_windows(filtro=""):
    if os.name != "nt":
        return {"successo": False, "messaggio": "Disponibile solo su Windows."}
    rows = []
    needle = str(filtro).lower()
    for service in psutil.win_service_iter():
        try:
            data = service.as_dict()
            if not needle or needle in data.get("name", "").lower() or needle in data.get("display_name", "").lower():
                rows.append({k: data.get(k) for k in ("name", "display_name", "status", "start_type")})
        except Exception:
            continue
    return {"successo": True, "messaggio": f"Trovati {len(rows)} servizi.", "dati": rows[:100]}


def crea_archivio_zip(sorgente, destinazione):
    source = Path(sorgente).expanduser().resolve(); target = Path(destinazione).expanduser().resolve()
    if not source.exists():
        return {"successo": False, "messaggio": "Sorgente inesistente."}
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        if source.is_file(): archive.write(source, source.name)
        else:
            for item in source.rglob("*"):
                if item.is_file(): archive.write(item, item.relative_to(source.parent))
    return {"successo": True, "messaggio": f"Archivio creato: {target}", "percorso": str(target)}


def estrai_archivio_zip(archivio, destinazione):
    source = Path(archivio).expanduser().resolve(); target = Path(destinazione).expanduser().resolve()
    if not source.exists(): return {"successo": False, "messaggio": "Archivio inesistente."}
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        root = str(target)
        for member in archive.infolist():
            candidate = str((target / member.filename).resolve())
            if not candidate.startswith(root + os.sep):
                return {"successo": False, "messaggio": "Archivio non sicuro: percorso esterno rilevato."}
        archive.extractall(target)
    return {"successo": True, "messaggio": f"Archivio estratto in {target}", "percorso": str(target)}


def spazio_cartella(percorso):
    root = Path(percorso).expanduser().resolve()
    if not root.exists(): return {"successo": False, "messaggio": "Percorso inesistente."}
    total = root.stat().st_size if root.is_file() else sum(x.stat().st_size for x in root.rglob("*") if x.is_file())
    return {"successo": True, "messaggio": f"Dimensione: {total / 1048576:.2f} MB.", "bytes": total}


def stato_wifi():
    if os.name != "nt": return {"successo": False, "messaggio": "Disponibile solo su Windows."}
    result = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=10, shell=False)
    return {"successo": result.returncode == 0, "messaggio": (result.stdout or result.stderr)[-5000:]}


def programmi_installati(query=""):
    if not shutil.which("winget"): return {"successo": False, "messaggio": "winget non disponibile."}
    command = ["winget", "list", "--disable-interactivity"]
    if str(query).strip(): command += ["--query", str(query).strip()]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, shell=False)
    return {"successo": result.returncode == 0, "messaggio": (result.stdout or result.stderr)[-12000:]}


def installa_programma(package_id, confermato=False):
    if not confermato: return {"successo": False, "messaggio": "Installazione in attesa di conferma."}
    from jarvis_broker import BrokerClient
    result = BrokerClient().execute("winget.install", {"package_id": str(package_id)}, confirmed=True, timeout=900)
    return {"successo": result.success, "messaggio": result.message, "dati": result.data}


def aggiorna_programma(package_id, confermato=False):
    if not confermato: return {"successo": False, "messaggio": "Aggiornamento in attesa di conferma."}
    from jarvis_broker import BrokerClient
    result = BrokerClient().execute("winget.upgrade", {"package_id": str(package_id)}, confirmed=True, timeout=900)
    return {"successo": result.success, "messaggio": result.message, "dati": result.data}
