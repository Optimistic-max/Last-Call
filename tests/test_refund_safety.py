# Synthetic F7 audit regressions. Only the guarded disposable PostgreSQL runner is used.
import threading
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

import db
import lifecycle
from tests import fake_paypal
from tests.test_refund_lifecycle import (
    refund_case, insert_person, event_row, refund_rows, posts,
)


# Create a known refund without making a PayPal call, as a crash-recovery fixture.
def saved_refund(case, state="IN_FLIGHT", status="PENDING"):
    conn = case["conn"]
    person = insert_person(conn, case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'audit-owner', "
                 "refund_revision = 1 WHERE id = %s", (case["event_id"],))
    row = db.fetch_one(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, refund_id, "
                            "send_state, status, send_started_at) "
                            "VALUES (%s, %s, 640, %s, %s, %s, now()) RETURNING *",
                       (person["capture"]["id"], uuid.uuid4().hex,
                        None if state == "READY" else fake_paypal.new_id("REFUND"), state, status))
    db.run(conn, "UPDATE holds SET refund_check_status = 'RESOLVED' WHERE id = %s", (person["hold_id"],))
    return person, row


def test_get_cannot_release_active_post(refund_case):
    _, row = saved_refund(refund_case)
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(row["refund_id"], "COMPLETED")]
    lifecycle.reconcile_refund(refund_case["conn"], row["id"], fake_paypal)
    current = refund_rows(refund_case["conn"], refund_case["event_id"])[0]
    assert current["send_state"] == "IN_FLIGHT"
    assert current["status"] == "PENDING"
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "REFUNDING"


def test_explicit_retry_remains_disabled_with_unknown_original_time(refund_case):
    _, row = saved_refund(refund_case, "ANSWERED", "FAILED")
    lifecycle.retry_failed_refund(refund_case["conn"], row["id"], fake_paypal)
    assert posts() == []
    assert refund_rows(refund_case["conn"], refund_case["event_id"])[0] == row


@pytest.mark.parametrize("pledge_status,hold_status", [("HELD", "CREATED"), ("DROPPED", "PENDING")])
def test_nonfailed_unresolved_hold_blocks_handoff(refund_case, pledge_status, hold_status):
    insert_person(refund_case["conn"], refund_case["event_id"], pledge_status, hold_status)
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.no_answer()]
    lifecycle.begin_refund_all(refund_case["conn"], refund_case["token"], fake_paypal)
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "NEEDS_ATTENTION"
    assert refund_rows(refund_case["conn"], refund_case["event_id"]) == []


@pytest.mark.parametrize("pledge_status", ["CHARGED", "REFUNDED"])
def test_missing_refund_blocks_completion(refund_case, pledge_status):
    person = insert_person(refund_case["conn"], refund_case["event_id"], pledge_status, "CAPTURED", "COMPLETED")
    db.run(refund_case["conn"], "UPDATE holds SET refund_check_status = 'RESOLVED' WHERE id = %s", (person["hold_id"],))
    db.run(refund_case["conn"], "UPDATE events SET status = 'REFUNDING', refund_run_token = 'audit-owner', "
                              "refund_revision = 1 WHERE id = %s", (refund_case["event_id"],))
    assert lifecycle.finish_refunding(refund_case["conn"], refund_case["event_id"], "audit-owner", 1) is False
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "REFUNDING"


@pytest.mark.parametrize("observed,check", [("VOIDED", "RESOLVED"), ("CAPTURED", "MANUAL_REVIEW"),
                                         ("PARTIALLY_CAPTURED", "MANUAL_REVIEW")])
def test_changed_authorization_state_is_recorded(refund_case, observed, check):
    person = insert_person(refund_case["conn"], refund_case["event_id"], "FAILED", "CREATED")
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back(observed, person["auth_id"])]
    lifecycle.begin_refund_all(refund_case["conn"], refund_case["token"], fake_paypal)
    hold = db.fetch_one(refund_case["conn"], "SELECT status, refund_check_status FROM holds WHERE id = %s",
                        (person["hold_id"],))
    assert hold == {"status": observed, "refund_check_status": check}
    assert "void_authorization" not in fake_paypal.called_functions()
    if check == "MANUAL_REVIEW":
        assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "NEEDS_ATTENTION"


