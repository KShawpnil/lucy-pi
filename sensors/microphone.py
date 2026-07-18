"""Wake word detection and speech transcription for Lucy Pi."""

from __future__ import annotations

import io
import os
import threading
import time
import wave

import numpy as np
import openwakeword
import sounddevice as sd
import speech_recognition as sr
from dotenv import load_dotenv
from openwakeword.model import Model

load_dotenv()

WAKE_WORD_THRESHOLD = 0.5
TRIM_AMPLITUDE_THRESHOLD = 500
MIN_NOTE_SECONDS = 0.5
RECORD_SECONDS = 30
RETRIGGER_SLEEP_SECONDS = 2


class MicrophoneManager:
    """OpenWakeWord + Google Speech Recognition for Lucy voice notes."""

    def __init__(self) -> None:
        self.is_detecting = False
        self.is_recording = False
        self.wake_word_callback = None
        self.wake_word_detected_callback = None
        self.sample_rate = 16000
        self.chunk_size = 1280

        self.owwModel = Model(
            wakeword_models=["hey_jarvis"],
            inference_framework="onnx",
        )

        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.pause_threshold = 1.5

        print("Lucy microphone manager initialised successfully")

    def start_wake_word_detection(self, callback) -> None:
        self.wake_word_callback = callback
        self.is_detecting = True
        thread = threading.Thread(
            target=self._detection_loop,
            name="lucy-wake-word-detection",
            daemon=True,
        )
        thread.start()
        print("Lucy wake word detection started, listening for Hey Jarvis")

    def _detection_loop(self) -> None:
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=self.chunk_size,
                device=None,
            ) as stream:
                while self.is_detecting:
                    try:
                        chunk, _overflowed = stream.read(self.chunk_size)
                        audio = np.asarray(chunk, dtype=np.int16).reshape(-1)

                        prediction = self.owwModel.predict(audio)
                        scores = prediction if isinstance(prediction, dict) else {}

                        if any(score > WAKE_WORD_THRESHOLD for score in scores.values()):
                            if not self.is_recording:
                                print("Wake word detected, starting recording")
                                self.is_recording = True
                                if self.wake_word_detected_callback is not None:
                                    threading.Thread(
                                        target=self.wake_word_detected_callback,
                                        name="lucy-wake-word-detected",
                                        daemon=True,
                                    ).start()
                                threading.Thread(
                                    target=self._record_and_transcribe,
                                    name="lucy-record-transcribe",
                                    daemon=True,
                                ).start()
                                time.sleep(RETRIGGER_SLEEP_SECONDS)
                    except Exception as exc:
                        print(f"Lucy microphone detection chunk error — {exc}")
        except Exception as exc:
            print(f"Lucy microphone detection loop error — {exc}")

    def _record_and_transcribe(self) -> None:
        print("Lucy is listening for your note")
        try:
            recording = sd.rec(
                int(self.sample_rate * RECORD_SECONDS),
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                blocking=True,
            )
            sd.wait()

            audio = np.asarray(recording, dtype=np.int16).reshape(-1)
            trimmed = self._trim_trailing_silence(audio, TRIM_AMPLITUDE_THRESHOLD)

            min_samples = int(self.sample_rate * MIN_NOTE_SECONDS)
            if len(trimmed) <= min_samples:
                return

            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(trimmed.tobytes())
            wav_buffer.seek(0)

            with sr.AudioFile(wav_buffer) as source:
                audio_data = self.recognizer.record(source)

            try:
                text = self.recognizer.recognize_google(audio_data, language="en-US")
                print(text)
                if self.wake_word_callback is not None:
                    self.wake_word_callback(text)
            except sr.UnknownValueError:
                print("Lucy could not understand the audio")
            except sr.RequestError:
                print("Google speech recognition service unavailable")
        except Exception as exc:
            print(f"Lucy record and transcribe error — {exc}")
        finally:
            self.is_recording = False

    def _trim_trailing_silence(
        self, audio: np.ndarray, amplitude_threshold: int
    ) -> np.ndarray:
        """Remove trailing silence using the last chunk above the amplitude threshold."""
        if audio.size == 0:
            return audio

        chunk_size = self.chunk_size
        last_index = 0
        for start in range(len(audio) - chunk_size, -1, -chunk_size):
            chunk = audio[start : start + chunk_size]
            if np.max(np.abs(chunk)) > amplitude_threshold:
                last_index = start + len(chunk)
                break

        return audio[:last_index]

    def stop(self) -> None:
        self.is_detecting = False
        print("Lucy microphone detection stopped")


microphone = MicrophoneManager()
