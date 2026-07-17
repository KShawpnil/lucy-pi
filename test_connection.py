"""Quick Supabase connectivity check: fetch one row from `patients`."""

import os

from services.supabase_client import count_records, describe_connection, read_records


def main() -> None:
    info = describe_connection()
    role = info["key_role"]

    print(f"Supabase URL: {info['url'] or '(missing)'}")
    print(f"API key role: {role or 'unknown'}")
    if role == "anon":
        print(
            "Warning: anon key detected. Row Level Security often hides all rows on the Pi.\n"
            "Add SUPABASE_SERVICE_ROLE_KEY to .env (Project Settings → API → service_role),\n"
            "or set SUPABASE_KEY to the service_role secret instead of the anon/public key."
        )

    patient_id = (os.getenv("LUCY_PATIENT_ID") or os.getenv("PATIENT_ID") or "").strip()
    filters = {"id": patient_id} if patient_id else None
    if filters:
        print(f"Filtering patients by id={patient_id}")

    try:
        total = count_records("patients", filters=filters)
        print(f"Visible patient rows (count): {total}")

        rows = read_records("patients", filters=filters, limit=1)
    except RuntimeError as exc:
        print(f"Query error: {exc}")
        return

    if rows:
        print("First patient row:")
        print(rows[0])
        return

    if role == "anon":
        print("No rows visible with the anon key — switch to the service_role key in .env.")
    elif total == 0:
        print("Connection OK, but `patients` has no rows (or none match your filter).")
    else:
        print("No row returned; check table name, filters, and API key permissions.")


if __name__ == "__main__":
    main()