# Both GETs read PENDING. A sibling READY row keeps the event open after the first completion.
@pytest.mark.parametrize("new_status", ["COMPLETED", "PENDING"])
def test_out_of_order_get_cannot_regress_completed(monkeypatch, refund_case, test_db_url, new_status):
    conn = refund_case["conn"]
    _, row = saved_refund(refund_case, "ANSWERED")
    other_person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents) VALUES (%s, %s, 640)",
           (other_person["capture"]["id"], uuid.uuid4().hex))
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def answer(refund_id):
        if threading.current_thread().name == "old-refund-get":
            entered.set()
            assert release.wait(10)
            return fake_paypal.refund_result(refund_id, "FAILED")
        return fake_paypal.refund_result(refund_id, new_status)

    def old_get():
        try:
            with db.connect(test_db_url) as other:
                lifecycle.reconcile_refund(other, row["id"], fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "get_refund", answer)
    worker = threading.Thread(target=old_get, name="old-refund-get")
    worker.start()
    try:
        assert entered.wait(10)
        lifecycle.reconcile_refund(conn, row["id"], fake_paypal)
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert errors == []
    current = db.fetch_one(conn, "SELECT status FROM refunds WHERE id = %s", (row["id"],))
    assert current["status"] == new_status


def test_paused_post_keeps_ownership_during_get(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def post(capture_id, request_id):
        entered.set()
        assert release.wait(10)
        return fake_paypal.refund_result("REFUNDPAUSED0001", "COMPLETED")

    def send():
        try:
            with db.connect(test_db_url) as other:
                lifecycle.begin_refund_all(other, refund_case["token"], fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "refund_capture", post)
    worker = threading.Thread(target=send)
    worker.start()
    try:
        assert entered.wait(10)
        # A saved ID may exist before a paused POST returns (for example an older recorded retry).
        row = db.fetch_one(conn, "UPDATE refunds SET refund_id = 'REFUNDPAUSED0001' WHERE capture_id = %s RETURNING *",
                            (person["capture"]["id"],))
        fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(row["refund_id"], "FAILED")]
        lifecycle.reconcile_refund(conn, row["id"], fake_paypal)
        assert db.fetch_one(conn, "SELECT send_state FROM refunds WHERE id = %s", (row["id"],))["send_state"] == "IN_FLIGHT"
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert errors == []


@pytest.mark.parametrize("operation", ["start_hold", "authorize_hold"])
def test_late_authorization_eligibility_is_rechecked(monkeypatch, refund_case, operation):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "PENDING_PAY", "PENDING")
    db.run(conn, "UPDATE holds SET auth_id = NULL, order_id = 'ORDERLATE000001' WHERE id = %s", (person["hold_id"],))
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    db.run(conn, "UPDATE events SET status = 'OPEN', hard_deadline = %s WHERE id = %s",
           (now + timedelta(hours=1), refund_case["event_id"]))
    token = db.fetch_one(conn, "SELECT pledger_token FROM pledges WHERE id = %s", (person["pledge_id"],))["pledger_token"]
    original = lifecycle.pledging_is_open
    calls = []

    def close_after_check(event, time):
        result = original(event, time)
        if not calls:
            calls.append(1)
            db.run(conn, "UPDATE events SET status = 'REFUNDING' WHERE id = %s", (refund_case["event_id"],))
        return result

    monkeypatch.setattr(lifecycle, "pledging_is_open", close_after_check)
    if operation == "start_hold":
        lifecycle.start_hold(conn, token, now, fake_paypal)
    else:
        lifecycle.authorize_hold(conn, "ORDERLATE000001", token, now, fake_paypal)
    assert "create_order" not in fake_paypal.called_functions()
    assert "authorize_order" not in fake_paypal.called_functions()


