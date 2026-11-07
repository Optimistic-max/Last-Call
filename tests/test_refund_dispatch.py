# Synthetic final-audit regressions: local PostgreSQL and fake PayPal only.
import threading

import psycopg
import pytest

import db
import lifecycle
from tests import fake_paypal
from tests.test_refund_lifecycle import refund_case, insert_person, refund_rows, event_row
from tests.test_refund_safety import saved_refund, maintenance_connection


# Build a fresh dispatch claim without sending HTTP, so duplicate deliveries are controllable.
def dispatch_claim(case):
    person, row = saved_refund(case, "READY")
    db.run(case["conn"], "UPDATE refunds SET send_started_at = NULL WHERE id = %s", (row["id"],))
    claim = lifecycle.claim_ready_refund(case["conn"], case["event_id"], "audit-owner", 1)
    return person, claim


# Read all financial records so a late-ID save cannot silently change another field.
def financial_snapshot(case):
    conn = case["conn"]
    return (refund_rows(conn, case["event_id"]),
            db.fetch_all(conn, "SELECT * FROM captures ORDER BY id"),
            db.fetch_all(conn, "SELECT * FROM pledges ORDER BY id"),
            event_row(conn, case["event_id"]))


@pytest.mark.parametrize("fence", ["IN_FLIGHT", "CHECK_ONLY"])
def test_fenced_post_preserves_id_only(monkeypatch, refund_case, test_db_url, maintenance_connection, fence):
    _, claim = dispatch_claim(refund_case)
    entered, release = threading.Event(), threading.Event()
    errors = []

    def post(capture_id, request_id):
        entered.set()
        assert release.wait(10)
        return fake_paypal.refund_result("REFUNDLATE00001", "COMPLETED")

    def worker():
        try:
            with db.connect(test_db_url) as conn:
                lifecycle.deliver_refund(conn, claim, fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "refund_capture", post)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(10)
        current = refund_rows(refund_case["conn"], refund_case["event_id"])[0]
        if fence == "CHECK_ONLY":
            assert lifecycle.recover_refund_check_only(maintenance_connection, refund_case["token"],
                   claim["id"], "audit-owner", 1, current["operation_revision"])
        else:
            db.run(refund_case["conn"], "UPDATE refunds SET operation_revision = operation_revision + 1 WHERE id = %s",
                   (claim["id"],))
        before = financial_snapshot(refund_case)
        # An explicit GET before the ID arrives must remain blocked.
        assert lifecycle.reconcile_refund(refund_case["conn"], claim["id"], fake_paypal) is None
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and errors == []
    after = financial_snapshot(refund_case)
    assert after[0][0]["refund_id"] == "REFUNDLATE00001"
    after[0][0]["refund_id"] = before[0][0]["refund_id"]
    assert after == before
    if fence == "CHECK_ONLY":
        lifecycle.reconcile_refund(refund_case["conn"], claim["id"], fake_paypal)
        assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "REFUNDED"


@pytest.mark.parametrize("shared", [True, False])
def test_same_claim_dispatches_once(monkeypatch, refund_case, test_db_url, shared):
    _, claim = dispatch_claim(refund_case)
    original = dict(claim)
    entered, release = threading.Event(), threading.Event()
    calls, errors = [], []

    def post(capture_id, request_id):
        calls.append(request_id)
        entered.set()
        assert release.wait(10)
        return fake_paypal.refund_result("REFUNDONCE00001", "PENDING")

    def worker():
        try:
            with db.connect(test_db_url) as conn:
                lifecycle.deliver_refund(conn, claim, fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "refund_capture", post)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(10)
        # Return the second response immediately; the first POST is definitely still active.
        def second_post(capture_id, request_id):
            calls.append(request_id)
            return fake_paypal.refund_result("REFUNDONCE00001", "PENDING")
        monkeypatch.setattr(fake_paypal, "refund_capture", second_post)
        lifecycle.deliver_refund(refund_case["conn"], claim if shared else dict(claim), fake_paypal)
        assert calls == [claim["request_id"]]
    finally:
        release.set()
        thread.join(10)
    assert errors == [] and not thread.is_alive()
    assert claim == original
    lifecycle.deliver_refund(refund_case["conn"], claim, fake_paypal)
    assert calls == [claim["request_id"]]


def test_crash_after_dispatch_commit_cannot_resend(monkeypatch, refund_case, test_db_url):
    _, claim = dispatch_claim(refund_case)
    original = dict(claim)
    calls = []

    def interrupted(capture_id, request_id):
        calls.append(request_id)
        with db.connect(test_db_url) as other:
            row = db.fetch_one(other, "SELECT * FROM refunds WHERE id = %s", (claim["id"],))
        assert row["operation_revision"] > original["operation_revision"]
        assert refund_case["conn"].info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        raise KeyboardInterrupt("synthetic crash after dispatch commit")

    monkeypatch.setattr(fake_paypal, "refund_capture", interrupted)
    with pytest.raises(KeyboardInterrupt):
        lifecycle.deliver_refund(refund_case["conn"], claim, fake_paypal)
    def unexpected_resend(capture_id, request_id):
        calls.append(request_id)
        return fake_paypal.refund_result("REFUNDCRASH0001", "PENDING")
    monkeypatch.setattr(fake_paypal, "refund_capture", unexpected_resend)
    lifecycle.deliver_refund(refund_case["conn"], claim, fake_paypal)
    lifecycle.resume_refund_all(refund_case["conn"], refund_case["token"], fake_paypal)
    lifecycle.retry_failed_refund(refund_case["conn"], claim["id"], fake_paypal)
    assert calls == [claim["request_id"]]
    assert claim == original
    assert refund_rows(refund_case["conn"], refund_case["event_id"])[0]["send_state"] == "IN_FLIGHT"


