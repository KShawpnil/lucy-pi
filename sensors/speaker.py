"""Text-to-speech output for Lucy Pi."""

from dotenv import load_dotenv

load_dotenv()

import pyttsx3


class SpeakerManager:
    def __init__(self) -> None:
        self.engine = pyttsx3.init()

    def speak(self, text: str) -> None:
        self.engine.say(text)
        self.engine.runAndWait()


speaker = SpeakerManager()
