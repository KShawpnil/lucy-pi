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
            if self.is_recording:
                time.sleep(0.5)
                continue
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
                            time.sleep(5)
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
            time.sleep(3.5)
            print("Lucy is listening for your note")
            max_samples = 60 * SAMPLE_RATE
            silence_samples = 3 * SAMPLE_RATE
            silence_threshold = 300
            chunk_samples = SAMPLE_RATE
            chunks = []
            while sum(len(chunk) for chunk in chunks) < max_samples:
                block = sd.rec(
                    chunk_samples,
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype='int16'
                )
                sd.wait()
                chunks.append(block.flatten())
                combined = np.concatenate(chunks)
                if len(combined) >= silence_samples:
                    last_window = combined[-silence_samples:]
                    if np.max(np.abs(last_window)) < silence_threshold:
                        break
            samples = np.concatenate(chunks)
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
                cleaned = transcription.strip()
                if cleaned.lower().startswith(WAKE_PHRASE):
                    cleaned = cleaned.replace(cleaned[: len(WAKE_PHRASE)], "", 1).strip()
                if cleaned.lower().endswith("stop"):
                    cleaned = cleaned.replace("stop", "", 1).strip()
                print(f"Lucy transcribed: {cleaned}")
                if self.wake_word_callback:
                    self.wake_word_callback(cleaned)
            except sr.UnknownValueError:
                print("Lucy could not understand the audio")
            except sr.RequestError as e:
                print(f"Lucy transcription error: {e}")
        except Exception as e:
            print(f"Lucy recording error: {e}")
        finally:
            self.is_recording = False

    def release_microphone(self):
        self.is_detecting = False
        self.is_recording = False
        sd.stop()
        sd.wait()
        time.sleep(2)
        print("Lucy microphone fully released")

    def stop(self):
        self.release_microphone()

    def restart(self):
        self.is_detecting = False
        time.sleep(1)
        self.start_wake_word_detection(self.wake_word_callback)


microphone = MicrophoneManager()
