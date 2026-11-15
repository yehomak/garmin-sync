# MCP server

`garmin-mcp` serves `garmin.duckdb` to any MCP client over stdio. Every tool is annotated
`readOnlyHint: true`: the server opens the database read-only and never talks to Garmin.

## Connect

**Claude Code**

```bash
claude mcp add -s user garmin -- "$PWD/.venv/bin/garmin-mcp"
# or against the synthetic demo database
claude mcp add -s user garmin-demo -e GARMIN_DB="$PWD/demo.duckdb" -- "$PWD/.venv/bin/garmin-mcp"
```

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "garmin": {
      "command": "/absolute/path/to/garmin-sync/.venv/bin/garmin-mcp",
      "env": { "GARMIN_DB": "/absolute/path/to/garmin-sync/garmin.duckdb" }
    }
  }
}
```

`GARMIN_DB` is optional; it defaults to `garmin.duckdb` in the repo root.

## Tools

| Tool | Use it for | Notable output |
|---|---|---|
| `get_snapshot` | "How am I today?", "Should I train hard?" | Latest day, `hrv_band`, partial-day note |
| `get_sleep_trend(days, end_date)` | Sleep quality and duration patterns | Averages, `nights_under_6h` |
| `get_recovery_trend(days, end_date)` | Fatigue, recovery, overreaching | Readiness, HRV vs baseline, RHR, Body Battery, stress |
| `get_training_log(days, end_date)` | Training volume and intensity | Per-type totals, HR zones, `manual_sessions` |
| `get_day(day)` | Explaining one specific day | Every metric plus that day's workouts |
| `compare_periods(a_from, a_to, b_from, b_to)` | "This week vs last", "before vs after the trip" | Averages for both periods and B − A deltas |
| `query_sql(sql)` | Everything else: correlations, streaks, custom cuts | Up to 500 rows |
| `describe_schema` | Before writing SQL, or "what does this metric mean?" | Column units, caveats, live fill rates |
| `get_profile` | Age, weight, race predictions, PRs | Staleness warning past 45 days |

There is also one prompt, `weekly_review`, which asks for the single most useful change for next week with
supporting numbers.

## What every response carries

```jsonc
{
  "data_through": "2026-03-31",   // latest date with watch data, not the latest row
  "stale_days": 4,
  "warning": "Data is 4 days old. Run a sync before drawing conclusions about recent days.",
  "notes": ["11 of 18 sessions (932 min) have no heart rate, usually because they were logged manually. ..."],
  ...
}
```

These fields exist because of problems found in real use:

- **Windows end at the latest synced day, not today.** When the scheduler silently stops,
  "last 7 days" relative to today returns mostly empty windows with no hint why. Anchored windows always
  hold data, and `stale_days` says how old it is.
- **Caveats travel with the data.** Manually logged workouts (common for contact sports, where the watch
  comes off) carry no heart rate, so Garmin's load, readiness and training status don't see them. The tool
  says so in `notes`, so the model doesn't have to know Garmin's quirks to answer correctly.
- **`hrv_band` instead of trusting `hrv_status`.** Garmin's label is built from the weekly average and lags.
  In real data it read `LOW` on nights that were inside the personal baseline.
- **Missing is `null`, never `0`.** A manual session's load is unknown. Summing it as zero turned a month
  of hard sessions into "training load: 0".

## `query_sql` safety

The connection is opened with `read_only=True`, `enable_external_access=false` and `lock_configuration=true`.
Model-written SQL cannot write to the database, read or write files (`read_csv`, `COPY`), install
extensions, attach other databases, or turn those settings back on. Only one `SELECT`/`WITH`/`DESCRIBE`/`SUMMARIZE`
statement runs per call. `tests/test_tools.py::test_query_sql_refuses_writes_and_file_access` covers each case.
