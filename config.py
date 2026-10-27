# Every setting and every number the app uses, in one place (AGENTS.md section 7).
# Secrets come only from environment variables: the .env file on your laptop, Render's settings in production.
# Nothing in this file prints a secret.

import os
import pathlib
from datetime import timedelta

from dotenv import load_dotenv

# Read the repo's .env file into the environment, if there is one. On Render there is no .env file,
# and load_dotenv never replaces a variable that is already set, so Render's settings win there.
REPO_ROOT = pathlib.Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")

# Settings from the environment. A missing value becomes "" instead of crashing here, so files that only
# need the numbers below (like Malama's money.py tests) still work on a laptop with no .env file.
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
PAYPAL_BASE_URL = os.environ.get("PAYPAL_BASE_URL", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "")

# The only PayPal address this app may ever talk to (AGENTS.md rule 12).
SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"

# Every PayPal request gives up after this many seconds. A timeout means "result unknown"
# (docs/PAYPAL_INTEGRATION.md section 5).
PAYPAL_TIMEOUT_SECONDS = 20

# PayPal's sandbox fee on each capture: 2.59% + $0.49 (docs/MONEY_RULES.md section 1).
# 1 basis point is 0.01%, so 259 basis points is 2.59%. Whole numbers, so no float ever touches money.
FEE_PERCENT_BASIS_POINTS = 259
FEE_FIXED_CENTS = 49

MIN_SHARE_CENTS = 500   # nobody is charged less than $5
MIN_MAX_CENTS = 500     # nobody can pledge a max under $5

# How long pledging stays open after the treasurer opens the event (D04).
# Demo mode uses minutes, so a whole event can be tested in one sitting.
PLEDGING_WINDOW = timedelta(hours=48)
DEMO_PLEDGING_WINDOW = timedelta(minutes=10)

# How long last call lasts once the goal is reached. Used from M2: in M1, last call runs until the
# hard deadline instead (D25).
LAST_CALL_WINDOW = timedelta(hours=1)
DEMO_LAST_CALL_WINDOW = timedelta(minutes=3)

# A lock still in LOCKING or CHARGING this long after lock_started_at counts as stuck, and the next
# request resumes it (D27, built in M2).
STUCK_LOCK_AFTER = timedelta(minutes=5)


# Stop the app unless PayPal's address is exactly the sandbox (AGENTS.md rule 12, test E10).
# It must be an exact match: a live URL, an empty value, a typo or a lookalike such as
# "https://api-m.sandbox.paypal.com.example.com" all stop the app.
# The message doesn't repeat the wrong value, in case a secret was pasted into the wrong line of .env.
def check_sandbox_url(base_url):
    if base_url != SANDBOX_BASE_URL:
        raise RuntimeError("PAYPAL_BASE_URL must be exactly " + SANDBOX_BASE_URL + ". Refusing to start.")
