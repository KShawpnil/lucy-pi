"""Device and Supabase IDs (see schema: patients.id vs patients.user_id)."""

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env", override=True)


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


# patients.id — use as patient_id on visits, transcriptions, health_readings, etc.
PATIENT_ROW_ID = _env("LUCY_PATIENT_ID") or _env("PATIENT_ID")

# auth.users.id / profiles.id — maps to patients.user_id, not patients.id
AUTH_USER_ID = _env("LUCY_USER_ID") or _env("USER_ID")
