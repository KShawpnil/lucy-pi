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
from daily import CallClient, Daily, EventHandler
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

# Pygame monitor output (HDMI)
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720

# Daily virtual microphone (fed from reSpeaker via sounddevice)
MIC_DEVICE_NAME = "lucy-respeaker"
MIC_SAMPLE_RATE = 16000  # reSpeaker XVF3800 native rate
MIC_SAMPLE_RATE_FALLBACKS = (16000, 44100, 48000)
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


def _configure_pi_hdmi_display_env() -> None:
    """
    Route pygame/SDL to the locally connected HDMI monitor, not an SSH session.

    Run before pygame.init() in the display thread.
    """
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
    # Prefer the Pi desktop/X11 session on HDMI; fall back to KMS if needed.
    if not os.environ.get("SDL_VIDEODRIVER"):
        os.environ["SDL_VIDEODRIVER"] = "x11"
    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")


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


def _is_valid_remote_participant_id(participant_id: str | None, info: Any = None) -> bool:
    """Daily session IDs only — never 'local', '*', or empty strings."""
    if not participant_id:
        return False
    pid = str(participant_id).strip()
    if not pid or pid.lower() in ("local", "*"):
        return False
    if isinstance(info, dict) and info.get("local"):
        return False
    return True


def _video_frame_to_surface(video_frame: Any) -> Any:
    """Convert a Daily VideoFrame buffer into a pygame Surface."""
    import pygame

    width = int(video_frame.width)
    height = int(video_frame.height)
    raw = video_frame.buffer
    if not isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw)

    color_format = getattr(video_frame, "color_format", "RGB")
    if color_format == "RGBA":
        surface = pygame.image.frombuffer(raw, (width, height), "RGBA")
        return surface.convert()
    if color_format == "RGB":
        return pygame.image.frombuffer(raw, (width, height), "RGB")

    array = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
    return pygame.surfarray.make_surface(np.transpose(array, (1, 0, 2)))


