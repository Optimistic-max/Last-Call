# Real PostgreSQL guards for the approved Stage 2B operation evidence.
import psycopg
import pytest

import db
from tests.test_refund_lifecycle import refund_case, refund_rows
from tests.test_refund_safety import saved_refund


def test_legacy_original_send_time_is_unknown(refund_case):
    _, row = saved_refund(refund_case, "ANSWERED", "FAILED")
    current = db.fetch_one(refund_case["conn"], "SELECT operation_revision, first_send_started_at "
                                             "FROM refunds WHERE id = %s", (row["id"],))
    assert current == {"operation_revision": 0, "first_send_started_at": None}


def test_original_send_time_is_immutable(refund_case):
    _, row = saved_refund(refund_case, "READY")
    conn = refund_case["conn"]
    db.run(conn, "UPDATE refunds SET send_started_at = NULL WHERE id = %s", (row["id"],))
    db.run(conn, "UPDATE refunds SET send_state = 'IN_FLIGHT', operation_revision = 1, "
                 "first_send_started_at = now(), send_started_at = now() WHERE id = %s", (row["id"],))
    before = refund_rows(conn, refund_case["event_id"])[0]
    for expression in ("NULL", "first_send_started_at + interval '1 second'"):
        sql = {"NULL": "UPDATE refunds SET first_send_started_at = NULL WHERE id = %s",
               "first_send_started_at + interval '1 second'":
                   "UPDATE refunds SET first_send_started_at = first_send_started_at + interval '1 second' WHERE id = %s"}[expression]
        with pytest.raises(psycopg.errors.CheckViolation):
            db.run(conn, sql, (row["id"],))
    assert refund_rows(conn, refund_case["event_id"])[0] == before


def test_check_only_cannot_become_a_post(refund_case):
    _, row = saved_refund(refund_case, "UNCERTAIN")
    conn = refund_case["conn"]
    db.run(conn, "UPDATE refunds SET send_state = 'CHECK_ONLY', operation_revision = 1 WHERE id = %s", (row["id"],))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(conn, "UPDATE refunds SET send_state = 'IN_FLIGHT', operation_revision = 2 WHERE id = %s", (row["id"],))


def test_revision_cannot_decrease_or_be_negative(refund_case):
    _, row = saved_refund(refund_case, "ANSWERED")
    conn = refund_case["conn"]
    db.run(conn, "UPDATE refunds SET operation_revision = 3 WHERE id = %s", (row["id"],))
    for revision in (2, -1):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.run(conn, "UPDATE refunds SET operation_revision = %s WHERE id = %s", (revision, row["id"]))


def test_completed_refund_cannot_regress_in_database(refund_case):
    _, row = saved_refund(refund_case, "ANSWERED", "COMPLETED")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(refund_case["conn"], "UPDATE refunds SET status = 'FAILED', operation_revision = 1 WHERE id = %s",
               (row["id"],))


def test_historical_original_send_time_cannot_be_invented(refund_case):
    _, row = saved_refund(refund_case, "ANSWERED", "FAILED")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(refund_case["conn"], "UPDATE refunds SET first_send_started_at = now(), "
                                   "operation_revision = 1 WHERE id = %s", (row["id"],))
