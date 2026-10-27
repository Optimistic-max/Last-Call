# Tests for GET /health in app.py (M0). Not docs/TEST_PLAN.md IDs.
# The first three swap db.connect for stand-ins, so they need no database. The last one uses the
# Neon test branch and is skipped until TEST_DATABASE_URL is set in .env.

import types

import psycopg

import app
import config
import db


# A stand-in connection that only remembers whether close() was called.
# SimpleNamespace makes a plain object with the attributes we give it.
def fake_connection(closed):
    def close():
        closed.append(True)
    return types.SimpleNamespace(close=close)


# Database answers: 200 and "ok", and the connection is closed afterwards.
def test_health_ok_when_database_answers(monkeypatch):
    closed = []
    monkeypatch.setattr(db, "connect", lambda url: fake_connection(closed))
    monkeypatch.setattr(db, "fetch_one", lambda conn, sql: {"?column?": 1})
    response = app.app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"
    assert closed == [True]


# Can't connect: 503 with a short message, and nothing from the error reaches the page.
def test_health_503_when_database_unreachable(monkeypatch):
    def failing_connect(url):
        raise RuntimeError("Could not connect to the database (tried twice).")
    monkeypatch.setattr(db, "connect", failing_connect)
    response = app.app.test_client().get("/health")
    assert response.status_code == 503
    assert response.get_data(as_text=True) == "database unavailable"


# Connected, but the query fails: still 503, and the connection is still closed.
# The error text contains a made-up password to prove it never reaches the page.
def test_health_503_when_query_fails_and_connection_closed(monkeypatch):
    closed = []

    def failing_query(conn, sql):
        raise psycopg.OperationalError("server closed the connection FAKE-PASSWORD-789")

    monkeypatch.setattr(db, "connect", lambda url: fake_connection(closed))
    monkeypatch.setattr(db, "fetch_one", failing_query)
    response = app.app.test_client().get("/health")
    assert response.status_code == 503
    assert "FAKE-PASSWORD" not in response.get_data(as_text=True)
    assert closed == [True]


# The real thing, against the Neon test branch: /health answers "ok".
def test_health_ok_on_the_test_database(monkeypatch, test_db_url):
    monkeypatch.setattr(config, "DATABASE_URL", test_db_url)
    response = app.app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"
