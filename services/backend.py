"""Backend data access (Supabase) for the Lucy Pi project."""

from services.supabase_client import (
    get_client,
    insert_record,
    read_records,
    subscribe_to_table,
    update_record,
)

__all__ = [
    "get_client",
    "insert_record",
    "read_records",
    "update_record",
    "subscribe_to_table",
]
