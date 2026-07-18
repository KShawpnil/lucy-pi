"""Wake word detection and speech transcription for Lucy Pi."""

import io
import os
import threading
import time
import wave

import numpy as np
import sounddevice as sd
import speech_recognition as sr
from dotenv import load_dotenv

load_dotenv()

DETECTION_SECONDS = 3
RETRIGGER_SLEEP_SECONDS = 2
REQUEST_ERROR_SLEEP_SECONDS = 5
WAKE_PHRASE = "hey lucy"


class MicrophoneManager:
    def __init__(self) -> None:
        self.is_detecting = False
        self.is_recording = False
        self.wake_word_callback = None
        self.sample_rate = 16000

        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.pause_threshold = 1.5

    def start_wake_word_detection(self, callback) -> None:
        self.wake_word_callback = callback
        self.is_detecting = True
        thread = threading.Thread(
            target=self._detection_loop,
            name="lucy-wake-word-detection",
            daemon=True,
        )
        thread.start()

    def _detection_loop(self) -> None:
        while self.is_detecting:
            try:
                recording = sd.rec(
                    int(self.sample_rate * DETECTION_SECONDS),
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                    blocking=True,
                )
                sd.wait()

                audio_bytes = np.asarray(recording, dtype=np.int16).reshape(-1).tobytes()
                audio_data = sr.AudioData(audio_bytes, self.sample_rate, 2)

                try:
                    text = self.recognizer.recognize_google(
                        audio_data, language="en-US"
                    )
                    if WAKE_PHRASE in text.lower():
                        if self.wake_word_callback is not None:
                            self.wake_word_callback(text)
                        time.sleep(RETRIGGER_SLEEP_SECONDS)
                except sr.UnknownValueError:
                    continue
                except sr.RequestError:
                    time.sleep(REQUEST_ERROR_SLEEP_SECONDS)
                    continue
            except Exception as exc:
                print(f"Lucy microphone detection error — {exc}")

    def stop(self) -> None:
        self.is_detecting = False


microphone = MicrophoneManager()
