# Architecture

```
                    read-only                     upsert                    read-only, sandboxed
Garmin Connect ──────────────▶ garmin_sync.sync ──────────▶ garmin.duckdb ◀──────────────────── garmin_sync.server ──▶ Claude
 (unofficial API)              extract.py (pure)            schema.sql                          tools.py (query layer)
                                                            + column comments ─────────────────▶ describe_schema
                                                                    │
                                                                    └──▶ docs/DATA.md (generated)
```

## Modules

| Module | Responsibility | Talks to |
|---|---|---|
| `config.py` | Every path and env var (`GARMIN_DB`, `.env`, `.garth/`) | filesystem |
| `auth.py` | Login with a cached session, fail fast on 429 / CAPTCHA | Garmin SSO |
| `extract.py` | Raw JSON → row dict. Pure functions, no I/O | nothing |
| `db.py` | Schema init + migrations, upsert | DuckDB |
| `sync.py` | Orchestration: which endpoints, retries, error collection | Garmin, `db` |
| `tools.py` | The query layer the model sees | DuckDB (read-only) |
| `server.py` | MCP wiring: tool docstrings, annotations, instructions | `tools` |
| `demo.py` | Synthetic database with planted patterns | `db` |
| `docs.py` | Generates `docs/DATA.md` from schema comments | `db` |
| `explore.py`, `physiology.py` | Raw dumps for new endpoints; slow-changing profile JSON | Garmin |

## Invariants

These are enforced by tests, not by convention:

1. **Every column is documented.** `schema.sql` has a `COMMENT ON COLUMN` for each one
   (`test_every_column_is_documented`). The same text reaches the model through `describe_schema` and
   humans through `docs/DATA.md`, which CI regenerates and diffs (`test_data_dictionary_matches_schema`).
2. **Schema changes are additive and in place.** New columns get an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
   in the migrations section, so existing databases upgrade on the next sync
   (`test_schema_is_reapplied_safely_and_migrates_old_dbs`).
3. **One failed endpoint never loses a day.** `fetch_day` collects errors and keeps going. A row with only
   a date doesn't overwrite existing data (`test_upsert_key_only_row_does_not_crash_or_erase`).
4. **The model can't change anything.** Every tool is read-only; `query_sql` runs on a locked, offline
   connection (`test_query_sql_refuses_writes_and_file_access`).
5. **No personal data in git.** Fixtures and the demo database are synthetic. `data/`, `*.duckdb`,
   `.env`, `.garth/` and `evals/results/` are ignored, and the `privacy-reviewer` agent checks diffs.

## Testing layers

| Layer | What it proves | Cost | Where |
|---|---|---|---|
| Unit | Extraction matches Garmin's response shapes | free | `tests/test_extract.py` |
| Integration | Sync orchestration, upserts, migrations (fake Garmin client) | free | `tests/test_sync.py` |
| Tool | Query layer behaviour on known data (demo DB) | free | `tests/test_tools.py` |
| Protocol | The MCP surface through a real MCP client | free | `tests/test_server.py` |
| Eval | Claude picks the right tools and gets the right answer | API tokens | `evals/` |

The eval cases compute ground truth with SQL on the demo database, so they never hold hand-typed numbers.
`python -m evals.run --check` validates every case, and the conversion of MCP tools to API tool definitions,
without calling the API. CI runs it.

## Decisions

- **Daily JSON endpoints, not FIT files.** Daily granularity answers the questions people actually ask
  ("how did I sleep this week?") at a fraction of the complexity. FIT parsing is out of scope.
- **DuckDB.** A single file, fast analytical SQL, and read-only connections with sandboxing. The model gets
  real SQL instead of a bespoke query language.
- **Curated tools plus raw SQL.** Curated tools encode judgment (anchoring, caveats, derived bands).
  `query_sql` covers the long tail. A new tool has to beat "describe_schema + query_sql" to earn its place.
- **Sync stays out of the server.** The MCP server never calls Garmin. Syncing is a scheduled job; reading is
  instant and safe to grant to a model.
