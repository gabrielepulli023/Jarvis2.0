import os
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path


ROOT = Path.home() / "Documents" / "Jarvis"


def crea_bozza_email(destinatario, oggetto, corpo, apri=True):
    folder = ROOT / "Bozze Email"; folder.mkdir(parents=True, exist_ok=True)
    message = EmailMessage()
    message["To"] = str(destinatario)
    message["Subject"] = str(oggetto)
    message.set_content(str(corpo))
    path = folder / f"bozza_{datetime.now():%Y%m%d_%H%M%S}.eml"
    path.write_bytes(message.as_bytes())
    if apri and os.name == "nt":
        os.startfile(path)
    return {"successo": True, "messaggio": f"Bozza email creata: {path}", "percorso": str(path)}


def crea_evento_calendario(titolo, inizio_iso, fine_iso, descrizione="", luogo="", apri=True):
    start = datetime.fromisoformat(str(inizio_iso))
    end = datetime.fromisoformat(str(fine_iso))
    if end <= start:
        return {"successo": False, "messaggio": "La fine deve essere successiva all'inizio."}
    folder = ROOT / "Calendario"; folder.mkdir(parents=True, exist_ok=True)
    def esc(value):
        return str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    content = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JARVIS//IT", "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@jarvis.local", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
        f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}",
        f"SUMMARY:{esc(titolo)}", f"DESCRIPTION:{esc(descrizione)}", f"LOCATION:{esc(luogo)}",
        "END:VEVENT", "END:VCALENDAR", "",
    ])
    path = folder / f"evento_{start:%Y%m%d_%H%M}.ics"
    path.write_text(content, encoding="utf-8")
    if apri and os.name == "nt":
        os.startfile(path)
    return {"successo": True, "messaggio": f"Evento calendario creato: {path}", "percorso": str(path)}
