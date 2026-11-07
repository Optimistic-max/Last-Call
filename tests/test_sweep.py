# Tests for the cleanup sweep, lifecycle.sweep_stranded_holds (D80, docs/TEST_PLAN.md F2, F12, F16-F21).
#
# They use the Neon test branch and tests/fake_paypal.py, like tests/test_lifecycle.py, whose helpers
# they borrow. They are skipped, with the reason shown, while TEST_DATABASE_URL is empty.
# Every test makes its own event and deletes it at the end. No test here may ever see a capture call:
# the sweep only cancels holds (AGENTS.md rule 6).

import inspect
import logging
import threading
import time
from datetime import timedelta

import psycopg

import config
import db
import lifecycle
from tests import fake_paypal
from tests.test_lifecycle import (AFTER_DEADLINE, NOW, auth_id_of, calls_for, calls_to, delete_event,
                                  event_where_ana_waits_for_kim, hold_for_order, make_open_event,
                                  pledge_and_authorize, pledges_of, set_event_status)

# The clock for every sweep: an hour after the deadline, so every hold is old enough to count as
# abandoned (PENDING_HOLD_GRACE) and nothing was tried recently (VOID_RETRY_AFTER).
SWEEP_NOW = AFTER_DEADLINE + timedelta(hours=1)

FINISHED = ("EXPIRED", "SETTLED", "NEEDS_ATTENTION")


# One HELD pledge (Ana, $40) with a CREATED hold, on an event that is then given this status.
# Returns the event ID and Ana's order ID.
def held_pledge_on_event(conn, status):
    event_id = make_open_event(conn)
    token, order_id, result = pledge_and_authorize(conn, event_id, "Ana", 4000)
    assert result["outcome"] == "HELD"
    set_event_status(conn, event_id, status)
    return event_id, order_id


def pledge_status(conn, event_id, name):
    return lifecycle.find_pledge_by_name(conn, event_id, name)["status"]


# A sweep with a fresh PayPal log. The fake's calls start empty each time.
def sweep(conn, now=SWEEP_NOW):
    lifecycle.sweep_stranded_holds(conn, now, fake_paypal)


def assert_nothing_was_captured():
    assert calls_to("capture_authorization") == []


# ---------- F2: a CREATED hold on a finished event is voided ----------

# F2: on an EXPIRED, a SETTLED and a NEEDS_ATTENTION event, the sweep voids the stranded hold. Its void
# request ID is already saved when the void call goes out (a second connection looks, rule 3). PayPal's
# GET says VOIDED, so the pledge is DROPPED. Nothing is captured.
def test_f2_the_sweep_voids_a_created_hold_on_a_finished_event(monkeypatch, test_db, test_db_url):
    other = db.connect(test_db_url)
    try:
        for status in FINISHED:
            fake_paypal.reset()
            event_id, order_id = held_pledge_on_event(test_db, status)
            saved_before_call = []
            original_void = fake_paypal.void_authorization

            def checking_void(auth_id, request_id):
                row = db.fetch_one(other, "SELECT id FROM holds WHERE void_request_id = %s", (request_id,))
                saved_before_call.append(row is not None)
                return original_void(auth_id, request_id)

            monkeypatch.setattr(fake_paypal, "void_authorization", checking_void)
            try:
                sweep(test_db)
                hold = hold_for_order(test_db, order_id)
                assert saved_before_call == [True]
                assert hold["status"] == "VOIDED"
                assert hold["void_tried_at"] == SWEEP_NOW
                assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
                assert lifecycle.find_event(test_db, event_id)["status"] == status
                assert_nothing_was_captured()
            finally:
                monkeypatch.setattr(fake_paypal, "void_authorization", original_void)
                delete_event(test_db, event_id)
    finally:
        other.close()


# F2: a hold whose pledge is DROPPED is voided even on a live event. The sweep does not drop anyone else
# there: Bo is still unpaid (PENDING_PAY, no hold) and stays that way.
def test_f2_a_dropped_pledges_hold_is_voided_on_a_live_event(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "OPEN")
    try:
        lifecycle.confirm_pledge(test_db, event_id, "Bo", 2500, NOW)
        db.run(test_db, "UPDATE pledges SET status = 'DROPPED' WHERE event_id = %s AND name = 'Ana'", (event_id,))
        sweep(test_db)
        assert hold_for_order(test_db, order_id)["status"] == "VOIDED"
        assert pledge_status(test_db, event_id, "Bo") == "PENDING_PAY"
        assert lifecycle.find_event(test_db, event_id)["status"] == "OPEN"
        assert_nothing_was_captured()
    finally:
        delete_event(test_db, event_id)