# A separate labelled connection is an administrative tool, never an application request.
@pytest.fixture
def maintenance_connection(test_db_url):
    with db.connect(test_db_url) as conn:
        conn.execute("SET application_name = 'last_call_refund_maintenance'")
        yield conn


def test_recovery_requires_authorized_maintenance_and_exact_claim(refund_case, maintenance_connection):
    _, row = saved_refund(refund_case)
    args = (refund_case["token"], row["id"], "audit-owner", 1, 0)
    with pytest.raises(PermissionError):
        lifecycle.recover_refund_check_only(refund_case["conn"], *args)
    assert lifecycle.recover_refund_check_only(maintenance_connection, "wrong-token", *args[1:]) is False
    assert lifecycle.recover_refund_check_only(maintenance_connection, *args[:-1], 99) is False
    assert lifecycle.recover_refund_check_only(maintenance_connection, *args) is True
    assert lifecycle.recover_refund_check_only(maintenance_connection, *args) is False
    current = refund_rows(refund_case["conn"], refund_case["event_id"])[0]
    assert current["send_state"] == "CHECK_ONLY"
    assert current["operation_revision"] == 1
    assert current["first_send_started_at"] is None
    assert fake_paypal.calls == []


@pytest.mark.parametrize("status", ["PENDING", "FAILED", "CANCELLED", "COMPLETED"])
def test_check_only_is_get_only_and_does_not_enable_retry(refund_case, maintenance_connection, status):
    _, row = saved_refund(refund_case, "UNCERTAIN")
    assert lifecycle.recover_refund_check_only(maintenance_connection, refund_case["token"], row["id"], "audit-owner", 1, 0)
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(row["refund_id"], status)]
    lifecycle.reconcile_refund(refund_case["conn"], row["id"], fake_paypal)
    lifecycle.retry_failed_refund(refund_case["conn"], row["id"], fake_paypal)
    current = refund_rows(refund_case["conn"], refund_case["event_id"])[0]
    assert current["status"] == status
    assert current["send_state"] == ("ANSWERED" if status == "COMPLETED" else "CHECK_ONLY")
    assert current["operation_revision"] == 3
    assert current["request_id"] == row["request_id"]
    assert current["first_send_started_at"] is None
    assert fake_paypal.called_functions() == ["get_refund"]


def test_recovery_without_known_id_stays_blocked(refund_case, maintenance_connection):
    _, row = saved_refund(refund_case, "UNCERTAIN")
    db.run(refund_case["conn"], "DELETE FROM refunds WHERE id = %s", (row["id"],))
    row = db.fetch_one(refund_case["conn"], "INSERT INTO refunds (capture_id, request_id, amount_cents, send_state) "
                                          "VALUES (%s, %s, 640, 'UNCERTAIN') RETURNING *", (row["capture_id"], row["request_id"]))
    assert lifecycle.recover_refund_check_only(maintenance_connection, refund_case["token"], row["id"], "audit-owner", 1, 0)
    assert lifecycle.reconcile_refund(refund_case["conn"], row["id"], fake_paypal) is None
    lifecycle.resume_refund_all(refund_case["conn"], refund_case["token"], fake_paypal)
    assert fake_paypal.calls == []
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "REFUNDING"


@pytest.mark.parametrize("outcome", ["COMPLETED", "NO_ANSWER"])
def test_operation_revision_rejects_stale_send_result(monkeypatch, refund_case, outcome):
    conn = refund_case["conn"]
    inserted = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")

    def replace_operation(capture_id, request_id):
        db.run(conn, "UPDATE refunds SET operation_revision = operation_revision + 1 WHERE capture_id = %s",
               (inserted["capture"]["id"],))
        if outcome == "NO_ANSWER":
            return fake_paypal.no_answer()
        return fake_paypal.refund_result("REFUNDSTALEOP01", "COMPLETED")

    monkeypatch.setattr(fake_paypal, "refund_capture", replace_operation)
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    row = refund_rows(conn, refund_case["event_id"])[0]
    assert row["send_state"] == "IN_FLIGHT"
    assert row["refund_id"] == ("REFUNDSTALEOP01" if outcome == "COMPLETED" else None)
    assert row["status"] == "PENDING"


