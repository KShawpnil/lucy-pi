"""Backend API for Lucy Pi — Supabase auth, CRUD, and call-session realtime."""

from __future__ import annotations

from typing import Any, Callable

from services import supabase_client as db


def authenticate() -> None:
    """Sign the device into Supabase (creates session on first call)."""
    db.get_client()


def insert_record(table: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    return db.insert_record(table, data)


def read_records(
    table: str,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return db.read_records(table, filters=filters)


def update_record(
    table: str,
    record_id: str,
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    return db.update_record(table, record_id, data)


def subscribe_call_sessions(
    on_pending_insert: Callable[[dict[str, Any]], None],
    on_ended_update: Callable[[dict[str, Any]], None],
    *,
    channel_name: str = "lucy-call-sessions",
) -> Any:
    """
    Subscribe to call_sessions INSERT (status pending) and UPDATE (status ended).

    Callbacks receive the Realtime postgres_changes payload.
    """
    client = db.get_client()
    channel = client.channel(channel_name)

    channel.on_postgres_changes(
        "INSERT",
        schema="public",
        table="call_sessions",
        filter="status=eq.pending",
        callback=on_pending_insert,
    )
    channel.on_postgres_changes(
        "UPDATE",
        schema="public",
        table="call_sessions",
        filter="status=eq.ended",
        callback=on_ended_update,
    )
    channel.subscribe()
    return channel
