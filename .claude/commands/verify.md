---
description: Run the full local verification loop and report what failed
---
Run these in order and stop at the first failure, then fix it and re-run from the top:

1. `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
2. `.venv/bin/python -m pytest`
3. `.venv/bin/python -m garmin_sync.docs --check` (if stale, regenerate with `python -m garmin_sync.docs` and include it in the change)
4. `.venv/bin/python -m evals.run --check`

Report each step as pass/fail in one line. Do not claim a change works unless all four pass.
