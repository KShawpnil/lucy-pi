"""Supabase client with device auth for the Lucy Pi project."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

_client: Client | None = None
_startup_auth_message_printed = False

T = TypeVar("T")


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _device_credentials() -> tuple[str, str]:
    email = _env("DEVICE_EMAIL")
    password = _env("DEVICE_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "DEVICE_EMAIL and DEVICE_PASSWORD must be set in the project .env file"
        )
    return email, password


def _sign_in(client: Client, *, startup: bool = False) -> None:
    global _startup_auth_message_printed
    email, password = _device_credentials()
    try:
        response = client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except Exception as exc:
        raise RuntimeError(f"Supabase sign-in failed for {email}: {exc}") from exc

    session = getattr(response, "session", None)
    user = getattr(response, "user", None)
    if session is None and user is None:
        raise RuntimeError(
            f"Supabase sign-in failed for {email}. Check credentials and Auth settings."
        )

    if startup and not _startup_auth_message_printed:
        print(f"Lucy Pi: Supabase authentication succeeded ({email}).")
        _startup_auth_message_printed = True


def _session_active(client: Client) -> bool:
    try:
        response = client.auth.get_user()
        user = getattr(response, "user", None)
        return user is not None
    except Exception:
        return False


def _ensure_authenticated(client: Client) -> None:
    if _session_active(client):
        return
    _sign_in(client, startup=False)


def _is_auth_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "jwt",
            "401",
            "unauthorized",
            "invalid claim",
            "token is expired",
            "expired",
            "not authenticated",
            "session not found",
        )
    )


def _run_with_auth_retry(operation: Callable[[], T]) -> T:
    client = get_client()
    try:
        return operation()
    except (APIError, RuntimeError) as exc:
        if not _is_auth_error(exc):
            raise
        _sign_in(client, startup=False)
        return operation()


def get_client() -> Client:
    """Return a shared Supabase client with an active device session."""
    global _client
    if _client is not None:
        _ensure_authenticated(_client)
        return _client

    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set in the project .env file"
        )

    _device_credentials()
    _client = create_client(url, key)
    _sign_in(_client, startup=True)
    return _client


def _apply_eq_filters(query: Any, filters: dict[str, Any] | None) -> Any:
    if not filters:
        return query
    for column, value in filters.items():
        query = query.eq(column, value)
    return query


def _response_data(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return data if isinstance(data, list) else []


def insert_record(table: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert a row into `table` using the authenticated session."""

    def _insert() -> list[dict[str, Any]]:
        response = get_client().table(table).insert(data).execute()
        return _response_data(response)

    return _run_with_auth_retry(_insert)


def read_records(
    table: str,
    filters: dict[str, Any] | None = None,
    *,
    gte_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read rows from `table`, with optional equality and >= filters."""

    def _read() -> list[dict[str, Any]]:
        query = get_client().table(table).select("*")
        query = _apply_eq_filters(query, filters)
        if gte_filters:
            for column, value in gte_filters.items():
                query = query.gte(column, value)
        try:
            response = query.execute()
        except APIError as exc:
            raise RuntimeError(f"Supabase query failed: {exc}") from exc
        return _response_data(response)

    return _run_with_auth_retry(_read)


def update_record(
    table: str,
    record_id: str,
    data: dict[str, Any],
    *,
    id_column: str = "id",
) -> list[dict[str, Any]]:
    """Update the row in `table` whose `id_column` matches `record_id`."""

    def _update() -> list[dict[str, Any]]:
        query = (
            get_client()
            .table(table)
            .update(data)
            .eq(id_column, record_id)
        )
        response = query.execute()
        return _response_data(response)

    return _run_with_auth_retry(_update)


def subscribe_to_realtime(
    table: str,
    callback: Callable[[dict[str, Any]], None],
    *,
    schema: str = "public",
    channel_name: str | None = None,
) -> Any:
    """Listen for new INSERT events on `table` using the authenticated session."""
    client = get_client()
    name = channel_name or f"lucy-{table}-inserts"
    channel = client.channel(name)
    channel.on_postgres_changes(
        "INSERT",
        schema=schema,
        table=table,
        callback=callback,
    )
    channel.subscribe()
    return channel


# Alias requested in earlier project docs
subscribe_to_table = subscribe_to_realtime
