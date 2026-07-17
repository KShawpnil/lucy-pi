"""Smoke test: Supabase connection and patients table read."""

from services import supabase_client


def main() -> None:
    rows = supabase_client.read_records("patients", limit=1)
    if not rows:
        print("No rows in patients table.")
        return
    print(rows[0])


if __name__ == "__main__":
    main()
