"""Text-to-speech output for Lucy Pi."""

import os

os.environ["AUDIODEV"] = "plughw:2,0"
os.environ["AUDIODRIVER"] = "alsa"
os.environ["ALSA_PCM_CARD"] = "2"
os.environ["ALSA_PCM_DEVICE"] = "0"

import threading
import time

import pyttsx3


class SpeakerManager:
    def __init__(self) -> None:
        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", 150)
        self.engine.setProperty("volume", 1.0)
        self.is_speaking = False
        print("Lucy speaker initialised successfully")

    def speak(self, text: str) -> None:
        try:
            self.is_speaking = True
            print(f"Lucy is about to say: {text}")
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as exc:
            print(f"Lucy speaker error — {exc}")
        finally:
            self.is_speaking = False

    def speak_async(self, text: str) -> None:
        thread = threading.Thread(
            target=self.speak,
            args=(text,),
            name="lucy-speaker",
            daemon=True,
        )
        thread.start()

    def is_active(self) -> bool:
        return self.is_speaking

    def stop(self) -> None:
        try:
            self.engine.stop()
        except Exception as exc:
            print(f"Lucy speaker stop error — {exc}")
        self.is_speaking = False


speaker = SpeakerManager()
