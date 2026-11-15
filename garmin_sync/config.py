"""Paths and settings. Everything that touches the filesystem resolves through here."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
TOKENSTORE = ROOT / ".garth"
RAW_DIR = ROOT / "data" / "raw"
PHYSIOLOGY_PATH = ROOT / "data" / "physiology.json"


def load_credentials() -> None:
    """Load .env (GARMIN_EMAIL / GARMIN_PASSWORD). Only the auth modules call this, so the
    MCP server process never holds Garmin credentials."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


def db_path() -> Path:
    """GARMIN_DB overrides the default location (used by tests, the demo DB and other consumers)."""
    return Path(os.environ.get("GARMIN_DB") or ROOT / "garmin.duckdb")
