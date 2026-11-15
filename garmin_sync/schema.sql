-- Source of truth for the database. Applied on every sync run, so every
-- statement here must be idempotent (IF NOT EXISTS / COMMENT ON).
--
-- Column comments are not decoration: the MCP server serves them to the model
-- via describe_schema(), and docs/DATA.md is generated from them
-- (python -m garmin_sync.docs). Put units and caveats here, nowhere else.

CREATE TABLE IF NOT EXISTS health_days (
    date                  DATE PRIMARY KEY,
    steps                 INTEGER,
    step_goal             INTEGER,
    floors_up             FLOAT,
    distance_km           FLOAT,
    calories_total        INTEGER,
    calories_active       INTEGER,
    calories_bmr          INTEGER,
    hr_min                INTEGER,
    hr_max                INTEGER,
    rhr                   INTEGER,
    stress_avg            INTEGER,
    bb_max                INTEGER,
    bb_min                INTEGER,
    bb_end                INTEGER,
    moderate_activity_min INTEGER,
    vigorous_activity_min INTEGER,
    sleep_start           TIMESTAMP,
    sleep_end             TIMESTAMP,
    sleep_score           INTEGER,
    sleep_qualifier       VARCHAR,
    sleep_total_min       FLOAT,
    sleep_deep_min        FLOAT,
    sleep_light_min       FLOAT,
    sleep_rem_min         FLOAT,
    sleep_awake_min       FLOAT,
    sleep_spo2_avg        FLOAT,
    sleep_rr_avg          FLOAT,
    hrv_weekly_avg        FLOAT,
    hrv_last_night        FLOAT,
    hrv_baseline_low      FLOAT,
    hrv_baseline_high     FLOAT,
    hrv_status            VARCHAR,
    spo2_avg              FLOAT,
    spo2_min              FLOAT,
    rr_waking_avg         FLOAT,
    training_readiness_score  INTEGER,
    training_readiness_level  VARCHAR,
    recovery_time_hours       INTEGER,
    endurance_score           INTEGER,
    fitness_age               FLOAT,
    training_status_phrase    VARCHAR,
    training_load_balance     VARCHAR,
    acwr_status               VARCHAR
);

CREATE TABLE IF NOT EXISTS health_activities (
    activity_id           VARCHAR PRIMARY KEY,
    date                  DATE,
    start_time            TIMESTAMP,
    activity_type         VARCHAR,
    duration_min          FLOAT,
    distance_km           FLOAT,
    avg_hr                INTEGER,
    max_hr                INTEGER,
    calories              INTEGER,
    training_effect_aerobic    FLOAT,
    training_effect_anaerobic  FLOAT,
    training_load         FLOAT,
    hr_zone1_min          FLOAT,
    hr_zone2_min          FLOAT,
    hr_zone3_min          FLOAT,
    hr_zone4_min          FLOAT,
    hr_zone5_min          FLOAT,
    avg_pace_min_km       FLOAT
);

-- Migrations: additive only, so existing databases upgrade in place.
ALTER TABLE health_activities ADD COLUMN IF NOT EXISTS is_manual BOOLEAN;

COMMENT ON TABLE health_days IS 'One row per calendar date (local time). Rows exist for every synced date, including days the watch was not worn, so expect fully-null rows.';
COMMENT ON TABLE health_activities IS 'One row per recorded or manually logged workout.';

