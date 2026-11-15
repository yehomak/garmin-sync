"""DuckDB access: schema init, upserts, read-only connections."""

from pathlib import Path

import duckdb

from garmin_sync.config import SCHEMA_PATH, db_path

TABLE_KEYS = {"health_days": "date", "health_activities": "activity_id"}


def connect(path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path or db_path()), read_only=read_only)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Idempotent: creates tables, applies additive migrations, refreshes column comments."""
    con.execute(SCHEMA_PATH.read_text())


def upsert(con: duckdb.DuckDBPyConnection, table: str, row: dict) -> None:
    """Insert or update one row. Column names come from dict keys, so they must match schema.sql."""
    pk = TABLE_KEYS[table]
    cols = ", ".join(row)
    params = ", ".join("?" for _ in row)
    updates = ", ".join(f"{k} = excluded.{k}" for k in row if k != pk)
    # A row holding only the key (every endpoint failed) has nothing to update.
    on_conflict = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    con.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({params}) ON CONFLICT ({pk}) {on_conflict}",
        list(row.values()),
    )
