"""Smoke test: Supabase connection and patients table read."""

from services import backend


def main() -> None:
    rows = backend.read_records("patients", limit=1)
    if not rows:
        print("No rows in patients table.")
        return
    print(rows[0])


if __name__ == "__main__":
    main()
