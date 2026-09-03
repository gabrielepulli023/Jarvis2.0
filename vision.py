import base64
import json
from dotenv import load_dotenv
from llm_gateway import openai_client

from settings_store import get_setting
from jarvis_perception.capture import ScreenCaptureEngine
from jarvis_core.logging import redact


load_dotenv()
client = openai_client(profile="vision")
_CAPTURE = ScreenCaptureEngine()


def _screen_data_url():
    frame = _CAPTURE.full()
    return "data:image/jpeg;base64," + base64.b64encode(frame.jpeg).decode("ascii")


def analizza_schermo(domanda="Descrivi ciò che è visibile e segnala eventuali errori."):
    """Analizza lo schermo corrente senza conservare l'immagine."""
    if not get_setting("vision_enabled", True):
        return {"successo": False, "messaggio": "La visione dello schermo è disattivata nelle impostazioni."}
    try:
        response = client.responses.create(
            model=str(get_setting("vision_model", get_setting("ai_model", "gpt-5.6-luna"))),
            instructions=(
                "Sei il modulo visivo di JARVIS. Analizza solo ciò che è realmente visibile. "
                "Non inventare elementi nascosti. Non trascrivere password, token o dati di carte: "
                "indicali come dati sensibili. Rispondi in italiano, in modo sintetico e operativo."
            ),
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": str(domanda)},
                {"type": "input_image", "image_url": _screen_data_url(), "detail": "high"},
            ]}],
            reasoning={"effort": "low"},
        )
        text = str(response.output_text or "").strip()
        return {"successo": bool(text), "messaggio": text or "Non riesco a interpretare lo schermo."}
    except Exception as exc:
        return {"successo": False, "messaggio": "Analisi visiva non disponibile.", "errore": redact(repr(exc))}


def individua_elemento(elemento):
    """Restituisce coordinate stimate di un elemento visibile, senza cliccare."""
    prompt = (
        f"Trova l'elemento seguente sullo schermo: {elemento}. "
        "Rispondi esclusivamente con JSON nel formato "
        '{"found":true,"x":123,"y":456,"confidence":0.9,"description":"..."}. '
        "Le coordinate devono riferirsi allo schermo originale. Se non è visibile usa found false."
    )
    result = analizza_schermo(prompt)
    if not result.get("successo"):
        return result
    raw = result["messaggio"].strip().removeprefix("```json").removesuffix("```").strip()
    try:
        data = json.loads(raw)
        if not data.get("found"):
            return {"successo": False, "messaggio": "Elemento non trovato.", "dati": data}
        return {"successo": True, "messaggio": f"Elemento individuato a {data.get('x')}, {data.get('y')}.", "dati": data}
    except Exception:
        return {"successo": False, "messaggio": "La posizione visiva non è abbastanza affidabile.", "risposta": raw}
