import speech_recognition as sr

print("Microfoni disponibili:\n")

microfoni = sr.Microphone.list_microphone_names()

for indice, nome in enumerate(microfoni):
    print(indice, "-", nome)


print("\nTest microfono selezionato")

indice = 28   # cambia questo numero per provare altri microfoni

riconoscitore = sr.Recognizer()


try:

    with sr.Microphone(device_index=indice) as fonte:

        print("\nParla ora...")

        riconoscitore.adjust_for_ambient_noise(
            fonte,
            duration=1
        )

        audio = riconoscitore.listen(
            fonte,
            timeout=5
        )


    print("Audio ricevuto")


    testo = riconoscitore.recognize_google(
        audio,
        language="it-IT"
    )

    print("Hai detto:", testo)


except Exception as errore:

    print("\nERRORE:")
    print(errore)