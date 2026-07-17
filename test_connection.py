"""Verify device auth and read sample rows from key Supabase tables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from postgrest.exceptions import APIError

from services.supabase_client import get_client, read_records

_PROJECT_ROOT = Path(__file__).resolve().parent

TABLES = (
    "call_sessions",
    "transcriptions",
    "visits",
    "notifications",
)


def _load_config() -> dict[str, str]:
    load_dotenv(_PROJECT_ROOT / ".env")
    return {
        "url": (os.getenv("SUPABASE_URL") or "").strip(),
        "key": (os.getenv("SUPABASE_KEY") or "").strip(),
        "email": (os.getenv("DEVICE_EMAIL") or "").strip(),
        "password": (os.getenv("DEVICE_PASSWORD") or "").strip(),
    }


def _missing_vars(config: dict[str, str]) -> list[str]:
    missing = []
    if not config["url"]:
        missing.append("SUPABASE_URL")
    if not config["key"]:
        missing.append("SUPABASE_KEY")
    if not config["email"]:
        missing.append("DEVICE_EMAIL")
    if not config["password"]:
        missing.append("DEVICE_PASSWORD")
    return missing


def _probe_table(table: str) -> None:
    print(f"\n--- {table} ---")
    try:
        rows = read_records(table)
        row = rows[0] if rows else None
    except RuntimeError as exc:
        print(f"Result: error — {exc}")
        return
    except APIError as exc:
        print(f"Result: error — {exc}")
        return
    except Exception as exc:
        print(f"Result: error — {exc}")
        return

    if row is not None:
        print("Result: returned data")
        print(row)
    else:
        print("Result: returned empty (no rows visible for this account)")


def main() -> None:
    config = _load_config()
    missing = _missing_vars(config)

    print(f"Supabase URL: {config['url'] or '(not set)'}")
    print(f"DEVICE_EMAIL: {config['email'] or '(not set)'}")
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        print("\nAuthentication: failed")
        print("\nSummary: Device is not authenticated. Fix .env and try again.")
        return

    try:
        get_client()
    except Exception as exc:
        print(f"\nAuthentication: failed")
        print(f"Reason: {exc}")
        print("\nSummary: Device is not authenticated. Check DEVICE_EMAIL and DEVICE_PASSWORD.")
        return

    print("\nAuthentication: succeeded")

    for table in TABLES:
        try:
            _probe_table(table)
        except Exception as exc:
            print(f"\n--- {table} ---")
            print(f"Result: error — {exc}")

    print(
        f"\nSummary: Device is authenticated and connected to the database at "
        f"{config['url']}."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        print("\nSummary: Device is not authenticated or connection could not be verified.")
