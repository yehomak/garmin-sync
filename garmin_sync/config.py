"""Paths and settings. Everything that touches the filesystem resolves through here."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
TOKENSTORE = ROOT / ".garth"
RAW_DIR = ROOT / "data" / "raw"
PHYSIOLOGY_PATH = ROOT / "data" / "physiology.json"


def db_path() -> Path:
    """GARMIN_DB overrides the default location (used by tests, the demo DB and other consumers)."""
    return Path(os.environ.get("GARMIN_DB") or ROOT / "garmin.duckdb")