def test_crash_between_dispatch_commit_and_http_stays_blocked(monkeypatch, refund_case):
    _, claim = dispatch_claim(refund_case)
    consume = lifecycle.consume_refund_dispatch

    def crash(conn, private_claim):
        assert consume(conn, private_claim) is not None
        raise KeyboardInterrupt("synthetic crash before HTTP")

    monkeypatch.setattr(lifecycle, "consume_refund_dispatch", crash)
    with pytest.raises(KeyboardInterrupt):
        lifecycle.deliver_refund(refund_case["conn"], claim, fake_paypal)
    monkeypatch.setattr(lifecycle, "consume_refund_dispatch", consume)
    lifecycle.deliver_refund(refund_case["conn"], claim, fake_paypal)
    lifecycle.resume_refund_all(refund_case["conn"], refund_case["token"], fake_paypal)
    assert fake_paypal.calls == []
    assert refund_rows(refund_case["conn"], refund_case["event_id"])[0]["send_state"] == "IN_FLIGHT"


def test_get_result_remains_owned_during_id_only_save(monkeypatch, refund_case, test_db_url, maintenance_connection):
    _, claim = dispatch_claim(refund_case)
    conn = refund_case["conn"]
    assert lifecycle.recover_refund_check_only(maintenance_connection, refund_case["token"], claim["id"], "audit-owner", 1, claim["operation_revision"])
    assert lifecycle.remember_late_refund_id(conn, claim, "REFUNDGETRACE01", fake_paypal)
    entered, release = threading.Event(), threading.Event()
    errors = []

    def get(refund_id):
        entered.set()
        assert release.wait(10)
        return fake_paypal.refund_result(refund_id, "COMPLETED")

    def worker():
        try:
            with db.connect(test_db_url) as other:
                lifecycle.reconcile_refund(other, claim["id"], fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "get_refund", get)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(10)
        before = financial_snapshot(refund_case)
        assert lifecycle.remember_late_refund_id(conn, claim, "REFUNDGETRACE01", fake_paypal)
        assert not lifecycle.remember_late_refund_id(conn, claim, "REFUNDWRONG001", fake_paypal)
        assert financial_snapshot(refund_case) == before
    finally:
        release.set()
        thread.join(10)
    assert errors == [] and not thread.is_alive()
    assert refund_rows(conn, refund_case["event_id"])[0]["status"] == "COMPLETED"
    assert not lifecycle.remember_late_refund_id(conn, claim, "REFUNDGETRACE01", fake_paypal)


def test_capture_zero_update_rolls_back_completion(monkeypatch, refund_case, test_db_url):
    person, claim = dispatch_claim(refund_case)

    def changed_capture(capture_id, request_id):
        with db.connect(test_db_url) as other:
            db.run(other, "UPDATE captures SET status = 'FAILED' WHERE id = %s", (person["capture"]["id"],))
        return fake_paypal.refund_result("REFUNDATOMIC001", "COMPLETED")

    monkeypatch.setattr(fake_paypal, "refund_capture", changed_capture)
    with pytest.raises(RuntimeError, match="capture"):
        lifecycle.deliver_refund(refund_case["conn"], claim, fake_paypal)
    row = refund_rows(refund_case["conn"], refund_case["event_id"])[0]
    assert (row["send_state"], row["status"], row["refund_id"]) == ("IN_FLIGHT", "PENDING", "REFUNDATOMIC001")
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "REFUNDING"
    assert db.fetch_one(refund_case["conn"], "SELECT status FROM pledges WHERE id = %s",
                        (person["pledge_id"],))["status"] == "CHARGED"


@pytest.mark.parametrize("field,value", [("id", -1), ("capture_row_id", -1),
    ("paypal_capture_id", "DIFFERENTCAPTURE"), ("request_id", "different-request"),
    ("amount_cents", 641), ("event_id", -1), ("pledge_id", -1),
    ("owner", "different-owner"), ("revision", 99)])
def test_late_id_checks_every_identity(refund_case, field, value):
    _, claim = dispatch_claim(refund_case)
    db.run(refund_case["conn"], "UPDATE refunds SET operation_revision = operation_revision + 1 WHERE id = %s", (claim["id"],))
    claim[field] = value
    before = financial_snapshot(refund_case)
    assert lifecycle.remember_late_refund_id(refund_case["conn"], claim, "REFUNDIDENTITY1", fake_paypal) is False
    assert financial_snapshot(refund_case) == before


