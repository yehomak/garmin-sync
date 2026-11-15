# garmin-sync

Garmin Connect → local DuckDB (`garmin_sync/sync.py`), plus a read-only MCP server over it (`garmin_sync/server.py`).
Python 3.13, `uv`, DuckDB, `garminconnect` 0.3.x (unofficial API), `mcp` 2.x (`MCPServer`, not v1 `FastMCP`).

## Verify every change

Run `/verify` (ruff, pytest, `docs --check`, `evals.run --check`). All four are offline and take seconds.
Don't say something works until they pass. For sync changes, also ask to run `garmin-sync --date <recent>` against
the real account.

## Commands

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format .
.venv/bin/python -m garmin_sync.docs          # regenerate docs/DATA.md after any schema.sql change
.venv/bin/garmin-demo                         # synthetic demo.duckdb
GARMIN_DB=demo.duckdb .venv/bin/garmin-mcp    # server against demo data
.venv/bin/python -m evals.run --check         # free; full run needs ANTHROPIC_API_KEY and costs money: ask first
.venv/bin/garmin-sync --status                # real DB summary, no network
```

## Layout

`extract.py` maps raw JSON to rows (pure) · `sync.py` orchestrates · `schema.sql` is the source of truth for columns
**and their meaning** · `tools.py` is the query layer the model sees · `server.py` is thin MCP wiring ·
`demo.py` makes synthetic data · `evals/` holds Claude-in-the-loop evals. Details: `docs/ARCHITECTURE.md`.

## Rules

- **Never send writes to Garmin.** Every Garmin call is a read. Ask before any command that hits the network
  (`sync`, `explore`, `physiology`); Garmin rate-limits by IP, with 30–60 min lockouts.
- **This repo is public; the author's real health data sits beside it.** `garmin.duckdb`, `data/`, `.env` and
  `.garth/` never go in git, and their values never go in code, fixtures, docs or commit messages. Fixtures are
  invented. Run the `privacy-reviewer` agent before committing tests, docs or examples.
- **Schema changes are additive:** column in `CREATE TABLE` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in the
  migrations block + `COMMENT ON COLUMN`, then regenerate docs. Never rename or drop a column: Personalkin, a private
  downstream consumer, reads columns by name and calls `python sync.py` (keep the root shim).
- **Missing is `None`, never `0`.** `secs_to_min(0)` is `0.0`; `secs_to_min(None)` is `None`.
- **Tools return dicts that include `**_freshness(con)`**, anchor windows to the latest synced date with
  `_window()`, and put caveats in `notes`. Tool docstrings are the model's only docs: say *when* to use the tool.
- New workflows: `/add-field` for a Garmin metric, `/add-tool` for an MCP tool, `/commit-push-pr` to ship.

## Garmin API facts (verified, not obvious)

- Use `get_activity_hr_in_timezones(id)` for HR zones (`[{zoneNumber, secsInZone}]`). `get_activity_details`
  has no zone summary; that bug left zones null for months.
- Activities logged by hand have `manualActivity: true`, no HR, no load and an empty zones list.
- `hrvWeeklyAverage` in training readiness is in 0.1 ms units.
- `training_status_phrase` carries numeric suffixes (`PRODUCTIVE_3`, `STRAINED_1`).
- `hrv_status` lags (weekly average); use `hrv_band` for a single night.
- `max_metrics`, `lactate_threshold` and `body_composition` return nothing for this account.
- `bodyBatteryMostRecentValue` for the current day is a mid-day value.

## PRs

Branch `feat/` · `fix/` · `chore/`, conventional commits, `gh pr create --fill`, template in `.github/`.
Ask before pushing.
