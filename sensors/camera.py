"""Video calling for Lucy Pi — Daily SDK + Picamera2 (Arducam CSI) + USB/HAT audio."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from daily import CallClient, Daily
from picamera2 import Picamera2

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

DAILY_API_KEY = (os.getenv("DAILY_API_KEY") or "").strip()

# Picamera2 / Daily virtual camera
CAMERA_DEVICE_NAME = "lucy-picamera"
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 30
VIDEO_COLOR_FORMAT = "RGB"

# Daily virtual microphone (fed from reSpeaker via sounddevice)
MIC_DEVICE_NAME = "lucy-respeaker"
MIC_SAMPLE_RATE = 48000
MIC_CHANNELS = 1
MIC_BLOCK_MS = 20

# reSpeaker XVF3800 — matched against PortAudio device names on the Pi
RESPEAKER_NAME_HINTS = ("xvf3800", "respeaker", "seeed")

_daily_initialized = False


def _ensure_daily_init() -> None:
    global _daily_initialized
    if not _daily_initialized:
        Daily.init()
        _daily_initialized = True


def _find_respeaker_input_device() -> int | None:
    """Return sounddevice input index for the reSpeaker USB mic, if found."""
    for index, device in enumerate(sd.query_devices()):
        name = str(device.get("name", "")).lower()
        if device.get("max_input_channels", 0) > 0 and any(
            hint in name for hint in RESPEAKER_NAME_HINTS
        ):
            return index
    return None


def _default_output_device() -> int | None:
    """Return the system default output device (InnoMaker HAT when set as default)."""
    try:
        devices = sd.default.device
        output = devices[1] if isinstance(devices, (list, tuple)) else devices
        return int(output) if int(output) >= 0 else None
    except (TypeError, ValueError, IndexError):
        return None


class CameraManager:
    """Manage Daily video calls with Picamera2 video and USB/HAT audio."""

    def __init__(self) -> None:
        self.is_call_active = False
        self.current_call_client: CallClient | None = None
        self.daily_api_key = DAILY_API_KEY

        self._picamera: Picamera2 | None = None
        self._virtual_camera: Any = None
        self._virtual_microphone: Any = None
        self._stop_event = threading.Event()
        self._video_thread: threading.Thread | None = None
        self._mic_thread: threading.Thread | None = None
        self._output_stream: sd.OutputStream | None = None
        self._respeaker_device: int | None = None
        self._output_device: int | None = None

    def join_video_call(self, room_url: str) -> None:
        if self.is_call_active:
            raise RuntimeError("A video call is already active. Leave it before joining another.")

        _ensure_daily_init()

        self._respeaker_device = _find_respeaker_input_device()
        self._output_device = _default_output_device()

        self._start_picamera()
        self._virtual_camera = Daily.create_camera_device(
            CAMERA_DEVICE_NAME,
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            color_format=VIDEO_COLOR_FORMAT,
        )
        self._virtual_microphone = Daily.create_microphone_device(
            MIC_DEVICE_NAME,
            sample_rate=MIC_SAMPLE_RATE,
            channels=MIC_CHANNELS,
            non_blocking=True,
        )

        client = CallClient()
        self.current_call_client = client

        client.join(
            room_url,
            client_settings={
                "inputs": {
                    "camera": {
                        "isEnabled": True,
                        "settings": {"deviceId": CAMERA_DEVICE_NAME},
                    },
                    "microphone": {
                        "isEnabled": True,
                        "settings": {"deviceId": MIC_DEVICE_NAME},
                    },
                },
                "publishing": {
                    "camera": {"isPublishing": True},
                    "microphone": {"isPublishing": True},
                },
            },
        )

        self._start_remote_audio_playback(client)
        self._stop_event.clear()
        self._video_thread = threading.Thread(
            target=self._stream_picamera_frames,
            name="lucy-video-stream",
            daemon=True,
        )
        self._mic_thread = threading.Thread(
            target=self._stream_respeaker_audio,
            name="lucy-mic-stream",
            daemon=True,
        )
        self._video_thread.start()
        self._mic_thread.start()

        self.is_call_active = True
        mic_label = (
            sd.query_devices(self._respeaker_device)["name"]
            if self._respeaker_device is not None
            else "default input (reSpeaker not detected by name)"
        )
        out_label = (
            sd.query_devices(self._output_device)["name"]
            if self._output_device is not None
            else "system default output"
        )
        print(
            f"Lucy Pi: joined video call at {room_url}\n"
            f"  Video: Picamera2 → {CAMERA_DEVICE_NAME} ({VIDEO_WIDTH}x{VIDEO_HEIGHT})\n"
            f"  Audio in: {mic_label}\n"
            f"  Audio out: {out_label}"
        )

    def leave_video_call(self) -> None:
        if not self.is_call_active and self.current_call_client is None:
            print("Lucy Pi: no active video call to leave.")
            return

        self._stop_event.set()

        if self._video_thread and self._video_thread.is_alive():
            self._video_thread.join(timeout=2.0)
        if self._mic_thread and self._mic_thread.is_alive():
            self._mic_thread.join(timeout=2.0)

        self._video_thread = None
        self._mic_thread = None

        if self.current_call_client is not None:
            try:
                self.current_call_client.leave()
            except Exception as exc:
                print(f"Lucy Pi: warning while leaving call — {exc}")

        self._stop_picamera()
        self._stop_remote_audio_playback()

        self.is_call_active = False
        self.current_call_client = None
        self._virtual_camera = None
        self._virtual_microphone = None

        print("Lucy Pi: video call ended cleanly.")

    def is_active(self) -> bool:
        return self.is_call_active

    def _start_picamera(self) -> None:
        picam = Picamera2()
        config = picam.create_video_configuration(
            main={"size": (VIDEO_WIDTH, VIDEO_HEIGHT), "format": "RGB888"}
        )
        picam.configure(config)
        picam.start()
        self._picamera = picam

    def _stop_picamera(self) -> None:
        if self._picamera is None:
            return
        try:
            self._picamera.stop()
            self._picamera.close()
        except Exception as exc:
            print(f"Lucy Pi: warning while stopping Picamera2 — {exc}")
        finally:
            self._picamera = None

    def _stream_picamera_frames(self) -> None:
        frame_interval = 1.0 / VIDEO_FPS
        while not self._stop_event.is_set():
            if self._picamera is None or self._virtual_camera is None:
                break
            try:
                frame = self._picamera.capture_array()
                self._virtual_camera.write_frame(frame.tobytes())
            except Exception as exc:
                print(f"Lucy Pi: video frame error — {exc}")
                break
            time.sleep(frame_interval)

    def _stream_respeaker_audio(self) -> None:
        block_frames = int(MIC_SAMPLE_RATE * MIC_BLOCK_MS / 1000)
        if self._virtual_microphone is None:
            return

        try:
            with sd.RawInputStream(
                samplerate=MIC_SAMPLE_RATE,
                channels=MIC_CHANNELS,
                dtype="int16",
                blocksize=block_frames,
                device=self._respeaker_device,
            ) as stream:
                while not self._stop_event.is_set():
                    data, _overflowed = stream.read(block_frames)
                    self._virtual_microphone.write_frames(data)
        except Exception as exc:
            if not self._stop_event.is_set():
                print(f"Lucy Pi: microphone stream error — {exc}")

    def _start_remote_audio_playback(self, client: CallClient) -> None:
        """Play remote call audio on the default output (InnoMaker HAT)."""

        def on_remote_audio(participant_id: str, audio_data: Any, audio_source: str) -> None:
            if self._stop_event.is_set() or self._output_stream is None:
                return
            try:
                samples = np.frombuffer(audio_data.audio_frames, dtype=np.int16)
                if audio_data.num_channels > 1:
                    samples = samples.reshape(-1, audio_data.num_channels)
                self._output_stream.write(samples)
            except Exception as exc:
                print(f"Lucy Pi: remote audio playback error — {exc}")

        self._output_stream = sd.OutputStream(
            samplerate=MIC_SAMPLE_RATE,
            channels=MIC_CHANNELS,
            dtype="int16",
            device=self._output_device,
        )
        self._output_stream.start()

        client.set_audio_renderer(
            "*",
            on_remote_audio,
            audio_source="microphone",
            sample_rate=MIC_SAMPLE_RATE,
        )


    def _stop_remote_audio_playback(self) -> None:
        if self._output_stream is None:
            return
        try:
            self._output_stream.stop()
            self._output_stream.close()
        except Exception as exc:
            print(f"Lucy Pi: warning while stopping audio output — {exc}")
        finally:
            self._output_stream = None


camera = CameraManager()
