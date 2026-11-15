"""The query layer the model sees, run against the synthetic demo database."""

from datetime import date

import pytest

from garmin_sync import tools
from tests.conftest import DEMO_END


def test_windows_anchor_to_latest_synced_date_not_today(demo_db):
    out = tools.get_sleep_trend(days=7, path=demo_db)
    assert out["to"] == DEMO_END.isoformat()
    assert out["from"] == "2026-03-25"
    assert all("2026-03-25" <= n["date"] <= "2026-03-31" for n in out["nightly"])


def test_stale_data_is_flagged(demo_db):
    out = tools.get_snapshot(path=demo_db, today=date(2026, 4, 10))
    assert out["stale_days"] == 10
    assert "10 days old" in out["warning"]


def test_today_is_flagged_as_partial(demo_db):
    out = tools.get_snapshot(path=demo_db, today=DEMO_END)
    assert out["stale_days"] == 0
    assert "warning" not in out
    assert any("partial" in n for n in out["notes"])


def test_snapshot_adds_hrv_band(demo_db):
    day = tools.get_snapshot(path=demo_db)["day"]
    assert day["hrv_band"] in {"below_baseline", "within_baseline", "above_baseline"}


@pytest.mark.parametrize(
    "value, band", [(60, "below_baseline"), (70, "within_baseline"), (90, "above_baseline"), (None, None)]
)
def test_hrv_band(value, band):
    assert tools.hrv_band(value, 64, 82) == band


def test_short_nights_are_listed(demo_db):
    out = tools.get_sleep_trend(days=120, path=demo_db)
    short = {n["date"] for n in out["nightly"] if n["sleep_total_min"] < 360}
    assert set(out["nights_under_6h"]) == short
    assert short


def test_training_log_flags_manual_sessions_as_unknown_load(demo_db):
    out = tools.get_training_log(days=28, path=demo_db)
    mma = out["by_type"]["mixed_martial_arts"]
    assert mma["sessions"] == mma["manual_sessions"] > 0
    assert any("no heart rate" in n for n in out["notes"])
    # recorded load excludes manual sessions: it is a sum of known values, not a total
    known = sum(a["training_load"] for a in out["activities"] if a["training_load"] is not None)
    assert out["recorded_training_load"] == round(known, 1)


def test_get_day_unworn_and_missing(demo_db):
    unworn = tools.query_sql("SELECT date FROM health_days WHERE steps IS NULL LIMIT 1", path=demo_db)
    d = unworn["rows"][0]["date"]
    assert tools.get_day(d, path=demo_db)["notes"] == ["No watch data for this day."]
    assert "error" in tools.get_day("1999-01-01", path=demo_db)


def test_compare_periods_deltas(demo_db):
    out = tools.compare_periods("2026-02-01", "2026-02-14", "2026-03-18", "2026-03-31", path=demo_db)
    for metric, delta in out["delta_b_minus_a"].items():
        assert delta == round(out["b"][metric] - out["a"][metric], 1)


def test_describe_schema_documents_every_column(demo_db):
    out = tools.describe_schema(path=demo_db)
    cols = out["tables"]["health_activities"]["columns"]
    assert all(c["description"] for c in cols)
    manual = next(c for c in cols if c["name"] == "is_manual")
    assert manual["fill_pct_last_60d"] == 100


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM health_days",
        "DROP TABLE health_days",
        "SELECT 1; DROP TABLE health_days",
        "COPY health_days TO 'out.csv'",
        "SELECT * FROM read_csv('/etc/hosts')",
        "WITH x AS (SELECT 1) SELECT * FROM read_text('/etc/passwd')",
        "ATTACH '/tmp/other.duckdb' AS o",
    ],
)
def test_query_sql_refuses_writes_and_file_access(demo_db, sql):
    assert "error" in tools.query_sql(sql, path=demo_db)
    assert tools.query_sql("SELECT COUNT(*) AS n FROM health_days", path=demo_db)["rows"] == [{"n": 120}]


def test_query_sql_truncates(demo_db):
    out = tools.query_sql("SELECT * FROM range(1000)", path=demo_db)
    assert out["row_count"] == tools.MAX_SQL_ROWS
    assert "truncated" in out


def test_missing_db_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="garmin_sync.sync"):
        tools.get_snapshot(path=tmp_path / "nope.duckdb")


def test_profile_missing(tmp_path):
    assert "error" in tools.get_profile(path=tmp_path / "physiology.json")
