# Tests for the D27 resume of a lock that died halfway (D81, docs/TEST_PLAN.md E11).
#
# They use the Neon test branch and tests/fake_paypal.py, like tests/test_lifecycle.py, whose helpers
# they borrow. They are skipped, with the reason shown, while TEST_DATABASE_URL is empty.
# A crash is simulated by making a fake PayPal call (or a lifecycle step) raise an error, so the lock
# stops exactly where a dead request would have stopped. Every test makes its own event and deletes it.

import inspect
import logging
import threading
import time
from datetime import timedelta

import pytest

import config
import db
import lifecycle
from tests import fake_paypal
from tests.test_lifecycle import (AFTER_DEADLINE, auth_id_of, calls_for, calls_to, delete_event,
                                  event_where_ana_waits_for_kim, make_open_event, only_capture_of,
                                  pledges_of, three_holds_that_reach_the_goal)

# A moment after the lock has been stuck for longer than STUCK_LOCK_AFTER (the crashed lock saved
# lock_started_at = AFTER_DEADLINE).
RESUME_NOW = AFTER_DEADLINE + config.STUCK_LOCK_AFTER + timedelta(minutes=1)
LATER_STILL = RESUME_NOW + config.STUCK_LOCK_AFTER + timedelta(minutes=1)


# Make the number-th capture call raise an error, like a request that died. With after_paypal=True the
# call first reaches the fake PayPal (the capture happened, the answer was lost). Returns nothing: the
# test restores the real function with monkeypatch.setattr(fake_paypal, "capture_authorization", original).
def crash_on_capture(monkeypatch, number, after_paypal=False):
    original = fake_paypal.capture_authorization
    seen = []

    def crashing(auth_id, amount_cents, request_id):
        seen.append(1)
        if len(seen) == number:
            if after_paypal:
                original(auth_id, amount_cents, request_id)
            raise RuntimeError("simulated crash during charging")
        return original(auth_id, amount_cents, request_id)

    monkeypatch.setattr(fake_paypal, "capture_authorization", crashing)
    return original


# Three pledges that reach the goal, locked at AFTER_DEADLINE, with the lock dying during the number-th
# capture. The first number-1 pledges are CHARGED, the number-th has a PENDING capture row, and the rest
# have none. The event is left in CHARGING. The fake's call log is cleared, so a test sees only the resume.
def stuck_charging_event(monkeypatch, conn, number=2, after_paypal=False):
    event_id = make_open_event(conn, 3000)
    three_holds_that_reach_the_goal(conn, event_id)
    original = crash_on_capture(monkeypatch, number, after_paypal)
    with pytest.raises(RuntimeError):
        lifecycle.lock_and_charge(conn, event_id, AFTER_DEADLINE, fake_paypal)
    monkeypatch.setattr(fake_paypal, "capture_authorization", original)
    fake_paypal.calls.clear()
    assert lifecycle.find_event(conn, event_id)["status"] == "CHARGING"
    return event_id


def event_status(conn, event_id):
    return lifecycle.find_event(conn, event_id)["status"]


def statuses(conn, event_id):
    names = []
    for pledge in pledges_of(conn, event_id):
        names.append(pledge["status"])
    return names


# ---------- E11: a lock that is not stuck yet ----------

# E11: a lock younger than STUCK_LOCK_AFTER is left alone: no PayPal call, nothing changes.
def test_e11_a_young_lock_is_left_alone(monkeypatch, test_db):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        young = AFTER_DEADLINE + config.STUCK_LOCK_AFTER - timedelta(minutes=1)
        lifecycle.settle_due_events(test_db, young, fake_paypal)
        assert lifecycle.resume_stuck_lock(test_db, event_id, young, fake_paypal) == "NOT_RESUMED"
        assert fake_paypal.calls == []
        assert event_status(test_db, event_id) == "CHARGING"
        assert statuses(test_db, event_id) == ["CHARGED", "HELD", "HELD"]
    finally:
        delete_event(test_db, event_id)


# ---------- E11: CHARGING ----------

