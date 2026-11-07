# Tests for a friend leaving an event (D82, docs/TEST_PLAN.md E3 and E6): lifecycle.leave_pledge,
# lifecycle.leave_page_state, the S6 routes in app.py, and the check_goal lock that stops a leave and the
# goal check racing each other.
#
# They use the Neon test branch and tests/fake_paypal.py, like tests/test_lifecycle.py, whose helpers
# they borrow. They are skipped, with the reason shown, while TEST_DATABASE_URL is empty.
# Every test makes its own event and deletes it. No test here may ever see a capture call made by a
# leave: leaving only cancels a hold (AGENTS.md rule 6).

import inspect
import logging
import random
import re
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from markupsafe import escape

import app
import conditions
import config
import db
import lifecycle
from tests import fake_paypal
from tests.test_lifecycle import (AFTER_DEADLINE, NOW, add_held_pledge, auth_id_of, calls_for, calls_to,
                                  confirm, counted_names, delete_event, event_where_ana_waits_for_kim,
                                  hold_for_order, make_open_event, pledge_and_authorize, pledges_of,
                                  set_event_status, three_holds_that_reach_the_goal)
from tests.test_routes import use_test_setup


# Settle-on-wake runs before most requests (app.py). These tests aren't about settling, so here it does
# nothing: otherwise a request could settle events with the real PayPal.
@pytest.fixture(autouse=True)
def do_not_settle(monkeypatch):
    monkeypatch.setattr(app, "settle_on_wake", lambda now: None)


def leave(conn, token, now=NOW):
    return lifecycle.leave_pledge(conn, token, now, fake_paypal)


def token_of(conn, event_id, name):
    return lifecycle.find_pledge_by_name(conn, event_id, name)["pledger_token"]


def pledge_status(conn, event_id, name):
    return lifecycle.find_pledge_by_name(conn, event_id, name)["status"]


def assert_nothing_was_captured():
    assert calls_to("capture_authorization") == []


# ---------- E6: leaving before last call ----------