# ---------- F12: an uncertain void stays claimed; the sweep does not resend it (D89) ----------

# F12: a 204 followed by CREATED is uncertain; a later sweep must not resend the void.
def test_f12_an_unconfirmed_void_is_blocked_for_review(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_id)]
        sweep(test_db)
        hold = hold_for_order(test_db, order_id)
        assert hold["status"] == "CREATED"
        assert pledge_status(test_db, event_id, "Ana") == "HELD"
        assert len(calls_for("void_authorization", [auth_id])) == 1

        fake_paypal.calls.clear()
        sweep(test_db, SWEEP_NOW + timedelta(minutes=1))
        assert fake_paypal.calls == []

        sweep(test_db, SWEEP_NOW + config.VOID_RETRY_AFTER + timedelta(minutes=1))
        voids = calls_for("void_authorization", [auth_id])
        assert len(voids) == 0
        assert hold_for_order(test_db, order_id)["void_run_token"] is not None
        assert hold_for_order(test_db, order_id)["status"] == "CREATED"
        assert pledge_status(test_db, event_id, "Ana") == "HELD"
        assert_nothing_was_captured()
    finally:
        delete_event(test_db, event_id)


# F12: the void is refused (422) and the GET says CREATED. The hold stays CREATED for a later GET-only check.
def test_f12_a_refused_void_leaves_the_hold_for_the_next_sweep(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        fake_paypal.next_answers["void_authorization"] = [fake_paypal.answer(422, {"name": "UNPROCESSABLE_ENTITY"})]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_id)]
        sweep(test_db)
        assert hold_for_order(test_db, order_id)["status"] == "CREATED"
        assert pledge_status(test_db, event_id, "Ana") == "HELD"
    finally:
        delete_event(test_db, event_id)


# F12: no answer at all from the void or the GET: the hold stays CREATED and the pledge HELD.
def test_f12_no_answer_from_paypal_leaves_the_hold_for_the_next_sweep(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        fake_paypal.next_answers["void_authorization"] = [fake_paypal.no_answer()]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.no_answer()]
        sweep(test_db)
        assert hold_for_order(test_db, order_id)["status"] == "CREATED"
        assert pledge_status(test_db, event_id, "Ana") == "HELD"
    finally:
        delete_event(test_db, event_id)


# F12: SWEEP_MAX_HOLDS is 1, so with two stranded holds one sweep calls PayPal for one of them, and the
# next sweep for the other.
def test_f12_one_sweep_voids_at_most_sweep_max_holds(test_db):
    fake_paypal.reset()
    event_id, first_order = held_pledge_on_event(test_db, "OPEN")
    try:
        token, second_order, result = pledge_and_authorize(test_db, event_id, "Bo", 2500)
        set_event_status(test_db, event_id, "EXPIRED")
        sweep(test_db)
        assert len(calls_to("void_authorization")) == config.SWEEP_MAX_HOLDS
        sweep(test_db)
        assert len(calls_to("void_authorization")) == 2 * config.SWEEP_MAX_HOLDS
        assert hold_for_order(test_db, first_order)["status"] == "VOIDED"
        assert hold_for_order(test_db, second_order)["status"] == "VOIDED"
    finally:
        delete_event(test_db, event_id)


