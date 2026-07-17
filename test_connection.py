"""Quick Supabase connectivity check: fetch one row from `patients`."""

from services.supabase_client import (
    count_records,
    describe_connection,
    patient_filters_from_env,
    read_records,
    resolve_patient_row,
)


def _filter_description(filters: dict | None) -> str:
    if not filters:
        return "none (first row in table)"
    column, value = next(iter(filters.items()))
    if column == "id":
        return f"patients.id = {value}"
    if column == "user_id":
        return f"patients.user_id = {value} (auth user / profiles.id)"
    return f"{column} = {value}"


def main() -> None:
    info = describe_connection()
    role = info["key_role"]
    filters = patient_filters_from_env()

    print(f"Supabase URL: {info['url'] or '(missing)'}")
    print(f"API key role: {role or 'unknown'}")
    print(f"Patient lookup: {_filter_description(filters)}")

    if role == "anon":
        print(
            "Warning: anon key detected. Row Level Security often hides all rows on the Pi.\n"
            "Add SUPABASE_SERVICE_ROLE_KEY to .env (Project Settings → API → service_role)."
        )

    try:
        total = count_records("patients", filters=filters)
        print(f"Visible patient rows (count): {total}")
        row = resolve_patient_row()
    except RuntimeError as exc:
        print(f"Query error: {exc}")
        return

    if row:
        misassigned = filters and "id" in filters and row.get("user_id") == filters["id"]
        if misassigned and row.get("id") != filters["id"]:
            print(
                "Note: your PATIENT_ID/LUCY_PATIENT_ID matches patients.user_id (auth user).\n"
                "Use LUCY_USER_ID=... for that UUID; use LUCY_PATIENT_ID only for patients.id."
            )
        print("Patient row:")
        print(row)
        print(f"\nUse patients.id for FKs (e.g. transcriptions.patient_id): {row.get('id')}")
        if row.get("user_id"):
            print(f"Linked auth user (profiles.id): {row['user_id']}")
        return

    if filters and "id" in filters:
        uid = filters["id"]
        try:
            by_user = read_records("patients", filters={"user_id": uid}, limit=1)
        except RuntimeError:
            by_user = []
        if not by_user:
            print(
                "No row for patients.id. If that UUID is from Auth/Users, set LUCY_USER_ID "
                f"(or USER_ID) instead of LUCY_PATIENT_ID / PATIENT_ID."
            )
        else:
            print(
                "No row for patients.id, but one exists for patients.user_id with the same UUID.\n"
                "Move that value to LUCY_USER_ID=... in .env (it is an auth user id, not patients.id)."
            )
            print("Patient row:")
            print(by_user[0])
        return

    if role == "anon":
        print("No rows visible with the anon key — switch to the service_role key in .env.")
    else:
        print("Connection OK, but no patient row matched (table empty or filter too strict).")


if __name__ == "__main__":
    main()
