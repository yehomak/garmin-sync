from datetime import date

import pytest

from garmin_sync import demo

DEMO_END = date(2026, 3, 31)  # fixed, so window maths and assertions are deterministic


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory):
    return demo.build(tmp_path_factory.mktemp("db") / "demo.duckdb", end=DEMO_END, days=120)


@pytest.fixture
def demo_env(demo_db, monkeypatch):
    """Point everything that reads GARMIN_DB (the MCP server) at the demo database."""
    monkeypatch.setenv("GARMIN_DB", str(demo_db))
    return demo_db