@pytest.mark.parametrize("resource", [None, "", "bad/id", "bad id", 123])
def test_late_id_rejects_invalid_resource(refund_case, resource):
    _, claim = dispatch_claim(refund_case)
    before = financial_snapshot(refund_case)
    assert lifecycle.remember_late_refund_id(refund_case["conn"], claim, resource, fake_paypal) is False
    assert financial_snapshot(refund_case) == before


def test_late_id_never_overwrites_conflict_or_changes_revision(refund_case):
    _, claim = dispatch_claim(refund_case)
    db.run(refund_case["conn"], "UPDATE refunds SET send_state = 'CHECK_ONLY', operation_revision = operation_revision + 1 WHERE id = %s", (claim["id"],))
    assert lifecycle.remember_late_refund_id(refund_case["conn"], claim, "REFUNDKEEP00001", fake_paypal)
    before = financial_snapshot(refund_case)
    assert lifecycle.remember_late_refund_id(refund_case["conn"], claim, "REFUNDKEEP00001", fake_paypal)
    assert not lifecycle.remember_late_refund_id(refund_case["conn"], claim, "REFUNDOTHER0001", fake_paypal)
    assert financial_snapshot(refund_case) == before


@pytest.mark.parametrize("state", ["READY", "ANSWERED", "UNCERTAIN"])
def test_late_id_refuses_other_states(refund_case, state):
    _, claim = dispatch_claim(refund_case)
    # Historical rows can have unknown timing; a late sender cannot claim them.
    db.run(refund_case["conn"], "DELETE FROM refunds WHERE id = %s", (claim["id"],))
    row = db.fetch_one(refund_case["conn"], "INSERT INTO refunds (capture_id, request_id, amount_cents, send_state) "
        "VALUES (%s, %s, 640, %s) RETURNING id", (claim["capture_row_id"], claim["request_id"], state))
    claim["id"] = row["id"]
    before = financial_snapshot(refund_case)
    assert not lifecycle.remember_late_refund_id(refund_case["conn"], claim, "REFUNDSTATE0001", fake_paypal)
    assert financial_snapshot(refund_case) == before


def test_multiple_captures_only_last_refund_completes_pledge(refund_case):
    person, claim = dispatch_claim(refund_case)
    conn = refund_case["conn"]
    other = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE holds SET pledge_id = %s WHERE id = %s", (person["pledge_id"], other["hold_id"]))
    db.run(conn, "DELETE FROM pledges WHERE id = %s", (other["pledge_id"],))
    db.run(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents) VALUES (%s, 'synthetic-second', 640)", (other["capture"]["id"],))
    lifecycle.deliver_refund(conn, claim, fake_paypal)
    assert db.fetch_one(conn, "SELECT status FROM pledges WHERE id = %s", (person["pledge_id"],))["status"] == "CHARGED"
    lifecycle.send_next_refund(conn, refund_case["event_id"], "audit-owner", 1, fake_paypal)
    assert db.fetch_one(conn, "SELECT status FROM pledges WHERE id = %s", (person["pledge_id"],))["status"] == "REFUNDED"


@pytest.mark.parametrize("state", ["ANSWERED", "UNCERTAIN", "CHECK_ONLY", "IN_FLIGHT"])
def test_nonready_cannot_reset_to_ready(refund_case, state):
    _, row = saved_refund(refund_case, state)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(refund_case["conn"], "UPDATE refunds SET send_state = 'READY', operation_revision = operation_revision + 1 WHERE id = %s", (row["id"],))


def test_second_inflight_entry_with_original_evidence_is_rejected(refund_case):
    # Preserve a historical anomalous READY row; do not repair it or permit it to send.
    person, _ = saved_refund(refund_case, "READY")
    conn = refund_case["conn"]
    db.run(conn, "DELETE FROM refunds WHERE capture_id = %s", (person["capture"]["id"],))
    row = db.fetch_one(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, first_send_started_at, send_started_at) "
        "VALUES (%s, 'synthetic-old-send', 640, now(), now()) RETURNING id", (person["capture"]["id"],))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.run(conn, "UPDATE refunds SET send_state = 'IN_FLIGHT', operation_revision = 1 WHERE id = %s", (row["id"],))


def test_inplace_dispatch_revision_increment_is_allowed(refund_case):
    _, claim = dispatch_claim(refund_case)
    assert db.run(refund_case["conn"], "UPDATE refunds SET operation_revision = operation_revision + 1 WHERE id = %s AND send_state = 'IN_FLIGHT'", (claim["id"],)) == 1


def test_d47_missing_capture_stays_investigation(refund_case):
    insert_person(refund_case["conn"], refund_case["event_id"], "FAILED", "CAPTURED")
    assert lifecycle.begin_refund_all(refund_case["conn"], refund_case["token"], fake_paypal) is None
    assert event_row(refund_case["conn"], refund_case["event_id"])["status"] == "NEEDS_ATTENTION"
    assert refund_rows(refund_case["conn"], refund_case["event_id"]) == []
    assert "refund_capture" not in fake_paypal.called_functions()