# E11, the main case: the lock died during the second capture, after its row was saved and before PayPal
# heard of it. settle_due_events resumes it. Ana (CHARGED) gets no PayPal call at all. Bo's PENDING row is
# sent again with the SAME saved request ID, on the same row, after a GET shows the hold still CREATED.
# Cy has no row yet, so he is charged the normal way. Each authorization is captured once.
def test_e11_resume_finishes_charging_after_a_crash(test_db, monkeypatch):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        auth_ana, auth_bo, auth_cy = auth_id_of(test_db, ana["id"]), auth_id_of(test_db, bo["id"]), auth_id_of(test_db, cy["id"])
        saved_row = only_capture_of(test_db, bo["id"])
        assert saved_row["status"] == "PENDING"
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_bo)]
        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        assert event_status(test_db, event_id) == "SETTLED"
        assert statuses(test_db, event_id) == ["CHARGED", "CHARGED", "CHARGED"]
        bo_row = only_capture_of(test_db, bo["id"])
        assert bo_row["status"] == "COMPLETED"
        assert bo_row["request_id"] == saved_row["request_id"]
        assert [call["request_id"] for call in calls_for("capture_authorization", [auth_bo])] == [saved_row["request_id"]]
        assert len(calls_for("capture_authorization", [auth_cy])) == 1
        assert calls_for("capture_authorization", [auth_ana]) == []
        assert calls_for("get_authorization", [auth_ana]) == []
        assert len(calls_to("get_capture")) == 2
    finally:
        delete_event(test_db, event_id)


# E11 / D47 / D49: the lock died AFTER PayPal captured Bo's share (the answer was lost). The GET shows
# CAPTURED, so there is no capture call: the hold is saved CAPTURED, the row stays PENDING, Bo is FAILED,
# an error is logged, Cy is still charged, and the event ends NEEDS_ATTENTION.
def test_e11_a_pending_row_whose_hold_reads_captured_follows_d47(caplog, monkeypatch, test_db):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db, after_paypal=True)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        auth_bo = auth_id_of(test_db, bo["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CAPTURED", auth_bo)]
        with caplog.at_level(logging.ERROR):
            lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        assert calls_for("capture_authorization", [auth_bo]) == []
        row = only_capture_of(test_db, bo["id"])
        assert row["status"] == "PENDING"
        assert row["hold_status"] == "CAPTURED"
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
        assert event_status(test_db, event_id) == "NEEDS_ATTENTION"
        assert "CAPTURED" in caplog.text
    finally:
        delete_event(test_db, event_id)


# E11: a PENDING row whose hold reads VOIDED (or anything but CREATED or CAPTURED) is a failed charge:
# no capture call, the row and the pledge FAILED, the event NEEDS_ATTENTION, and the others are charged.
def test_e11_a_pending_row_whose_hold_is_closed_fails_the_pledge(monkeypatch, test_db):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        auth_bo = auth_id_of(test_db, bo["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", auth_bo)]
        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        assert calls_for("capture_authorization", [auth_bo]) == []
        assert only_capture_of(test_db, bo["id"])["status"] == "FAILED"
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
        assert event_status(test_db, event_id) == "NEEDS_ATTENTION"
    finally:
        delete_event(test_db, event_id)


# E11: no answer to the GET. Nothing is decided about Bo (still HELD, row PENDING), Cy is charged, and
# the event stays CHARGING. A resume inside STUCK_LOCK_AFTER does nothing; one after it finishes the job.
def test_e11_no_answer_from_the_get_leaves_the_event_charging_until_the_next_resume(monkeypatch, test_db):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        auth_bo = auth_id_of(test_db, bo["id"])
        saved_row = only_capture_of(test_db, bo["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.no_answer()]
        assert lifecycle.resume_stuck_lock(test_db, event_id, RESUME_NOW, fake_paypal) == "CHARGING"
        assert calls_for("capture_authorization", [auth_bo]) == []
        assert statuses(test_db, event_id) == ["CHARGED", "HELD", "CHARGED"]
        assert event_status(test_db, event_id) == "CHARGING"

        fake_paypal.calls.clear()
        assert lifecycle.resume_stuck_lock(test_db, event_id, RESUME_NOW + timedelta(minutes=1), fake_paypal) == "NOT_RESUMED"
        assert fake_paypal.calls == []

        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_bo)]
        assert lifecycle.resume_stuck_lock(test_db, event_id, LATER_STILL, fake_paypal) == "SETTLED"
        assert [call["request_id"] for call in calls_for("capture_authorization", [auth_bo])] == [saved_row["request_id"]]
        assert statuses(test_db, event_id) == ["CHARGED", "CHARGED", "CHARGED"]
    finally:
        delete_event(test_db, event_id)


