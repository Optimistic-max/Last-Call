# Shared test setup. pytest loads this file by itself before running any test in tests/.
# Any test that names test_db_url or test_db as an argument gets the matching fixture below.

import pytest

import config
import db


# The Neon test branch's URL, after two safety checks. Tests empty tables, so they must never touch
# the dev or main branch (docs/TEAM.md, the db.py row).
# A missing TEST_DATABASE_URL skips the test instead of failing it, so pytest still runs on a laptop
# with no .env. The URLs themselves are never printed, only compared.
@pytest.fixture
def test_db_url():
    if config.TEST_DATABASE_URL == "":
        pytest.skip("TEST_DATABASE_URL is not set in .env, so this database test is skipped")
    if config.TEST_DATABASE_URL == config.DATABASE_URL:
        pytest.fail("TEST_DATABASE_URL is the same as DATABASE_URL. Tests must use the Neon test branch.")
    return config.TEST_DATABASE_URL


# One connection to the test branch for one test, closed afterwards.
# Code before "yield" runs before the test, and code after it runs when the test is over.
@pytest.fixture
def test_db(test_db_url):
    conn = db.connect(test_db_url)
    yield conn
    conn.close()
