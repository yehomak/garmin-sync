"""
Query layer behind the MCP server. Plain functions returning JSON-able dicts,
so tests and evals call exactly what the model calls.

Design rules (they are the point of this module):
- Windows are anchored to the latest synced date, not today, and every response
  says how fresh the data is. A stale DB must never look like a bad week.
- Caveats travel with the data in `notes` (partial current day, manual workouts
  without HR, lagging Garmin labels) so the model does not have to know them.
- Nulls stay null. Missing is not zero.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

import duckdb

from garmin_sync.config import PHYSIOLOGY_PATH, db_path

MAX_SQL_ROWS = 500


# ── connection & helpers ──────────────────────────────────────────────────────


def _conn(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Read-only, no filesystem/network access, config locked. Safe for model-written SQL."""
    path = path or db_path()
    if not path.exists():
        raise FileNotFoundError(f"No database at {path}. Run `python -m garmin_sync.sync --backfill 30` first.")
    return duckdb.connect(
        str(path),
        read_only=True,
        config={"enable_external_access": False, "lock_configuration": True},
    )


def _jsonable(v):
    if isinstance(v, float):
        return round(v, 2)  # FLOAT columns are single precision: 0.489 comes back as 0.48899999
    return v.isoformat() if hasattr(v, "isoformat") else v


