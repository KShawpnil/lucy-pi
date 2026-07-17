"""Backend API for Lucy Pi — Supabase auth and CRUD."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from services import supabase_client as db


def authenticate() -> None:
    """Sign the device into Supabase (creates session on first call)."""
    db.get_client()


def insert_record(table: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    return db.insert_record(table, data)


def read_records(
    table: str,
    filters: dict[str, Any] | None = None,
    *,
    gte_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return db.read_records(table, filters, gte_filters=gte_filters)


def update_record(
    table: str,
    record_id: str,
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    return db.update_record(table, record_id, data)


def read_recent_pending_call_sessions(within_seconds: int = 60) -> list[dict[str, Any]]:
    """Return pending call_sessions created within the last `within_seconds`."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
    ).isoformat()
    return read_records(
        "call_sessions",
        filters={"status": "pending"},
        gte_filters={"created_at": cutoff},
    )


def read_call_session(session_id: str) -> dict[str, Any] | None:
    rows = read_records("call_sessions", filters={"id": session_id})
    return rows[0] if rows else None
