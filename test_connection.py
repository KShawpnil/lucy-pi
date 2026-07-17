"""Quick Supabase connectivity check: fetch one row from `patients`."""

from services.supabase_client import read_records

rows = read_records("patients", limit=1)

if rows:
    print("First patient row:")
    print(rows[0])
else:
    print("No rows found in `patients` (or table empty).")