class _CallEventHandler(EventHandler):
    """Handle remote participants joining — attach audio and incoming video."""

    def __init__(self, manager: "CameraManager") -> None:
        super().__init__()
        self._manager = manager

    def on_participant_joined(self, participant: Any) -> None:
        if _is_local_participant(participant):
            session_id = _participant_id(participant)
            if session_id and session_id.lower() not in ("local", "*"):
                self._manager._local_participant_id = session_id
            print("Lucy Pi: local participant joined Daily room.")
            return

        participant_id = _participant_id(participant)
        if not _is_valid_remote_participant_id(participant_id, participant):
            print(f"Lucy Pi: ignored participant join (invalid id={participant_id!r}).")
            return

        print(f"Lucy Pi: remote participant joined — session_id={participant_id}")
        self._manager._on_remote_participant_joined(str(participant_id))

    def on_participant_updated(self, participant: Any) -> None:
        if _is_local_participant(participant):
            return
        participant_id = _participant_id(participant)
        if _is_valid_remote_participant_id(participant_id, participant):
            self._manager._on_remote_participant_joined(str(participant_id))


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
        self._mic_sample_rate: int = MIC_SAMPLE_RATE
        self._local_participant_id: str | None = None
        self._audio_renderer_participants: set[str] = set()
        self._video_renderer_participants: set[str] = set()
        self._on_remote_audio: Any = None
        self._on_remote_video: Any = None
        self._display_thread: threading.Thread | None = None
        self._display_active = False
        self._display_ready = threading.Event()
        self._frame_lock = threading.Lock()
        self._pending_frame: Any = None
        self._pygame_screen: Any = None

    def _resolve_mic_sample_rate(self) -> int:
        """Pick the first supported input sample rate (16 kHz preferred for reSpeaker)."""
        last_error: Exception | None = None
        for rate in MIC_SAMPLE_RATE_FALLBACKS:
            try:
                sd.check_input_settings(
                    device=self._respeaker_device,
                    samplerate=rate,
                    channels=MIC_CHANNELS,
                )
                if rate != MIC_SAMPLE_RATE:
                    print(
                        f"Lucy Pi: mic using fallback sample rate {rate} Hz "
                        f"({MIC_SAMPLE_RATE} Hz unavailable)."
                    )
                return rate
            except Exception as exc:
                last_error = exc
                print(f"Lucy Pi: mic sample rate {rate} Hz failed — {exc}")
        raise RuntimeError(
            "Could not configure reSpeaker microphone at 16000, 44100, or 48000 Hz"
        ) from last_error

    def join_video_call(self, room_url: str) -> None:
        if self.is_call_active:
            raise RuntimeError("A video call is already active. Leave it before joining another.")

        _ensure_daily_init()

        self._respeaker_device = _find_respeaker_input_device()
        self._output_device = _default_output_device()
        self._mic_sample_rate = self._resolve_mic_sample_rate()

        self._start_picamera()
        self._virtual_camera = Daily.create_camera_device(
            CAMERA_DEVICE_NAME,
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            color_format=VIDEO_COLOR_FORMAT,
        )
        self._virtual_microphone = Daily.create_microphone_device(
            MIC_DEVICE_NAME,
            sample_rate=self._mic_sample_rate,
            channels=MIC_CHANNELS,
            non_blocking=True,
        )

        self._stop_event.clear()
        self._display_ready.clear()
        self._start_remote_audio_playback()
        self._ensure_remote_video_callback()
        self._start_incoming_video_display()

        client = CallClient(event_handler=_CallEventHandler(self))
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

        self._register_existing_remote_participants(client)

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
            f"  Audio in: {mic_label} @ {self._mic_sample_rate} Hz\n"
            f"  Audio out: {out_label}\n"
            f"  Display: HDMI monitor {DISPLAY_WIDTH}x{DISPLAY_HEIGHT} (DISPLAY={os.environ.get('DISPLAY', ':0')})"
        )

    def leave_video_call(self) -> None:
        if not self.is_call_active and self.current_call_client is None:
            print("Lucy Pi: no active video call to leave.")
            return

        self._stop_event.set()
        self._display_active = False

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
        self._stop_incoming_video_display()

        self.is_call_active = False
        self.current_call_client = None
        self._virtual_camera = None
        self._virtual_microphone = None
        self._local_participant_id = None
        self._audio_renderer_participants.clear()
        self._video_renderer_participants.clear()
        self._on_remote_audio = None
        self._on_remote_video = None
        with self._frame_lock:
            self._pending_frame = None

        print("Lucy Pi: video call ended cleanly.")

    def is_active(self) -> bool:
        return self.is_call_active

    def _on_remote_participant_joined(self, participant_id: str) -> None:
        """Start HDMI display (if needed) and subscribe to remote camera video."""
        self._attach_remote_audio_renderer(participant_id)
        self.display_incoming_video(participant_id)

    def display_incoming_video(self, participant_id: str) -> None:
        """Register a Daily video renderer for one remote participant session ID."""
        if not _is_valid_remote_participant_id(participant_id):
            return
        if (
            self.current_call_client is None
            or participant_id in self._video_renderer_participants
            or participant_id == self._local_participant_id
        ):
            return

        self._start_incoming_video_display()
        if not self._display_ready.wait(timeout=10.0):
            print("Lucy Pi: HDMI display not ready — video may not appear.")

        self._ensure_remote_video_callback()

        try:
            self.current_call_client.set_video_renderer(
                participant_id,
                self._on_remote_video,
                video_source="camera",
                color_format="RGBA",
            )
            self._video_renderer_participants.add(participant_id)
            print(
                f"Lucy Pi: receiving video from participant {participant_id} "
                f"on {DISPLAY_WIDTH}x{DISPLAY_HEIGHT} HDMI display."
            )
        except Exception as exc:
            print(
                f"Lucy Pi: could not attach video renderer for "
                f"participant {participant_id} — {exc}"
            )

    def _ensure_remote_video_callback(self) -> None:
        if self._on_remote_video is not None:
            return

        def on_remote_video(
            remote_participant_id: str, video_frame: Any, video_source: str
        ) -> None:
            if self._stop_event.is_set() or not self._display_active:
                return
            try:
                surface = _video_frame_to_surface(video_frame)
                with self._frame_lock:
                    self._pending_frame = surface
            except Exception as exc:
                print(f"Lucy Pi: incoming video frame error — {exc}")

        self._on_remote_video = on_remote_video

    def _start_incoming_video_display(self) -> None:
        if self._display_thread and self._display_thread.is_alive():
            return

        self._display_active = True
        self._display_thread = threading.Thread(
            target=self._pygame_display_loop,
            name="lucy-incoming-video-display",
            daemon=True,
        )
        self._display_thread.start()

    def _pygame_display_loop(self) -> None:
        import pygame

        try:
            _configure_pi_hdmi_display_env()
            pygame.init()
            pygame.display.init()

            try:
                self._pygame_screen = pygame.display.set_mode(
                    (DISPLAY_WIDTH, DISPLAY_HEIGHT),
                    pygame.FULLSCREEN,
                )
            except pygame.error:
                # Some Pi setups reject FULLSCREEN — still use 1280x720 windowed on HDMI.
                self._pygame_screen = pygame.display.set_mode(
                    (DISPLAY_WIDTH, DISPLAY_HEIGHT)
                )

            pygame.display.set_caption("Lucy — Incoming Call")
            self._pygame_screen.fill((0, 0, 0))
            pygame.display.flip()
            self._display_ready.set()
            print(
                f"Lucy Pi: pygame display ready on HDMI "
                f"({DISPLAY_WIDTH}x{DISPLAY_HEIGHT}, DISPLAY={os.environ.get('DISPLAY')})."
            )

            clock = pygame.time.Clock()
            while not self._stop_event.is_set() and self._display_active:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._display_active = False
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        self._display_active = False

                assert self._pygame_screen is not None
                self._pygame_screen.fill((0, 0, 0))

                with self._frame_lock:
                    frame = self._pending_frame

                if frame is not None:
                    if frame.get_size() != (DISPLAY_WIDTH, DISPLAY_HEIGHT):
                        frame = pygame.transform.smoothscale(
                            frame, (DISPLAY_WIDTH, DISPLAY_HEIGHT)
                        )
                    self._pygame_screen.blit(frame, (0, 0))

                pygame.display.flip()
                clock.tick(30)
        except Exception as exc:
            print(f"Lucy Pi: incoming video display error — {exc}")
        finally:
            try:
                pygame.display.quit()
                pygame.quit()
            except Exception:
                pass
            self._pygame_screen = None
            self._display_active = False
            self._display_ready.clear()
            print("Lucy Pi: pygame display closed.")

    def _stop_incoming_video_display(self) -> None:
        self._display_active = False
        if self._display_thread and self._display_thread.is_alive():
            self._display_thread.join(timeout=3.0)
        self._display_thread = None
        self._display_ready.clear()
        with self._frame_lock:
            self._pending_frame = None

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
        block_frames = int(self._mic_sample_rate * MIC_BLOCK_MS / 1000)
        if self._virtual_microphone is None:
            return

        try:
            with sd.RawInputStream(
                samplerate=self._mic_sample_rate,
                channels=MIC_CHANNELS,
                dtype="int16",
                blocksize=block_frames,
                device=self._respeaker_device,
            ) as stream:
                while not self._stop_event.is_set():
                    data, _overflowed = stream.read(block_frames)
                    self._virtual_microphone.write_frames(bytes(data))
        except Exception as exc:
            if not self._stop_event.is_set():
                print(f"Lucy Pi: microphone stream error — {exc}")

    def _register_existing_remote_participants(self, client: CallClient) -> None:
        """Attach audio/video for remote participants already in the room."""
        try:
            participants = client.participants()
        except Exception as exc:
            print(f"Lucy Pi: could not list participants — {exc}")
            return

        for participant_key, info in participants.items():
            if isinstance(info, dict) and info.get("local"):
                session_id = _participant_id(info)
                if session_id and session_id.lower() not in ("local", "*"):
                    self._local_participant_id = session_id
                continue

            remote_id = _participant_id(info) if isinstance(info, dict) else None
            candidate = remote_id if _is_valid_remote_participant_id(remote_id, info) else None
            if candidate is None and _is_valid_remote_participant_id(participant_key, info):
                candidate = str(participant_key)
            if candidate:
                self._on_remote_participant_joined(candidate)

    def _attach_remote_audio_renderer(self, participant_id: str) -> None:
        """Register Daily audio output for one remote participant session ID."""
        if not _is_valid_remote_participant_id(participant_id):
            return
        if (
            self.current_call_client is None
            or participant_id in self._audio_renderer_participants
            or participant_id == self._local_participant_id
            or self._on_remote_audio is None
        ):
            return

        try:
            self.current_call_client.set_audio_renderer(
                participant_id,
                self._on_remote_audio,
                audio_source="microphone",
                sample_rate=self._mic_sample_rate,
            )
            self._audio_renderer_participants.add(participant_id)
            print(f"Lucy Pi: receiving audio from participant {participant_id}.")
        except Exception as exc:
            print(
                f"Lucy Pi: could not attach audio renderer for "
                f"participant {participant_id} — {exc}"
            )

    def _start_remote_audio_playback(self) -> None:
        """Prepare speaker output; renderers are attached per remote participant ID."""

        def on_remote_audio(
            participant_id: str, audio_data: Any, audio_source: str
        ) -> None:
            if self._stop_event.is_set() or self._output_stream is None:
                return
            try:
                samples = np.frombuffer(audio_data.audio_frames, dtype=np.int16)
                if audio_data.num_channels > 1:
                    samples = samples.reshape(-1, audio_data.num_channels)
                self._output_stream.write(samples)
            except Exception as exc:
                print(f"Lucy Pi: remote audio playback error — {exc}")

        self._on_remote_audio = on_remote_audio

        self._output_stream = sd.OutputStream(
            samplerate=self._mic_sample_rate,
            channels=MIC_CHANNELS,
            dtype="int16",
            device=self._output_device,
        )
        self._output_stream.start()

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
