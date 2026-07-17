"""Supabase client and helpers for the Lucy Pi project."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

_client: Client | None = None


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _jwt_role(api_key: str) -> str | None:
    try:
        payload = api_key.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        return data.get("role")
    except (IndexError, json.JSONDecodeError, ValueError):
        return None


def _resolve_credentials() -> tuple[str, str]:
    url = (
        _env("SUPABASE_URL")
        or _env("VITE_SUPABASE_URL")
        or _env("NEXT_PUBLIC_SUPABASE_URL")
    )
    # Pi/backend should use the service role key so RLS does not return zero rows.
    key = (
        _env("SUPABASE_SERVICE_ROLE_KEY")
        or _env("SUPABASE_KEY")
        or _env("SUPABASE_ANON_KEY")
        or _env("VITE_SUPABASE_ANON_KEY")
    )
    return url, key


def get_client() -> Client:
    """Return a shared Supabase client (created on first use)."""
    global _client
    if _client is not None:
        return _client

    url, key = _resolve_credentials()
    if not url or not key:
        raise RuntimeError(
            "Set SUPABASE_URL and SUPABASE_KEY (service role recommended on the Pi) "
            f"in {_PROJECT_ROOT / '.env'}"
        )

    _client = create_client(url, key)
    return _client


def describe_connection() -> dict[str, str | None]:
    """URL and JWT role (anon vs service_role) for the configured API key."""
    url, key = _resolve_credentials()
    return {
        "url": url or None,
        "key_role": _jwt_role(key) if key else None,
    }


def patient_filters_from_env() -> dict[str, Any] | None:
    """
    Build equality filters for the `patients` table from device env vars.

    - LUCY_PATIENT_ID / PATIENT_ID → patients.id (patient role row UUID)
    - LUCY_USER_ID / USER_ID → patients.user_id (auth.users.id / profiles.id)
    """
    patient_row_id = _env("LUCY_PATIENT_ID") or _env("PATIENT_ID")
    if patient_row_id:
        return {"id": patient_row_id}

    auth_user_id = _env("LUCY_USER_ID") or _env("USER_ID")
    if auth_user_id:
        return {"user_id": auth_user_id}

    return None


def resolve_patient_row() -> dict[str, Any] | None:
    """
    Load the patient row for this device.

    Uses patient_filters_from_env() when set; otherwise returns the first patient row.
    """
    filters = patient_filters_from_env()
    rows = read_records("patients", filters=filters, limit=1)
    if rows:
        return rows[0]

    # Common misconfiguration: auth user UUID stored in PATIENT_ID.
    misassigned = _env("LUCY_PATIENT_ID") or _env("PATIENT_ID")
    if misassigned and filters and "id" in filters:
        rows = read_records("patients", filters={"user_id": misassigned}, limit=1)
        if rows:
            return rows[0]

    return None


def _apply_eq_filters(query: Any, filters: dict[str, Any] | None) -> Any:
    if not filters:
        return query
    for column, value in filters.items():
        query = query.eq(column, value)
    return query


def _response_data(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return data if isinstance(data, list) else []


def _run_select(query: Any) -> Any:
    try:
        return query.execute()
    except APIError as exc:
        raise RuntimeError(f"Supabase query failed: {exc}") from exc


def insert_record(
    table: str,
    record: dict[str, Any] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Insert one or more rows into `table`. Returns inserted row(s) when available."""
    response = get_client().table(table).insert(record).execute()
    return _response_data(response)


def read_records(
    table: str,
    *,
    columns: str = "*",
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
    order_by: str | None = None,
    descending: bool = False,
) -> list[dict[str, Any]]:
    """Read rows from `table`, optionally filtered with column equality (`eq`)."""
    query = get_client().table(table).select(columns)
    query = _apply_eq_filters(query, filters)
    if order_by is not None:
        query = query.order(order_by, desc=descending)
    if limit is not None:
        query = query.limit(limit)
    response = _run_select(query)
    return _response_data(response)


def count_records(
    table: str,
    *,
    filters: dict[str, Any] | None = None,
) -> int:
    """Return row count for `table` (respects RLS for the configured API key)."""
    query = get_client().table(table).select("*", count="exact")
    query = _apply_eq_filters(query, filters)
    response = _run_select(query.limit(0))
    count = getattr(response, "count", None)
    return int(count) if count is not None else 0


def update_record(
    table: str,
    updates: dict[str, Any],
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    """Update rows in `table` matching `filters`. Returns updated row(s) when available."""
    if not filters:
        raise ValueError("filters are required for update")

    query = get_client().table(table).update(updates)
    query = _apply_eq_filters(query, filters)
    response = query.execute()
    return _response_data(response)


def subscribe_to_table(
    table: str,
    callback: Callable[[dict[str, Any]], None],
    *,
    event: str = "*",
    schema: str = "public",
    channel_name: str | None = None,
    row_filter: str | None = None,
) -> Any:
    """
    Subscribe to Realtime Postgres changes on `table`.

    `event` is one of INSERT, UPDATE, DELETE, or *.
    `row_filter` uses Supabase filter syntax, e.g. ``id=eq.42``.
    Returns the Realtime channel (keep a reference while subscribed).

    Enable Realtime for the table in the Supabase dashboard before use.
    """
    client = get_client()
    name = channel_name or f"lucy-{table}-changes"
    channel = client.channel(name)

    kwargs: dict[str, Any] = {
        "schema": schema,
        "table": table,
        "callback": callback,
    }
    if row_filter is not None:
        kwargs["filter"] = row_filter

    channel.on_postgres_changes(event, **kwargs)
    channel.subscribe()
    return channel
