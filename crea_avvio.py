import asyncio
import edge_tts


async def crea():

    testo = "Jarvis online."

    voce = "it-IT-DiegoNeural"

    comunicazione = edge_tts.Communicate(
        testo,
        voce
    )

    await comunicazione.save("avvio.mp3")


asyncio.run(crea())

print("File avvio.mp3 creato")