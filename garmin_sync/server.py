"""
MCP server over garmin.duckdb. Read-only: nothing here can write to the DB or call Garmin.

  python -m garmin_sync.server          # stdio transport, for Claude Code / Claude Desktop

Tool docstrings are the model's documentation. Keep them about *when* to use a
tool and what its output means, not how it is implemented.
"""

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from garmin_sync import tools

INSTRUCTIONS = """\
Personal Garmin health data (sleep, HRV, resting HR, Body Battery, stress, training readiness, workouts),
synced daily into a local DuckDB database.

How to work with it:
- Check `data_through` / `warning` in responses. Windows end at the latest synced date, not today.
- Start with get_snapshot for "how am I today", the *_trend tools for patterns, compare_periods for
  "this week vs last", and query_sql for anything else. Call describe_schema before writing SQL.
- Read the `notes` field. Manually logged workouts have no heart rate, so their load is unknown,
  not zero. Garmin's hrv_status lags; hrv_band compares last night to the personal baseline.
- Garmin's readiness score is computed from sleep and HRV, so do not present their correlation as a discovery.
- Health data is personal: answer the question asked and do not speculate about medical conditions.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

mcp = MCPServer("garmin", instructions=INSTRUCTIONS)


@mcp.tool(annotations=READ_ONLY)
def describe_schema() -> dict:
    """Tables, columns, units, caveats, and how often each column is actually filled (last 60 days).
    Call before writing SQL, or when unsure what a metric means."""
    return tools.describe_schema()


@mcp.tool(annotations=READ_ONLY)
def get_snapshot() -> dict:
    """The latest synced day: sleep, HRV vs baseline, resting HR, Body Battery, stress, readiness.
    Use for "how am I doing today" or "should I train hard today"."""
    return tools.get_snapshot()


@mcp.tool(annotations=READ_ONLY)
def get_sleep_trend(days: int = 14, end_date: str | None = None) -> dict:
    """Nightly sleep score, duration and stages over `days` nights ending at end_date (YYYY-MM-DD,
    default latest synced day). Includes averages and nights under 6 hours."""
    return tools.get_sleep_trend(days, end_date)


@mcp.tool(annotations=READ_ONLY)
def get_recovery_trend(days: int = 14, end_date: str | None = None) -> dict:
    """Daily readiness, HRV (with hrv_band vs personal baseline), resting HR, Body Battery and stress
    over `days` days ending at end_date. Use for fatigue, recovery and overreaching questions."""
    return tools.get_recovery_trend(days, end_date)


@mcp.tool(annotations=READ_ONLY)
def get_training_log(days: int = 28, end_date: str | None = None) -> dict:
    """Workouts over `days` days ending at end_date: type, duration, HR, load, training effect, HR zones,
    plus totals per activity type. Notes flag sessions without heart rate."""
    return tools.get_training_log(days, end_date)


@mcp.tool(annotations=READ_ONLY)
def get_day(day: str) -> dict:
    """Every metric for one date (YYYY-MM-DD) plus that day's workouts.
    Use to explain a specific good or bad day."""
    return tools.get_day(day)


@mcp.tool(annotations=READ_ONLY)
def compare_periods(a_from: str, a_to: str, b_from: str, b_to: str) -> dict:
    """Average sleep, HRV, RHR, readiness, Body Battery, stress, steps and session count for period A
    vs period B (dates YYYY-MM-DD, inclusive), with B minus A deltas. Use for "this week vs last",
    "before vs after the trip", "this month vs last"."""
    return tools.compare_periods(a_from, a_to, b_from, b_to)


@mcp.tool(annotations=READ_ONLY)
def query_sql(sql: str) -> dict:
    """Run one read-only DuckDB SELECT against health_days / health_activities (max 500 rows).
    Use for questions the other tools don't answer: correlations, streaks, custom aggregations.
    Call describe_schema first for column names and units. For "last N days", anchor to
    (SELECT MAX(date) ...) or the data_through date, not current_date: syncs can lag."""
    return tools.query_sql(sql)


@mcp.tool(annotations=READ_ONLY)
def get_profile() -> dict:
    """Age, sex, height, weight, race time predictions and running PRs. Changes slowly.
    Use to put metrics in context (e.g. age-appropriate HRV) or for running goals."""
    return tools.get_profile()


@mcp.prompt()
def weekly_review() -> str:
    """Review the last 7 days against the 4 weeks before."""
    return (
        "Review my last 7 synced days. Use compare_periods (last 7 days vs the 28 before), "
        "get_sleep_trend(7) and get_training_log(7). Lead with the one thing most worth changing next week, "
        "then up to three supporting observations with numbers. Say if the data is stale or if workouts "
        "were missing heart rate."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
