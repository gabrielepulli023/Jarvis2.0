#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEST COMPLETO - Simula il flusso di main.py senza il loop Qt
Traccia quante volte viene generato il barge-in per una risposta
"""

import os
import sys
import threading
import queue
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Encoding UTF-8
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 90)
print("TEST COMPLETO - TRACCIA FLUSSO AI → TTS → PLAYBACK")
print("=" * 90)

sys.path.insert(0, str(Path.cwd()))

try:
    from ai import chiedi_jarvis, frase_pronta
    from settings_store import get_setting
    
    # Configurazione
    print(f"\n[CONFIG]")
    print(f"  prefer_local_stt: {get_setting('prefer_local_stt')}")
    print(f"  local_streaming_stt: {get_setting('local_streaming_stt')}")
    
    # Domanda che genera risposta lunga con MULTIPLE FRASI BREVI
    domanda = "Rispondi CON EXACT questo schema. Frase1: primo argomento. Frase2: secondo argomento. Frase3: terzo argomento. Frase4: quarto argomento. Frase5: quinto argomento."
    
    print(f"\n[DOMANDA]")
    print(f"  {repr(domanda)}\n")
    
    # Simula il flusso di main.py
    phrase_queue = queue.Queue()
    producer_error = []
    phrase_data = {"count": 0, "start": time.perf_counter(), "frasi": []}
    
    def produce_response():
        """Producer thread - legge da chiedi_jarvis()"""
        full = ""
        try:
            for phrase in chiedi_jarvis(domanda):
                if not phrase:
                    continue
                phrase_data["count"] += 1
                idx = phrase_data["count"]
                elapsed = time.perf_counter() - phrase_data["start"]
                
                full = (full + " " + phrase).strip()
                phrase_data["frasi"].append({
                    "num": idx,
                    "testo": phrase,
                    "lunghezza": len(phrase),
                    "tempo": elapsed
                })
                
                print(f"[AI STREAM] Frase {idx} ricevuta (t={elapsed:.2f}s):")
                print(f"  {repr(phrase[:80])}")
                
                phrase_queue.put(phrase)
        except Exception as exc:
            producer_error.append(exc)
            print(f"[ERRORE PRODUCER] {exc}")
        finally:
            phrase_queue.put(None)
    
    # Avvia producer
    producer = threading.Thread(target=produce_response, daemon=True)
    producer.start()
    
    # Simula il flusso di main thread
    print("\n[MAIN THREAD - Simulazione parla_controllato() calls]\n")
    parla_calls = []
    parla_idx = 0
    
    while True:
        frase = phrase_queue.get()
        if frase is None:
            break
        
        parla_idx += 1
        elapsed = time.perf_counter() - phrase_data["start"]
        parla_calls.append({
            "num": parla_idx,
            "testo": frase,
            "tempo": elapsed
        })
        
        print(f"[PARLA CALL #{parla_idx}] (t={elapsed:.2f}s):")
        print(f"  {repr(frase[:80])}")
        print(f"  Durata stimata TTS: {max(1, len(frase) // 20):.1f}s")
        
        # Simula playback duration
        playback_duration = max(1, len(frase) // 20)
        print(f"  → Playback simulato...")
        time.sleep(0.1)  # Minimal delay
    
    # Report
    print("\n" + "=" * 90)
    print("REPORT DIAGNOSTICA")
    print("=" * 90)
    
    print(f"\nTotale frasi generate da chiedi_jarvis(): {phrase_data['count']}")
    print(f"Totale parla_controllato() calls: {parla_idx}")
    
    if phrase_data['count'] > 1:
        print(f"\n⚠️  PROBLEMA TROVATO!")
        print(f"La risposta è stata spezzata in {phrase_data['count']} frasi separate")
        print(f"Questo causa {phrase_data['count']} file TTS generati separatamente")
        print(f"E {phrase_data['count']} playback separati")
        print(f"\nDettagli frasi:")
        for frase in phrase_data["frasi"]:
            print(f"  [{frase['num']}] t={frase['tempo']:.2f}s, len={frase['lunghezza']}, termina: {repr(frase['testo'][-10:])}")
    else:
        print(f"\n✅ OK: Risposta generata come una singola frase")
        print(f"   Una sola chiamata a parla(), un solo playback")
    
    print("\n[ANALISI]")
    print("Se ce sono MULTIPLE parla() calls, il problema è:")
    print("1. frase_pronta() spezza la risposta in frasi separate")
    print("2. Ogni frase genera un file TTS separato")
    print("3. Ogni playback è separato dagli altri")
    print("4. Tra playback c'è un gap di silenzio")
    print("5. Durante il gap, barge-in si attiva → falso rilevamento voce")
    print("\nSOLUZIONE:")
    print("- Accumulare tutte le frasi in un buffer unico")
    print("- Generare UN SOLO file TTS per intera risposta")
    print("- UN playback continuo")
    print("- Barge-in solo DURANTE playback, non tra playback")
    
except Exception as e:
    print(f"\n❌ ERRORE: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 90)