def _rows(con, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [{c: _jsonable(v) for c, v in zip(cols, r, strict=True)} for r in cur.fetchall()]


def _avg(values, digits: int = 1):
    vals = [v for v in values if v is not None]
    return round(mean(vals), digits) if vals else None


def _latest_date(con) -> date | None:
    """Latest date with any watch data (not just a row: rows exist for unworn days)."""
    return con.execute(
        "SELECT MAX(date) FROM health_days WHERE steps IS NOT NULL OR sleep_score IS NOT NULL"
    ).fetchone()[0]


def _freshness(con, today: date | None = None) -> dict:
    latest = _latest_date(con)
    today = today or date.today()
    out = {"data_through": _jsonable(latest), "stale_days": (today - latest).days if latest else None}
    if latest and out["stale_days"] > 1:
        out["warning"] = (
            f"Data is {out['stale_days']} days old. Run a sync before drawing conclusions about recent days."
        )
    return out


def _window(con, days: int, end_date: str | None) -> tuple[date, date]:
    end = date.fromisoformat(end_date) if end_date else (_latest_date(con) or date.today())
    return end - timedelta(days=max(1, days) - 1), end


def hrv_band(last_night, low, high) -> str | None:
    """Last night's HRV against the personal balanced band. Garmin's hrv_status lags by days."""
    if last_night is None or low is None or high is None:
        return None
    if last_night < low:
        return "below_baseline"
    if last_night > high:
        return "above_baseline"
    return "within_baseline"


# ── tools ─────────────────────────────────────────────────────────────────────


def describe_schema(path: Path | None = None) -> dict:
    con = _conn(path)
    tables = {}
    for table, comment in con.execute(
        "SELECT table_name, comment FROM duckdb_tables() WHERE schema_name = 'main' ORDER BY table_name"
    ).fetchall():
        latest = con.execute(f"SELECT MAX(date) FROM {table}").fetchone()[0]
        recent = f"date > DATE '{latest}' - INTERVAL 60 DAY" if latest else "TRUE"
        n_recent = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {recent}").fetchone()[0]
        columns = []
        for name, dtype, col_comment in con.execute(
            "SELECT column_name, data_type, comment FROM duckdb_columns() "
            "WHERE schema_name = 'main' AND table_name = ? ORDER BY column_index",
            [table],
        ).fetchall():
            filled = con.execute(f'SELECT COUNT("{name}") FROM {table} WHERE {recent}').fetchone()[0]
            columns.append(
                {
                    "name": name,
                    "type": dtype,
                    "description": col_comment,
                    "fill_pct_last_60d": round(100 * filled / n_recent) if n_recent else None,
                }
            )
        tables[table] = {
            "description": comment,
            "rows": con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
            "columns": columns,
        }
    return {**_freshness(con), "tables": tables}


def get_snapshot(path: Path | None = None, today: date | None = None) -> dict:
    con = _conn(path)
    latest = _latest_date(con)
    if latest is None:
        return {"error": "No health data yet. Run a sync."}
    day = _rows(con, "SELECT * FROM health_days WHERE date = ?", [latest])[0]
    day["hrv_band"] = hrv_band(day["hrv_last_night"], day["hrv_baseline_low"], day["hrv_baseline_high"])
    fresh = _freshness(con, today)
    notes = []
    if fresh["stale_days"] == 0:
        notes.append("This is today: steps, calories, stress and bb_end are partial until the day ends.")
    return {**fresh, "day": day, "notes": notes}


def get_sleep_trend(days: int = 14, end_date: str | None = None, path: Path | None = None) -> dict:
    con = _conn(path)
    start, end = _window(con, days, end_date)
    rows = _rows(
        con,
        """
        SELECT date, sleep_score, sleep_qualifier, sleep_total_min, sleep_deep_min,
               sleep_rem_min, sleep_light_min, sleep_awake_min, sleep_start, sleep_end,
               sleep_spo2_avg, sleep_rr_avg
        FROM health_days WHERE date BETWEEN ? AND ? AND sleep_score IS NOT NULL ORDER BY date
    """,
        [start, end],
    )
    short = [r["date"] for r in rows if (r["sleep_total_min"] or 0) < 360]
    return {
        **_freshness(con),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "nights": len(rows),
        "avg_score": _avg(r["sleep_score"] for r in rows),
        "avg_total_min": _avg(r["sleep_total_min"] for r in rows),
        "avg_deep_min": _avg(r["sleep_deep_min"] for r in rows),
        "avg_rem_min": _avg(r["sleep_rem_min"] for r in rows),
        "nights_under_6h": short,
        "notes": ["sleep_start/sleep_end are UTC."],
        "nightly": rows,
    }


def get_recovery_trend(days: int = 14, end_date: str | None = None, path: Path | None = None) -> dict:
    con = _conn(path)
    start, end = _window(con, days, end_date)
    rows = _rows(
        con,
        """
        SELECT date, training_readiness_score, training_readiness_level, hrv_last_night,
               hrv_weekly_avg, hrv_baseline_low, hrv_baseline_high, hrv_status, rhr,
               bb_max, bb_min, bb_end, stress_avg, recovery_time_hours
        FROM health_days
        WHERE date BETWEEN ? AND ? AND (hrv_last_night IS NOT NULL OR rhr IS NOT NULL)
        ORDER BY date
    """,
        [start, end],
    )
    for r in rows:
        r["hrv_band"] = hrv_band(r["hrv_last_night"], r["hrv_baseline_low"], r["hrv_baseline_high"])
    return {
        **_freshness(con),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": len(rows),
        "avg_readiness": _avg(r["training_readiness_score"] for r in rows),
        "avg_hrv_ms": _avg(r["hrv_last_night"] for r in rows),
        "avg_rhr": _avg(r["rhr"] for r in rows),
        "avg_bb_max": _avg(r["bb_max"] for r in rows),
        "avg_stress": _avg(r["stress_avg"] for r in rows),
        "days_hrv_below_baseline": [r["date"] for r in rows if r["hrv_band"] == "below_baseline"],
        "notes": ["hrv_status is Garmin's weekly-average label and lags; prefer hrv_band for a single night."],
        "daily": rows,
    }


def get_training_log(days: int = 28, end_date: str | None = None, path: Path | None = None) -> dict:
    con = _conn(path)
    start, end = _window(con, days, end_date)
    acts = _rows(
        con,
        """
        SELECT date, start_time, activity_type, duration_min, distance_km, avg_hr, max_hr,
               training_load, training_effect_aerobic, training_effect_anaerobic,
               hr_zone1_min, hr_zone2_min, hr_zone3_min, hr_zone4_min, hr_zone5_min,
               avg_pace_min_km, is_manual
        FROM health_activities WHERE date BETWEEN ? AND ? ORDER BY start_time
    """,
        [start, end],
    )
    by_type: dict[str, dict] = {}
    for a in acts:
        t = by_type.setdefault(a["activity_type"] or "unknown", {"sessions": 0, "minutes": 0.0, "manual_sessions": 0})
        t["sessions"] += 1
        t["minutes"] = round(t["minutes"] + (a["duration_min"] or 0), 1)
        t["manual_sessions"] += bool(a["is_manual"])
    no_hr = [a for a in acts if a["avg_hr"] is None]
    notes = []
    if no_hr:
        mins = round(sum(a["duration_min"] or 0 for a in no_hr))
        notes.append(
            f"{len(no_hr)} of {len(acts)} sessions ({mins} min) have no heart rate, usually because they were "
            "logged manually. Their load is unknown, not zero, and Garmin readiness and training status do not "
            "account for them."
        )
    loads = [a["training_load"] for a in acts if a["training_load"] is not None]
    return {
        **_freshness(con),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "sessions": len(acts),
        "total_minutes": round(sum(a["duration_min"] or 0 for a in acts), 1),
        "recorded_training_load": round(sum(loads), 1) if loads else None,
        "by_type": by_type,
        "notes": notes,
        "activities": acts,
    }


def get_day(day: str, path: Path | None = None) -> dict:
    con = _conn(path)
    rows = _rows(con, "SELECT * FROM health_days WHERE date = ?", [day])
    if not rows:
        return {**_freshness(con), "error": f"No row for {day}. It may be outside the synced range."}
    row = rows[0]
    row["hrv_band"] = hrv_band(row["hrv_last_night"], row["hrv_baseline_low"], row["hrv_baseline_high"])
    acts = _rows(
        con,
        """
        SELECT activity_type, start_time, duration_min, avg_hr, training_load, is_manual
        FROM health_activities WHERE date = ? ORDER BY start_time
    """,
        [day],
    )
    notes = [] if row["steps"] is not None or row["sleep_score"] is not None else ["No watch data for this day."]
    return {**_freshness(con), "day": row, "activities": acts, "notes": notes}


COMPARE_METRICS = [
    "sleep_score",
    "sleep_total_min",
    "sleep_deep_min",
    "sleep_rem_min",
    "hrv_last_night",
    "rhr",
    "training_readiness_score",
    "bb_max",
    "bb_end",
    "stress_avg",
    "steps",
]


def compare_periods(a_from: str, a_to: str, b_from: str, b_to: str, path: Path | None = None) -> dict:
    """Averages for period A vs period B, with B - A deltas."""
    con = _conn(path)
    select = ", ".join(f"ROUND(AVG({m}), 1) AS {m}" for m in COMPARE_METRICS)

    def period(lo, hi):
        stats = _rows(
            con, f"SELECT COUNT(sleep_score) AS nights, {select} FROM health_days WHERE date BETWEEN ? AND ?", [lo, hi]
        )[0]
        stats["sessions"] = con.execute(
            "SELECT COUNT(*) FROM health_activities WHERE date BETWEEN ? AND ?", [lo, hi]
        ).fetchone()[0]
        return {"from": lo, "to": hi, **stats}

    a, b = period(a_from, a_to), period(b_from, b_to)
    delta = {m: round(b[m] - a[m], 1) for m in COMPARE_METRICS + ["sessions"] if a[m] is not None and b[m] is not None}
    return {**_freshness(con), "a": a, "b": b, "delta_b_minus_a": delta}


def query_sql(sql: str, path: Path | None = None) -> dict:
    """Run one read-only SELECT. The connection cannot write, touch files or reach the network."""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        return {"error": "One statement per call."}
    if not stripped.lower().startswith(("select", "with", "describe", "summarize")):
        return {"error": "Only SELECT / WITH / DESCRIBE / SUMMARIZE queries are allowed."}
    con = _conn(path)
    try:
        cur = con.execute(stripped)
    except duckdb.Error as e:
        return {"error": f"{type(e).__name__}: {e}"}
    cols = [d[0] for d in cur.description]
    raw = cur.fetchmany(MAX_SQL_ROWS + 1)
    rows = [{c: _jsonable(v) for c, v in zip(cols, r, strict=True)} for r in raw[:MAX_SQL_ROWS]]
    out = {"columns": cols, "rows": rows, "row_count": len(rows)}
    if len(raw) > MAX_SQL_ROWS:
        out["truncated"] = f"Only the first {MAX_SQL_ROWS} rows returned. Aggregate or add LIMIT."
    return out


def get_profile(path: Path | None = None) -> dict:
    path = path or PHYSIOLOGY_PATH
    if not path.exists():
        return {"error": "No profile yet. Run `python -m garmin_sync.physiology`."}
    data = json.loads(path.read_text())
    generated = data.get("generated")
    if generated:
        age_days = (date.today() - date.fromisoformat(generated)).days
        data["profile_age_days"] = age_days
        if age_days > 45:
            data["warning"] = f"Profile is {age_days} days old. Race predictions and weight may have changed."
    return data
