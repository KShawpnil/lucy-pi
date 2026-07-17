"""Lucy Pi main entry point — startup, call monitoring, and keep-alive loop."""

from dotenv import load_dotenv

load_dotenv()

import os
import threading
import time
from datetime import datetime, timezone

from sensors import motor
from sensors.camera import camera
from services import backend


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


def _record_from_payload(payload: dict) -> dict:
    """Extract the new row from a Supabase Realtime postgres_changes payload."""
    if "new" in payload and isinstance(payload["new"], dict):
        return payload["new"]
    if "record" in payload and isinstance(payload["record"], dict):
        return payload["record"]
    return payload


def handle_incoming_call(payload: dict) -> None:
    record = _record_from_payload(payload)
    session_id = record.get("id")
    room_url = record.get("room_url")

    print(
        f"Lucy Pi: incoming call detected — "
        f"session_id={session_id}, room_url={room_url}"
    )

    if not room_url:
        print("Lucy Pi: missing room_url in call_sessions payload; skipping join.")
        return
    if not session_id:
        print("Lucy Pi: missing session id in call_sessions payload; skipping join.")
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
    print(f"Lucy Pi: call is now active (session_id={session_id}).")


def handle_call_ended(session_id: str, started_at: str | datetime | None) -> None:
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
    print(
        f"Lucy Pi: eyelids closed and call session updated "
        f"(session_id={session_id})."
    )


def _on_pending_insert(payload: dict) -> None:
    try:
        handle_incoming_call(payload)
    except Exception as exc:
        print(f"Lucy Pi: error handling incoming call — {exc}")


def _on_ended_update(payload: dict) -> None:
    try:
        record = _record_from_payload(payload)
        session_id = record.get("id")
        if not session_id:
            print("Lucy Pi: ended update missing session id; skipping.")
            return
        started_at = record.get("started_at") or record.get("answered_at")
        handle_call_ended(str(session_id), started_at)
    except Exception as exc:
        print(f"Lucy Pi: error handling call ended — {exc}")


def monitor_calls() -> None:
    """Listen for pending and ended call_sessions via Supabase Realtime."""
    while True:
        try:
            backend.subscribe_call_sessions(
                on_pending_insert=_on_pending_insert,
                on_ended_update=_on_ended_update,
            )
            while True:
                time.sleep(1)
        except Exception as exc:
            print(f"Lucy Pi: realtime subscription error — {exc}. Reconnecting in 5s…")
            time.sleep(5)


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

    print("Lucy Pi: ready and listening for calls.")


if __name__ == "__main__":
    startup()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nLucy Pi: shutting down.")
