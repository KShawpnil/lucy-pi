import os
import io
import time
import wave
import threading
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from dotenv import load_dotenv

load_dotenv()

SAMPLE_RATE = 16000
CHUNK_SECONDS = 3
RECORD_SECONDS = 45
PAUSE_THRESHOLD = 2.5
ENERGY_THRESHOLD = 200
WAKE_PHRASE = "hey lucy"


class MicrophoneManager:

    def __init__(self):
        self.is_detecting = False
        self.is_recording = False
        self.wake_word_callback = None
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = ENERGY_THRESHOLD
        self.recognizer.pause_threshold = PAUSE_THRESHOLD
        print("Lucy microphone manager initialised successfully")

    def start_wake_word_detection(self, callback):
        self.wake_word_callback = callback
        self.is_detecting = True
        t = threading.Thread(target=self._detection_loop, daemon=True)
        t.start()
        print("Lucy wake word detection started, listening for Hey Lucy")

    def _detection_loop(self):
        while self.is_detecting:
            try:
                audio_data = sd.rec(
                    int(CHUNK_SECONDS * SAMPLE_RATE),
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype='int16'
                )
                sd.wait()
                raw_bytes = audio_data.tobytes()
                audio = sr.AudioData(raw_bytes, SAMPLE_RATE, 2)
                try:
                    text = self.recognizer.recognize_google(audio, language="en-US")
                    print(f"Lucy heard: {text}")
                    if WAKE_PHRASE in text.lower():
                        if not self.is_recording:
                            self.is_recording = True
                            print("Wake word detected")
                            t = threading.Thread(
                                target=self._record_and_transcribe,
                                daemon=True
                            )
                            t.start()
                            time.sleep(2)
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    print(f"Lucy speech recognition error: {e}")
                    time.sleep(5)
            except Exception as e:
                print(f"Lucy detection loop error: {e}")
                time.sleep(1)

    def _record_and_transcribe(self):
        try:
            time.sleep(2.5)
            print("Lucy is listening for your note")
            audio_data = sd.rec(
                int(RECORD_SECONDS * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype='int16'
            )
            sd.wait()
            samples = audio_data.flatten()
            last_sound = np.where(np.abs(samples) > 500)[0]
            if len(last_sound) > 0:
                trimmed = samples[:last_sound[-1] + 1]
            else:
                trimmed = samples
            duration = len(trimmed) / SAMPLE_RATE
            if duration < 0.5:
                print("Lucy did not capture enough audio")
                self.is_recording = False
                return
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(trimmed.tobytes())
            buf.seek(0)
            with sr.AudioFile(buf) as source:
                recorded = self.recognizer.record(source)
            try:
                transcription = self.recognizer.recognize_google(
                    recorded, language="en-US"
                )
                print(f"Lucy transcribed: {transcription}")
                if self.wake_word_callback:
                    self.wake_word_callback(transcription)
            except sr.UnknownValueError:
                print("Lucy could not understand the audio")
            except sr.RequestError as e:
                print(f"Lucy transcription error: {e}")
        except Exception as e:
            print(f"Lucy recording error: {e}")
        finally:
            self.is_recording = False

    def stop(self):
        self.is_detecting = False
        print("Lucy microphone detection stopped")


microphone = MicrophoneManager()
