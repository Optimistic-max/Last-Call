# Tests for retrying a failed charge once (D83, docs/TEST_PLAN.md F4 and F14).
#
# The rule: a capture that fails is retried ONCE, inside the lock, as attempt 2 with a NEW saved request ID,
# and only if the GET of the hold answered CREATED and PayPal sent back no capture ID. Attempt 2 is final.
# A PENDING row is never retried this way: that is the resume's job (D81), with its own saved request ID.
#
# They use the Neon test branch and tests/fake_paypal.py, like tests/test_lifecycle.py, whose helpers they
# borrow. They are skipped, with the reason shown, while TEST_DATABASE_URL is empty.
# In every event here the three pledges join in the order Ana, Bo, Cy, so the fake's capture answers are
# queued in that order: Ana first, then Bo's attempt 1 (and attempt 2 if there is one), then Cy.

import inspect
import logging

import pytest

import db
import lifecycle
from tests import fake_paypal
from tests.test_lifecycle import (AFTER_DEADLINE, auth_id_of, calls_for, calls_to, captures_of, delete_event,
                                  make_open_event, pledges_of, three_holds_that_reach_the_goal)
from tests.test_resume import RESUME_NOW, crash_on_capture


def ok():
    return fake_paypal.captured(fake_paypal.new_id("CAPTURE"), "COMPLETED")


def refused():
    return fake_paypal.capture_refused("TRANSACTION_REFUSED")


def lock(conn, event_id):
    return lifecycle.lock_and_charge(conn, event_id, AFTER_DEADLINE, fake_paypal)


def event_status(conn, event_id):
    return lifecycle.find_event(conn, event_id)["status"]


def statuses(conn, event_id):
    names = []
    for pledge in pledges_of(conn, event_id):
        names.append(pledge["status"])
    return names


def assert_no_refund_was_called():
    for name in fake_paypal.called_functions():
        assert "refund" not in name


# A $30 event with Ana, Bo and Cy held and last call open, ready to lock. Returns the event ID, Bo's
# pledge and Bo's authorization ID.
def ready_event(conn):
    event_id = make_open_event(conn, 3000)
    three_holds_that_reach_the_goal(conn, event_id)
    fake_paypal.calls.clear()
    bo = pledges_of(conn, event_id)[1]
    return event_id, bo, auth_id_of(conn, bo["id"])


# ---------- F4: the retry ----------

# F4a: Bo's first capture is refused and the GET says his hold is still CREATED, so he is retried. Attempt 2
# is a NEW row with attempt = 2 and a NEW request ID, and both rows are saved (PENDING) before their
# calls go out (rule 3, a second connection looks). Attempt 2 completes: Bo is CHARGED, the fee and net are
# saved on row 2, and the event ends SETTLED. Bo gets 2 capture calls, the others 1. Nothing is refunded.
def test_f4a_a_refused_capture_with_the_hold_still_created_is_retried_once(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    other = db.connect(test_db_url)
    seen = []
    original = fake_paypal.capture_authorization

    def checking_capture(auth_id, amount_cents, request_id):
        row = db.fetch_one(other, "SELECT attempt, status FROM captures WHERE request_id = %s", (request_id,))
        if auth_id == bo_auth:
            seen.append(row)
        return original(auth_id, amount_cents, request_id)

    monkeypatch.setattr(fake_paypal, "capture_authorization", checking_capture)
    try:
        fake_paypal.next_answers["capture_authorization"] = [ok(), refused(), ok()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth)]
        assert lock(test_db, event_id) == "SETTLED"
        assert seen == [{"attempt": 1, "status": "PENDING"}, {"attempt": 2, "status": "PENDING"}]
        rows = captures_of(test_db, bo["id"])
        assert [row["attempt"] for row in rows] == [1, 2]
        assert [row["status"] for row in rows] == ["FAILED", "COMPLETED"]
        assert rows[0]["error_code"] == "TRANSACTION_REFUSED"
        assert rows[0]["request_id"] != rows[1]["request_id"]
        assert rows[0]["amount_cents"] == rows[1]["amount_cents"]
        assert rows[1]["fee_cents"] == 62 and rows[1]["net_cents"] == 438
        assert [call["request_id"] for call in calls_for("capture_authorization", [bo_auth])] == \
            [rows[0]["request_id"], rows[1]["request_id"]]
        assert statuses(test_db, event_id) == ["CHARGED", "CHARGED", "CHARGED"]
        assert len(calls_to("capture_authorization")) == 4
        assert_no_refund_was_called()
    finally:
        other.close()
        delete_event(test_db, event_id)


