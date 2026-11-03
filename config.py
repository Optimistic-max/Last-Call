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
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "")

# The AI that reads one friend's pledge: any chat API that follows OpenAI's format (D75: Azure OpenAI or Groq).
# The provider is a setting, not code. If AI_BASE_URL is missing or empty (".env.example" leaves it empty),
# Groq's address is used (D15), so nothing breaks. "or" is needed because an empty line in .env gives "", not None.
# Groq's address read in docs: https://console.groq.com/docs/api-reference (Nov 1). Added by Malama for ai_parser.py.
AI_BASE_URL = os.environ.get("AI_BASE_URL") or "https://api.groq.com/openai/v1"

# Reading one pledge gives up after this many seconds, and the friend sees "please retype"
# (docs/AI_PARSER.md section 4). They can always fill in the confirm step by hand. 8 seconds (D73), so
# the confirm step never hangs for long.
AI_TIMEOUT_SECONDS = 8

# The longest pledge text POST /api/pledges/parse accepts, counted after trimming spaces (D73). Short
# text keeps each AI call small and quick. Longer text is refused before the AI is called.
MAX_PLEDGE_TEXT_CHARS = 280

# What a friend may save with a pledge (D77). At most this many condition names ("only if Jay's in"),
# each at most this many characters. The same character limit applies to the pledger's own name, so
# nobody can pledge under a name that no condition could ever write. The server checks both, because a
# friend can type conditions by hand and not only through the AI.
MAX_CONDITIONS = 3
MAX_NAME_CHARS = 40

# The only PayPal address this app may ever talk to (AGENTS.md rule 12).
SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"

# Every PayPal request gives up after this many seconds. A timeout means "result unknown"
# (docs/PAYPAL_INTEGRATION.md section 5). 10 seconds, so a lock with a few slow calls still finishes
# inside gunicorn's 120-second worker timeout (D71).
PAYPAL_TIMEOUT_SECONDS = 10

# PayPal's access token says how long it lasts. We treat it as expired this many seconds early,
# so a token never runs out in the middle of a call.
TOKEN_REFRESH_MARGIN_SECONDS = 60

# PayPal's sandbox fee on each capture: 2.59% + $0.49 (docs/MONEY_RULES.md section 1).
# 1 basis point is 0.01%, so 259 basis points is 2.59%. Whole numbers, so no float ever touches money.
FEE_PERCENT_BASIS_POINTS = 259
FEE_FIXED_CENTS = 49

MIN_SHARE_CENTS = 500   # nobody is charged less than $5
MIN_MAX_CENTS = 500     # nobody can pledge a max under $5
MAX_MAX_CENTS = 200000  # nobody can pledge a max over $2,000 (D58)

# The deposit limits (D58, D61). Test C3 proved the club is never short only for deposits from $20
# to $2,000, so the app accepts nothing outside that range.
MIN_DEPOSIT_CENTS = 2000     # no event can have a deposit under $20
MAX_DEPOSIT_CENTS = 200000   # no event can have a deposit over $2,000

# How long pledging stays open after the treasurer opens the event (D04).
# Demo mode uses minutes, so a whole event can be tested in one sitting.
PLEDGING_WINDOW = timedelta(hours=48)
DEMO_PLEDGING_WINDOW = timedelta(minutes=10)

# How long last call lasts once the goal is reached, but never past the hard deadline (D04).
# lifecycle.last_call_window picks one. (In M1, last call ran until the hard deadline instead, D25.)
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