def test_first_send_evidence_commits_before_post(monkeypatch, refund_case, test_db_url):
    person = insert_person(refund_case["conn"], refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")

    def inspect_commit(capture_id, request_id):
        assert refund_case["conn"].info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        with db.connect(test_db_url) as other:
            row = db.fetch_one(other, "SELECT * FROM refunds WHERE capture_id = %s", (person["capture"]["id"],))
        assert row["operation_revision"] == 2  # First-send claim, then one-use dispatch consumption.
        assert row["first_send_started_at"] is not None
        assert row["first_send_started_at"] <= row["send_started_at"]
        assert row["request_id"] == request_id
        return fake_paypal.refund_result("REFUNDEVIDENCE1", "COMPLETED")

    monkeypatch.setattr(fake_paypal, "refund_capture", inspect_commit)
    lifecycle.begin_refund_all(refund_case["conn"], refund_case["token"], fake_paypal)
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "REFUNDED"


def test_zero_payment_completion_requires_resolved_holds(refund_case):
    person = insert_person(refund_case["conn"], refund_case["event_id"], "DROPPED", "VOIDED")
    lifecycle.begin_refund_all(refund_case["conn"], refund_case["token"], fake_paypal)
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "REFUNDED"
    assert refund_rows(refund_case["conn"], refund_case["event_id"]) == []
    assert fake_paypal.called_functions() == ["get_authorization"]


@pytest.mark.parametrize("status", ["COMPLETED", "FAILED", "CANCELLED", "PENDING"])
def test_any_explicit_retry_is_disabled_even_with_known_time(refund_case, status):
    _, row = saved_refund(refund_case, "READY")
    conn = refund_case["conn"]
    db.run(conn, "UPDATE refunds SET send_started_at = NULL WHERE id = %s", (row["id"],))
    db.run(conn, "UPDATE refunds SET send_state = 'IN_FLIGHT', operation_revision = 1, "
                 "first_send_started_at = now() - interval '50 days', send_started_at = now() WHERE id = %s", (row["id"],))
    db.run(conn, "UPDATE refunds SET send_state = 'ANSWERED', status = %s, operation_revision = 2 WHERE id = %s", (status, row["id"]))
    before = refund_rows(conn, refund_case["event_id"])[0]
    assert lifecycle.retry_failed_refund(conn, row["id"], fake_paypal) is None
    assert lifecycle.claim_failed_refund(conn, row["id"]) is None
    assert refund_rows(conn, refund_case["event_id"])[0] == before
    assert fake_paypal.calls == []


def test_recorded_pending_allows_independent_refund(refund_case):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    fake_paypal.next_answers["refund_capture"] = [fake_paypal.refund_result("REFUNDPENDING02", "PENDING")]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    first = refund_rows(conn, refund_case["event_id"])[0]
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    assert len(posts()) == 2
    rows = refund_rows(conn, refund_case["event_id"])
    assert [(row["send_state"], row["status"]) for row in rows] == [("ANSWERED", "PENDING"), ("ANSWERED", "COMPLETED")]
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDING"
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(first["refund_id"], "COMPLETED")]
    lifecycle.reconcile_refund(conn, first["id"], fake_paypal)
    assert len(posts()) == 2
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDED"


def test_uncertain_post_blocks_independent_refund(refund_case):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    fake_paypal.next_answers["refund_capture"] = [fake_paypal.no_answer()]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    assert len(posts()) == 1
    assert [row["send_state"] for row in refund_rows(conn, refund_case["event_id"])] == ["UNCERTAIN", "READY"]


