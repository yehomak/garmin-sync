# garmin-sync

**Ask Claude about your Garmin data.** A daily sync from Garmin Connect into a local DuckDB file, and a
read-only MCP server that lets Claude answer questions about your sleep, recovery and training, with the
caveats Garmin doesn't tell you attached to every answer.

```
Garmin Connect ──▶ garmin-sync ──▶ garmin.duckdb ──▶ garmin-mcp ──▶ Claude Code / Claude Desktop
                  (daily, read-only)  (local file)    (read-only tools)
```

> "How did I sleep this week compared with last month?"
> "Is my readiness lower after short nights, and by how much?"
> "Which of my workouts this month did Garmin not actually measure?"

## Try it in a minute, no Garmin account needed

```bash
git clone https://github.com/Yegor-M/garmin-sync.git && cd garmin-sync
uv sync                                   # or: python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/garmin-demo                     # 120 days of synthetic data → demo.duckdb
claude mcp add garmin-demo -e GARMIN_DB="$PWD/demo.duckdb" -- "$PWD/.venv/bin/garmin-mcp"
```

Then ask Claude *"how was my training last month?"* The demo data has patterns planted in it (short nights,
a hard training block, workouts logged by hand) so there's something to find.

## Use it with your own data

```bash
cp .env.example .env          # GARMIN_EMAIL, GARMIN_PASSWORD (only used for the first login)
python3 bootstrap.py          # venv → install → login → backfill → profile. Safe to re-run.
claude mcp add -s user garmin -- "$PWD/.venv/bin/garmin-mcp"
```

Keep it fresh with a daily job. On macOS, a launchd agent is better than cron because it runs missed jobs
after sleep.

```bash
0 8 * * * cd /path/to/garmin-sync && .venv/bin/garmin-sync >> /tmp/garmin-sync.log 2>&1
```

Garmin rate-limits logins per IP. If you get a 429, wait 30–60 minutes. After the first login the session
is cached in `.garth/`, so daily syncs don't log in again.

## What the model actually gets

This is real output from `get_training_log(28)` on the demo database:

```json
{
  "data_through": "2026-03-31",
  "sessions": 18,
  "total_minutes": 1102.3,
  "recorded_training_load": 523.0,
  "by_type": {
    "mixed_martial_arts": { "sessions": 11, "minutes": 932.3, "manual_sessions": 11 },
    "running":            { "sessions": 4,  "minutes": 152.2, "manual_sessions": 0 },
    "breathwork":         { "sessions": 3,  "minutes": 17.8,  "manual_sessions": 0 }
  },
  "notes": [
    "11 of 18 sessions (932 min) have no heart rate, usually because they were logged manually. Their load is unknown, not zero, and Garmin readiness and training status do not account for them."
  ]
}
```

Garmin only measures load for the runs, so most of this training is invisible to it, and its training status
can read DETRAINING through weeks of hard sessions. An assistant reading the raw numbers repeats that with
confidence. The point of this project is everything around the numbers:

| Problem in the raw data | What the server does |
|---|---|
| The sync stops silently; "last 7 days" goes empty | Windows end at the latest synced day; every response has `data_through`, `stale_days` and a `warning` |
| Manual workouts have no HR, and their load reads as 0 | `null` stays `null`; `notes` say how many sessions and minutes are unmeasured |
| `hrv_status` is a lagging weekly label | `hrv_band` compares last night to your personal baseline |
| Today's steps and Body Battery are half a day | Flagged as partial |
| The model doesn't know units or quirks | `describe_schema` serves every column's unit, caveats and real fill rate |
| Questions the tools didn't anticipate | `query_sql`: sandboxed, read-only DuckDB SQL |

Full tool reference: [docs/MCP.md](docs/MCP.md). Every column: [docs/DATA.md](docs/DATA.md).

## How it's built

- **One source of truth for meaning.** Column units and caveats live as `COMMENT ON COLUMN` in
  [`schema.sql`](garmin_sync/schema.sql). The model reads them through `describe_schema`, and
  [docs/DATA.md](docs/DATA.md) is generated from them. A test fails if a column has no comment, and CI fails if
  the doc is stale.
- **Read-only by construction.** The server never calls Garmin. `query_sql` runs on a DuckDB connection with
  external access disabled and configuration locked, so model-written SQL can't write, read files or reach the
  network. Each of those is a test case.
- **Tested at every layer.** Pure extraction functions against synthetic fixtures; sync orchestration with a
  fake Garmin client; tools against a seeded demo database; the MCP surface through a real MCP client.
- **Evals with computed ground truth.** [`evals/`](evals/) runs Claude against the real server and grades its
  answers with SQL on the demo data, never with hand-typed numbers. `--check` validates every case for free
  and runs in CI. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- **Built with Claude Code, and set up for it.** [`CLAUDE.md`](CLAUDE.md) holds the project rules, and
  [`.claude/`](.claude/) holds shared permissions, a format-on-edit hook, slash commands for the real workflows
  (`/verify`, `/add-field`, `/add-tool`, `/audit-data`, `/commit-push-pr`), and a `privacy-reviewer` agent that
  checks diffs for personal data before they reach this public repo.

```bash
.venv/bin/python -m pytest                     # about 2 s, no network
.venv/bin/python -m evals.run --check          # validate eval cases, no API calls
ANTHROPIC_API_KEY=... .venv/bin/python -m evals.run   # full eval against Claude
```

## Commands

```bash
garmin-sync                          # yesterday + today
garmin-sync --date 2026-05-15        # one date
garmin-sync --backfill 90            # last N days
garmin-sync --backfill 200 --activities-only   # re-fetch workouts only
garmin-sync --status                 # what's in the database, no network
garmin-mcp                           # MCP server on stdio
garmin-demo                          # synthetic database
python -m garmin_sync.explore --date 2026-05-21   # dump raw API JSON to data/raw/ (for new fields)
python -m garmin_sync.physiology                  # age, weight, race predictions, PRs → data/physiology.json
```

`python sync.py` still works for existing schedulers.

## Limits

- Uses [`garminconnect`](https://github.com/cyberjunky/python-garminconnect), an unofficial wrapper around
  Garmin Connect's internal API. It can break when Garmin changes things. For personal use.
- Daily granularity from JSON endpoints. No FIT files, no second-by-second data.
- Sleep start and end are stored in UTC.

MIT licensed.
