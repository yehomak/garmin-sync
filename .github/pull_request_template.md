## What
<!-- One sentence. -->

## Why
<!-- The gap, bug or question this answers. -->

## Schema changes
<!-- New columns need a CREATE TABLE entry, an ALTER TABLE ... ADD COLUMN IF NOT EXISTS migration and a COMMENT ON COLUMN. -->
None

## Testing
- [ ] `/verify` passes (ruff, pytest, docs --check, evals --check)
- [ ] For sync changes: `python -m garmin_sync.sync --date <recent date>` runs cleanly against a real account
- [ ] For tool changes: an eval case covers the new behaviour
- [ ] No personal data in fixtures, docs or examples (privacy-reviewer: CLEAN)