def test_connection_loss_after_paypal_keeps_claim(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    worker = db.connect(test_db_url)

    def lose_connection(capture_id, request_id):
        fake_paypal.calls.append({"function": "refund_capture", "request_id": request_id})
        worker.close()
        return fake_paypal.refund_result("REFUNDCONNECTION1", "COMPLETED")

    monkeypatch.setattr(fake_paypal, "refund_capture", lose_connection)
    try:
        with pytest.raises((psycopg.OperationalError, psycopg.InterfaceError)):
            lifecycle.begin_refund_all(worker, refund_case["token"], fake_paypal)
    finally:
        worker.close()
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    row = refund_rows(conn, refund_case["event_id"])[0]
    assert row["send_state"] == "IN_FLIGHT"
    assert row["first_send_started_at"] is not None
    assert row["refund_id"] is None
    assert len(posts()) == 1


def test_completion_updates_roll_back_together(monkeypatch, refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    original = db.run

    def fail_pledge(connection, sql, params=()):
        if sql.startswith("UPDATE pledges SET status = 'REFUNDED'"):
            raise psycopg.OperationalError("synthetic failure before pledge update")
        return original(connection, sql, params)

    monkeypatch.setattr(db, "run", fail_pledge)
    with pytest.raises(psycopg.OperationalError):
        lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    row = refund_rows(conn, refund_case["event_id"])[0]
    assert row["send_state"] == "IN_FLIGHT"
    assert row["status"] == "PENDING"
    assert row["refund_id"] is not None  # Saved before the later transaction failed.
    assert db.fetch_one(conn, "SELECT status FROM captures WHERE id = %s", (person["capture"]["id"],))["status"] == "COMPLETED"
    assert db.fetch_one(conn, "SELECT status FROM pledges WHERE id = %s", (person["pledge_id"],))["status"] == "CHARGED"


@pytest.mark.parametrize("answer", ["missing", "wrong_id"])
def test_unusable_authorization_read_cannot_change_hold(refund_case, answer):
    person = insert_person(refund_case["conn"], refund_case["event_id"], "FAILED", "CREATED")
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.no_answer() if answer == "missing" else
                                                   fake_paypal.hold_read_back("VOIDED", "OTHER_AUTH")]
    lifecycle.begin_refund_all(refund_case["conn"], refund_case["token"], fake_paypal)
    hold = db.fetch_one(refund_case["conn"], "SELECT status, refund_check_status FROM holds WHERE id = %s", (person["hold_id"],))
    assert hold == {"status": "CREATED", "refund_check_status": None}
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "NEEDS_ATTENTION"


@pytest.mark.parametrize("operation", ["start_hold", "authorize_hold"])
def test_event_lock_serializes_late_checkout(monkeypatch, refund_case, test_db_url, operation):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "PENDING_PAY", "PENDING")
    db.run(conn, "UPDATE holds SET auth_id = NULL, order_id = 'ORDERLOCK000001' WHERE id = %s", (person["hold_id"],))
    token = db.fetch_one(conn, "SELECT pledger_token FROM pledges WHERE id = %s", (person["pledge_id"],))["pledger_token"]
    now = datetime(2026, 11, 6, tzinfo=timezone.utc)
    db.run(conn, "UPDATE events SET status = 'OPEN', hard_deadline = %s WHERE id = %s",
           (now + timedelta(hours=1), refund_case["event_id"]))
    waiting = threading.Event()
    errors = []
    original = db.fetch_one

    def observe(connection, sql, params=()):
        if connection is not conn and sql == "SELECT * FROM events WHERE id = %s FOR UPDATE":
            waiting.set()
        return original(connection, sql, params)

    def checkout():
        try:
            with db.connect(test_db_url) as other:
                if operation == "start_hold":
                    lifecycle.start_hold(other, token, now, fake_paypal)
                else:
                    lifecycle.authorize_hold(other, "ORDERLOCK000001", token, now, fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(db, "fetch_one", observe)
    worker = threading.Thread(target=checkout)
    try:
        with conn.transaction():
            original(conn, "SELECT * FROM events WHERE id = %s FOR UPDATE", (refund_case["event_id"],))
            worker.start()
            assert waiting.wait(10)
            db.run(conn, "UPDATE events SET status = 'REFUNDING' WHERE id = %s", (refund_case["event_id"],))
    finally:
        worker.join(10)
    assert not worker.is_alive()
    assert errors == []
    assert fake_paypal.calls == []


def test_failed_first_attempt_and_recorded_success_are_both_accounted_for(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "INSERT INTO captures (hold_id, request_id, amount_cents, status, attempt) "
                 "VALUES (%s, %s, 640, 'FAILED', 1)", (person["hold_id"], uuid.uuid4().hex))
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    assert len(posts()) == 1
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDED"


@pytest.mark.parametrize("status,has_id", [("PENDING", False), ("FAILED", True)])
def test_unknown_capture_attempt_blocks_entire_plan(refund_case, status, has_id):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "INSERT INTO captures (hold_id, request_id, amount_cents, status, capture_id) "
                 "VALUES (%s, %s, 640, %s, %s)",
           (person["hold_id"], uuid.uuid4().hex, status, fake_paypal.new_id("CAPTURE") if has_id else None))
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    assert posts() == []
    assert refund_rows(conn, refund_case["event_id"]) == []
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"


