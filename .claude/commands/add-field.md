---
description: Add a new Garmin metric end to end (explore → extract → schema → docs → test)
argument-hint: <what to add, e.g. "sleep need from the sleep endpoint">
---
Add $ARGUMENTS to the sync. Follow this order; each step has a reason.

1. **See the real shape.** Ask before running `python -m garmin_sync.explore --date <recent date>`; it calls Garmin.
   Read the relevant file in `data/raw/`. That output is the user's personal data: never paste values from it
   into code, tests or commit messages.
2. **Fixture first.** Add or extend a *synthetic* fixture in `tests/fixtures/` that mirrors the key path, with
   invented values. Write the failing test in `tests/test_extract.py`.
3. **Extract.** Map it in the right function in `garmin_sync/extract.py`. Missing stays `None`, never `0`.
4. **Schema.** In `garmin_sync/schema.sql` add the column to the `CREATE TABLE` *and* an
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` line in the migrations section (existing databases upgrade in place),
   plus a `COMMENT ON COLUMN` with unit and caveats. `test_every_column_is_documented` fails without it.
5. **Docs.** `python -m garmin_sync.docs`.
6. **Expose it** if the model should see it outside `query_sql`: add it to the relevant query in `garmin_sync/tools.py`.
7. Run `/verify`.
