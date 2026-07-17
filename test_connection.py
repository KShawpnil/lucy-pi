"""Probe Supabase connection and read one row from each expected table."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from postgrest.exceptions import APIError

from services.supabase_client import get_client, read_records

_PROJECT_ROOT = Path(__file__).resolve().parent
TABLES = (
    "users",
    "patients",
    "profiles",
    "caregivers",
    "family_members",
    "visits",
    "notes",
    "alerts",
    "messages",
    "calls",
)


def _load_env() -> tuple[str, str]:
    load_dotenv(_PROJECT_ROOT / ".env")
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_KEY") or "").strip()
    return url, key


def _classify_error(message: str) -> str:
    lower = message.lower()
    if (
        "pgrst205" in lower
        or "does not exist" in lower
        or "could not find the table" in lower
        or "relation" in lower and "does not exist" in lower
    ):
        return "not_found"
    return "error"


def _probe_table(table: str) -> tuple[str, str | dict | None]:
    """
    Returns (status, detail).
    status: data | empty | not_found | error
    """
    try:
        rows = read_records(table, limit=1)
    except RuntimeError as exc:
        kind = _classify_error(str(exc))
        return kind, str(exc)
    except APIError as exc:
        kind = _classify_error(str(exc))
        return kind, str(exc)
    except Exception as exc:
        return "error", str(exc)

    if rows:
        return "data", rows[0]
    return "empty", None


def _print_table_result(table: str, status: str, detail: str | dict | None) -> None:
    print(f"\n--- {table} ---")
    if status == "data":
        print("Result: returned data")
        print(detail)
    elif status == "empty":
        print("Result: returned empty")
    elif status == "not_found":
        print("Result: table not found (skipped)")
        if detail:
            print(f"Detail: {detail}")
    else:
        print("Result: error")
        if detail:
            print(f"Detail: {detail}")


def main() -> None:
    url, key = _load_env()
    print(f"Supabase URL: {url if url else '(not set)'}")

    if not url or not key:
        print("\nSummary: Connection failed")
        return

    try:
        get_client()
    except Exception as exc:
        print(f"\nCould not create Supabase client: {exc}")
        print("\nSummary: Connection failed")
        return

    has_data = False
    had_query_success = False

    for table in TABLES:
        try:
            status, detail = _probe_table(table)
        except Exception as exc:
            status, detail = "error", str(exc)

        _print_table_result(table, status, detail)

        if status == "data":
            has_data = True
            had_query_success = True
        elif status == "empty":
            had_query_success = True
        elif status == "not_found":
            had_query_success = True
        # status == "error" does not count as successful query

    print()
    if has_data:
        print("Summary: Connection successful with data found")
    elif had_query_success:
        print("Summary: Connection successful but all tables empty")
    else:
        print("Summary: Connection failed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        print("\nSummary: Connection failed")