@pytest.mark.parametrize("pledge_status,status", [("HELD", "CREATED"), ("DROPPED", "PENDING")])
def test_unresolved_nonfailed_hold_blocks_completion(refund_case, pledge_status, status):
    insert_person(refund_case["conn"], refund_case["event_id"], pledge_status, status)
    db.run(refund_case["conn"], "UPDATE events SET status = 'REFUNDING', refund_run_token = 'audit-owner', "
                              "refund_revision = 1 WHERE id = %s", (refund_case["event_id"],))
    assert lifecycle.finish_refunding(refund_case["conn"], refund_case["event_id"], "audit-owner", 1) is False


def test_deliver_refuses_stale_claim_before_http(refund_case):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    assert lifecycle.review_failed_holds(conn, refund_case["event_id"], fake_paypal)
    owner = lifecycle.open_refunding(conn, refund_case["event_id"])
    claim = lifecycle.claim_ready_refund(conn, owner["event_id"], owner["owner"], owner["revision"])
    db.run(conn, "UPDATE refunds SET operation_revision = operation_revision + 1 WHERE id = %s", (claim["id"],))
    lifecycle.deliver_refund(conn, claim, fake_paypal)
    assert posts() == []


def test_ready_row_with_existing_resource_is_not_a_first_send(refund_case):
    _, row = saved_refund(refund_case, "READY")
    db.run(refund_case["conn"], "UPDATE refunds SET send_started_at = NULL, "
                              "refund_id = COALESCE(refund_id, 'REFUNDKNOWN00001') WHERE id = %s", (row["id"],))
    assert lifecycle.claim_ready_refund(refund_case["conn"], refund_case["event_id"], "audit-owner", 1) is None
    current = refund_rows(refund_case["conn"], refund_case["event_id"])[0]
    assert current["first_send_started_at"] is None
    assert current["send_state"] == "READY"


def test_completed_refund_without_resource_id_blocks_completion(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "REFUNDED", "CAPTURED", "COMPLETED")
    db.run(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, status, send_state) "
                 "VALUES (%s, %s, 640, 'COMPLETED', 'ANSWERED')", (person["capture"]["id"], uuid.uuid4().hex))
    db.run(conn, "UPDATE captures SET status = 'REFUNDED' WHERE id = %s", (person["capture"]["id"],))
    db.run(conn, "UPDATE holds SET refund_check_status = 'RESOLVED' WHERE id = %s", (person["hold_id"],))
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'audit-owner', "
                 "refund_revision = 1 WHERE id = %s", (refund_case["event_id"],))
    assert lifecycle.finish_refunding(conn, refund_case["event_id"], "audit-owner", 1) is False
