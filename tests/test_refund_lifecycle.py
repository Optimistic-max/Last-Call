# F7 Stage 2B: refund lifecycle, crash recovery, and stale-owner races.
# Fake PayPal only. Each test builds its own event and deletes it afterwards.
import inspect
import threading
import time
import uuid
from pathlib import Path

import psycopg
import pytest

import db
import lifecycle
from tests import fake_paypal

ROOT = Path(__file__).resolve().parents[1]
REFUND_FUNCTION_NAMES = (
    "begin_refund_all",
    "resume_refund_all",
    "reconcile_refund",
    "retry_failed_refund",
    "finish_refunding",
    "save_refund_check",
    "reconcile_refund_for_treasurer",
)


# One synthetic event. The finalizer removes its rows even when the test fails.
@pytest.fixture
def refund_case(test_db, request, monkeypatch):
    event_id, admin_token = insert_event(test_db)
    request.addfinalizer(lambda: delete_event(test_db, event_id))
    fake_paypal.reset()
    # Synthetic server defaults match each fixture's authorization; explicit queues still win.
    def authorization(auth_id):
        row = db.fetch_one(test_db, "SELECT status FROM holds WHERE auth_id = %s", (auth_id,))
        status = row["status"] if row is not None else "VOIDED"
        return fake_paypal.record_and_answer("get_authorization", {"auth_id": auth_id},
                                            fake_paypal.hold_read_back(status, auth_id))
    monkeypatch.setattr(fake_paypal, "get_authorization", authorization)
    return {"conn": test_db, "event_id": event_id, "token": admin_token}


def insert_event(conn, status="NEEDS_ATTENTION"):
    token = uuid.uuid4().hex
    row = db.fetch_one(conn, "INSERT INTO events (title, deposit_cents, admin_token, status) "
                             "VALUES ('synthetic refund lifecycle', 2000, %s, %s) RETURNING id",
                       (token, status))
    return row["id"], token


def insert_person(conn, event_id, pledge_status, hold_status, capture_status=None, amount_cents=640):
    key = uuid.uuid4().hex
    pledge = db.fetch_one(conn, "INSERT INTO pledges (event_id, name, max_cents, pledger_token, status) "
                                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                          (event_id, "Synthetic " + key[:8], amount_cents, key, pledge_status))
    auth_id = "FAKE" + key[:20]
    hold = db.fetch_one(conn, "INSERT INTO holds (pledge_id, create_request_id, amount_cents, auth_id, status) "
                              "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (pledge["id"], key, amount_cents, auth_id, hold_status))
    capture = None
    if capture_status is not None:
        capture = db.fetch_one(conn, "INSERT INTO captures (hold_id, request_id, amount_cents, capture_id, status) "
                                    "VALUES (%s, %s, %s, %s, %s) RETURNING id, capture_id, amount_cents",
                              (hold["id"], key + "cap", amount_cents, "CAPTURE" + key[:16], capture_status))
    return {"pledge_id": pledge["id"], "hold_id": hold["id"], "auth_id": auth_id, "capture": capture}


def delete_event(conn, event_id):
    db.run(conn, "DELETE FROM refunds WHERE capture_id IN (SELECT captures.id FROM captures "
                 "JOIN holds ON holds.id = captures.hold_id JOIN pledges ON pledges.id = holds.pledge_id "
                 "WHERE pledges.event_id = %s)", (event_id,))
    db.run(conn, "DELETE FROM captures WHERE hold_id IN (SELECT holds.id FROM holds JOIN pledges "
                 "ON pledges.id = holds.pledge_id WHERE pledges.event_id = %s)", (event_id,))
    db.run(conn, "DELETE FROM holds WHERE pledge_id IN (SELECT id FROM pledges WHERE event_id = %s)", (event_id,))
    db.run(conn, "DELETE FROM pledges WHERE event_id = %s", (event_id,))
    db.run(conn, "DELETE FROM events WHERE id = %s", (event_id,))


def event_row(conn, event_id):
    return db.fetch_one(conn, "SELECT status, refund_run_token, refund_revision FROM events WHERE id = %s",
                        (event_id,))


def refund_rows(conn, event_id):
    return db.fetch_all(conn, "SELECT refunds.* FROM refunds JOIN captures ON captures.id = refunds.capture_id "
                              "JOIN holds ON holds.id = captures.hold_id JOIN pledges ON pledges.id = holds.pledge_id "
                              "WHERE pledges.event_id = %s ORDER BY refunds.id", (event_id,))


def posts():
    found = []
    for call in fake_paypal.calls:
        if call["function"] == "refund_capture":
            found.append(call)
    return found


def test_refund_functions_do_not_capture_or_run_from_settlement():
    missing = []
    for name in REFUND_FUNCTION_NAMES:
        if not hasattr(lifecycle, name):
            missing.append(name)
    assert missing == []
    for name in REFUND_FUNCTION_NAMES:
        source = inspect.getsource(getattr(lifecycle, name))
        assert "capture_authorization" not in source
        assert "send_capture(" not in source
        assert "lock_and_charge(" not in source
        assert "sweep_stranded_holds(" not in source
    settle = inspect.getsource(lifecycle.settle_due_events)
    assert "begin_refund_all" not in settle
    assert "refund_capture" not in settle
    # Stage 3 explicitly authorizes routes; settlement must still never initiate refunds.
    assert "resume_refund_all" not in settle


def test_unknown_token_and_wrong_status_do_not_call_paypal(refund_case):
    conn = refund_case["conn"]
    assert lifecycle.begin_refund_all(conn, "missing-token", fake_paypal) is None
    db.run(conn, "UPDATE events SET status = 'OPEN' WHERE id = %s", (refund_case["event_id"],))
    assert lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal) is None
    assert fake_paypal.calls == []
    assert refund_rows(conn, refund_case["event_id"]) == []