COMMENT ON COLUMN health_days.date IS 'Calendar date, local time. Primary key.';
COMMENT ON COLUMN health_days.steps IS 'Total steps. The current date is partial until the day ends.';
COMMENT ON COLUMN health_days.step_goal IS 'Garmin auto-adjusting daily step goal.';
COMMENT ON COLUMN health_days.floors_up IS 'Floors climbed (barometric).';
COMMENT ON COLUMN health_days.distance_km IS 'Total distance from all movement, km.';
COMMENT ON COLUMN health_days.calories_total IS 'Total kcal (active + BMR).';
COMMENT ON COLUMN health_days.calories_active IS 'Active kcal.';
COMMENT ON COLUMN health_days.calories_bmr IS 'Resting metabolic kcal. Nearly constant; low information.';
COMMENT ON COLUMN health_days.hr_min IS 'Lowest heart rate of the day, bpm.';
COMMENT ON COLUMN health_days.hr_max IS 'Highest heart rate of the day, bpm.';
COMMENT ON COLUMN health_days.rhr IS 'Resting heart rate, bpm. Lower is generally better; a rise of 5+ bpm over baseline suggests fatigue or illness.';
COMMENT ON COLUMN health_days.stress_avg IS 'Average all-day stress, 0-100 (HRV-derived). 0-25 rest, 26-50 low, 51-75 medium, 76-100 high.';
COMMENT ON COLUMN health_days.bb_max IS 'Body Battery daily high, 0-100. Usually reached on waking.';
COMMENT ON COLUMN health_days.bb_min IS 'Body Battery daily low, 0-100.';
COMMENT ON COLUMN health_days.bb_end IS 'Most recent Body Battery value at sync time. For the current date this is a mid-day value, not end of day.';
COMMENT ON COLUMN health_days.moderate_activity_min IS 'Moderate intensity minutes (HR-based). Manually logged workouts contribute nothing.';
COMMENT ON COLUMN health_days.vigorous_activity_min IS 'Vigorous intensity minutes (HR-based). Count double toward the WHO 150 min/week target.';
COMMENT ON COLUMN health_days.sleep_start IS 'Sleep start, UTC. Convert to local time before reasoning about bedtimes.';
COMMENT ON COLUMN health_days.sleep_end IS 'Sleep end (wake), UTC.';
COMMENT ON COLUMN health_days.sleep_score IS 'Garmin sleep score, 0-100. 90+ excellent, 80-89 good, 60-79 fair, <60 poor. Attributed to the date you woke up.';
COMMENT ON COLUMN health_days.sleep_qualifier IS 'Sleep score band: EXCELLENT, GOOD, FAIR, POOR.';
COMMENT ON COLUMN health_days.sleep_total_min IS 'Time asleep (deep + light + REM), minutes. Excludes awake time.';
COMMENT ON COLUMN health_days.sleep_deep_min IS 'Deep sleep, minutes. Typical adult range 60-90.';
COMMENT ON COLUMN health_days.sleep_light_min IS 'Light sleep, minutes.';
COMMENT ON COLUMN health_days.sleep_rem_min IS 'REM sleep, minutes. Typical adult range 90-120.';
COMMENT ON COLUMN health_days.sleep_awake_min IS 'Awake time during the sleep window, minutes. Over 30 suggests fragmented sleep.';
COMMENT ON COLUMN health_days.sleep_spo2_avg IS 'Average blood oxygen during sleep, %.';
COMMENT ON COLUMN health_days.sleep_rr_avg IS 'Average respiration rate during sleep, breaths/min.';
COMMENT ON COLUMN health_days.hrv_weekly_avg IS 'Rolling 7-day average of overnight HRV, ms.';
COMMENT ON COLUMN health_days.hrv_last_night IS 'Average overnight HRV (RMSSD), ms. Primary recovery signal; compare against the baseline band, not population norms.';
COMMENT ON COLUMN health_days.hrv_baseline_low IS 'Lower bound of the personal balanced HRV band, ms.';
COMMENT ON COLUMN health_days.hrv_baseline_high IS 'Upper bound of the personal balanced HRV band, ms.';
COMMENT ON COLUMN health_days.hrv_status IS 'Garmin HRV status, e.g. BALANCED, UNBALANCED, LOW, NONE (not enough history). Based on the weekly average, so it lags last night''s value by days.';
COMMENT ON COLUMN health_days.spo2_avg IS 'Average daytime blood oxygen, %.';
COMMENT ON COLUMN health_days.spo2_min IS 'Lowest blood oxygen reading, %. Single low readings are often sensor movement.';
COMMENT ON COLUMN health_days.rr_waking_avg IS 'Average waking respiration rate, breaths/min.';
COMMENT ON COLUMN health_days.training_readiness_score IS 'Garmin training readiness, 0-100. Computed by Garmin from sleep, HRV, recovery time and load, so it correlates with those inputs by construction.';
COMMENT ON COLUMN health_days.training_readiness_level IS 'Readiness band: PRIME, HIGH, MODERATE, LOW, POOR.';
COMMENT ON COLUMN health_days.recovery_time_hours IS 'Garmin estimated hours until fully recovered.';
COMMENT ON COLUMN health_days.endurance_score IS 'Garmin endurance score, raw scale (~3500-10500). Changes over weeks, not days.';
COMMENT ON COLUMN health_days.fitness_age IS 'Garmin fitness age, years. Changes rarely.';
COMMENT ON COLUMN health_days.training_status_phrase IS 'Garmin training status with a numeric suffix, e.g. PRODUCTIVE_3, DETRAINING, STRAINED_3. Ignores manually logged workouts.';
COMMENT ON COLUMN health_days.training_load_balance IS 'Training load focus feedback, e.g. BELOW_TARGETS, AEROBIC_LOW_SHORTAGE, AEROBIC_HIGH_SHORTAGE.';
COMMENT ON COLUMN health_days.acwr_status IS 'Acute:chronic workload ratio band: LOW, OPTIMAL, HIGH.';

