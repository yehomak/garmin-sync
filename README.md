# garmin-sync

Ask Claude about your Garmin data. A daily sync copies Garmin Connect into a local DuckDB file, and a
read-only MCP server lets Claude answer questions about your sleep, recovery and training.

```bash
git clone https://github.com/Yegor-M/garmin-sync.git && cd garmin-sync
uv sync && .venv/bin/garmin-demo        # synthetic data, no Garmin account needed
claude mcp add garmin-demo -e GARMIN_DB="$PWD/demo.duckdb" -- "$PWD/.venv/bin/garmin-mcp"
claude "how was my training over the last month?"
```

## Why

Giving a model raw health data produces confident, wrong answers. The sync stops and an empty week reads
as a bad week. Workouts logged by hand have no heart rate, so their load sums to zero. Garmin's own labels
lag the numbers underneath them. All of these happened while building this. Each one is now fixed in the
tools rather than left to the prompt. The full write-up: **[docs/LESSONS.md](docs/LESSONS.md)**.

## Principles

Each principle is enforced by code and checked by a test, not by convention.

1. **Say how fresh the data is.** Windows end at the latest synced day, and every database tool returns
   `data_through`, `stale_days` and a warning.
   [`_freshness`](garmin_sync/tools.py) · `test_stale_data_is_flagged`
2. **Unknown is not zero.** Missing stays `null`, and tools say in words what they couldn't count.
   [`get_training_log`](garmin_sync/tools.py) · `test_training_log_flags_manual_sessions_as_unknown_load`
3. **Caveats travel with the data.** They go in each response's `notes`, where the model can't miss them,
   not in a system prompt it may or may not apply.
4. **One source of truth for meaning.** Units and caveats are `COMMENT ON COLUMN` in
   [`schema.sql`](garmin_sync/schema.sql). The model reads them through `describe_schema`, and
   [docs/DATA.md](docs/DATA.md) is generated from them. · `test_every_column_is_documented`,
   `test_data_dictionary_matches_schema`
5. **Read-only by construction.** The server never calls Garmin. `query_sql` runs on a locked, offline,
   read-only connection. · `test_query_sql_refuses_writes_and_file_access`
6. **Measure with evals.** Claude answers real questions through the real server, graded against
   SQL-computed ground truth. · [`evals/`](evals/)

## What the model sees

Real output of `get_training_log(28)` on the demo database:

```json
{
  "data_through": "2026-03-31",
  "sessions": 18,
  "recorded_training_load": 523.0,
  "by_type": {
    "mixed_martial_arts": { "sessions": 11, "minutes": 932.3, "manual_sessions": 11 },
    "running":            { "sessions": 4,  "minutes": 152.2, "manual_sessions": 0 }
  },
  "notes": [
    "11 of 18 sessions (932 min) have no heart rate, usually because they were logged manually. Their load is unknown, not zero, and Garmin readiness and training status do not account for them."
  ]
}
```

Nine tools: `get_snapshot`, `get_sleep_trend`, `get_recovery_trend`, `get_training_log`, `get_day`,
`compare_periods`, `query_sql`, `describe_schema` and `get_profile`, plus a `weekly_review` prompt.
Reference: [docs/MCP.md](docs/MCP.md).

## Use your own data

```bash
cp .env.example .env       # Garmin email + password, used only for the first login
python3 bootstrap.py       # venv, install, login, backfill, profile. Safe to re-run.
claude mcp add -s user garmin -- "$PWD/.venv/bin/garmin-mcp"
```

Schedule `garmin-sync` daily: a launchd agent on macOS, cron elsewhere (`garmin-sync --help` for the
options). After the first login the session is
cached in `.garth/`. Garmin rate-limits logins per IP; on a 429, wait 30–60 minutes.

Your data stays on your machine. Claude sees only what the tools return in a conversation.

## Working on this repo with Claude Code

The repo is set up so Claude Code can make changes and prove they work.

| File | What it does |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Project rules and the non-obvious Garmin API facts. When Claude gets something wrong here, the fix includes a line in this file. |
| [`/verify`](.claude/commands/verify.md) | The verification loop: ruff, pytest, docs drift, eval validity. Offline, seconds. Nothing counts as done until it passes. |
| [`/add-field`](.claude/commands/add-field.md), [`/add-tool`](.claude/commands/add-tool.md) | The two common changes, as step-by-step workflows that keep the schema, docs, tests and evals in sync. |
| [`/audit-data`](.claude/commands/audit-data.md) | Fill-rate audit on real data. It catches what tests can't (see lesson 2). |
| [`/commit-push-pr`](.claude/commands/commit-push-pr.md) | Verify → privacy review → commit → PR. Asks before pushing. |
| [`privacy-reviewer`](.claude/agents/privacy-reviewer.md) | Subagent that checks diffs for personal data. The author's real data lives next to this public repo. |
| [`settings.json`](.claude/settings.json) | Shared permissions: local checks run without prompts, anything that hits Garmin or costs money asks first, and `.env` and `.garth/` can't be read. A hook formats every edited Python file. |

A typical change: describe it, let Claude plan, review the plan, let it edit, run `/verify`, then
`/commit-push-pr`.

## Tests and evals

```bash
.venv/bin/python -m pytest              # unit, sync, tools, MCP protocol, eval loop. ~2 s, no network
.venv/bin/python -m evals.run --check   # validates every eval case and its grader, no API calls (runs in CI)
.venv/bin/python -m evals.run --backend claude-code   # Claude against the real server, on your Claude login
.venv/bin/python -m evals.run           # same, over the Messages API. Needs ANTHROPIC_API_KEY.
```

**Latest eval: 10/10** (Claude Opus 5.5 via Claude Code, one run): 7 lookups and 3 traps where the literal
answer is wrong. Raw score 9/10; the miss was a grader bug, not the model. Details:
[docs/LESSONS.md](docs/LESSONS.md#second-run-trap-questions).

How it fits together: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Limits

- Built on [`garminconnect`](https://github.com/cyberjunky/python-garminconnect), an unofficial wrapper
  around Garmin Connect's internal API. It can break when Garmin changes things. Personal use only.
- Daily granularity. No FIT files.
- Sleep times are stored in UTC.

MIT
