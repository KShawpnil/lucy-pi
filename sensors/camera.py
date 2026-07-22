"""Video calling for Lucy Pi — Daily SDK + Picamera2 (Arducam CSI) + USB/HAT audio."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from daily import CallClient, Daily, EventHandler
from picamera2 import Picamera2

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CAMERA_DEVICE_NAME = "lucy-picamera"
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 30
VIDEO_COLOR_FORMAT = "RGB"
MIC_SAMPLE_RATE = 16000
MIC_CHANNELS = 1


def _participant_id(participant: Any) -> str | None:
    if isinstance(participant, dict):
        return (
            participant.get("session_id")
            or participant.get("id")
            or participant.get("user_id")
        )
    return (
        getattr(participant, "session_id", None)
        or getattr(participant, "id", None)
        or getattr(participant, "user_id", None)
    )


def _is_local_participant(participant: Any) -> bool:
    if isinstance(participant, dict):
        return bool(participant.get("local"))
    return bool(getattr(participant, "local", False))


def _stream_picamera_frames(
    picamera: Picamera2,
    virtual_camera: Any,
    stop_event: threading.Event,
) -> None:
    frame_interval = 1.0 / VIDEO_FPS
    while not stop_event.is_set():
        try:
            frame = picamera.capture_array()
            virtual_camera.write_frame(frame.tobytes())
        except Exception as exc:
            print(f"Lucy Pi: video frame error — {exc}")
            break
        time.sleep(frame_interval)


def _attach_remote_audio(
    client: CallClient | None,
    participant_id: str,
    on_remote_audio: Any,
    attached: set[str],
) -> None:
    if client is None or participant_id in attached:
        return

    try:
        client.set_audio_renderer(
            participant_id,
            on_remote_audio,
            audio_source="microphone",
            sample_rate=MIC_SAMPLE_RATE,
        )
        attached.add(participant_id)
        print(f"Lucy Pi: receiving audio from participant {participant_id}.")
    except Exception as exc:
        print(
            f"Lucy Pi: could not attach audio renderer for "
            f"participant {participant_id} — {exc}"
        )


def _register_remote_participants(
    client: CallClient,
    on_remote_audio: Any,
    attached: set[str],
) -> None:
    try:
        participants = client.participants()
    except Exception as exc:
        print(f"Lucy Pi: could not list participants — {exc}")
        return

    for participant_key, info in participants.items():
        if isinstance(info, dict) and info.get("local"):
            continue

        remote_id = _participant_id(info) if isinstance(info, dict) else None
        candidate = remote_id or (
            str(participant_key)
            if participant_key and str(participant_key).lower() not in ("local", "*")
            else None
        )
        if candidate:
            _attach_remote_audio(client, candidate, on_remote_audio, attached)


class _CallEventHandler(EventHandler):
    """Print when remote participants join and route their audio to the HAT."""

    def __init__(self) -> None:
        super().__init__()
        self.client: CallClient | None = None
        self.on_remote_audio: Any = None
        self.attached: set[str] = set()

    def on_participant_joined(self, participant: Any) -> None:
        if _is_local_participant(participant):
            return

        participant_id = _participant_id(participant)
        if not participant_id:
            return

        print(f"Lucy Pi: remote participant joined — session_id={participant_id}")
        _attach_remote_audio(
            self.client,
            str(participant_id),
            self.on_remote_audio,
            self.attached,
        )


class CameraManager:
    """Join and leave Daily video calls using Picamera2 and system audio devices."""

    def __init__(self) -> None:
        self.is_call_active = False
        self.current_call_client = None
        self.browser_process = None

    def join_video_call(self, room_url: str) -> None:
        if self.is_call_active:
            raise RuntimeError("A video call is already active. Leave it before joining another.")

        print("Lucy Pi: joining the call.")

        Daily.init()

        picamera = Picamera2()
        config = picamera.create_video_configuration(
            main={"size": (VIDEO_WIDTH, VIDEO_HEIGHT), "format": "RGB888"}
        )
        picamera.configure(config)
        picamera.start()

        virtual_camera = Daily.create_camera_device(
            CAMERA_DEVICE_NAME,
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            color_format=VIDEO_COLOR_FORMAT,
        )

        stop_event = threading.Event()
        attached_participants: set[str] = set()

        output_stream = sd.OutputStream(
            samplerate=MIC_SAMPLE_RATE,
            channels=MIC_CHANNELS,
            dtype="int16",
            device=None,
        )
        output_stream.start()

        def on_remote_audio(participant_id: str, audio_data: Any, audio_source: str) -> None:
            if stop_event.is_set():
                return
            try:
                samples = np.frombuffer(audio_data.audio_frames, dtype=np.int16)
                if audio_data.num_channels > 1:
                    samples = samples.reshape(-1, audio_data.num_channels)
                output_stream.write(samples)
            except Exception as exc:
                print(f"Lucy Pi: remote audio playback error — {exc}")

        event_handler = _CallEventHandler()
        event_handler.on_remote_audio = on_remote_audio
        event_handler.attached = attached_participants

        client = CallClient(event_handler=event_handler)
        event_handler.client = client
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
                    },
                },
                "publishing": {
                    "camera": {"isPublishing": True},
                    "microphone": {"isPublishing": True},
                },
            },
        )

        _register_remote_participants(client, on_remote_audio, attached_participants)

        video_thread = threading.Thread(
            target=_stream_picamera_frames,
            args=(picamera, virtual_camera, stop_event),
            name="lucy-video-stream",
            daemon=True,
        )
        video_thread.start()

        self._stop_event = stop_event
        self._picamera = picamera
        self._virtual_camera = virtual_camera
        self._output_stream = output_stream
        self._video_thread = video_thread

        self.is_call_active = True
        print(f"Lucy Pi: joined the call successfully — {room_url}")

    def leave_video_call(self) -> None:
        if not self.is_call_active:
            print("Lucy Pi: no active video call to leave.")
            return

        if hasattr(self, "_stop_event"):
            self._stop_event.set()

        if hasattr(self, "_video_thread") and self._video_thread is not None:
            if self._video_thread.is_alive():
                self._video_thread.join(timeout=2.0)
            self._video_thread = None

        if self.current_call_client is not None:
            try:
                self.current_call_client.leave()
            except Exception as exc:
                print(f"Lucy Pi: warning while leaving call — {exc}")

        if hasattr(self, "_picamera") and self._picamera is not None:
            try:
                self._picamera.stop()
                self._picamera.close()
            except Exception as exc:
                print(f"Lucy Pi: warning while stopping Picamera2 — {exc}")
            self._picamera = None

        if hasattr(self, "_output_stream") and self._output_stream is not None:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception as exc:
                print(f"Lucy Pi: warning while stopping audio output — {exc}")
            self._output_stream = None

        self._virtual_camera = None
        self.is_call_active = False
        self.current_call_client = None
        print("Lucy Pi: left the call cleanly.")

    def is_active(self) -> bool:
        return self.is_call_active


camera = CameraManager()
