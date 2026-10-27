# The database connection and three small query helpers. Owner: Malama.
# No business rules live here: lifecycle.py decides what to save, and this file only runs the SQL.
#
# Three promises to lifecycle.py and its tests (docs/TEAM.md, the db.py row):
# 1. Autocommit: every write is saved the moment it runs, so a crash right after a PayPal call can't
#    roll back an order ID or auth ID we already saved (rule 3, test F1).
# 2. The database URL is passed in, so the app connects to DATABASE_URL and tests to TEST_DATABASE_URL.
# 3. No shared connection: every caller gets its own from connect(). app.py opens one per request,
#    and each thread in test E8 opens its own.
#
# The URL contains the database password, so it is never printed or logged (docs/SECURITY.md).

import logging
import time

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# Neon's free database sleeps after 5 minutes idle and may refuse a connection while it wakes up
# (docs/SYSTEM_DESIGN.md section 2). A failed connection waits this long and tries once more (D33).
RETRY_WAIT_SECONDS = 2

# Give up on one connection attempt after this many seconds, so a page never hangs forever.
CONNECT_TIMEOUT_SECONDS = 10


# One attempt at opening a connection.
# autocommit=True saves each statement the moment it runs (promise 1).
# row_factory=dict_row makes rows come back as dicts, so code reads row["status"] instead of row[3].
def open_connection(database_url):
    return psycopg.connect(database_url, autocommit=True, row_factory=dict_row,
                           connect_timeout=CONNECT_TIMEOUT_SECONDS)


# Open a new connection to the database at database_url. If it fails, wait 2 seconds and try once
# more, because Neon may be waking up (D33). The caller closes the connection when done.
# Only the error's type ("OperationalError") is logged: its message can include the host and user name.
# The final error is raised outside the except blocks on purpose, so psycopg's original error
# (and anything it says about the URL) is not attached to it.
def connect(database_url):
    if database_url == "":
        raise RuntimeError("No database URL is set. Check DATABASE_URL or TEST_DATABASE_URL in .env.")
    try:
        return open_connection(database_url)
    except psycopg.OperationalError as error:
        logger.warning("Database connection failed (%s). Trying once more in %d seconds.",
                       type(error).__name__, RETRY_WAIT_SECONDS)
    time.sleep(RETRY_WAIT_SECONDS)
    try:
        return open_connection(database_url)
    except psycopg.OperationalError as error:
        logger.warning("Database connection failed again (%s).", type(error).__name__)
    raise RuntimeError("Could not connect to the database (tried twice).")


# Run one INSERT, UPDATE or DELETE and return how many rows it changed.
# Compare-and-set depends on this number: an UPDATE ... WHERE status = 'LAST_CALL' that changed
# 1 row won, and 0 rows means another request got there first (docs/SYSTEM_DESIGN.md section 4).
# params fills the %s placeholders in order. Never build SQL with f-strings or + (AGENTS.md section 5).
def run(conn, sql, params=()):
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.rowcount


# Run a query and return its first row as a dict, or None if there are no rows.
# Also used for INSERT ... RETURNING id, to get the new row's id back.
def fetch_one(conn, sql, params=()):
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


# Run a query and return every row as a list of dicts (an empty list if there are none).
def fetch_all(conn, sql, params=()):
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()
