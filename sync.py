"""Compatibility entry point: `python sync.py` is what existing schedulers call.

Prefer `python -m garmin_sync.sync`. Same flags.
"""

from garmin_sync.sync import main

if __name__ == "__main__":
    main()
