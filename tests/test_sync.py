"""Sync orchestration and DB writes, with a fake Garmin client (no network)."""

import json
from pathlib import Path

import duckdb
import pytest

from garmin_sync import sync
from garmin_sync.db import connect, init_schema, upsert

FIXTURES = Path(__file__).parent / "fixtures"


class FakeGarmin:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.zone_calls = []

    def _maybe_fail(self, name):
        if name in self.fail:
            raise RuntimeError(f"{name} exploded")

    def get_stats(self, d):
        self._maybe_fail("stats")
        return {"totalSteps": 5000, "restingHeartRate": 48}

    def get_sleep_data(self, d):
        self._maybe_fail("sleep")
        return json.loads((FIXTURES / "sleep.json").read_text())

    def get_hrv_data(self, d):
        return {"hrvSummary": {"weeklyAvg": None, "lastNightAvg": 88}}

    def get_training_readiness(self, d):
        return [{"score": 70, "level": "MODERATE", "hrvWeeklyAverage": 812}]

    def get_endurance_score(self, a, b):
        return {"enduranceScoreDTO": {"overallScore": 4800}}

    def get_fitnessage_data(self, d):
        return {"fitnessAge": 21.0}

    def get_training_status(self, d):
        return json.loads((FIXTURES / "training_status.json").read_text())

    def get_activities_by_date(self, a, b):
        return json.loads((FIXTURES / "activities.json").read_text())

    def get_activity_hr_in_timezones(self, activity_id):
        self.zone_calls.append(activity_id)
        return json.loads((FIXTURES / "hr_zones.json").read_text())


@pytest.fixture
def db(tmp_path):
    con = connect(tmp_path / "t.duckdb")
    init_schema(con)
    yield con
    con.close()


def test_fetch_day_keeps_going_when_an_endpoint_fails():
    row, errors = sync.fetch_day(FakeGarmin(fail={"stats"}), "2026-03-01")
    assert errors == ["stats: stats exploded"]
    assert "steps" not in row
    assert row["sleep_score"] == 84
    assert row["hrv_weekly_avg"] == 81.2  # fallback from readiness, 0.1 ms units
    assert row["training_status_phrase"] == "PRODUCTIVE_3"


def test_fetch_activities_skips_zone_call_for_manual_activities():
    api = FakeGarmin()
    rows, errors = sync.fetch_activities(api, "2026-03-01", "2026-03-02")
    assert errors == []
    assert [r["activity_id"] for r in rows] == ["9001", "9002"]
    assert api.zone_calls == ["9001"]
    assert rows[0]["hr_zone3_min"] == 20.0
    assert rows[1]["hr_zone3_min"] is None


def test_call_retries_rate_limits(monkeypatch):
    monkeypatch.setattr(sync.time, "sleep", lambda s: None)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("429 Too Many Requests")
        return "ok"

    assert sync._call(flaky) == "ok"
    assert len(attempts) == 3


def test_call_does_not_retry_other_errors():
    with pytest.raises(ValueError):
        sync._call(lambda: (_ for _ in ()).throw(ValueError("boom")))


def test_upsert_is_idempotent_and_updates(db):
    upsert(db, "health_days", {"date": "2026-03-01", "steps": 1})
    upsert(db, "health_days", {"date": "2026-03-01", "steps": 2})
    assert db.execute("SELECT COUNT(*), MAX(steps) FROM health_days").fetchone() == (1, 2)


def test_upsert_key_only_row_does_not_crash_or_erase(db):
    """Every endpoint failing leaves a row with just the date. That must not wipe existing data."""
    upsert(db, "health_days", {"date": "2026-03-01", "steps": 5})
    upsert(db, "health_days", {"date": "2026-03-01"})
    assert db.execute("SELECT steps FROM health_days").fetchone() == (5,)


def test_schema_is_reapplied_safely_and_migrates_old_dbs(tmp_path):
    """An install from before the migrations section existed upgrades in place, keeping its rows."""
    from garmin_sync.config import SCHEMA_PATH

    con = duckdb.connect(str(tmp_path / "old.duckdb"))
    con.execute(SCHEMA_PATH.read_text().split("-- Migrations")[0])
    con.execute("INSERT INTO health_activities (activity_id, date) VALUES ('1', '2026-01-01')")
    init_schema(con)
    init_schema(con)
    cols = [r[0] for r in con.execute("DESCRIBE health_activities").fetchall()]
    assert "is_manual" in cols
    assert con.execute("SELECT COUNT(*) FROM health_activities").fetchone() == (1,)


def test_every_column_is_documented(db):
    """Column comments feed describe_schema() and docs/DATA.md. A new column without one fails here."""
    missing = db.execute(
        "SELECT table_name || '.' || column_name FROM duckdb_columns() "
        "WHERE NOT internal AND schema_name = 'main' AND (comment IS NULL OR comment = '')"
    ).fetchall()
    assert missing == []
