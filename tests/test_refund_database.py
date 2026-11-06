# PostgreSQL behavior tests. No schema setup or migration runs here; a human must approve and
# migrate an isolated/reserved test target first. TEST_DATABASE_URL='' safely skips these tests.
import uuid

import psycopg
import pytest

import db


# Register cleanup immediately after creating our event, even if child-record setup then fails.
# Only this event's records are deleted. No real PayPal IDs or payment calls are used.
@pytest.fixture
def refund_capture_row(test_db, request):
    event = db.fetch_one(test_db, "INSERT INTO events (title, deposit_cents, admin_token) "
                                 "VALUES (%s, %s, %s) RETURNING id",
                         ("synthetic F7 stage 1 test", 2000, uuid.uuid4().hex))
    request.addfinalizer(lambda: delete_refund_event(test_db, event["id"]))
    pledge = db.fetch_one(test_db, "INSERT INTO pledges (event_id, name, max_cents, pledger_token) "
                                  "VALUES (%s, %s, %s, %s) RETURNING id",
                          (event["id"], "Synthetic pledger", 500, uuid.uuid4().hex))
    hold = db.fetch_one(test_db, "INSERT INTO holds (pledge_id, create_request_id, amount_cents) "
                                "VALUES (%s, %s, %s) RETURNING id",
                        (pledge["id"], uuid.uuid4().hex, 500))
    return db.fetch_one(test_db, "INSERT INTO captures "
                                "(hold_id, request_id, amount_cents, capture_id, status) "
                                "VALUES (%s, %s, %s, %s, 'COMPLETED') RETURNING *",
                        (hold["id"], uuid.uuid4().hex, 500, "FAKE" + uuid.uuid4().hex))


# Children go first. The event ID is ours, so committed records from other runs are untouched.
def delete_refund_event(conn, event_id):
    with conn.transaction():
        db.run(conn, "DELETE FROM refunds WHERE capture_id IN (SELECT captures.id FROM captures "
                     "JOIN holds ON holds.id = captures.hold_id JOIN pledges ON pledges.id = holds.pledge_id "
                     "WHERE pledges.event_id = %s)", (event_id,))
        db.run(conn, "DELETE FROM captures WHERE hold_id IN (SELECT holds.id FROM holds JOIN pledges "
                     "ON pledges.id = holds.pledge_id WHERE pledges.event_id = %s)", (event_id,))
        db.run(conn, "DELETE FROM holds WHERE pledge_id IN (SELECT id FROM pledges WHERE event_id = %s)",
               (event_id,))
        db.run(conn, "DELETE FROM pledges WHERE event_id = %s", (event_id,))
        db.run(conn, "DELETE FROM events WHERE id = %s", (event_id,))


# Each call represents planning a refund, not sending one.
def insert_refund(conn, capture, amount_cents=500):
    return db.fetch_one(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents) "
                             "VALUES (%s, %s, %s) RETURNING *",
                        (capture["id"], uuid.uuid4().hex, amount_cents))


# A different request ID must not create another logical refund for the same capture.
def test_f7_one_logical_refund_per_capture(test_db, refund_capture_row):
    insert_refund(test_db, refund_capture_row)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_refund(test_db, refund_capture_row)


# Exercise real PostgreSQL triggers, including retention time and a changed capture reference.
@pytest.mark.parametrize("sql", [
    "UPDATE refunds SET request_id = 'replacement' WHERE id = %s",
    "UPDATE refunds SET amount_cents = 501 WHERE id = %s",
    "UPDATE refunds SET created_at = created_at + interval '1 second' WHERE id = %s",
])
def test_f7_refund_identity_cannot_change(test_db, refund_capture_row, sql):
    refund = insert_refund(test_db, refund_capture_row)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(test_db, sql, (refund["id"],))
    assert db.fetch_one(test_db, "SELECT * FROM refunds WHERE id = %s", (refund["id"],)) == refund


# Use another VALID capture so a foreign-key error cannot masquerade as identity protection.
def test_f7_refund_cannot_move_to_another_valid_capture(test_db, refund_capture_row):
    refund = insert_refund(test_db, refund_capture_row)
    other = db.fetch_one(test_db, "INSERT INTO captures "
                                 "(hold_id, request_id, amount_cents, capture_id, status) "
                                 "VALUES (%s, %s, %s, %s, 'COMPLETED') RETURNING id",
                         (refund_capture_row["hold_id"], uuid.uuid4().hex, 500, "FAKE" + uuid.uuid4().hex))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(test_db, "UPDATE refunds SET capture_id = %s WHERE id = %s", (other["id"], refund["id"]))


# The first returned refund ID can be recorded and kept, but cannot be erased or replaced.
@pytest.mark.parametrize("replacement", [None, "FAKEREPLACEMENT"])
def test_f7_assigned_refund_id_cannot_change(test_db, refund_capture_row, replacement):
    refund = insert_refund(test_db, refund_capture_row)
    refund_id = "FAKE" + uuid.uuid4().hex
    db.run(test_db, "UPDATE refunds SET refund_id = %s WHERE id = %s", (refund_id, refund["id"]))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(test_db, "UPDATE refunds SET refund_id = %s WHERE id = %s", (replacement, refund["id"]))
    db.run(test_db, "UPDATE refunds SET status = 'COMPLETED' WHERE id = %s", (refund["id"],))


# Unknown/unconfirmed captures cannot be put into the refund plan.
@pytest.mark.parametrize("status,capture_id", [("PENDING", "FAKE1"), ("FAILED", "FAKE2"),
                                               ("COMPLETED", None), ("COMPLETED", "")])
def test_f7_refund_requires_recorded_success(test_db, refund_capture_row, status, capture_id):
    db.run(test_db, "UPDATE captures SET status = %s, capture_id = %s WHERE id = %s",
           (status, capture_id, refund_capture_row["id"]))
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_refund(test_db, refund_capture_row)


# A full refund records exactly the captured integer cents, including rejection of zero/negative.
@pytest.mark.parametrize("amount_cents", [0, -1, 499, 501])
def test_f7_refund_amount_must_match_capture(test_db, refund_capture_row, amount_cents):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_refund(test_db, refund_capture_row, amount_cents)


# New rows are unsent. Recording a possible send requires a timestamp, not a timer-based lease.
def test_f7_recovery_fields_start_unsent_and_require_send_evidence(test_db, refund_capture_row):
    refund = insert_refund(test_db, refund_capture_row)
    assert refund["send_state"] == "READY"
    assert refund["send_started_at"] is None
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(test_db, "UPDATE refunds SET send_state = 'IN_FLIGHT' WHERE id = %s", (refund["id"],))
    db.run(test_db, "UPDATE refunds SET send_state = 'IN_FLIGHT', send_started_at = created_at, "
                   "first_send_started_at = created_at, operation_revision = 1 WHERE id = %s",
           (refund["id"],))
