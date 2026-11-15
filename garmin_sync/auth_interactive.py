"""
First-time authentication via garth directly.

Use this instead of garmin_sync.auth when the scripted login hits CAPTCHA or
MFA issues. It does a single clean attempt — no strategy cycling, no retries.

  python -m garmin_sync.auth_interactive

After success, .garth/ is saved and every other command reuses the session.
"""

import os
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning, module="garth")

import garth.http  # noqa: E402

from garmin_sync.config import TOKENSTORE  # noqa: E402


def main():
    email = os.environ["GARMIN_EMAIL"]
    password = os.environ["GARMIN_PASSWORD"]

    client = garth.http.Client()
    print("Attempting login via garth...")
    client.login(email, password, prompt_mfa=lambda: input("MFA code: "))

    TOKENSTORE.mkdir(exist_ok=True)
    client.dump(str(TOKENSTORE))
    print(f"Session saved to {TOKENSTORE}")
    print(f"Logged in as: {client.username}")


if __name__ == "__main__":
    main()