def test_completed_refund_updates_capture_pledge_and_event(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    refund = refund_rows(conn, refund_case["event_id"])[0]
    assert refund["amount_cents"] == 640
    assert refund["send_state"] == "ANSWERED"
    assert refund["status"] == "COMPLETED"
    assert refund["refund_id"]
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDED"
    assert event_row(conn, refund_case["event_id"])["refund_run_token"] is None
    assert db.fetch_one(conn, "SELECT status FROM captures WHERE id = %s",
                        (person["capture"]["id"],))["status"] == "REFUNDED"
    assert db.fetch_one(conn, "SELECT status FROM pledges WHERE id = %s",
                        (person["pledge_id"],))["status"] == "REFUNDED"
    assert [call["function"] for call in fake_paypal.calls] == ["get_authorization", "refund_capture"]


def test_failed_pledge_is_not_marked_refunded(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "VOIDED", "COMPLETED")
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", person["auth_id"])]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    assert db.fetch_one(conn, "SELECT status FROM pledges WHERE id = %s",
                        (person["pledge_id"],))["status"] == "FAILED"
    assert db.fetch_one(conn, "SELECT status FROM captures WHERE id = %s",
                        (person["capture"]["id"],))["status"] == "REFUNDED"


def test_two_overlapping_begins_send_one_refund(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    started = threading.Barrier(2)
    release = threading.Event()
    in_post = threading.Event()
    errors = []
    finished = []

    def paused(capture_id, request_id):
        fake_paypal.calls.append({"function": "refund_capture", "capture_id": capture_id,
                                  "request_id": request_id})
        in_post.set()
        if not release.wait(10):
            raise RuntimeError("test did not release the refund")
        return fake_paypal.refund_result("REFUND" + uuid.uuid4().hex[:12].upper(), "COMPLETED")

    def caller():
        try:
            started.wait(10)
            with db.connect(test_db_url) as other:
                lifecycle.begin_refund_all(other, refund_case["token"], fake_paypal)
        except Exception as error:
            errors.append(error)
        finished.append(1)

    monkeypatch.setattr(fake_paypal, "refund_capture", paused)
    workers = [threading.Thread(target=caller), threading.Thread(target=caller)]
    for worker in workers:
        worker.start()
    try:
        assert in_post.wait(10)
        deadline = time.monotonic() + 10
        while len(finished) < 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(finished) == 1
        assert len(posts()) == 1
        assert len(refund_rows(conn, refund_case["event_id"])) == 1
    finally:
        release.set()
        for worker in workers:
            worker.join(10)
    assert errors == []
    assert len(posts()) == 1
    assert len(refund_rows(conn, refund_case["event_id"])) == 1


def test_request_and_inflight_are_committed_before_post(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    seen = []

    def checking(capture_id, request_id):
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        with db.connect(test_db_url) as other:
            row = db.fetch_one(other, "SELECT refunds.request_id, refunds.send_state, refunds.send_started_at "
                                      "FROM refunds JOIN captures ON captures.id = refunds.capture_id "
                                      "JOIN holds ON holds.id = captures.hold_id "
                                      "JOIN pledges ON pledges.id = holds.pledge_id "
                                      "WHERE pledges.event_id = %s", (refund_case["event_id"],))
        seen.append((row["request_id"], row["send_state"], row["send_started_at"] is not None, request_id))
        return fake_paypal.refund_result("REFUNDCOMMITTED1", "COMPLETED")

    monkeypatch.setattr(fake_paypal, "refund_capture", checking)
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    assert seen == [(seen[0][0], "IN_FLIGHT", True, seen[0][0])]


def test_paused_post_blocks_the_sibling_refund(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED", 640)
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED", 700)
    entered = threading.Event()
    release = threading.Event()

    def paused(capture_id, request_id):
        fake_paypal.calls.append({"function": "refund_capture", "capture_id": capture_id,
                                  "request_id": request_id})
        if len(posts()) == 1:
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test did not release the refund")
        return fake_paypal.refund_result("REFUND" + uuid.uuid4().hex[:12].upper(), "COMPLETED")

    def starter():
        with db.connect(test_db_url) as other:
            lifecycle.begin_refund_all(other, refund_case["token"], fake_paypal)

    monkeypatch.setattr(fake_paypal, "refund_capture", paused)
    worker = threading.Thread(target=starter)
    worker.start()
    try:
        assert entered.wait(10)
        lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
        lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
        assert len(posts()) == 1
        states = [row["send_state"] for row in refund_rows(conn, refund_case["event_id"])]
        assert states == ["IN_FLIGHT", "READY"]
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    assert len(posts()) == 2
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDED"
    assert [row["amount_cents"] for row in refund_rows(conn, refund_case["event_id"])] == [640, 700]


def test_pending_refund_keeps_the_event_refunding(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    fake_paypal.next_answers["refund_capture"] = [fake_paypal.refund_result("REFUNDPENDING01", "PENDING")]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    refund = refund_rows(conn, refund_case["event_id"])[0]
    assert refund["send_state"] == "ANSWERED"
    assert refund["status"] == "PENDING"
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDING"
    assert db.fetch_one(conn, "SELECT status FROM captures WHERE id = %s",
                        (person["capture"]["id"],))["status"] == "COMPLETED"
    assert len(posts()) == 1


def test_failed_refund_cannot_retry_until_retention_is_verified(refund_case):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    fake_paypal.next_answers["refund_capture"] = [
        fake_paypal.refund_result("REFUNDFAILED001", "FAILED"),
        fake_paypal.refund_result("REFUNDFAILED001", "COMPLETED"),
    ]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    assert len(posts()) == 1
    refund = refund_rows(conn, refund_case["event_id"])[0]
    assert refund["status"] == "FAILED"
    saved_request = refund["request_id"]
    lifecycle.retry_failed_refund(conn, refund["id"], fake_paypal)
    assert len(posts()) == 1
    assert posts()[0]["request_id"] == saved_request
    assert len(refund_rows(conn, refund_case["event_id"])) == 1
    assert event_row(conn, refund_case["event_id"])["refund_revision"] == 1


def test_lost_answer_stays_uncertain_and_is_not_posted_again(refund_case):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    fake_paypal.next_answers["refund_capture"] = [fake_paypal.no_answer()]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    refund = refund_rows(conn, refund_case["event_id"])[0]
    assert refund["send_state"] == "UNCERTAIN"
    assert refund["refund_id"] is None
    assert len(posts()) == 1
    assert lifecycle.reconcile_refund(conn, refund["id"], fake_paypal) is None
    assert "get_refund" not in fake_paypal.called_functions()


def test_exception_after_post_stays_uncertain(monkeypatch, refund_case):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")

    def explode(capture_id, request_id):
        fake_paypal.calls.append({"function": "refund_capture", "capture_id": capture_id,
                                  "request_id": request_id})
        raise RuntimeError("connection dropped after the POST")

    monkeypatch.setattr(fake_paypal, "refund_capture", explode)
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    assert refund_rows(conn, refund_case["event_id"])[0]["send_state"] == "UNCERTAIN"
    assert len(posts()) == 1


def test_reconcile_uses_get_only_when_a_refund_id_is_saved(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'owner-token', refund_revision = 2 "
                 "WHERE id = %s", (refund_case["event_id"],))
    refund = db.fetch_one(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, refund_id, "
                                "send_state, send_started_at) VALUES (%s, %s, 640, 'REFUNDSAVED0001', "
                                "'CHECK_ONLY', now()) RETURNING id",
                          (person["capture"]["id"], uuid.uuid4().hex))
    db.run(conn, "UPDATE holds SET refund_check_status = 'RESOLVED' WHERE id = %s", (person["hold_id"],))
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result("REFUNDSAVED0001", "COMPLETED")]
    lifecycle.reconcile_refund(conn, refund["id"], fake_paypal)
    assert fake_paypal.called_functions() == ["get_refund"]
    assert refund_rows(conn, refund_case["event_id"])[0]["status"] == "COMPLETED"
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDED"


@pytest.mark.parametrize("state", ["UNCERTAIN", "IN_FLIGHT"])
def test_retry_of_uncertain_or_inflight_posts_nothing(refund_case, state):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'owner-token', refund_revision = 2 "
                 "WHERE id = %s", (refund_case["event_id"],))
    uncertain = db.fetch_one(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, send_state, send_started_at) "
                                  "VALUES (%s, %s, 640, %s, now()) RETURNING id",
                            (person["capture"]["id"], uuid.uuid4().hex, state))
    assert lifecycle.retry_failed_refund(conn, uncertain["id"], fake_paypal) is None
    assert posts() == []


def test_pending_and_failed_captures_are_not_refunded(refund_case):
    conn = refund_case["conn"]
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "PENDING", 640)
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "FAILED", 640)
    kept = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED", 640)
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    rows = refund_rows(conn, refund_case["event_id"])
    assert rows == []
    assert posts() == []
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"


