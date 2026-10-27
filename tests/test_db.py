# Tests for db.py and schema.sql. These check the three promises db.py makes to lifecycle.py
# (docs/TEAM.md) and two schema rules. They are not docs/TEST_PLAN.md IDs.
#
# The first four tests swap psycopg.connect and time.sleep for stand-ins, so they need no database.
# The rest use the Neon test branch through the fixtures in tests/conftest.py, and are skipped
# until TEST_DATABASE_URL is set in .env.

import logging
import secrets

import psycopg
import pytest

import db

# A made-up URL with a made-up password, so a test can check the password never shows up anywhere.
FAKE_URL = "postgresql://someone:FAKE-PASSWORD-789@example.invalid/neondb"


# Replace psycopg.connect with a stand-in that fails the first `failures` times, then succeeds.
# Its error message contains the URL on purpose, to prove db.py never passes that message on.
# Also replace time.sleep, so the tests don't really wait. Both lists record what happened.
def fake_psycopg(monkeypatch, failures):
    calls = []
    waits = []

    def fake_connect(url, **options):
        calls.append(options)
        if len(calls) <= failures:
            raise psycopg.OperationalError("connection failed for " + url)
        return "FAKE-CONNECTION"

    def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    monkeypatch.setattr(db.time, "sleep", fake_sleep)
    return calls, waits


# Promise 1: every connection is opened with autocommit on. No failure means no waiting.
def test_connect_turns_on_autocommit(monkeypatch):
    calls, waits = fake_psycopg(monkeypatch, failures=0)
    assert db.connect(FAKE_URL) == "FAKE-CONNECTION"
    assert calls[0]["autocommit"] is True
    assert waits == []


# D33: one failure (Neon waking up) means wait 2 seconds and try exactly once more.
def test_connect_retries_once_after_two_seconds(monkeypatch):
    calls, waits = fake_psycopg(monkeypatch, failures=1)
    assert db.connect(FAKE_URL) == "FAKE-CONNECTION"
    assert len(calls) == 2
    assert waits == [2]


# Two failures: give up after the second try, and never show the password in the error or the log.
# __context__ is where Python attaches an earlier error; it must be empty, or a traceback would
# print psycopg's message (which here contains the whole URL).
def test_connect_gives_up_without_showing_the_password(monkeypatch, caplog):
    calls, waits = fake_psycopg(monkeypatch, failures=2)
    caplog.set_level(logging.WARNING)
    with pytest.raises(RuntimeError) as caught:
        db.connect(FAKE_URL)
    assert len(calls) == 2
    assert "FAKE-PASSWORD" not in str(caught.value)
    assert caught.value.__context__ is None
    assert "FAKE-PASSWORD" not in caplog.text


# An empty URL (a missing .env line) is refused before trying to connect at all.
def test_connect_refuses_an_empty_url(monkeypatch):
    calls, waits = fake_psycopg(monkeypatch, failures=0)
    with pytest.raises(RuntimeError):
        db.connect("")
    assert calls == []


# Add one DRAFT event for a test and return its id. The admin token is random, so tests never clash.
def make_test_event(conn):
    row = db.fetch_one(conn, "INSERT INTO events (title, deposit_cents, admin_token) "
                             "VALUES (%s, %s, %s) RETURNING id",
                       ("db.py test event", 30000, secrets.token_urlsafe(24)))
    return row["id"]


# Add one pledge to an event and return its id.
def make_test_pledge(conn, event_id, name):
    row = db.fetch_one(conn, "INSERT INTO pledges (event_id, name, max_cents, pledger_token) "
                             "VALUES (%s, %s, %s, %s) RETURNING id",
                       (event_id, name, 4000, secrets.token_urlsafe(24)))
    return row["id"]


# Delete everything a test made for one event. Children go first, because a hold can't outlive
# its pledge and a pledge can't outlive its event (the REFERENCES rules in schema.sql).
def delete_test_event(conn, event_id):
    db.run(conn, "DELETE FROM holds WHERE pledge_id IN (SELECT id FROM pledges WHERE event_id = %s)",
           (event_id,))
    db.run(conn, "DELETE FROM pledge_conditions WHERE pledge_id IN "
                 "(SELECT id FROM pledges WHERE event_id = %s)", (event_id,))
    db.run(conn, "DELETE FROM pledges WHERE event_id = %s", (event_id,))
    db.run(conn, "DELETE FROM events WHERE id = %s", (event_id,))


# Promise 1, on the real database: a row written on one connection, with no commit() call,
# can be read straight away from a different connection. So it was saved the moment it ran.
def test_autocommit_write_is_seen_by_a_second_connection(test_db, test_db_url):
    event_id = make_test_event(test_db)
    other = db.connect(test_db_url)
    try:
        row = db.fetch_one(other, "SELECT title FROM events WHERE id = %s", (event_id,))
        assert row["title"] == "db.py test event"
    finally:
        other.close()
        delete_test_event(test_db, event_id)


# Promise 3 and compare-and-set: two separate connections try the same status change.
# The first changes 1 row (it wins), the second changes 0 (it must do nothing).
# They run one after the other here. Two at the very same moment is test E8 (Emmanuel's).
def test_compare_and_set_only_one_connection_wins(test_db, test_db_url):
    event_id = make_test_event(test_db)
    first = db.connect(test_db_url)
    second = db.connect(test_db_url)
    change = "UPDATE events SET status = 'OPEN' WHERE id = %s AND status = 'DRAFT'"
    try:
        assert first is not second
        assert db.run(first, change, (event_id,)) == 1
        assert db.run(second, change, (event_id,)) == 0
    finally:
        first.close()
        second.close()
        delete_test_event(test_db, event_id)


# D24 "save before you send": a hold row can be saved with only its create_request_id,
# before PayPal has returned an order ID. It starts PENDING with order_id empty (None in Python).
def test_hold_can_be_saved_before_the_order_id(test_db):
    event_id = make_test_event(test_db)
    try:
        pledge_id = make_test_pledge(test_db, event_id, "Ana")
        hold = db.fetch_one(test_db, "INSERT INTO holds (pledge_id, create_request_id, amount_cents) "
                                     "VALUES (%s, %s, %s) RETURNING order_id, status",
                            (pledge_id, secrets.token_urlsafe(16), 4000))
        assert hold["order_id"] is None
        assert hold["status"] == "PENDING"
    finally:
        delete_test_event(test_db, event_id)


# The unique name index: "Ana" and "ana" can't both pledge to one event, so "only if Ana's in"
# always means one person. (Trimming spaces is done by code before saving, not by the index.)
def test_names_are_unique_per_event_ignoring_case(test_db):
    event_id = make_test_event(test_db)
    try:
        make_test_pledge(test_db, event_id, "Ana")
        with pytest.raises(psycopg.errors.UniqueViolation):
            make_test_pledge(test_db, event_id, "ana")
    finally:
        delete_test_event(test_db, event_id)