COMMENT ON COLUMN health_activities.activity_id IS 'Garmin activity id. Primary key.';
COMMENT ON COLUMN health_activities.date IS 'Local start date.';
COMMENT ON COLUMN health_activities.start_time IS 'Local start time.';
COMMENT ON COLUMN health_activities.activity_type IS 'Garmin type key, e.g. running, mixed_martial_arts, breathwork, strength_training.';
COMMENT ON COLUMN health_activities.duration_min IS 'Duration, minutes.';
COMMENT ON COLUMN health_activities.distance_km IS 'Distance, km. Null for non-distance activities.';
COMMENT ON COLUMN health_activities.avg_hr IS 'Average heart rate, bpm. Null for manually logged activities.';
COMMENT ON COLUMN health_activities.max_hr IS 'Max heart rate, bpm. Null for manually logged activities.';
COMMENT ON COLUMN health_activities.calories IS 'Activity kcal. For manual activities this is user-entered or estimated.';
COMMENT ON COLUMN health_activities.training_effect_aerobic IS 'Aerobic training effect, 0-5. 0-0.9 none, 1-1.9 minor, 2-2.9 maintaining, 3-3.9 improving, 4-4.9 highly improving, 5 overreaching.';
COMMENT ON COLUMN health_activities.training_effect_anaerobic IS 'Anaerobic training effect, 0-5. Same bands as aerobic.';
COMMENT ON COLUMN health_activities.training_load IS 'Garmin EPOC-based load for the session. Null (not zero) for manual activities.';
COMMENT ON COLUMN health_activities.hr_zone1_min IS 'Minutes in HR zone 1 (warm-up).';
COMMENT ON COLUMN health_activities.hr_zone2_min IS 'Minutes in HR zone 2 (easy / aerobic base).';
COMMENT ON COLUMN health_activities.hr_zone3_min IS 'Minutes in HR zone 3 (aerobic / tempo).';
COMMENT ON COLUMN health_activities.hr_zone4_min IS 'Minutes in HR zone 4 (threshold).';
COMMENT ON COLUMN health_activities.hr_zone5_min IS 'Minutes in HR zone 5 (max).';
COMMENT ON COLUMN health_activities.avg_pace_min_km IS 'Average pace, min/km. Only meaningful for GPS activities.';
COMMENT ON COLUMN health_activities.is_manual IS 'True if logged by hand in the app rather than recorded on the watch. Manual activities have no HR, zones, load or training effect, and Garmin readiness/training status do not see them.';