def test_created_failed_hold_is_voided_before_refunding(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    seen = []
    fake_paypal.next_answers["get_authorization"] = [
        fake_paypal.hold_read_back("CREATED", person["auth_id"]),
        fake_paypal.hold_read_back("VOIDED", person["auth_id"]),
    ]

    def watch_void(auth_id, request_id):
        with db.connect(test_db_url) as other:
            seen.append(db.fetch_one(other, "SELECT status FROM events WHERE id = %s",
                                    (refund_case["event_id"],))["status"])
        return fake_paypal.answer(204, {})

    monkeypatch.setattr(fake_paypal, "void_authorization", watch_void)
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    assert seen == ["NEEDS_ATTENTION"]
    assert "refund_capture" not in fake_paypal.called_functions()
    hold = db.fetch_one(conn, "SELECT status, void_run_token, refund_check_status FROM holds WHERE id = %s",
                        (person["hold_id"],))
    assert hold["status"] == "VOIDED"
    assert hold["void_run_token"] is None
    assert hold["refund_check_status"] == "RESOLVED"
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDED"


def test_void_token_on_another_hold_blocks_handoff(refund_case):
    conn = refund_case["conn"]
    failed = insert_person(conn, refund_case["event_id"], "FAILED", "VOIDED")
    other = insert_person(conn, refund_case["event_id"], "HELD", "CREATED")
    db.run(conn, "UPDATE holds SET void_run_token = 'void-owner' WHERE id = %s", (other["hold_id"],))
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", failed["auth_id"])]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"
    assert db.fetch_one(conn, "SELECT void_run_token FROM holds WHERE id = %s",
                        (other["hold_id"],))["void_run_token"] == "void-owner"
    assert refund_rows(conn, refund_case["event_id"]) == []


def test_uncertain_void_blocks_handoff_and_keeps_the_token(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    created = fake_paypal.hold_read_back("CREATED", person["auth_id"])
    fake_paypal.next_answers["get_authorization"] = [created, created]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    hold = db.fetch_one(conn, "SELECT status, void_run_token FROM holds WHERE id = %s", (person["hold_id"],))
    assert hold["status"] == "CREATED"
    assert hold["void_run_token"] is not None
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"
    assert refund_rows(conn, refund_case["event_id"]) == []
    assert "refund_capture" not in fake_paypal.called_functions()


def test_captured_read_is_manual_review_and_blocks_refunded(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CAPTURED")
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CAPTURED", person["auth_id"])]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    hold = db.fetch_one(conn, "SELECT refund_check_status FROM holds WHERE id = %s", (person["hold_id"],))
    assert hold["refund_check_status"] == "MANUAL_REVIEW"
    assert "void_authorization" not in fake_paypal.called_functions()
    assert "refund_capture" not in fake_paypal.called_functions()
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"
    lifecycle.finish_refunding(conn, refund_case["event_id"],
                              event_row(conn, refund_case["event_id"])["refund_run_token"],
                              event_row(conn, refund_case["event_id"])["refund_revision"])
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"


def test_void_read_back_captured_is_manual_review(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    fake_paypal.next_answers["get_authorization"] = [
        fake_paypal.hold_read_back("CREATED", person["auth_id"]),
        fake_paypal.hold_read_back("CAPTURED", person["auth_id"]),
    ]
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    hold = db.fetch_one(conn, "SELECT status, void_run_token, refund_check_status FROM holds WHERE id = %s",
                        (person["hold_id"],))
    assert hold["status"] == "CAPTURED"
    assert hold["void_run_token"] is None
    assert hold["refund_check_status"] == "MANUAL_REVIEW"
    assert "refund_capture" not in fake_paypal.called_functions()
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"


def test_new_failed_pledge_during_get_blocks_handoff(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "VOIDED")
    insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")

    def drift(auth_id):
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        with db.connect(test_db_url) as other:
            insert_person(other, refund_case["event_id"], "FAILED", "CAPTURED")
        return fake_paypal.hold_read_back("VOIDED", auth_id)

    monkeypatch.setattr(fake_paypal, "get_authorization", drift)
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"
    assert refund_rows(conn, refund_case["event_id"]) == []
    assert posts() == []
    assert db.fetch_one(conn, "SELECT refund_check_status FROM holds WHERE id = %s",
                        (person["hold_id"],))["refund_check_status"] == "RESOLVED"


def test_changed_hold_during_get_blocks_handoff(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "VOIDED")

    def change_hold(auth_id):
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        with db.connect(test_db_url) as other:
            db.run(other, "UPDATE holds SET status = 'EXPIRED' WHERE id = %s", (person["hold_id"],))
        return fake_paypal.hold_read_back("VOIDED", auth_id)

    monkeypatch.setattr(fake_paypal, "get_authorization", change_hold)
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    assert event_row(conn, refund_case["event_id"])["status"] == "NEEDS_ATTENTION"
    assert db.fetch_one(conn, "SELECT refund_check_status FROM holds WHERE id = %s",
                        (person["hold_id"],))["refund_check_status"] is None


def test_check_write_refuses_after_refunding(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CAPTURED")
    db.run(conn, "UPDATE holds SET refund_check_status = 'MANUAL_REVIEW' WHERE id = %s", (person["hold_id"],))
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'owner-token', refund_revision = 1 "
                 "WHERE id = %s", (refund_case["event_id"],))
    snapshot = {"id": person["hold_id"], "event_id": refund_case["event_id"], "pledge_id": person["pledge_id"],
                "auth_id": person["auth_id"], "status": "CAPTURED", "void_run_token": None}
    assert lifecycle.save_refund_check(conn, snapshot, "RESOLVED") is False
    assert db.fetch_one(conn, "SELECT refund_check_status FROM holds WHERE id = %s",
                        (person["hold_id"],))["refund_check_status"] == "MANUAL_REVIEW"


def test_stale_token_cannot_save_completed(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")

    def replace_owner(capture_id, request_id):
        with db.connect(test_db_url) as other:
            db.run(other, "UPDATE events SET refund_run_token = 'replacement-owner' WHERE id = %s",
                   (refund_case["event_id"],))
            db.run(other, "UPDATE refunds SET status = 'FAILED' WHERE capture_id = %s", (person["capture"]["id"],))
        return fake_paypal.refund_result("REFUNDSTALE0001", "COMPLETED")

    monkeypatch.setattr(fake_paypal, "refund_capture", replace_owner)
    lifecycle.begin_refund_all(conn, refund_case["token"], fake_paypal)
    refund = refund_rows(conn, refund_case["event_id"])[0]
    assert refund["send_state"] == "IN_FLIGHT"
    assert refund["status"] == "FAILED"
    assert refund["refund_id"] is None
    assert event_row(conn, refund_case["event_id"])["refund_run_token"] == "replacement-owner"
    assert db.fetch_one(conn, "SELECT status FROM captures WHERE id = %s",
                        (person["capture"]["id"],))["status"] == "COMPLETED"
    assert db.fetch_one(conn, "SELECT status FROM pledges WHERE id = %s",
                        (person["pledge_id"],))["status"] == "CHARGED"


def test_stale_revision_cannot_reconcile_over_a_replacement(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'owner-token', refund_revision = 4 "
                 "WHERE id = %s", (refund_case["event_id"],))
    refund = db.fetch_one(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, refund_id, "
                                "send_state, send_started_at) VALUES (%s, %s, 640, 'REFUNDKEEP00001', "
                                "'ANSWERED', now()) RETURNING id",
                          (person["capture"]["id"], uuid.uuid4().hex))

    def replace_revision(refund_id):
        with db.connect(test_db_url) as other:
            db.run(other, "UPDATE events SET refund_revision = refund_revision + 1 WHERE id = %s",
                   (refund_case["event_id"],))
            db.run(other, "UPDATE refunds SET status = 'FAILED' WHERE id = %s", (refund["id"],))
        return fake_paypal.refund_result(refund_id, "COMPLETED")

    monkeypatch.setattr(fake_paypal, "get_refund", replace_revision)
    lifecycle.reconcile_refund(conn, refund["id"], fake_paypal)
    row = refund_rows(conn, refund_case["event_id"])[0]
    assert row["send_state"] == "ANSWERED"
    assert row["status"] == "FAILED"
    assert row["refund_id"] == "REFUNDKEEP00001"
    assert event_row(conn, refund_case["event_id"])["refund_revision"] == 5
    assert db.fetch_one(conn, "SELECT status FROM pledges WHERE id = %s",
                        (person["pledge_id"],))["status"] == "CHARGED"


def test_stale_retry_cannot_overwrite_a_replacement(monkeypatch, refund_case, test_db_url):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'owner-token', refund_revision = 3 "
                 "WHERE id = %s", (refund_case["event_id"],))
    refund = db.fetch_one(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, status, send_state) "
                                "VALUES (%s, %s, 640, 'FAILED', 'ANSWERED') RETURNING id, request_id",
                          (person["capture"]["id"], uuid.uuid4().hex))

    def replace_owner(capture_id, request_id):
        assert request_id == refund["request_id"]
        with db.connect(test_db_url) as other:
            db.run(other, "UPDATE events SET refund_run_token = 'replacement-owner' WHERE id = %s",
                   (refund_case["event_id"],))
            db.run(other, "UPDATE refunds SET status = 'CANCELLED' WHERE id = %s", (refund["id"],))
        return fake_paypal.refund_result("REFUNDRETRY0001", "COMPLETED")

    monkeypatch.setattr(fake_paypal, "refund_capture", replace_owner)
    lifecycle.retry_failed_refund(conn, refund["id"], fake_paypal)
    row = refund_rows(conn, refund_case["event_id"])[0]
    assert row["send_state"] == "ANSWERED"
    assert row["status"] == "FAILED"
    assert row["request_id"] == refund["request_id"]
    assert event_row(conn, refund_case["event_id"])["refund_run_token"] == "owner-token"
    assert db.fetch_one(conn, "SELECT status FROM captures WHERE id = %s",
                        (person["capture"]["id"],))["status"] == "COMPLETED"


def test_stale_finish_cannot_close_the_event(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'owner-token', refund_revision = 6 "
                 "WHERE id = %s", (refund_case["event_id"],))
    db.run(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, refund_id, status, send_state) "
                 "VALUES (%s, %s, 640, 'REFUNDDONE00001', 'COMPLETED', 'ANSWERED')",
           (person["capture"]["id"], uuid.uuid4().hex))
    db.run(conn, "UPDATE captures SET status = 'REFUNDED' WHERE id = %s", (person["capture"]["id"],))
    db.run(conn, "UPDATE pledges SET status = 'REFUNDED' WHERE id = %s", (person["pledge_id"],))
    db.run(conn, "UPDATE events SET refund_run_token = 'replacement-owner' WHERE id = %s",
           (refund_case["event_id"],))
    assert lifecycle.finish_refunding(conn, refund_case["event_id"], "owner-token", 6) is False
    assert event_row(conn, refund_case["event_id"])["status"] == "REFUNDING"
    assert event_row(conn, refund_case["event_id"])["refund_run_token"] == "replacement-owner"


def test_old_claim_is_not_cleared_or_resent(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE events SET status = 'REFUNDING', refund_run_token = 'owner-token', refund_revision = 2 "
                 "WHERE id = %s", (refund_case["event_id"],))
    db.run(conn, "INSERT INTO refunds (capture_id, request_id, amount_cents, send_state, send_started_at) "
                 "VALUES (%s, %s, 640, 'IN_FLIGHT', TIMESTAMP '2000-01-01')",
           (person["capture"]["id"], uuid.uuid4().hex))
    lifecycle.resume_refund_all(conn, refund_case["token"], fake_paypal)
    refund = refund_rows(conn, refund_case["event_id"])[0]
    assert refund["send_state"] == "IN_FLIGHT"
    assert event_row(conn, refund_case["event_id"])["refund_run_token"] == "owner-token"
    assert posts() == []