# F12: the older hold is already claimed. It must not take the one slot or refresh its lease.
# The younger hold is still eligible, so this sweep voids that one.
def test_f12_a_claimed_hold_does_not_consume_the_sweep_slot(test_db):
    fake_paypal.reset()
    event_id, older_order = held_pledge_on_event(test_db, "OPEN")
    try:
        token, younger_order, result = pledge_and_authorize(test_db, event_id, "Bo", 2500)
        assert result["outcome"] == "HELD"
        set_event_status(test_db, event_id, "EXPIRED")
        older = hold_for_order(test_db, older_order)
        younger = hold_for_order(test_db, younger_order)
        db.run(test_db, "UPDATE holds SET void_run_token = %s, void_request_id = %s WHERE id = %s",
               ("claimed-owner", "saved-void-request", older["id"]))
        fake_paypal.calls.clear()
        sweep(test_db)
        older_after = hold_for_order(test_db, older_order)
        assert older_after["status"] == "CREATED"
        assert older_after["void_run_token"] == "claimed-owner"
        assert older_after["void_tried_at"] is None
        assert calls_for("void_authorization", [older["auth_id"]]) == []
        assert len(calls_for("void_authorization", [younger["auth_id"]])) == 1
        assert hold_for_order(test_db, younger_order)["status"] == "VOIDED"
        assert_nothing_was_captured()
    finally:
        delete_event(test_db, event_id)


