"""Raw Garmin JSON → row dicts. Fixtures are synthetic but mirror real response shapes."""

import json
from pathlib import Path

from garmin_sync import extract

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_stats_maps_keys_and_converts_distance():
    row = extract.stats(
        {"totalSteps": 8000, "totalDistanceMeters": 6123, "restingHeartRate": 47, "bodyBatteryMostRecentValue": 40}
    )
    assert row["steps"] == 8000
    assert row["distance_km"] == 6.123
    assert row["rhr"] == 47
    assert row["bb_end"] == 40


def test_stats_tolerates_empty_response():
    row = extract.stats(None)
    assert set(row.values()) == {None}


def test_sleep_stages_and_zero_awake_is_zero_not_null():
    row = extract.sleep(load("sleep.json"))
    assert row["sleep_total_min"] == 440.0  # deep + light + REM, excludes awake
    assert row["sleep_deep_min"] == 80.0
    assert row["sleep_awake_min"] == 0.0
    assert row["sleep_score"] == 84
    assert row["sleep_qualifier"] == "GOOD"
    assert row["sleep_start"].startswith("2026-02-27T")


def test_sleep_without_a_sleep_window_writes_nothing():
    assert extract.sleep({"dailySleepDTO": {"sleepStartTimestampGMT": None}}) == {}
    assert extract.sleep(None) == {}


def test_hrv_summary():
    row = extract.hrv(
        {
            "hrvSummary": {
                "weeklyAvg": 80,
                "lastNightAvg": 88,
                "status": "BALANCED",
                "baseline": {"balancedLow": 70, "balancedUpper": 95},
            }
        }
    )
    assert row == {
        "hrv_weekly_avg": 80,
        "hrv_last_night": 88,
        "hrv_baseline_low": 70,
        "hrv_baseline_high": 95,
        "hrv_status": "BALANCED",
    }


def test_training_readiness_list_and_tenth_ms_fallback():
    row, fallback = extract.training_readiness(
        [{"score": 73, "level": "MODERATE", "recoveryTime": 12, "hrvWeeklyAverage": 805}]
    )
    assert row == {"training_readiness_score": 73, "training_readiness_level": "MODERATE", "recovery_time_hours": 12}
    assert fallback == 80.5


def test_training_status_prefers_primary_device():
    row = extract.training_status(load("training_status.json"))
    assert row == {
        "training_status_phrase": "PRODUCTIVE_3",
        "training_load_balance": "AEROBIC_LOW_SHORTAGE",
        "acwr_status": "OPTIMAL",
    }


def test_activity_recorded_vs_manual():
    run, mma, no_id = (extract.activity(a) for a in load("activities.json"))
    assert run["activity_id"] == "9001"
    assert run["date"] == "2026-03-01"
    assert run["duration_min"] == 40.0
    assert run["avg_pace_min_km"] == 6.67
    assert run["is_manual"] is False
    assert mma["is_manual"] is True
    assert mma["avg_hr"] is None and mma["training_load"] is None
    assert no_id is None


def test_hr_zones_from_timezones_endpoint():
    row = extract.hr_zones(load("hr_zones.json"))
    assert row == {
        "hr_zone1_min": 2.0,
        "hr_zone2_min": 5.0,
        "hr_zone3_min": 20.0,
        "hr_zone4_min": 13.0,
        "hr_zone5_min": 0.0,
    }


def test_hr_zones_empty_for_activity_without_hr():
    assert set(extract.hr_zones([]).values()) == {None}
