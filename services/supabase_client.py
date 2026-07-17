"""Supabase client and helpers for the Lucy Pi project."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import Client, create_client

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

_client: Client | None = None


def get_client() -> Client:
    """Return a shared Supabase client (SUPABASE_URL + SUPABASE_KEY from .env)."""
    global _client
    if _client is not None:
        return _client

    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set in the project .env file"
        )

    _client = create_client(url, key)
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
    try:
        response = query.execute()
    except APIError as exc:
        raise RuntimeError(f"Supabase query failed: {exc}") from exc
    return _response_data(response)


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