# E6: on an OPEN event, a HELD pledger leaves. The pledge is DROPPED BEFORE the void goes out (a second
# connection looks when the void call is made), and the void's request ID is saved before the call too
# (rule 3). The GET reads VOIDED, claim_hold marked the hold as tried, the board drops the row and the
# held total falls by the leaver's max. Nothing is captured.
def test_e6_leaving_drops_the_pledge_then_voids_the_hold(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    other = db.connect(test_db_url)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        pledge_and_authorize(test_db, event_id, "Bo", 2500)
        held_before = lifecycle.held_total_cents(test_db, event_id)
        seen = []
        original_void = fake_paypal.void_authorization

        def checking_void(auth_id, request_id):
            saved = db.fetch_one(other, "SELECT id FROM holds WHERE void_request_id = %s", (request_id,))
            pledge = db.fetch_one(other, "SELECT status FROM pledges WHERE pledger_token = %s", (token,))
            seen.append((saved is not None, pledge["status"]))
            return original_void(auth_id, request_id)

        monkeypatch.setattr(fake_paypal, "void_authorization", checking_void)
        fake_paypal.calls.clear()
        assert leave(test_db, token)["outcome"] == "LEFT"
        assert seen == [(True, "DROPPED")]
        hold = hold_for_order(test_db, order_id)
        assert hold["status"] == "VOIDED"
        assert hold["void_tried_at"] == NOW
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
        assert lifecycle.held_total_cents(test_db, event_id) == held_before - 4000
        assert [row["name"] for row in lifecycle.board_rows(test_db, event_id)] == ["Bo"]
        assert_nothing_was_captured()
    finally:
        other.close()
        delete_event(test_db, event_id)


# E6: a pledger who never held (PENDING_PAY) or whose card was declined (DECLINED) leaves with no PayPal call.
def test_e6_an_unpaid_or_declined_pledger_leaves_without_paypal(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        unpaid_token = confirm(test_db, event_id, "Ana", 4000)
        fake_paypal.next_answers["authorize_order"] = [fake_paypal.authorized("DENIED", fake_paypal.new_id("AUTH"))]
        declined_token, order_id, result = pledge_and_authorize(test_db, event_id, "Bo", 2500)
        assert result["outcome"] == "DECLINED"
        fake_paypal.calls.clear()
        assert leave(test_db, unpaid_token)["outcome"] == "LEFT"
        assert leave(test_db, declined_token)["outcome"] == "LEFT"
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
        assert pledge_status(test_db, event_id, "Bo") == "DROPPED"
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# E6, D81 case 1: once the event is past OPEN and LAST_CALL, leaving is refused, whatever the status. The
# pledge, its hold and PayPal are left alone. DRAFT, LOCKING, CHARGING, SETTLED, NEEDS_ATTENTION,
# REFUNDING, REFUNDED and EXPIRED each get their own event.
def test_e6_leaving_is_refused_once_the_event_is_past_last_call(test_db):
    fake_paypal.reset()
    event_ids = []
    try:
        for status in ("DRAFT", "LOCKING", "CHARGING", "SETTLED", "NEEDS_ATTENTION", "REFUNDING",
                       "REFUNDED", "EXPIRED"):
            event_id = make_open_event(test_db)
            event_ids.append(event_id)
            token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
            set_event_status(test_db, event_id, status)
            fake_paypal.calls.clear()
            assert leave(test_db, token)["outcome"] == "CLOSED", status
            assert pledge_status(test_db, event_id, "Ana") == "HELD", status
            assert hold_for_order(test_db, order_id)["status"] == "CREATED", status
            assert fake_paypal.calls == [], status
    finally:
        for event_id in event_ids:
            delete_event(test_db, event_id)


# E6: the clock counts too. An OPEN event past its hard deadline, and a LAST_CALL past last_call_ends, are
# closed to leaving even though settling hasn't run yet.
def test_e6_leaving_is_refused_after_the_deadline_even_before_settling(test_db):
    fake_paypal.reset()
    open_event = make_open_event(test_db)
    last_call_event = make_open_event(test_db, 3000)
    try:
        open_token, order_id, result = pledge_and_authorize(test_db, open_event, "Ana", 4000)
        last_call_tokens = three_holds_that_reach_the_goal(test_db, last_call_event)
        assert lifecycle.find_event(test_db, last_call_event)["status"] == "LAST_CALL"
        fake_paypal.calls.clear()
        assert leave(test_db, open_token, AFTER_DEADLINE)["outcome"] == "CLOSED"
        assert leave(test_db, last_call_tokens[0], AFTER_DEADLINE)["outcome"] == "CLOSED"
        assert pledge_status(test_db, open_event, "Ana") == "HELD"
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, open_event)
        delete_event(test_db, last_call_event)


# E6: a pledger whose pledge is CHARGED, FAILED or REFUNDED can't leave, whatever the event says.
def test_e6_a_charged_failed_or_refunded_pledger_cannot_leave(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        tokens = []
        for name in ("Ana", "Bo", "Cy"):
            token, order_id, result = pledge_and_authorize(test_db, event_id, name, 1000)
            tokens.append(token)
        for token, status in zip(tokens, ("CHARGED", "FAILED", "REFUNDED")):
            db.run(test_db, "UPDATE pledges SET status = %s WHERE pledger_token = %s", (status, token))
        fake_paypal.calls.clear()
        for token in tokens:
            assert leave(test_db, token)["outcome"] == "CLOSED"
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# An unknown token is NOT_FOUND. The treasurer's admin_token is just another unknown token: it never
# works as a pledger's.
def test_e6_an_unknown_or_admin_token_is_not_found(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        admin_token = lifecycle.find_event(test_db, event_id)["admin_token"]
        assert leave(test_db, "not-a-real-token")["outcome"] == "NOT_FOUND"
        assert leave(test_db, admin_token)["outcome"] == "NOT_FOUND"
        assert lifecycle.leave_page_state(test_db, admin_token, NOW)["state"] == "NOT_FOUND"
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# ---------- E3: during last call ----------

# E3: in LAST_CALL, a counted pledger can't leave. Nothing changes and PayPal isn't called.
def test_e3_a_counted_pledger_cannot_leave_during_last_call(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        tokens = three_holds_that_reach_the_goal(test_db, event_id)
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"
        fake_paypal.calls.clear()
        assert leave(test_db, tokens[0])["outcome"] == "COUNTED"
        assert pledge_status(test_db, event_id, "Ana") == "HELD"
        assert lifecycle.leave_page_state(test_db, tokens[0], NOW)["state"] == "COUNTED"
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# E3, invariant 2: Ana is HELD but not counted (she waits for Kim, who never pledges). She can leave in
# LAST_CALL: her hold is voided and she is DROPPED. The counted set, the goal, the progress and the
# estimated shares are exactly what they were, and the event stays in LAST_CALL.
def test_e3_an_uncounted_pledger_can_leave_without_changing_anyone_else(test_db):
    fake_paypal.reset()
    event_id = event_where_ana_waits_for_kim(test_db)
    try:
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"

        def snapshot():
            event = lifecycle.find_event(test_db, event_id)
            counted = lifecycle.counted_held_pledges(test_db, event_id)
            goal = lifecycle.board_goal_cents(event, counted)
            return (counted_names(test_db, event_id), goal, lifecycle.board_progress_percent(event, counted),
                    lifecycle.estimated_shares(event, counted, goal))

        before = snapshot()
        held_before = lifecycle.held_total_cents(test_db, event_id)
        ana_token = token_of(test_db, event_id, "Ana")
        ana_auth = auth_id_of(test_db, lifecycle.find_pledge_by_name(test_db, event_id, "Ana")["id"])
        fake_paypal.calls.clear()
        assert leave(test_db, ana_token)["outcome"] == "LEFT"
        assert snapshot() == before
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
        assert len(calls_for("void_authorization", [ana_auth])) == 1
        assert lifecycle.held_total_cents(test_db, event_id) == held_before - 1000
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"
        assert_nothing_was_captured()
    finally:
        delete_event(test_db, event_id)


# E3 / D80: Ana leaves in LAST_CALL but her void is not confirmed (the GET says CREATED). She is DROPPED
# anyway, so the lock never counts or charges her. The uncertain void stays blocked for review.
def test_e3_a_leave_with_an_uncertain_void_is_never_charged(test_db):
    fake_paypal.reset()
    event_id = event_where_ana_waits_for_kim(test_db)
    try:
        ana = lifecycle.find_pledge_by_name(test_db, event_id, "Ana")
        ana_auth = auth_id_of(test_db, ana["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", ana_auth)]
        assert leave(test_db, ana["pledger_token"])["outcome"] == "LEFT"
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
        assert db.fetch_one(test_db, "SELECT status FROM holds WHERE auth_id = %s", (ana_auth,))["status"] == "CREATED"

        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "SETTLED"
        assert calls_for("capture_authorization", [ana_auth]) == []
        assert len(calls_to("capture_authorization")) == 3
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"

        lifecycle.sweep_stranded_holds(test_db, AFTER_DEADLINE + timedelta(minutes=10), fake_paypal)
        hold = db.fetch_one(test_db, "SELECT status, void_run_token FROM holds WHERE auth_id = %s", (ana_auth,))
        assert hold["status"] == "CREATED"
        assert hold["void_run_token"] is not None
        assert len(calls_for("void_authorization", [ana_auth])) == 1
        assert calls_for("capture_authorization", [ana_auth]) == []
    finally:
        delete_event(test_db, event_id)


# E6, rule 5 and D80: the void answers 204 but the GET still says CREATED. The pledge is DROPPED all the
# same, and S6 says the hold is being cancelled. A sweep inside VOID_RETRY_AFTER makes no PayPal call
# (the leave claimed the hold); the uncertain operation remains blocked after that interval too.
def test_e6_an_uncertain_void_stays_blocked_for_review(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_id)]
        assert leave(test_db, token)["outcome"] == "LEFT"
        hold = hold_for_order(test_db, order_id)
        assert hold["status"] == "CREATED"
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
        assert lifecycle.leave_page_state(test_db, token, NOW)["state"] == "LEFT_CANCELLING"

        fake_paypal.calls.clear()
        lifecycle.sweep_stranded_holds(test_db, NOW + timedelta(minutes=1), fake_paypal)
        assert fake_paypal.calls == []

        lifecycle.sweep_stranded_holds(test_db, NOW + config.VOID_RETRY_AFTER + timedelta(minutes=1), fake_paypal)
        voids = calls_for("void_authorization", [auth_id])
        assert len(voids) == 0
        assert hold_for_order(test_db, order_id)["void_run_token"] is not None
        assert hold_for_order(test_db, order_id)["status"] == "CREATED"
        assert lifecycle.leave_page_state(test_db, token, NOW)["state"] == "LEFT_CANCELLING"
        assert_nothing_was_captured()
    finally:
        delete_event(test_db, event_id)


# ---------- double clicks and races ----------

# E6: a double click. Two requests leave at the same moment, each on its own connection. One wins and
# voids; the other is told ALREADY_LEFT and makes no PayPal call. A third, later click does nothing too.
def test_e6_a_double_click_voids_once(test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    barrier = threading.Barrier(2)
    outcomes = []
    errors = []

    def leave_in_its_own_connection(token):
        try:
            conn = db.connect(test_db_url)
            try:
                barrier.wait(timeout=30)
                outcomes.append(leave(conn, token)["outcome"])
            finally:
                conn.close()
        except Exception as error:      # a thread's error is otherwise only printed, so keep it to check
            errors.append(error)

    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        workers = []
        for count in range(2):
            worker = threading.Thread(target=leave_in_its_own_connection, args=(token,))
            worker.start()
            workers.append(worker)
        for worker in workers:
            worker.join(timeout=60)
        assert errors == []
        assert sorted(outcomes) == ["ALREADY_LEFT", "LEFT"]
        assert len(calls_for("void_authorization", [auth_id])) == 1
        assert leave(test_db, token)["outcome"] == "ALREADY_LEFT"
        assert len(calls_for("void_authorization", [auth_id])) == 1
    finally:
        delete_event(test_db, event_id)


# The compare-and-set on the pledge itself: if the pledge's status changes between the check and the
# drop (here a second connection drops it in between), the drop changes 0 rows and the leave does
# nothing more, in particular no void.
def test_e6_the_drop_is_a_compare_and_set_on_the_pledge_status(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    other = db.connect(test_db_url)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        original = lifecycle.why_cannot_leave

        def check_then_change(conn, pledge, event, now):
            answer = original(conn, pledge, event, now)
            db.run(other, "UPDATE pledges SET status = 'DROPPED' WHERE pledger_token = %s", (token,))
            return answer

        monkeypatch.setattr(lifecycle, "why_cannot_leave", check_then_change)
        fake_paypal.calls.clear()
        assert leave(test_db, token)["outcome"] == "NOT_LEFT"
        assert fake_paypal.calls == []
    finally:
        other.close()
        delete_event(test_db, event_id)


# Leave against the lock. A second connection has changed the event to LOCKING but not saved it yet.
# The leave must WAIT for it (the event row is locked FOR UPDATE), and once the lock is saved the leave
# sees LOCKING and is refused. Without the wait, the leave would read the old status and go through.
def test_e6_a_leave_waits_for_the_lock_and_is_then_refused(test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    holder = db.connect(test_db_url)
    leaver = db.connect(test_db_url)
    started = threading.Event()
    release = threading.Event()
    results = []
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        fake_paypal.calls.clear()

        def hold_the_lock():
            with holder.transaction():
                db.run(holder, "UPDATE events SET status = 'LOCKING', lock_started_at = %s WHERE id = %s",
                       (NOW, event_id))
                started.set()
                release.wait(timeout=30)

        def leave_meanwhile():
            results.append(leave(leaver, token)["outcome"])

        holding = threading.Thread(target=hold_the_lock)
        holding.start()
        assert started.wait(timeout=30)
        leaving = threading.Thread(target=leave_meanwhile)
        leaving.start()
        time.sleep(0.7)
        assert results == []
        release.set()
        holding.join(timeout=30)
        leaving.join(timeout=30)
        assert results == ["CLOSED"]
        assert pledge_status(test_db, event_id, "Ana") == "HELD"
        assert fake_paypal.calls == []
    finally:
        release.set()
        holder.close()
        leaver.close()
        delete_event(test_db, event_id)


# check_goal against a leave in progress. Ana and Cy are HELD and so is Bo, whose leave is half done in a
# second connection (event row locked, Bo DROPPED, not saved yet). With Bo the goal is reached, without
# him it is not. check_goal must WAIT for the leave, then see the real group and leave the event OPEN.
# Without the lock it would count Bo, open last call, and the lock would later find the goal missed.
def test_e6_check_goal_waits_for_a_leave_in_progress(test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    holder = db.connect(test_db_url)
    checker = db.connect(test_db_url)
    started = threading.Event()
    release = threading.Event()
    results = []
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        pledge_and_authorize(test_db, event_id, "Bo", 1000)
        add_held_pledge(test_db, event_id, "Cy", 1500)
        assert lifecycle.find_event(test_db, event_id)["status"] == "OPEN"

        def leave_half_done():
            with holder.transaction():
                db.fetch_one(holder, "SELECT * FROM events WHERE id = %s FOR UPDATE", (event_id,))
                db.run(holder, "UPDATE pledges SET status = 'DROPPED' WHERE event_id = %s AND name = 'Bo'",
                       (event_id,))
                started.set()
                release.wait(timeout=30)

        def check_meanwhile():
            results.append(lifecycle.check_goal(checker, event_id, NOW))

        leaving = threading.Thread(target=leave_half_done)
        leaving.start()
        assert started.wait(timeout=30)
        checking = threading.Thread(target=check_meanwhile)
        checking.start()
        time.sleep(0.7)
        assert results == []
        release.set()
        leaving.join(timeout=30)
        checking.join(timeout=30)
        assert results == [False]
        assert lifecycle.find_event(test_db, event_id)["status"] == "OPEN"
    finally:
        release.set()
        holder.close()
        checker.close()
        delete_event(test_db, event_id)


# F11 with a leave: the pledger leaves while the authorize call is in flight (the pledge is still
# PENDING_PAY, with no hold to void yet). The authorize then comes back CREATED, but the pledge is
# DROPPED, so it can't become HELD: the hold is voided at once and nothing is captured.
def test_e6_leaving_while_the_authorize_is_in_flight_voids_the_late_hold(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    other = db.connect(test_db_url)
    try:
        token = confirm(test_db, event_id, "Ana", 4000)
        order = lifecycle.start_hold(test_db, token, NOW, fake_paypal)
        original_authorize = fake_paypal.authorize_order

        def leaving_authorize(order_id, request_id):
            assert lifecycle.leave_pledge(other, token, NOW, fake_paypal)["outcome"] == "LEFT"
            return original_authorize(order_id, request_id)

        monkeypatch.setattr(fake_paypal, "authorize_order", leaving_authorize)
        result = lifecycle.authorize_hold(test_db, order["order_id"], token, NOW, fake_paypal)
        assert result["outcome"] == "NOT_HELD"
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
        assert hold_for_order(test_db, order["order_id"])["status"] == "VOIDED"
        assert_nothing_was_captured()
    finally:
        other.close()
        delete_event(test_db, event_id)


# ---------- invariant 2, with no database ----------

# Invariant 2 (docs/STATE_MACHINE.md): removing a pledger the circle rule does not count never changes
# who is counted. 300 random groups with a fixed seed, so a failure can be run again.
def test_removing_an_uncounted_pledger_never_changes_who_is_counted():
    generator = random.Random(4)
    names = ["Ana", "Bo", "Cy", "Dee", "Eli", "Fay"]
    checked = 0
    for group in range(300):
        members = generator.sample(names, generator.randint(2, 6))
        pledges = []
        for name in members:
            wanted = generator.sample(names, generator.randint(0, 2))
            pledges.append({"name": name, "conditions": [n for n in wanted if n != name]})
        counted = set(conditions.counted_pledges(pledges))
        for pledge in pledges:
            if pledge["name"] in counted:
                continue
            others = [p for p in pledges if p["name"] != pledge["name"]]
            assert set(conditions.counted_pledges(others)) == counted
            checked = checked + 1
    assert checked > 100


# Rule 6: no leave function names the capture call.
def test_no_leave_function_can_capture():
    for function in (lifecycle.leave_pledge, lifecycle.drop_for_leave, lifecycle.why_cannot_leave,
                     lifecycle.cancel_holds_after_leave, lifecycle.leave_page_state):
        assert "capture_authorization" not in inspect.getsource(function)


# ---------- the routes ----------

def get_page(token):
    return app.app.test_client().get("/p/" + token)


# S6 for a pledger who can leave: 200, the cancel button, and a form that posts to this pledge's leave
# address. Showing the page changes nothing: the pledge and the hold are exactly as they were.
def test_s6_shows_the_cancel_button_and_changes_nothing(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        pledge_before = lifecycle.find_pledge_by_name(test_db, event_id, "Ana")
        hold_before = hold_for_order(test_db, order_id)
        fake_paypal.calls.clear()
        page = get_page(token)
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert 'id="leave-button"' in html
        assert 'action="/p/%s/leave"' % token in html
        assert str(escape(app.LEAVE_BUTTON_TEXT)) in html
        assert "SANDBOX DEMO: fake money, no real charges" in html
        assert lifecycle.find_pledge_by_name(test_db, event_id, "Ana") == pledge_before
        assert hold_for_order(test_db, order_id) == hold_before
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# S6 texts for each state: counted (the text from docs/UI_DESIGN.md section 4, no button), left, hold
# still being cancelled, and closed.
def test_s6_shows_the_right_text_for_each_state(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    counted_event = make_open_event(test_db, 3000)
    open_event = make_open_event(test_db)
    closed_event = make_open_event(test_db)
    try:
        counted_tokens = three_holds_that_reach_the_goal(test_db, counted_event)
        html = get_page(counted_tokens[0]).get_data(as_text=True)
        assert str(escape("You're counted, so you can't leave during last call.")) in html
        assert 'id="leave-button"' not in html

        token, order_id, result = pledge_and_authorize(test_db, open_event, "Ana", 4000)
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_id)]
        leave(test_db, token)
        html = get_page(token).get_data(as_text=True)
        assert str(escape(app.LEAVE_CANCELLING_TEXT)) in html
        assert 'id="leave-button"' not in html
        db.run(test_db, "UPDATE holds SET status = 'VOIDED' WHERE order_id = %s", (order_id,))
        assert str(escape(app.LEAVE_DONE_TEXT)) in get_page(token).get_data(as_text=True)

        closed_token, order_id, result = pledge_and_authorize(test_db, closed_event, "Ana", 4000)
        # Pledging time is up but the event is not settled yet: still "too late". A settled or other
        # finished event shows the friend's receipt instead (D95, tests/test_receipt.py).
        db.run(test_db, "UPDATE events SET hard_deadline = %s WHERE id = %s", (NOW - timedelta(minutes=1), closed_event))
        html = get_page(closed_token).get_data(as_text=True)
        assert str(escape(app.LEAVE_CLOSED_TEXT)) in html
        assert 'id="leave-button"' not in html
    finally:
        delete_event(test_db, counted_event)
        delete_event(test_db, open_event)
        delete_event(test_db, closed_event)


# An unknown token and the treasurer's admin_token are both a 404, for the page and for the leave.
def test_s6_unknown_and_admin_tokens_are_404(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        admin_token = lifecycle.find_event(test_db, event_id)["admin_token"]
        client = app.app.test_client()
        for token in ("nothing-like-a-token", admin_token):
            for answer in (client.get("/p/" + token), client.post("/p/" + token + "/leave")):
                assert answer.status_code == 404
                assert answer.get_data(as_text=True) == app.ERROR_TEXT
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# POST /p/<token>/leave leaves and redirects (303) back to the page, so a refresh can't send it again.
# The hold is voided once; a second POST redirects again and makes no PayPal call. The log lines name
# the route and IDs, never the token.
def test_s6_leave_redirects_voids_once_and_never_logs_the_token(monkeypatch, caplog, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        auth_id = hold_for_order(test_db, order_id)["auth_id"]
        client = app.app.test_client()
        with caplog.at_level(logging.INFO):
            first = client.post("/p/" + token + "/leave")
            second = client.post("/p/" + token + "/leave")
            get_page(token)
        assert first.status_code == 303 and first.headers["Location"].endswith("/p/" + token)
        assert second.status_code == 303
        assert pledge_status(test_db, event_id, "Ana") == "DROPPED"
        assert len(calls_for("void_authorization", [auth_id])) == 1
        assert token not in caplog.text
        assert_nothing_was_captured()
    finally:
        delete_event(test_db, event_id)


# POST for a counted pledger in LAST_CALL redirects too, and changes nothing.
def test_s6_leave_of_a_counted_pledger_changes_nothing(monkeypatch, test_db, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        tokens = three_holds_that_reach_the_goal(test_db, event_id)
        fake_paypal.calls.clear()
        answer = app.app.test_client().post("/p/" + tokens[0] + "/leave")
        assert answer.status_code == 303
        assert pledge_status(test_db, event_id, "Ana") == "HELD"
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# ---------- the link on the pledge page ----------

# The pledge page has a hidden line for the S6 link with the placeholder text (D57), and the script shows
# it after "Held" with textContent, never innerHTML. The older test already checks that every id the script
# uses exists in the template.
def test_the_pledge_page_shows_the_leave_link_after_held():
    root = Path(__file__).resolve().parent.parent
    template = (root / "templates" / "pledge.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "pledge_paypal.js").read_text(encoding="utf-8")
    assert re.search(r'id="leave-link-line"[^>]*\bhidden\b', template)
    assert 'id="leave-link"' in template
    assert "Keep this link to cancel before last call." in template
    code = "\n".join(line for line in script.split("\n") if not line.strip().startswith("//"))
    assert 'getElementById("leave-link")' in code and 'getElementById("leave-link-line")' in code
    assert '"/p/"' in code
    assert "innerHTML" not in code
