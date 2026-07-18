"""Lucy Pi main entry point — startup, call monitoring, and keep-alive loop."""

from dotenv import load_dotenv

load_dotenv()

import os
import threading
import time
from datetime import datetime, timezone

from sensors import motor
from sensors.camera import camera
from sensors.microphone import microphone
from sensors.speaker import speaker
from services import backend

POLL_INTERVAL_SECONDS = 2
PENDING_LOOKBACK_SECONDS = 60

processed_calls: set[str] = set()
active_session_id: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def handle_incoming_call(record: dict) -> None:
    global active_session_id

    session_id = record.get("id")
    room_url = record.get("room_url")

    print(
        f"Lucy Pi: incoming call detected — "
        f"session_id={session_id}, room_url={room_url}"
    )

    if not room_url:
        print("Lucy Pi: missing room_url in call_sessions row; skipping join.")
        return
    if not session_id:
        print("Lucy Pi: missing session id in call_sessions row; skipping join.")
        return

    motor.open_eyelids()
    camera.join_video_call(room_url)
    backend.update_record(
        "call_sessions",
        str(session_id),
        {
            "status": "active",
            "answered_at": _utc_now_iso(),
        },
    )
    active_session_id = str(session_id)
    print(f"Lucy Pi: call is now active (session_id={session_id}).")


def handle_call_ended(session_id: str, started_at: str | datetime | None) -> None:
    global active_session_id

    print(f"Lucy Pi: call has ended (session_id={session_id}).")

    camera.leave_video_call()
    motor.close_eyelids()

    duration_seconds: float | None = None
    started = _parse_utc(started_at)
    if started is not None:
        duration_seconds = (datetime.now(timezone.utc) - started).total_seconds()

    update_data: dict = {
        "ended_at": _utc_now_iso(),
        "ended_reason": "completed",
    }
    if duration_seconds is not None:
        update_data["duration_seconds"] = int(duration_seconds)

    backend.update_record("call_sessions", str(session_id), update_data)
    if active_session_id == str(session_id):
        active_session_id = None

    print(
        f"Lucy Pi: eyelids closed and call session updated "
        f"(session_id={session_id})."
    )


def _poll_pending_calls() -> None:
    rows = backend.read_recent_pending_call_sessions(PENDING_LOOKBACK_SECONDS)
    for row in rows:
        session_id = row.get("id")
        if not session_id:
            continue
        session_key = str(session_id)
        if session_key in processed_calls:
            continue
        processed_calls.add(session_key)
        try:
            handle_incoming_call(row)
        except Exception as exc:
            print(f"Lucy Pi: error handling incoming call — {exc}")


def _poll_active_call_ended() -> None:
    global active_session_id

    if not camera.is_active() or not active_session_id:
        return

    try:
        row = backend.read_call_session(active_session_id)
    except Exception as exc:
        print(f"Lucy Pi: error checking active call session — {exc}")
        return

    if row is None:
        return

    if row.get("status") == "ended":
        started_at = row.get("started_at") or row.get("answered_at")
        try:
            handle_call_ended(active_session_id, started_at)
        except Exception as exc:
            print(f"Lucy Pi: error handling call ended — {exc}")


def monitor_calls() -> None:
    """Poll call_sessions for pending and ended calls every two seconds."""
    while True:
        try:
            _poll_pending_calls()
            _poll_active_call_ended()
        except Exception as exc:
            print(f"Lucy Pi: call monitor error — {exc}")
        time.sleep(POLL_INTERVAL_SECONDS)


def handle_wake_word(transcribed_text: str) -> None:
    print(f"Lucy Pi: new transcription received — {transcribed_text}")
    speaker.speak("Got it, I have saved your note.")
    try:
        backend.insert_record(
            "transcriptions",
            {
                "patient_id": os.getenv("PATIENT_ID"),
                "content": transcribed_text,
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
            },
        )
        print("Lucy Pi: transcription saved to Supabase successfully.")
    except Exception as exc:
        print(f"Lucy Pi: error saving transcription — {exc}")


def handle_wake_word_detected() -> None:
    speaker.speak("Lucy here, go ahead.")
    time.sleep(0.8)


def startup() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Lucy Pi: starting up at {now}.")

    backend.authenticate()

    thread = threading.Thread(
        target=monitor_calls,
        name="lucy-call-monitor",
        daemon=True,
    )
    thread.start()

    microphone.wake_word_detected_callback = handle_wake_word_detected
    microphone.start_wake_word_detection(handle_wake_word)
    print("Lucy Pi: wake word detection is active and listening.")

    print("Lucy Pi: ready and listening for calls.")


if __name__ == "__main__":
    startup()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nLucy Pi: shutting down.")
