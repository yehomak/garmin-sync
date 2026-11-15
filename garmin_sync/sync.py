"""
Sync Garmin Connect → DuckDB. Read-only against Garmin; idempotent against the DB.

  python -m garmin_sync.sync                     # yesterday + today
  python -m garmin_sync.sync --date 2026-05-01   # one date
  python -m garmin_sync.sync --backfill 30       # last N days
  python -m garmin_sync.sync --backfill 200 --activities-only   # re-fetch workouts only
  python -m garmin_sync.sync --status            # DB summary, no network
"""

import argparse
import time
from datetime import date, timedelta

from garmin_sync import extract
from garmin_sync.config import TOKENSTORE, db_path
from garmin_sync.db import connect, init_schema, upsert

VERBOSE_THRESHOLD = 14  # one line per day below this, milestone lines above


def _call(fn, retries: int = 2, wait: int = 5):
    """Call fn(), retrying on 429 / rate-limit errors with linear backoff."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            msg = str(e).lower()
            if ("429" in msg or "too many" in msg) and attempt < retries:
                time.sleep(wait * (attempt + 1))
                continue
            raise


def fetch_day(api, d: str) -> tuple[dict, list[str]]:
    """Returns (row, errors). Never raises: one failing endpoint must not lose the day."""
    row: dict = {"date": d}
    errors: list[str] = []

    def attempt(name: str, fn):
        try:
            row.update(_call(fn))
        except Exception as e:
            errors.append(f"{name}: {e}")

    attempt("stats", lambda: extract.stats(api.get_stats(d)))
    attempt("sleep", lambda: extract.sleep(api.get_sleep_data(d)))
    attempt("hrv", lambda: extract.hrv(api.get_hrv_data(d)))

    try:
        readiness, hrv_fallback = extract.training_readiness(_call(lambda: api.get_training_readiness(d)))
        row.update(readiness)
        if hrv_fallback and not row.get("hrv_weekly_avg"):
            row["hrv_weekly_avg"] = hrv_fallback
    except Exception as e:
        errors.append(f"training_readiness: {e}")

    attempt("endurance", lambda: extract.endurance_score(api.get_endurance_score(d, d)))
    attempt("fitness_age", lambda: extract.fitness_age(api.get_fitnessage_data(d)))
    attempt("training_status", lambda: extract.training_status(api.get_training_status(d)))
    return row, errors


def fetch_activities(api, start: str, end: str) -> tuple[list[dict], list[str]]:
    """Returns (rows, errors). Never raises."""
    try:
        raw = _call(lambda: api.get_activities_by_date(start, end)) or []
    except Exception as e:
        return [], [f"activities list: {e}"]

    rows, errors = [], []
    for a in raw:
        row = extract.activity(a)
        if row is None:
            continue
        row.update(extract.hr_zones([]))
        if not row["is_manual"]:  # manual activities have no HR stream to bucket
            try:
                aid = row["activity_id"]
                row.update(extract.hr_zones(_call(lambda aid=aid: api.get_activity_hr_in_timezones(aid))))
            except Exception as e:
                errors.append(f"zones {row['activity_id']}: {e}")
        rows.append(row)
    return rows, errors


def sync_range(start: date, end: date, activities_only: bool = False) -> None:
    from garmin_sync.auth import get_client  # lazy: --status and tests must not need credentials

    total = (end - start).days + 1
    verbose = total <= VERBOSE_THRESHOLD
    milestone = max(1, round(total / 10))
    t0 = time.monotonic()
    print(f"Syncing {start} → {end} ({total} day{'s' if total != 1 else ''})")

    api = get_client()
    con = connect()
    init_schema(con)

    all_errors: list[str] = []
    partial_days = 0
    for i in range(0 if activities_only else total):
        ds = (start + timedelta(days=i)).isoformat()
        row, errors = fetch_day(api, ds)
        upsert(con, "health_days", row)
        if errors:
            partial_days += 1
            all_errors.extend(f"  {ds} {e}" for e in errors)
        if verbose:
            status = f"partial ({', '.join(e.split(':')[0] for e in errors)})" if errors else "ok"
            print(f"  [{i + 1}/{total}] {ds} {status}")
        elif (i + 1) % milestone == 0 or i + 1 == total:
            print(f"  [{i + 1}/{total}] {ds} ({round((i + 1) / total * 100)}%)")

    print(f"Activities {start} → {end} ...", end=" ", flush=True)
    activity_rows, act_errors = fetch_activities(api, start.isoformat(), end.isoformat())
    for row in activity_rows:
        upsert(con, "health_activities", row)
    all_errors.extend(f"  {e}" for e in act_errors)
    print(f"{len(activity_rows)} synced")
    con.close()

    n = len(all_errors)
    print(
        f"\nDone — {0 if activities_only else total} day{'' if total == 1 and not activities_only else 's'} "
        f"({partial_days} partial), {len(activity_rows)} activities, "
        f"{n} error{'s' if n != 1 else ''} [{time.monotonic() - t0:.1f}s]"
    )
    if all_errors:
        print("\nErrors:\n" + "\n".join(all_errors))


def show_status() -> None:
    path = db_path()
    if not path.exists():
        print(f"{path} not found — run a sync first")
        return
    con = connect(read_only=True)
    count, first, last = con.execute(
        "SELECT COUNT(*), MIN(date)::VARCHAR, MAX(date)::VARCHAR FROM health_days"
    ).fetchone()
    acts = con.execute("SELECT COUNT(*) FROM health_activities").fetchone()[0]
    con.close()
    print(f"Database:    {path} ({path.stat().st_size // 1024} KB)")
    print(f"health_days: {count} rows  {first} → {last}")
    print(f"activities:  {acts} rows")
    print(f"Session:     {'cached' if (TOKENSTORE / 'garmin_tokens.json').exists() else 'missing — run auth'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sync Garmin Connect data into DuckDB.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--date", help="Sync one date (YYYY-MM-DD)")
    group.add_argument("--backfill", type=int, metavar="DAYS", help="Sync the last N days")
    group.add_argument("--status", action="store_true", help="Show DB summary without syncing")
    parser.add_argument(
        "--activities-only", action="store_true", help="Only re-fetch workouts (e.g. after an activity schema change)"
    )
    args = parser.parse_args(argv)

    today = date.today()
    if args.status:
        show_status()
    elif args.date:
        d = date.fromisoformat(args.date)
        sync_range(d, d, args.activities_only)
    elif args.backfill:
        sync_range(today - timedelta(days=args.backfill), today, args.activities_only)
    else:
        sync_range(today - timedelta(days=1), today, args.activities_only)


if __name__ == "__main__":
    main()
