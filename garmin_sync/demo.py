"""
Build a synthetic database with the real schema, so anyone can try the MCP server
without a Garmin account, and tests/evals run on data with known properties.

  python -m garmin_sync.demo                       # → demo.duckdb, 120 days ending today
  GARMIN_DB=demo.duckdb python -m garmin_sync.server

No real person's data is in here. The generator plants patterns the evals check for:
- short nights (<6 h) lower sleep score, next-day HRV and readiness
- a hard-training block in weeks 6-7 that pushes HRV below baseline
- MMA sessions logged manually: no HR, no load, no zones
- a few unworn days (rows with only a date), like the real thing
"""

import argparse
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from garmin_sync.config import ROOT
from garmin_sync.db import connect, init_schema, upsert

DEFAULT_PATH = ROOT / "demo.duckdb"
BASE_HRV = 76.0
BASE_RHR = 52


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _band(value, thresholds, floor):
    return next((label for cutoff, label in thresholds if value >= cutoff), floor)


def build(path: Path = DEFAULT_PATH, end: date | None = None, days: int = 120, seed: int = 7) -> Path:
    rng = random.Random(seed)
    end = end or date.today()
    start = end - timedelta(days=days - 1)
    path.unlink(missing_ok=True)
    con = connect(path)
    init_schema(con)

    prev_load = 0.0
    hrv_history: list[float] = []
    for i in range(days):
        d = start + timedelta(days=i)
        week = i // 7
        hard_block = week in (5, 6)
        unworn = rng.random() < 0.03
        if unworn:
            upsert(con, "health_days", {"date": d.isoformat()})
            prev_load = 0.0
            continue

        # sleep: weekends longer, ~1 in 6 nights short
        short = rng.random() < 0.17
        sleep_min = rng.gauss(300, 30) if short else rng.gauss(460 if d.weekday() >= 5 else 420, 35)
        sleep_min = _clamp(sleep_min, 180, 600)
        deep = _clamp(sleep_min * rng.gauss(0.17, 0.03), 20, 130)
        rem = _clamp(sleep_min * rng.gauss(0.22, 0.04), 10, 160)
        light = sleep_min - deep - rem
        sleep_score = round(_clamp(30 + (sleep_min - 240) / 4.2 + rng.gauss(0, 5), 20, 98))
        qualifier = _band(sleep_score, [(90, "EXCELLENT"), (80, "GOOD"), (60, "FAIR")], "POOR")
        bedtime_utc = datetime(d.year, d.month, d.day) - timedelta(minutes=sleep_min + rng.gauss(90, 40))

        # HRV and RHR respond to sleep and yesterday's load
        hrv = BASE_HRV + (sleep_min - 420) / 18 - prev_load / 25 - (9 if hard_block else 0) + rng.gauss(0, 4)
        hrv = round(_clamp(hrv, 35, 120))
        hrv_history.append(hrv)
        weekly = round(sum(hrv_history[-7:]) / len(hrv_history[-7:]), 1)
        rhr = round(BASE_RHR - (hrv - BASE_HRV) / 6 + rng.gauss(0, 1))
        readiness = 0.55 * sleep_score + 0.9 * (hrv - BASE_HRV) + 30 - prev_load / 10 + rng.gauss(0, 6)
        readiness = round(_clamp(readiness, 1, 100))
        level = _band(readiness, [(95, "PRIME"), (75, "HIGH"), (50, "MODERATE"), (25, "LOW")], "POOR")
        bb_max = round(_clamp(35 + sleep_score * 0.65 + rng.gauss(0, 6), 20, 100))

        # workouts
        load_today = 0.0
        sessions = []
        if d.weekday() in (0, 2, 4) or (hard_block and d.weekday() == 5):
            sessions.append(("mixed_martial_arts", rng.gauss(85, 10), True))
        if d.weekday() == 6 or (hard_block and d.weekday() == 3):
            sessions.append(("running", rng.gauss(40, 8), False))
        if rng.random() < 0.3:
            sessions.append(("breathwork", rng.gauss(6, 1), False))

        moderate = vigorous = 0
        for n, (kind, minutes, manual) in enumerate(sessions):
            minutes = round(_clamp(minutes, 3, 150), 1)
            st = datetime(d.year, d.month, d.day, 18 if kind != "breathwork" else 8, 0) + timedelta(minutes=n * 5)
            row = {
                "activity_id": f"demo-{d.isoformat()}-{n}",
                "date": d.isoformat(),
                "start_time": st.isoformat(),
                "activity_type": kind,
                "duration_min": minutes,
                "is_manual": manual,
                "calories": round(minutes * (9 if kind != "breathwork" else 1.5)),
            }
            if kind == "running":
                km = round(minutes / rng.gauss(5.8, 0.3), 2)
                load = round(minutes * rng.gauss(3.6, 0.4) * (1.3 if hard_block else 1))
                z = [0.04, 0.12, 0.5, 0.3, 0.04]
                row.update(
                    {
                        "distance_km": km,
                        "avg_pace_min_km": round(minutes / km, 2),
                        "avg_hr": round(rng.gauss(150, 5)),
                        "max_hr": round(rng.gauss(176, 4)),
                        "training_load": load,
                        "training_effect_aerobic": round(_clamp(rng.gauss(3.4, 0.4), 0, 5), 1),
                        "training_effect_anaerobic": round(_clamp(rng.gauss(1.2, 0.4), 0, 5), 1),
                        **{f"hr_zone{k + 1}_min": round(minutes * f, 1) for k, f in enumerate(z)},
                    }
                )
                load_today += load
                moderate += round(minutes * 0.6)
                vigorous += round(minutes * 0.35)
            elif kind == "breathwork":
                row.update(
                    {
                        "avg_hr": round(rng.gauss(61, 3)),
                        "max_hr": round(rng.gauss(90, 6)),
                        "training_load": 0.0,
                        "training_effect_aerobic": 0.0,
                        "training_effect_anaerobic": 0.0,
                    }
                )
            elif kind == "mixed_martial_arts":
                load_today += 160 * (1.4 if hard_block else 1)  # real cost the watch never sees
            upsert(con, "health_activities", row)

        steps = round(_clamp(rng.gauss(7500, 2500), 800, 22000))
        stress = round(_clamp(rng.gauss(30, 7) + (6 if short else 0), 8, 70))
        upsert(
            con,
            "health_days",
            {
                "date": d.isoformat(),
                "steps": steps,
                "step_goal": 7000,
                "floors_up": float(rng.randint(0, 15)),
                "distance_km": round(steps * 0.00078, 2),
                "calories_active": round(steps * 0.04 + load_today * 1.5),
                "calories_bmr": 1750,
                "calories_total": round(1750 + steps * 0.04 + load_today * 1.5),
                "hr_min": rhr - 4,
                "hr_max": round(rng.gauss(150 if sessions else 115, 10)),
                "rhr": rhr,
                "stress_avg": stress,
                "bb_max": bb_max,
                "bb_min": round(_clamp(bb_max - rng.gauss(65, 12), 5, 60)),
                "bb_end": round(_clamp(bb_max - rng.gauss(55, 12), 5, 80)),
                "moderate_activity_min": moderate,
                "vigorous_activity_min": vigorous,
                "sleep_start": bedtime_utc.isoformat(),
                "sleep_end": (bedtime_utc + timedelta(minutes=sleep_min + 15)).isoformat(),
                "sleep_score": sleep_score,
                "sleep_qualifier": qualifier,
                "sleep_total_min": round(sleep_min, 1),
                "sleep_deep_min": round(deep, 1),
                "sleep_light_min": round(light, 1),
                "sleep_rem_min": round(rem, 1),
                "sleep_awake_min": round(_clamp(rng.gauss(18, 8), 2, 60), 1),
                "sleep_spo2_avg": float(round(rng.gauss(96, 0.7))),
                "sleep_rr_avg": float(round(rng.gauss(14, 0.5))),
                "hrv_last_night": float(hrv),
                "hrv_weekly_avg": weekly,
                "hrv_baseline_low": 64.0,
                "hrv_baseline_high": 82.0,
                "hrv_status": "BALANCED" if 64 <= weekly <= 82 else "UNBALANCED" if weekly > 82 else "LOW",
                "spo2_avg": float(round(rng.gauss(95.5, 0.7))),
                "spo2_min": float(round(rng.gauss(88, 2))),
                "rr_waking_avg": float(round(rng.gauss(14, 0.5))),
                "training_readiness_score": readiness,
                "training_readiness_level": level,
                "recovery_time_hours": round(load_today / 6),
                "endurance_score": 5200 + i * 3,
                "fitness_age": 27.0,
                "training_status_phrase": "STRAINED_1" if hard_block else "MAINTAINING_1",
                "training_load_balance": "BELOW_TARGETS",
                "acwr_status": "HIGH" if hard_block else "OPTIMAL",
            },
        )
        prev_load = load_today

    con.close()
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a synthetic demo database.")
    parser.add_argument("--out", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="Last date (default today)")
    args = parser.parse_args()
    out = build(args.out, args.end, args.days)
    print(f"Wrote {out}\nUse it: GARMIN_DB={out} garmin-mcp")


if __name__ == "__main__":
    main()