# F4b: refused twice (the hold still CREATED both times): Bo is FAILED after attempt 2, with exactly 2 calls
# and 2 rows, never a third. The other two stay CHARGED, nothing is refunded, and the event ends
# NEEDS_ATTENTION.
def test_f4b_refused_twice_fails_the_pledge_after_exactly_two_attempts(test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [ok(), refused(), refused(), ok()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth),
                                                         fake_paypal.hold_read_back("CREATED", bo_auth)]
        assert lock(test_db, event_id) == "NEEDS_ATTENTION"
        rows = captures_of(test_db, bo["id"])
        assert [row["attempt"] for row in rows] == [1, 2]
        assert [row["status"] for row in rows] == ["FAILED", "FAILED"]
        assert rows[1]["hold_status"] == "CREATED"
        assert len(calls_for("capture_authorization", [bo_auth])) == 2
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
        assert len(calls_to("capture_authorization")) == 4
        assert_no_refund_was_called()
    finally:
        delete_event(test_db, event_id)


# F4b, rule 5: attempt 2 comes back HTTP 201 but with status PENDING. That is not a charge: Bo is FAILED,
# the reason is saved, and there is no attempt 3.
def test_f4b_attempt_two_answering_pending_is_not_a_charge(test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [
            ok(), refused(), fake_paypal.captured(fake_paypal.new_id("CAPTURE"), "PENDING"), ok()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth),
                                                         fake_paypal.hold_read_back("CREATED", bo_auth)]
        assert lock(test_db, event_id) == "NEEDS_ATTENTION"
        rows = captures_of(test_db, bo["id"])
        assert [row["status"] for row in rows] == ["FAILED", "FAILED"]
        assert rows[1]["error_code"] == "STATUS_PENDING"
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
    finally:
        delete_event(test_db, event_id)


# F4c: "no answer" CASE 1 of 2. The CAPTURE call itself timed out (no answer from PayPal), but the GET of
# the hold DID answer, and says CREATED: nothing was captured, so Bo is retried with a new request ID and
# this time it works. Do NOT merge this into the next test: they look alike and have opposite results.
def test_f4c_a_capture_that_times_out_with_the_hold_still_created_is_retried(test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [ok(), fake_paypal.no_answer(), ok()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth)]
        assert lock(test_db, event_id) == "SETTLED"
        rows = captures_of(test_db, bo["id"])
        assert [row["attempt"] for row in rows] == [1, 2]
        assert [row["status"] for row in rows] == ["FAILED", "COMPLETED"]
        assert rows[0]["error_code"] == "NO_ANSWER"
        assert rows[0]["request_id"] != rows[1]["request_id"]
        assert len(calls_for("capture_authorization", [bo_auth])) == 2
        assert statuses(test_db, event_id) == ["CHARGED", "CHARGED", "CHARGED"]
    finally:
        delete_event(test_db, event_id)