# F12: a claimed hold is the only stranded hold. After the retry interval the sweep still leaves it alone.
def test_f12_a_claimed_hold_alone_is_not_selected(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        hold = hold_for_order(test_db, order_id)
        tried_at = SWEEP_NOW - timedelta(hours=1)
        db.run(test_db, "UPDATE holds SET void_run_token = %s, void_request_id = %s, void_tried_at = %s "
                       "WHERE id = %s", ("claimed-owner", "saved-void-request", tried_at, hold["id"]))
        fake_paypal.calls.clear()
        sweep(test_db)
        after = hold_for_order(test_db, order_id)
        assert fake_paypal.calls == []
        assert after["status"] == "CREATED"
        assert after["void_run_token"] == "claimed-owner"
        assert after["void_tried_at"] == tried_at
        assert_nothing_was_captured()
    finally:
        delete_event(test_db, event_id)


# ---------- F16: the D70 case ----------

# F16: an uncertain void at lock stays blocked while the other pledges are charged normally.
def test_f16_an_uncertain_void_at_lock_stays_blocked(test_db):
    fake_paypal.reset()
    event_id = event_where_ana_waits_for_kim(test_db)
    try:
        ana, bo, cy, dee = pledges_of(test_db, event_id)
        ana_auth = auth_id_of(test_db, ana["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", ana_auth)]
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "SETTLED"
        assert pledges_of(test_db, event_id)[0]["status"] == "HELD"
        captures_before = len(calls_to("capture_authorization"))
        fake_paypal.calls.clear()
        sweep(test_db)
        assert pledges_of(test_db, event_id)[0]["status"] == "HELD"
        assert len(calls_for("void_authorization", [ana_auth])) == 0
        assert len(calls_to("void_authorization")) == 0
        assert db.fetch_one(test_db, "SELECT void_run_token FROM holds WHERE auth_id = %s", (ana_auth,))["void_run_token"] is not None
        assert captures_before == 3
        assert_nothing_was_captured()
        for pledge in pledges_of(test_db, event_id)[1:]:
            assert pledge["status"] == "CHARGED"
    finally:
        delete_event(test_db, event_id)


# ---------- F17: PENDING holds ----------

# A pledge with a PENDING hold (order created, authorize never sent), on an event with this status.
# The hold is made to look this old. Returns the event ID and the hold's ID.
def pending_hold_on_event(conn, status, age=timedelta(hours=2)):
    event_id = make_open_event(conn)
    token = lifecycle.confirm_pledge(conn, event_id, "Ana", 4000, NOW)["pledger_token"]
    order = lifecycle.start_hold(conn, token, NOW, fake_paypal)
    hold = hold_for_order(conn, order["order_id"])
    db.run(conn, "UPDATE holds SET created_at = %s WHERE id = %s", (SWEEP_NOW - age, hold["id"]))
    set_event_status(conn, event_id, status)
    return event_id, hold["id"]


def hold_status(conn, hold_id):
    return db.fetch_one(conn, "SELECT status FROM holds WHERE id = %s", (hold_id,))["status"]


# F17: this is dev event 19's holds 8 and 9: an order was created, authorize was never sent, and the
# event finished. Nothing can be held at PayPal, so the sweep marks the hold NOT_PLACED with no PayPal
# call at all.
def test_f17_a_pending_hold_that_never_sent_authorize_is_not_placed(test_db):
    fake_paypal.reset()
    ids = []
    try:
        for status in FINISHED:
            ids.append(pending_hold_on_event(test_db, status))
        fake_paypal.calls.clear()
        sweep(test_db)
        for event_id, hold_id in ids:
            assert hold_status(test_db, hold_id) == "NOT_PLACED"
        assert fake_paypal.calls == []
    finally:
        for event_id, hold_id in ids:
            delete_event(test_db, event_id)


# F17: a PENDING hold that is not old enough (it may still be a checkout in progress), and one on an event
# that is still OPEN or in LAST_CALL, are left alone.
def test_f17_young_pending_holds_and_live_events_are_left_alone(test_db):
    fake_paypal.reset()
    ids = []
    try:
        ids.append(pending_hold_on_event(test_db, "EXPIRED", age=config.PENDING_HOLD_GRACE - timedelta(minutes=1)))
        ids.append(pending_hold_on_event(test_db, "OPEN"))
        ids.append(pending_hold_on_event(test_db, "LAST_CALL"))
        fake_paypal.calls.clear()
        sweep(test_db)
        for event_id, hold_id in ids:
            assert hold_status(test_db, hold_id) == "PENDING"
        assert fake_paypal.calls == []
    finally:
        for event_id, hold_id in ids:
            delete_event(test_db, event_id)


# F17: authorize WAS sent (its request ID is saved) but no authorization ID came back, so PayPal may be
# holding money we can't see. The sweep calls PayPal for nothing, leaves the hold PENDING and logs a
# warning with the hold ID only: no order ID, no request ID.
def test_f17_a_pending_hold_whose_authorize_was_sent_stays_pending_and_warns(caplog, test_db):
    fake_paypal.reset()
    event_id, hold_id = pending_hold_on_event(test_db, "EXPIRED")
    try:
        db.run(test_db, "UPDATE holds SET authorize_request_id = 'sent-but-no-answer' WHERE id = %s", (hold_id,))
        fake_paypal.calls.clear()
        with caplog.at_level(logging.WARNING):
            sweep(test_db)
        hold = db.fetch_one(test_db, "SELECT * FROM holds WHERE id = %s", (hold_id,))
        assert hold["status"] == "PENDING"
        assert fake_paypal.calls == []
        assert "hold %d" % hold_id in caplog.text
        assert "sent-but-no-answer" not in caplog.text
        assert hold["order_id"] not in caplog.text
        assert hold["create_request_id"] not in caplog.text
    finally:
        delete_event(test_db, event_id)


# F17: closing PENDING holds uses no PayPal call, so it does not use up the sweep's one void.
def test_f17_closing_pending_holds_does_not_use_up_the_void_budget(test_db):
    fake_paypal.reset()
    pending_event, pending_id = pending_hold_on_event(test_db, "EXPIRED")
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        sweep(test_db)
        assert hold_status(test_db, pending_id) == "NOT_PLACED"
        assert hold_for_order(test_db, order_id)["status"] == "VOIDED"
    finally:
        delete_event(test_db, pending_event)
        delete_event(test_db, event_id)


# F17: an authorize answer that arrives after the sweep marked the hold NOT_PLACED is handled by the old
# F11 path: the pledging-closed check fails, so the hold is voided at once.
def test_f17_a_late_authorize_answer_after_not_placed_is_still_voided(test_db):
    fake_paypal.reset()
    event_id, hold_id = pending_hold_on_event(test_db, "EXPIRED")
    try:
        sweep(test_db)
        assert hold_status(test_db, hold_id) == "NOT_PLACED"
        hold = db.fetch_one(test_db, "SELECT holds.*, pledges.event_id, pledges.pledger_token, "
                                     "pledges.name, pledges.status AS pledge_status FROM holds "
                                     "JOIN pledges ON pledges.id = holds.pledge_id WHERE holds.id = %s",
                            (hold_id,))
        authorization = {"id": fake_paypal.new_id("AUTH"), "status": "CREATED"}
        db.run(test_db, "UPDATE holds SET auth_id = %s, status = 'CREATED' WHERE id = %s",
               (authorization["id"], hold_id))
        result = lifecycle.act_on_authorization(test_db, hold, authorization, SWEEP_NOW, fake_paypal)
        assert result["outcome"] == "CLOSED_AND_VOIDED"
        assert hold_status(test_db, hold_id) == "VOIDED"
    finally:
        delete_event(test_db, event_id)


# ---------- F18: PayPal already closed the hold ----------

# F18: the void is refused because the hold is already voided, and the GET says VOIDED: saved, pledge dropped.
def test_f18_a_hold_that_is_already_voided_is_saved_and_the_pledge_dropped(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        fake_paypal.next_answers["void_authorization"] = [fake_paypal.answer(422, {"name": "UNPROCESSABLE_ENTITY"})]
        sweep(test_db)
        assert hold_for_order(test_db, order_id)["status"] == "VOIDED"
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
    finally:
        delete_event(test_db, event_id)


# F18: the hold expired at PayPal: the GET says EXPIRED. There is nothing left to cancel, so the real
# status is saved and the pledge is dropped.
def test_f18_a_hold_that_expired_at_paypal_is_saved_and_the_pledge_dropped(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        fake_paypal.next_answers["void_authorization"] = [fake_paypal.answer(422, {"name": "UNPROCESSABLE_ENTITY"})]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("EXPIRED", auth_id)]
        sweep(test_db)
        assert hold_for_order(test_db, order_id)["status"] == "EXPIRED"
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
        fake_paypal.calls.clear()
        sweep(test_db, SWEEP_NOW + timedelta(hours=1))
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# F18: surprise: the GET says CAPTURED (someone captured by hand). Nothing is captured by us; the hold is
# saved as CAPTURED, the pledge is FAILED (D47 style), the event is unchanged, and an error is logged.
def test_f18_a_captured_surprise_fails_the_pledge_and_captures_nothing(caplog, test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CAPTURED", auth_id)]
        with caplog.at_level(logging.ERROR):
            sweep(test_db)
        assert hold_for_order(test_db, order_id)["status"] == "CAPTURED"
        assert pledge_status(test_db, event_id, "Ana") == "FAILED"
        assert lifecycle.find_event(test_db, event_id)["status"] == "EXPIRED"
        assert_nothing_was_captured()
        assert "CAPTURED" in caplog.text
    finally:
        delete_event(test_db, event_id)


# ---------- F19: two sweeps cannot act on the same hold ----------

# F19: claim_hold is the compare-and-set. The first claim wins, a second one right after loses, and after
# VOID_RETRY_AFTER the hold can be claimed again.
def test_f19_claim_hold_lets_only_one_sweep_in(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        hold_id = hold_for_order(test_db, order_id)["id"]
        assert lifecycle.claim_hold(test_db, hold_id, SWEEP_NOW) is True
        assert lifecycle.claim_hold(test_db, hold_id, SWEEP_NOW) is False
        assert lifecycle.claim_hold(test_db, hold_id, SWEEP_NOW + timedelta(minutes=1)) is False
        later = SWEEP_NOW + config.VOID_RETRY_AFTER + timedelta(minutes=1)
        assert lifecycle.claim_hold(test_db, hold_id, later) is True
    finally:
        delete_event(test_db, event_id)


# F19: two sweeps start at the same moment, each on its own connection. The fake void is slow, so both
# have chosen the hold before either finishes. PayPal is still called once for that hold.
def test_f19_two_sweeps_at_once_void_a_hold_once(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    barrier = threading.Barrier(2)
    errors = []
    original_void = fake_paypal.void_authorization

    def slow_void(auth_id, request_id):
        time.sleep(0.5)
        return original_void(auth_id, request_id)

    def sweep_in_its_own_connection():
        try:
            conn = db.connect(test_db_url)
            try:
                barrier.wait(timeout=30)
                sweep(conn)
            finally:
                conn.close()
        except Exception as error:      # a thread's error is otherwise only printed, so keep it to check
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "void_authorization", slow_void)
    try:
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        workers = []
        for count in range(2):
            worker = threading.Thread(target=sweep_in_its_own_connection)
            worker.start()
            workers.append(worker)
        for worker in workers:
            worker.join(timeout=60)
        assert errors == []
        assert len(calls_for("void_authorization", [auth_id])) == 1
        assert hold_for_order(test_db, order_id)["status"] == "VOIDED"
    finally:
        delete_event(test_db, event_id)


# ---------- F20: what the sweep must not touch ----------

# F20: holds the sweep leaves alone. A DROPPED pledge's hold during LOCKING and CHARGING (the lock owns
# it), a FAILED pledge's hold (D28 c: refund-all decides), HELD pledges on OPEN and LAST_CALL events,
# and a PENDING_PAY pledge's PENDING hold on an OPEN event. No PayPal call, no change.
def test_f20_the_sweep_leaves_the_rest_alone(test_db):
    fake_paypal.reset()
    cases = []
    try:
        for event_status, pledge_status_wanted in (("LOCKING", "DROPPED"), ("CHARGING", "DROPPED"),
                                                   ("NEEDS_ATTENTION", "FAILED"), ("OPEN", "HELD"),
                                                   ("LAST_CALL", "HELD")):
            event_id, order_id = held_pledge_on_event(test_db, event_status)
            db.run(test_db, "UPDATE pledges SET status = %s WHERE event_id = %s", (pledge_status_wanted, event_id))
            cases.append((event_id, order_id, pledge_status_wanted))
        pending_event, pending_id = pending_hold_on_event(test_db, "OPEN")
        fake_paypal.calls.clear()
        sweep(test_db)
        for event_id, order_id, wanted in cases:
            assert hold_for_order(test_db, order_id)["status"] == "CREATED"
            assert pledges_of(test_db, event_id)[0]["status"] == wanted
        assert hold_status(test_db, pending_id) == "PENDING"
        assert pledge_status(test_db, pending_event, "Ana") == "PENDING_PAY"
        assert fake_paypal.calls == []
    finally:
        for event_id, order_id, wanted in cases:
            delete_event(test_db, event_id)
        delete_event(test_db, pending_event)


# F20: the sweep never captures. The functions that make it up never name the capture call, and no test
# above saw one (assert_nothing_was_captured).
def test_f20_no_sweep_function_can_capture():
    for function in (lifecycle.sweep_stranded_holds, lifecycle.close_unplaced_holds,
                     lifecycle.warn_about_lost_authorizations, lifecycle.stranded_created_holds,
                     lifecycle.claim_hold, lifecycle.sweep_one_hold):
        source = inspect.getsource(function)
        assert "capture_authorization" not in source
        assert "get_capture" not in source


# The GET-only recheck must not be able to void, capture, refund, or start a void.
def test_f20_reconcile_cannot_send_a_void_or_capture():
    for function in (lifecycle.reconcile_uncertain_void, lifecycle.read_uncertain_void_claim,
                     lifecycle.finish_void_operation, lifecycle.drop_pledges_without_a_hold,
                     lifecycle.sweep_void_is_eligible):
        source = inspect.getsource(function)
        assert "void_authorization" not in source
        assert "capture_authorization" not in source
        assert "refund_capture" not in source
        assert "void_hold(" not in source
        assert "send_capture(" not in source
        assert "get_capture" not in source


# ---------- F21: when it runs ----------

# F21: settle-on-wake runs the sweep, even when no event is due.
def test_f21_settle_due_events_runs_the_sweep(test_db):
    fake_paypal.reset()
    event_id, order_id = held_pledge_on_event(test_db, "EXPIRED")
    try:
        lifecycle.settle_due_events(test_db, SWEEP_NOW, fake_paypal)
        assert hold_for_order(test_db, order_id)["status"] == "VOIDED"
        assert_nothing_was_captured()
    finally:
        delete_event(test_db, event_id)


# F21: a database error inside the sweep is caught and logged (the error type only), so the page is
# still served and the events already settled stay settled.
def test_f21_a_database_error_in_the_sweep_does_not_escape(monkeypatch, caplog, test_db):
    fake_paypal.reset()

    def broken_sweep(conn, now, paypal):
        raise psycopg.OperationalError("secret-looking detail")

    monkeypatch.setattr(lifecycle, "sweep_stranded_holds", broken_sweep)
    with caplog.at_level(logging.WARNING):
        lifecycle.settle_due_events(test_db, SWEEP_NOW, fake_paypal)
    assert "OperationalError" in caplog.text
    assert "secret-looking detail" not in caplog.text
