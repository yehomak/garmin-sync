"""
Eval cases: questions a real user asks, with ground truth computed from the demo DB.

Each case has
  question  what the user types
  truth     fn(sql) -> expected value, computed with the same read-only SQL the model can run
  check     fn(answer, expected) -> bool, applied to the model's final `ANSWER:` line
  tools     at least one of these must be called (catches answering from priors)

Ground truth is queried, never hand-typed, so cases stay valid when the demo generator changes.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Case:
    id: str
    question: str
    truth: Callable
    check: Callable
    tools: set[str] = field(default_factory=set)


def _one(sql, q):
    return next(iter(sql(q)["rows"][0].values()))


def _number_within(tol):
    def check(answer, expected):
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", answer)]
        return any(abs(n - expected) <= tol for n in nums)

    return check


def _contains(answer, expected):
    return str(expected).lower() in answer.lower()


def _yes_no(answer, expected):
    a = answer.strip().lower()
    return a.startswith("yes") if expected else a.startswith("no")


LATEST = "(SELECT MAX(date) FROM health_days WHERE sleep_score IS NOT NULL OR steps IS NOT NULL)"

CASES = [
    Case(
        id="avg_sleep_7d",
        question="What was my average sleep score over the last 7 nights?",
        truth=lambda sql: round(
            _one(
                sql,
                f"""
            SELECT AVG(sleep_score) FROM health_days
            WHERE date > {LATEST} - INTERVAL 7 DAY AND date <= {LATEST}""",
            ),
            1,
        ),
        check=_number_within(1.0),
        tools={"get_sleep_trend", "query_sql", "compare_periods"},
    ),
    Case(
        id="worst_night_14d",
        question="Which night in the last two weeks had my lowest sleep score? Give the date.",
        truth=lambda sql: str(
            _one(
                sql,
                f"""
            SELECT date FROM health_days
            WHERE date > {LATEST} - INTERVAL 14 DAY AND sleep_score IS NOT NULL
            ORDER BY sleep_score, date LIMIT 1""",
            )
        ),
        check=_contains,
        tools={"get_sleep_trend", "query_sql"},
    ),
    Case(
        id="manual_sessions_28d",
        question="How many of my workouts in the last 4 weeks have no heart-rate data?",
        truth=lambda sql: _one(
            sql,
            f"""
            SELECT COUNT(*) FROM health_activities
            WHERE avg_hr IS NULL AND date > {LATEST} - INTERVAL 28 DAY""",
        ),
        check=_number_within(0),
        tools={"get_training_log", "query_sql"},
    ),
    Case(
        id="weekend_sleep",
        question="Do I sleep longer on weekends (Sat/Sun nights' wake dates) than on weekdays? Answer yes or no.",
        truth=lambda sql: _one(
            sql,
            """
            SELECT AVG(sleep_total_min) FILTER (WHERE dayofweek(date) IN (0, 6))
                 > AVG(sleep_total_min) FILTER (WHERE dayofweek(date) NOT IN (0, 6))
            FROM health_days""",
        ),
        check=_yes_no,
        tools={"query_sql"},
    ),
    Case(
        id="short_sleep_readiness",
        question=(
            "On average, how many points lower is my training readiness after nights under 6 hours "
            "compared with other nights? Give one number."
        ),
        truth=lambda sql: round(
            _one(
                sql,
                """
            SELECT AVG(training_readiness_score) FILTER (WHERE sleep_total_min >= 360)
                 - AVG(training_readiness_score) FILTER (WHERE sleep_total_min < 360)
            FROM health_days""",
            ),
            1,
        ),
        check=_number_within(2.0),
        tools={"query_sql"},
    ),
    Case(
        id="hrv_below_baseline_14d",
        question="On how many of the last 14 days was my overnight HRV below my personal baseline?",
        truth=lambda sql: _one(
            sql,
            f"""
            SELECT COUNT(*) FROM health_days
            WHERE date > {LATEST} - INTERVAL 14 DAY AND hrv_last_night < hrv_baseline_low""",
        ),
        check=_number_within(0),
        tools={"get_recovery_trend", "query_sql"},
    ),
    Case(
        id="staleness",
        question="How many days old is my most recent data?",
        truth=lambda sql: _one(sql, f"SELECT current_date - {LATEST}"),
        check=_number_within(0),
        tools=set(),  # every tool reports freshness
    ),
]