# F4 / Q3: "no answer" CASE 2 of 2. The capture timed out AND the GET of the hold got no answer either.
# We cannot tell whether money moved, so there is NO retry: Bo is FAILED after exactly one capture call
# (D39), the event ends NEEDS_ATTENTION, and the others stay CHARGED. Do NOT "fix" this into case 1: a
# retry here could be a second attempt on a hold that was already captured.
def test_q3_a_get_that_gets_no_answer_means_no_retry(test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [ok(), fake_paypal.no_answer(), ok()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.no_answer()]
        assert lock(test_db, event_id) == "NEEDS_ATTENTION"
        rows = captures_of(test_db, bo["id"])
        assert [row["attempt"] for row in rows] == [1]
        assert rows[0]["status"] == "FAILED" and rows[0]["error_code"] == "NO_ANSWER"
        assert len(calls_for("capture_authorization", [bo_auth])) == 1
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
        assert_no_refund_was_called()
    finally:
        delete_event(test_db, event_id)


# ---------- F14: when there is no retry ----------

# F14a, D47: the capture's answer was lost and the GET says CAPTURED: the money moved. No retry: exactly one
# capture call, the row stays PENDING, the hold is saved CAPTURED, Bo is FAILED, an error is logged, and
# the event ends NEEDS_ATTENTION.
def test_f14a_a_hold_that_reads_captured_is_never_retried(caplog, test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [ok(), fake_paypal.no_answer(), ok()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CAPTURED", bo_auth)]
        with caplog.at_level(logging.ERROR):
            assert lock(test_db, event_id) == "NEEDS_ATTENTION"
        rows = captures_of(test_db, bo["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "PENDING" and rows[0]["hold_status"] == "CAPTURED"
        assert len(calls_for("capture_authorization", [bo_auth])) == 1
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
        assert "CAPTURED" in caplog.text
    finally:
        delete_event(test_db, event_id)


# F14b: the GET says VOIDED or EXPIRED: the hold can't be charged, so no retry. One capture call, the row
# and the pledge FAILED, and the event NEEDS_ATTENTION.
def test_f14b_a_hold_that_reads_voided_or_expired_is_never_retried(test_db):
    fake_paypal.reset()
    event_ids = []
    try:
        for hold_status in ("VOIDED", "EXPIRED"):
            event_id, bo, bo_auth = ready_event(test_db)
            event_ids.append(event_id)
            fake_paypal.next_answers["capture_authorization"] = [ok(), refused(), ok()]
            fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back(hold_status, bo_auth)]
            assert lock(test_db, event_id) == "NEEDS_ATTENTION", hold_status
            rows = captures_of(test_db, bo["id"])
            assert len(rows) == 1 and rows[0]["status"] == "FAILED", hold_status
            assert len(calls_for("capture_authorization", [bo_auth])) == 1, hold_status
            assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"], hold_status
    finally:
        for event_id in event_ids:
            delete_event(test_db, event_id)


# F14c: the first answer is HTTP 201 WITH a capture ID but status PENDING, and the GET says CREATED. A capture
# object already exists at PayPal, so a second capture could make another one: no retry. Bo is FAILED.
def test_f14c_an_answer_that_carries_a_capture_id_is_never_retried(test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [
            ok(), fake_paypal.captured(fake_paypal.new_id("CAPTURE"), "PENDING"), ok()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth)]
        assert lock(test_db, event_id) == "NEEDS_ATTENTION"
        rows = captures_of(test_db, bo["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "FAILED" and rows[0]["error_code"] == "STATUS_PENDING"
        assert rows[0]["capture_id"] is not None
        assert len(calls_for("capture_authorization", [bo_auth])) == 1
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
    finally:
        delete_event(test_db, event_id)


# F14d, D47 on attempt 2: attempt 1 is refused (hold CREATED), attempt 2's answer is lost and the GET now says
# CAPTURED. Attempt 2's row stays PENDING, the hold is saved CAPTURED, Bo is FAILED, and there is no attempt 3.
def test_f14d_a_lost_answer_on_attempt_two_follows_d47(test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [ok(), refused(), fake_paypal.no_answer(), ok()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth),
                                                         fake_paypal.hold_read_back("CAPTURED", bo_auth)]
        assert lock(test_db, event_id) == "NEEDS_ATTENTION"
        rows = captures_of(test_db, bo["id"])
        assert [row["attempt"] for row in rows] == [1, 2]
        assert [row["status"] for row in rows] == ["FAILED", "PENDING"]
        assert rows[1]["hold_status"] == "CAPTURED"
        assert len(calls_for("capture_authorization", [bo_auth])) == 2
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
    finally:
        delete_event(test_db, event_id)


# ---------- F4 and the resume (D81) ----------

# F4e: the lock dies DURING attempt 2 (its row is saved PENDING, the call never reaches PayPal). The resume
# sends THAT row again with its own saved request ID, after a GET shows the hold CREATED. It never makes
# an attempt 3: Bo ends with exactly 2 rows. The event is SETTLED.
def test_f4e_a_lock_that_dies_during_attempt_two_is_resumed_without_an_attempt_three(monkeypatch, test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [ok(), refused()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth)]
        original = crash_on_capture(monkeypatch, 3)
        with pytest.raises(RuntimeError):
            lock(test_db, event_id)
        monkeypatch.setattr(fake_paypal, "capture_authorization", original)
        rows = captures_of(test_db, bo["id"])
        assert [row["status"] for row in rows] == ["FAILED", "PENDING"]
        assert event_status(test_db, event_id) == "CHARGING"

        fake_paypal.calls.clear()
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth)]
        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        rows_after = captures_of(test_db, bo["id"])
        assert [row["attempt"] for row in rows_after] == [1, 2]
        assert [call["request_id"] for call in calls_for("capture_authorization", [bo_auth])] == \
            [rows[1]["request_id"]]
        assert statuses(test_db, event_id) == ["CHARGED", "CHARGED", "CHARGED"]
        assert event_status(test_db, event_id) == "SETTLED"
    finally:
        delete_event(test_db, event_id)


# F4e (Q4): the lock dies BETWEEN the two attempts (attempt 1 failed and was saved FAILED, attempt 2 was
# never started). The resume does NOT start an attempt 2: Bo's pledge is marked FAILED with no capture call,
# and the event ends NEEDS_ATTENTION. Conservative on purpose.
def test_f4e_a_lock_that_dies_between_the_attempts_fails_the_pledge_without_a_capture(monkeypatch, test_db):
    fake_paypal.reset()
    event_id, bo, bo_auth = ready_event(test_db)
    try:
        fake_paypal.next_answers["capture_authorization"] = [ok(), refused()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", bo_auth)]
        original_new_request_id = lifecycle.new_request_id
        made = []

        def dying_new_request_id():
            made.append(1)
            if len(made) == 3:
                raise RuntimeError("simulated crash between the two attempts")
            return original_new_request_id()

        monkeypatch.setattr(lifecycle, "new_request_id", dying_new_request_id)
        with pytest.raises(RuntimeError):
            lock(test_db, event_id)
        monkeypatch.setattr(lifecycle, "new_request_id", original_new_request_id)
        rows = captures_of(test_db, bo["id"])
        assert [row["status"] for row in rows] == ["FAILED"]
        assert pledges_of(test_db, event_id)[1]["status"] == "HELD"

        fake_paypal.calls.clear()
        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        assert calls_for("capture_authorization", [bo_auth]) == []
        assert len(captures_of(test_db, bo["id"])) == 1
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
        assert event_status(test_db, event_id) == "NEEDS_ATTENTION"
    finally:
        delete_event(test_db, event_id)


# ---------- rule 6 ----------

# Rule 6 still holds with the retry: send_capture is the only place in lifecycle.py that calls PayPal's
# capture, and the retry (charge_one_pledge) goes through it.
def test_f4_send_capture_is_still_the_only_capture_call():
    source = open(lifecycle.__file__, encoding="utf-8").read()
    assert source.count("paypal.capture_authorization(") == 1
    assert "paypal.capture_authorization(" in inspect.getsource(lifecycle.send_capture)
    assert "capture_authorization" not in inspect.getsource(lifecycle.charge_one_pledge)
    assert "send_capture(" in inspect.getsource(lifecycle.charge_one_pledge)
