"""
Pure mapping from raw Garmin JSON to row dicts. No network, no DB.

Each function takes one endpoint's response and returns {column: value}.
Keys must match schema.sql exactly. If a field comes back null after an API
change, run `python -m garmin_sync.explore` and compare key names here.
"""

from datetime import UTC, datetime


def secs_to_min(v) -> float | None:
    return None if v is None else round(v / 60, 1)


def ms_to_ts(ms) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).replace(tzinfo=None).isoformat()


def _primary(device_map: dict) -> dict:
    """Garmin keys some payloads by device id; prefer the primary training device."""
    if not device_map:
        return {}
    return next(
        (v for v in device_map.values() if v.get("primaryTrainingDevice")),
        next(iter(device_map.values())),
    )


def stats(s: dict) -> dict:
    s = s or {}
    meters = s.get("totalDistanceMeters")
    return {
        "steps": s.get("totalSteps"),
        "step_goal": s.get("dailyStepGoal"),
        "floors_up": s.get("floorsAscended"),
        "distance_km": round(meters / 1000, 3) if meters else None,
        "calories_total": s.get("totalKilocalories"),
        "calories_active": s.get("activeKilocalories"),
        "calories_bmr": s.get("bmrKilocalories"),
        "hr_min": s.get("minHeartRate"),
        "hr_max": s.get("maxHeartRate"),
        "rhr": s.get("restingHeartRate"),
        "stress_avg": s.get("averageStressLevel"),
        "bb_max": s.get("bodyBatteryHighestValue"),
        "bb_min": s.get("bodyBatteryLowestValue"),
        "bb_end": s.get("bodyBatteryMostRecentValue"),
        "moderate_activity_min": s.get("moderateIntensityMinutes"),
        "vigorous_activity_min": s.get("vigorousIntensityMinutes"),
        "spo2_avg": s.get("averageSpo2"),
        "spo2_min": s.get("lowestSpo2"),
        "rr_waking_avg": s.get("avgWakingRespirationValue"),
    }


def sleep(data: dict) -> dict:
    dto = (data or {}).get("dailySleepDTO") or {}
    if not dto.get("sleepStartTimestampGMT"):
        return {}
    score = (dto.get("sleepScores") or {}).get("overall") or {}
    deep = dto.get("deepSleepSeconds") or 0
    light = dto.get("lightSleepSeconds") or 0
    rem = dto.get("remSleepSeconds") or 0
    return {
        "sleep_start": ms_to_ts(dto.get("sleepStartTimestampGMT")),
        "sleep_end": ms_to_ts(dto.get("sleepEndTimestampGMT")),
        "sleep_score": score.get("value"),
        "sleep_qualifier": score.get("qualifierKey"),
        "sleep_total_min": secs_to_min(deep + light + rem),
        "sleep_deep_min": secs_to_min(deep),
        "sleep_light_min": secs_to_min(light),
        "sleep_rem_min": secs_to_min(rem),
        "sleep_awake_min": secs_to_min(dto.get("awakeSleepSeconds")),
        "sleep_spo2_avg": dto.get("averageSpO2Value"),
        "sleep_rr_avg": dto.get("averageRespirationValue"),
    }


def hrv(data: dict) -> dict:
    summary = (data or {}).get("hrvSummary") or {}
    if not summary:
        return {}
    baseline = summary.get("baseline") or {}
    return {
        "hrv_weekly_avg": summary.get("weeklyAvg"),
        "hrv_last_night": summary.get("lastNightAvg"),
        "hrv_baseline_low": baseline.get("balancedLow"),
        "hrv_baseline_high": baseline.get("balancedUpper"),
        "hrv_status": summary.get("status"),
    }


def training_readiness(data) -> tuple[dict, float | None]:
    """Returns (row, hrv_weekly_fallback_ms).

    hrvWeeklyAverage here is in 0.1 ms units. It is used as a fallback when the
    HRV endpoint has no weekly average yet (first weeks after pairing a watch).
    """
    item = (data or [{}])[0] if isinstance(data, list) else (data or {})
    weekly = item.get("hrvWeeklyAverage")
    row = {
        "training_readiness_score": item.get("score"),
        "training_readiness_level": item.get("level"),
        "recovery_time_hours": item.get("recoveryTime"),
    }
    return row, (round(weekly / 10, 1) if weekly else None)


def endurance_score(data: dict) -> dict:
    return {"endurance_score": ((data or {}).get("enduranceScoreDTO") or {}).get("overallScore")}


def fitness_age(data: dict) -> dict:
    return {"fitness_age": (data or {}).get("fitnessAge")}


def training_status(data: dict) -> dict:
    data = data or {}
    status_map = (data.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
    status = _primary(status_map)
    balance_map = (data.get("mostRecentTrainingLoadBalance") or {}).get("metricsTrainingLoadBalanceDTOMap") or {}
    balance = _primary(balance_map)
    return {
        "training_status_phrase": status.get("trainingStatusFeedbackPhrase"),
        "training_load_balance": balance.get("trainingBalanceFeedbackPhrase"),
        "acwr_status": (status.get("acuteTrainingLoadDTO") or {}).get("acwrStatus"),
    }


def activity(a: dict) -> dict | None:
    """One entry from get_activities_by_date(). Returns None if it has no id."""
    activity_id = str(a.get("activityId") or "")
    if not activity_id:
        return None
    meters = a.get("distance")
    speed = a.get("averageSpeed")
    return {
        "activity_id": activity_id,
        "date": (a.get("startTimeLocal") or "")[:10] or None,
        "start_time": a.get("startTimeLocal"),
        "activity_type": (a.get("activityType") or {}).get("typeKey"),
        "duration_min": secs_to_min(a.get("duration")),
        "distance_km": round(meters / 1000, 3) if meters else None,
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "calories": a.get("calories"),
        "training_effect_aerobic": a.get("aerobicTrainingEffect"),
        "training_effect_anaerobic": a.get("anaerobicTrainingEffect"),
        "training_load": a.get("activityTrainingLoad"),
        "avg_pace_min_km": round(1000 / speed / 60, 2) if speed else None,
        "is_manual": bool(a.get("manualActivity")),
    }


def hr_zones(zones: list) -> dict:
    """Response of get_activity_hr_in_timezones(): [{zoneNumber, secsInZone}, ...].
    Empty list for activities without HR (e.g. manually logged)."""
    row = {f"hr_zone{i}_min": None for i in range(1, 6)}
    for z in zones or []:
        n = z.get("zoneNumber")
        if n in range(1, 6):
            row[f"hr_zone{n}_min"] = secs_to_min(z.get("secsInZone"))
    return row