# E11: the lock died inside record_failed_charge: Bo's row is FAILED but his pledge is still HELD. The
# resume marks him FAILED with no capture call, and the event ends NEEDS_ATTENTION.
def test_e11_a_failed_row_with_a_held_pledge_becomes_failed(monkeypatch, test_db):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        auth_bo = auth_id_of(test_db, bo["id"])
        db.run(test_db, "UPDATE captures SET status = 'FAILED', error_code = 'TRANSACTION_REFUSED' "
                        "WHERE id = %s", (only_capture_of(test_db, bo["id"])["id"],))
        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        assert calls_for("capture_authorization", [auth_bo]) == []
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
        assert event_status(test_db, event_id) == "NEEDS_ATTENTION"
    finally:
        delete_event(test_db, event_id)


# E11: the lock died inside record_charge: Bo's row is COMPLETED (with its capture ID) but his pledge is
# still HELD and his hold CREATED. The resume finishes recording it: no capture call, the hold CAPTURED,
# the pledge CHARGED, and the fee and net read back with a GET of that capture.
def test_e11_a_completed_row_with_a_held_pledge_is_finished_without_a_capture(monkeypatch, test_db):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        auth_bo = auth_id_of(test_db, bo["id"])
        db.run(test_db, "UPDATE captures SET status = 'COMPLETED', capture_id = '3CAPTUREFORBO01' WHERE id = %s",
               (only_capture_of(test_db, bo["id"])["id"],))
        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        assert calls_for("capture_authorization", [auth_bo]) == []
        row = only_capture_of(test_db, bo["id"])
        assert row["hold_status"] == "CAPTURED"
        assert row["fee_cents"] == 62 and row["net_cents"] == 438
        assert {"function": "get_capture", "capture_id": "3CAPTUREFORBO01"} in fake_paypal.calls
        assert statuses(test_db, event_id) == ["CHARGED", "CHARGED", "CHARGED"]
        assert event_status(test_db, event_id) == "SETTLED"
    finally:
        delete_event(test_db, event_id)


