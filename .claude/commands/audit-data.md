---
description: Report which synced columns are actually filled and used
---
Against the real database (read-only), call `garmin_sync.tools.describe_schema()` and list:

- columns under 50% filled in the last 60 days, with the likely reason (sensor not on this watch,
  manual activities, account setting)
- columns that are 100% constant (zero information)
- whether `stale_days` is above 1, and if so say the scheduler is probably not running

One table, then at most three recommendations. Do not print individual health values.
