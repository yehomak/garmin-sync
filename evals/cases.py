"""
Eval cases: questions a real user asks, with ground truth computed from the demo DB.

Each case has
  question  what the user types
  truth     fn(sql) -> expected value, computed with the same read-only SQL the model can run
  check     fn(answer, expected) -> bool, applied to the model's final `ANSWER:` line
            (or to the whole reply when grade_full_text is set)
  tools     at least one of these must be called (catches answering from priors)

Ground truth is queried, never hand-typed, so cases stay valid when the demo generator changes.

Trap cases have no single right number: the literal answer is wrong because the data misleads. They are
graded on whether the reply names the trap, and carry a `good` and a `naive` example reply. `--check`
asserts the grader accepts the first and rejects the second, so a too-loose grader fails before any run.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Case:
    id: str
    question: str
    truth: Callable
    check: Callable
    tools: set[str] = field(default_factory=set)
    grade_full_text: bool = False
    good: str | list[str] | None = None  # one or more replies the grader must accept
    naive: str | None = None


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


def _mentions(*patterns):
    """Pass if any pattern matches the reply (case-insensitive)."""

    def check(text, expected):
        return any(re.search(p, text, re.IGNORECASE | re.DOTALL) for p in patterns)

    return check


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
        # date.today(), not DuckDB current_date: that can be in another timezone, and the tools use date.today()
        truth=lambda sql: (date.today() - date.fromisoformat(str(_one(sql, f"SELECT {LATEST}")))).days,
        check=_number_within(0),
        tools=set(),  # every tool reports freshness
    ),
    # ── traps: the literal answer is wrong ────────────────────────────────────────
    Case(
        id="trap_unmeasured_load",
        question="What was my training load over the last 4 weeks? Is it high or low?",
        truth=lambda sql: _one(
            sql,
            f"""
            SELECT COUNT(*) FROM health_activities
            WHERE avg_hr IS NULL AND date > {LATEST} - INTERVAL 28 DAY""",
        ),
        check=_mentions(
            r"(no|without|missing|lack\w*) (heart[- ]rate|HR)",
            r"(un|not |never )(measured|recorded|tracked|counted)",
            r"(manual(ly)?[- ]logged|logged (by hand|manually))",
            r"load (is |was )?unknown",
        ),
        tools={"get_training_log", "query_sql"},
        grade_full_text=True,
        good="Garmin recorded 523, but 11 sessions were logged manually with no heart rate, so the real load is "
        "unknown and likely much higher.\nANSWER: recorded 523, but most sessions are unmeasured",
        naive="Your training load over the last 4 weeks was 523, which is on the low side.\nANSWER: 523, low",
    ),
    Case(
        id="trap_stale_last_night",
        question="How did I sleep last night?",
        truth=lambda sql: str(_one(sql, f"SELECT {LATEST}")),
        check=_mentions(
            r"\b\d+ days? (old|ago|behind|out of date|stale)",
            r"(not|hasn't|haven't|isn't) (been )?(yet )?synced",
            r"\bsync\b",
            r"(don't|do not|can't|cannot) (have|see) (data for )?last night",
            r"(no|missing) data for last night",
        ),
        grade_full_text=True,
        good="I don't have last night yet: your data ends 4 days ago. Run a sync.\nANSWER: no data for last night",
        naive="Last night you slept 7.2 hours with a sleep score of 81, which is good.\nANSWER: 7.2 h, score 81",
    ),
    Case(
        id="trap_correlation_by_construction",
        question="Does better sleep improve my training readiness? Answer yes or no and explain.",
        truth=lambda sql: round(_one(sql, "SELECT corr(sleep_score, training_readiness_score) FROM health_days"), 2),
        check=_mentions(
            r"readiness[^.]{0,120}(computed|calculated|derived|built|based|uses|includes|factors?|input|formula)"
            r"[^.]{0,80}sleep",
            r"sleep[^.]{0,80}(is |as )?(an |one )?(input|component|factor|ingredient)s?[^.]{0,40}(of|to|in)"
            r"[^.]{0,40}readiness",
            r"(calculat|comput|deriv|build|bas)\w* (the )?readiness[^.]{0,80}(from|on|using|with)[^.]{0,40}sleep",
            r"by construction|by design|by definition|circular|built[- ]in|how the score is defined",
        ),
        grade_full_text=True,
        good=[
            "They move together, but readiness is partly computed from sleep, so the link is by construction "
            "and this data can't show cause and effect.\nANSWER: partly by construction",
            # Claude's actual reply in the 2026-11-15 run, which the first version of this grader wrongly failed
            "Yes. Better sleep goes with higher training readiness. Part of that link is built in, though. "
            "Garmin calculates readiness partly from your sleep and overnight HRV.\nANSWER: yes, partly by design",
        ],
        naive="Yes. There is a strong correlation of 0.6 between sleep score and readiness, so better sleep "
        "clearly boosts your readiness.\nANSWER: yes",
    ),
]