# E11 / rule 5: the resent capture comes back HTTP 201 but with status PENDING, which is not a charge.
# Bo is FAILED with the reason saved, and the event ends NEEDS_ATTENTION.
def test_e11_a_resent_capture_that_is_not_completed_fails_the_pledge(monkeypatch, test_db):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        auth_bo = auth_id_of(test_db, bo["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_bo)]
        fake_paypal.next_answers["capture_authorization"] = [fake_paypal.captured(fake_paypal.new_id("CAPTURE"), "PENDING")]
        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        row = only_capture_of(test_db, bo["id"])
        assert row["status"] == "FAILED"
        assert row["error_code"] == "STATUS_PENDING"
        assert statuses(test_db, event_id) == ["CHARGED", "FAILED", "CHARGED"]
        assert event_status(test_db, event_id) == "NEEDS_ATTENTION"
    finally:
        delete_event(test_db, event_id)


# E11: a pledge that FAILED in the first run still counts. Ana's capture was refused before the crash;
# the resume charges Bo and Cy, and the event ends NEEDS_ATTENTION because of her.
def test_e11_a_failure_from_the_first_run_still_ends_needs_attention(monkeypatch, test_db):
    fake_paypal.reset()
    fake_paypal.next_answers["capture_authorization"] = [fake_paypal.capture_refused("TRANSACTION_REFUSED")]
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        assert ana["status"] == "FAILED"
        auth_ana, auth_bo = auth_id_of(test_db, ana["id"]), auth_id_of(test_db, bo["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_bo)]
        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        assert statuses(test_db, event_id) == ["FAILED", "CHARGED", "CHARGED"]
        assert event_status(test_db, event_id) == "NEEDS_ATTENTION"
        assert calls_for("capture_authorization", [auth_ana]) == []
    finally:
        delete_event(test_db, event_id)


# ---------- E11: two requests, and a resume that dies ----------

# E11: two requests resume the same stuck event at the same moment. The fake capture is slow and every GET
# says CREATED, so a second resumer WOULD send Bo's capture again. Only one wins the compare-and-set, so
# each authorization is captured exactly once.
def test_e11_two_resumes_at_once_capture_each_share_once(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db, number=1)
    barrier = threading.Barrier(2)
    errors = []
    original_capture = fake_paypal.capture_authorization
    original_get = fake_paypal.get_authorization

    def slow_capture(auth_id, amount_cents, request_id):
        time.sleep(0.4)
        return original_capture(auth_id, amount_cents, request_id)

    def get_says_created(auth_id):
        original_get(auth_id)
        return fake_paypal.hold_read_back("CREATED", auth_id)

    def resume_in_its_own_connection():
        try:
            conn = db.connect(test_db_url)
            try:
                barrier.wait(timeout=30)
                lifecycle.settle_due_events(conn, RESUME_NOW, fake_paypal)
            finally:
                conn.close()
        except Exception as error:      # a thread's error is otherwise only printed, so keep it to check
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "capture_authorization", slow_capture)
    monkeypatch.setattr(fake_paypal, "get_authorization", get_says_created)
    try:
        auth_ids = []
        for pledge in pledges_of(test_db, event_id):
            auth_ids.append(auth_id_of(test_db, pledge["id"]))
        workers = []
        for count in range(2):
            worker = threading.Thread(target=resume_in_its_own_connection)
            worker.start()
            workers.append(worker)
        for worker in workers:
            worker.join(timeout=60)
        assert errors == []
        for auth_id in auth_ids:
            assert len(calls_for("capture_authorization", [auth_id])) == 1
        assert event_status(test_db, event_id) == "SETTLED"
        assert statuses(test_db, event_id) == ["CHARGED", "CHARGED", "CHARGED"]
    finally:
        delete_event(test_db, event_id)


# E11: a resume that itself dies is picked up again, but only after another STUCK_LOCK_AFTER (it saves
# lock_started_at again). Bo's capture row is still the same single row with the same request ID.
def test_e11_a_resume_that_dies_is_resumed_again_later(monkeypatch, test_db):
    fake_paypal.reset()
    event_id = stuck_charging_event(monkeypatch, test_db)
    try:
        ana, bo, cy = pledges_of(test_db, event_id)
        auth_bo = auth_id_of(test_db, bo["id"])
        saved_row = only_capture_of(test_db, bo["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_bo)]
        original = crash_on_capture(monkeypatch, 1)
        with pytest.raises(RuntimeError):
            lifecycle.resume_stuck_lock(test_db, event_id, RESUME_NOW, fake_paypal)
        monkeypatch.setattr(fake_paypal, "capture_authorization", original)
        assert lifecycle.resume_stuck_lock(test_db, event_id, RESUME_NOW + timedelta(minutes=1), fake_paypal) == "NOT_RESUMED"

        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_bo)]
        lifecycle.settle_due_events(test_db, LATER_STILL, fake_paypal)
        assert event_status(test_db, event_id) == "SETTLED"
        assert only_capture_of(test_db, bo["id"])["request_id"] == saved_row["request_id"]
        assert len(calls_for("capture_authorization", [auth_bo])) == 1
    finally:
        delete_event(test_db, event_id)


# ---------- E11: LOCKING ----------

# E11, D78: the lock died in LOCKING after the shares were saved (while voiding the uncounted holds). The
# world then changes: Ana's condition is removed and Bo's max is raised, so working out the counted set
# or the shares again would give different answers. The resume works out nothing: it voids the hold of the
# pledge with no saved share (Ana), drops her, and charges exactly the saved shares.
def test_e11_locking_after_shares_were_saved_never_recomputes(monkeypatch, test_db):
    fake_paypal.reset()
    event_id = event_where_ana_waits_for_kim(test_db)
    try:
        original = lifecycle.void_uncounted_holds

        def crash(conn, held, counted, paypal):
            raise RuntimeError("simulated crash while voiding the uncounted holds")

        monkeypatch.setattr(lifecycle, "void_uncounted_holds", crash)
        with pytest.raises(RuntimeError):
            lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal)
        monkeypatch.setattr(lifecycle, "void_uncounted_holds", original)

        ana, bo, cy, dee = pledges_of(test_db, event_id)
        assert event_status(test_db, event_id) == "LOCKING"
        assert ana["share_cents"] is None
        saved_shares = [bo["share_cents"], cy["share_cents"], dee["share_cents"]]
        assert None not in saved_shares
        auth_ana = auth_id_of(test_db, ana["id"])
        db.run(test_db, "DELETE FROM pledge_conditions WHERE pledge_id = %s", (ana["id"],))
        db.run(test_db, "UPDATE pledges SET max_cents = 3000 WHERE id = %s", (bo["id"],))
        fake_paypal.calls.clear()

        assert lifecycle.resume_stuck_lock(test_db, event_id, RESUME_NOW, fake_paypal) == "SETTLED"
        ana, bo, cy, dee = pledges_of(test_db, event_id)
        assert ana["status"] == "DROPPED"
        assert [bo["status"], cy["status"], dee["status"]] == ["CHARGED", "CHARGED", "CHARGED"]
        assert [bo["share_cents"], cy["share_cents"], dee["share_cents"]] == saved_shares
        assert only_capture_of(test_db, bo["id"])["amount_cents"] == saved_shares[0]
        assert only_capture_of(test_db, cy["id"])["amount_cents"] == saved_shares[1]
        assert only_capture_of(test_db, dee["id"])["amount_cents"] == saved_shares[2]
        assert calls_for("capture_authorization", [auth_ana]) == []
        assert len(calls_for("void_authorization", [auth_ana])) == 1
        assert len(calls_to("capture_authorization")) == 3
    finally:
        delete_event(test_db, event_id)


# E11, D81 case 1: the lock died in LOCKING while the shares were being saved. save_shares is one
# transaction, so a second connection sees NO goal and NO share (all or nothing). No first result was
# saved, so D78 has nothing to protect: the resume puts the event back to LAST_CALL and the normal lock
# runs, which works the shares out and charges. Each share is captured once.
def test_e11_locking_before_shares_were_saved_runs_the_normal_lock(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    other = db.connect(test_db_url)
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        fake_paypal.calls.clear()
        original_run = db.run
        share_updates = []

        def crashing_run(conn, sql, params=()):
            if sql.startswith("UPDATE pledges SET share_cents"):
                share_updates.append(1)
                if len(share_updates) == 2:
                    raise RuntimeError("simulated crash while saving the shares")
            return original_run(conn, sql, params)

        monkeypatch.setattr(db, "run", crashing_run)
        with pytest.raises(RuntimeError):
            lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal)
        monkeypatch.setattr(db, "run", original_run)

        event = lifecycle.find_event(other, event_id)
        assert event["status"] == "LOCKING"
        assert event["goal_cents"] is None
        for pledge in pledges_of(other, event_id):
            assert pledge["share_cents"] is None
        assert fake_paypal.calls == []

        lifecycle.settle_due_events(test_db, RESUME_NOW, fake_paypal)
        assert event_status(test_db, event_id) == "SETTLED"
        assert lifecycle.find_event(test_db, event_id)["goal_cents"] is not None
        assert statuses(test_db, event_id) == ["CHARGED", "CHARGED", "CHARGED"]
        for pledge in pledges_of(test_db, event_id):
            assert len(calls_for("capture_authorization", [auth_id_of(test_db, pledge["id"])])) == 1
    finally:
        other.close()
        delete_event(test_db, event_id)


# ---------- E11 / rule 6: one capture call ----------

# Rule 6 (D81): send_capture is the only place in lifecycle.py that calls PayPal's capture, and none of
# the resume functions names it.
def test_e11_send_capture_is_the_only_capture_call():
    source = open(lifecycle.__file__, encoding="utf-8").read()
    assert source.count("paypal.capture_authorization(") == 1
    assert "paypal.capture_authorization(" in inspect.getsource(lifecycle.send_capture)
    for function in (lifecycle.resume_stuck_lock, lifecycle.win_resume, lifecycle.resume_charging,
                     lifecycle.resume_one_pledge, lifecycle.resend_pending_capture, lifecycle.finish_charging,
                     lifecycle.finish_locking_from_saved_shares):
        assert "capture_authorization" not in inspect.getsource(function)
