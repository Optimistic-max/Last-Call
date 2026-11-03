# Tests for lifecycle.py and the app's startup rules (docs/TEST_PLAN.md sections E and F).
#
# The E10 tests and a few others need nothing. The pledge and hold tests (step 2.3) use the Neon test
# branch through Malama's test_db and test_db_url fixtures (tests/conftest.py), and tests/fake_paypal.py
# instead of PayPal. They are skipped, with the reason shown, while TEST_DATABASE_URL is empty.
# Every test makes its own event and deletes it at the end, so tests never see each other's rows.
# Step 2.5 added the goal check, settle, lock and charge, and expire tests (E5, E7, E8, F13, D25, D39,
# D45, D47) at the end of the file.

import os
import random
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import conditions
import config
import db
import lifecycle
import money
from tests import fake_paypal

# A fixed "now" for every test, so no result depends on the real clock.
NOW = datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc)


# Add one OPEN event that opened at NOW, and return its id. Pledging ends 10 minutes after NOW in demo
# mode (the default), or 48 hours after NOW when a test asks for demo_mode=False.
# Opening an event through the app comes in step 5b, so the test writes the row itself.
# The deposit is $300 unless a test asks for another one (a small one makes the goal easy to reach).
def make_open_event(conn, deposit_cents=30000, demo_mode=True):
    hard_deadline = NOW + config.DEMO_PLEDGING_WINDOW
    if not demo_mode:
        hard_deadline = NOW + config.PLEDGING_WINDOW
    row = db.fetch_one(conn, "INSERT INTO events (title, deposit_cents, status, admin_token, demo_mode, "
                             "opens_at, hard_deadline) VALUES (%s, %s, 'OPEN', %s, %s, %s, %s) RETURNING id",
                       ("lifecycle test event", deposit_cents, lifecycle.new_token(), demo_mode, NOW,
                        hard_deadline))
    return row["id"]


# Delete everything a test made for one event. Children go first, because a capture can't outlive its
# hold, a hold its pledge, or a pledge its event (the REFERENCES rules in schema.sql).
def delete_event(conn, event_id):
    db.run(conn, "DELETE FROM captures WHERE hold_id IN (SELECT holds.id FROM holds JOIN pledges "
                 "ON pledges.id = holds.pledge_id WHERE pledges.event_id = %s)", (event_id,))
    db.run(conn, "DELETE FROM holds WHERE pledge_id IN (SELECT id FROM pledges WHERE event_id = %s)",
           (event_id,))
    db.run(conn, "DELETE FROM pledge_conditions WHERE pledge_id IN "
                 "(SELECT id FROM pledges WHERE event_id = %s)", (event_id,))
    db.run(conn, "DELETE FROM pledges WHERE event_id = %s", (event_id,))
    db.run(conn, "DELETE FROM events WHERE id = %s", (event_id,))


def set_event_status(conn, event_id, status):
    db.run(conn, "UPDATE events SET status = %s WHERE id = %s", (status, event_id))


# Confirm a pledge and return its private token. The test fails here if it wasn't confirmed.
# The clock is NOW unless a test passes another time.
def confirm(conn, event_id, name, max_cents, now=NOW):
    result = lifecycle.confirm_pledge(conn, event_id, name, max_cents, now)
    assert result["outcome"] == "CONFIRMED"
    return result["pledger_token"]


# Do what the pledge page does: confirm, create the order, then authorize it.
# Returns the token, the order ID and what authorize_hold answered. The clock is NOW unless a test
# passes another time.
def pledge_and_authorize(conn, event_id, name, max_cents, now=NOW):
    token = confirm(conn, event_id, name, max_cents, now)
    order = lifecycle.start_hold(conn, token, now, fake_paypal)
    assert order["outcome"] == "ORDER_CREATED"
    result = lifecycle.authorize_hold(conn, order["order_id"], token, now, fake_paypal)
    return token, order["order_id"], result


def hold_for_order(conn, order_id):
    return db.fetch_one(conn, "SELECT * FROM holds WHERE order_id = %s", (order_id,))


def pledge_for_event(conn, event_id, name):
    return lifecycle.find_pledge_by_name(conn, event_id, name)


# The calls made to one fake PayPal function, in order.
def calls_to(function_name):
    found = []
    for call in fake_paypal.calls:
        if call["function"] == function_name:
            found.append(call)
    return found


# ---------- E10: the sandbox guard ----------

# E10: the live PayPal address must be refused.
def test_e10_live_url_is_refused():
    with pytest.raises(RuntimeError):
        config.check_sandbox_url("https://api-m.paypal.com")


# E10: an empty PAYPAL_BASE_URL (a missing .env line) must be refused, not treated as "fine".
def test_e10_empty_url_is_refused():
    with pytest.raises(RuntimeError):
        config.check_sandbox_url("")


# E10: an address that only starts like the sandbox's must be refused.
def test_e10_lookalike_url_is_refused():
    with pytest.raises(RuntimeError):
        config.check_sandbox_url("https://api-m.sandbox.paypal.com.example.com")


# E10: the exact sandbox address is accepted (no error raised).
def test_e10_sandbox_url_is_accepted():
    config.check_sandbox_url("https://api-m.sandbox.paypal.com")


# Start a separate Python that only imports app.py, with PAYPAL_BASE_URL set to base_url. It's a
# separate program on purpose: importing app.py is exactly how "flask run" and gunicorn start the app.
# load_dotenv never replaces a variable that is already set, so app.py sees the value given here.
def import_app_with(base_url):
    env = dict(os.environ)
    env["PAYPAL_BASE_URL"] = base_url
    return subprocess.run([sys.executable, "-c", "import app"], cwd=config.REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


# E10 at startup: app.py refuses to start with the live address, before serving anything.
def test_e10_app_refuses_to_start_with_the_live_url():
    finished = import_app_with("https://api-m.paypal.com")
    assert finished.returncode != 0
    assert "Refusing to start" in finished.stderr


# E10 at startup: with the exact sandbox address, app.py starts.
def test_e10_app_starts_with_the_sandbox_url():
    finished = import_app_with(config.SANDBOX_BASE_URL)
    assert finished.returncode == 0


# ---------- Pledging (step 2.3) ----------

# Pledges are taken only while the event is OPEN (before the hard deadline) or LAST_CALL (before last
# call ends, D04).
def test_pledging_is_open_checks_status_and_clock():
    deadline = NOW + timedelta(minutes=10)
    last_call_ends = NOW + timedelta(minutes=3)
    in_last_call = {"status": "LAST_CALL", "hard_deadline": deadline, "last_call_ends": last_call_ends}
    assert lifecycle.pledging_is_open({"status": "OPEN", "hard_deadline": deadline}, NOW)
    assert lifecycle.pledging_is_open(in_last_call, NOW)
    assert not lifecycle.pledging_is_open(in_last_call, last_call_ends)
    assert not lifecycle.pledging_is_open({"status": "LAST_CALL", "hard_deadline": deadline,
                                           "last_call_ends": None}, NOW)
    assert not lifecycle.pledging_is_open({"status": "OPEN", "hard_deadline": deadline}, deadline)
    assert not lifecycle.pledging_is_open({"status": "DRAFT", "hard_deadline": None}, NOW)
    for status in ["LOCKING", "CHARGING", "SETTLED", "NEEDS_ATTENTION", "EXPIRED"]:
        assert not lifecycle.pledging_is_open({"status": status, "hard_deadline": deadline}, NOW)
    assert not lifecycle.pledging_is_open(None, NOW)


# A blank name or a max under $5 is refused before the database is touched (conn is None here).
def test_confirm_pledge_refuses_blank_name_and_small_max():
    assert lifecycle.confirm_pledge(None, 1, "   ", 4000, NOW) == {"outcome": "NO_NAME"}
    assert lifecycle.confirm_pledge(None, 1, "Ana", 499, NOW) == {"outcome": "TOO_SMALL"}


# D58: a max over $2,000 is refused before the database is touched (conn is None here).
def test_confirm_pledge_refuses_a_max_over_2000_dollars():
    assert lifecycle.confirm_pledge(None, 1, "Ana", 200001, NOW) == {"outcome": "TOO_BIG"}


# D58: exactly $2,000.00 is the largest max that can be saved.
def test_confirm_pledge_accepts_a_max_of_exactly_2000_dollars(test_db):
    event_id = make_open_event(test_db)
    try:
        token = confirm(test_db, event_id, "Ana", 200000)
        assert lifecycle.find_pledge_by_token(test_db, token)["max_cents"] == 200000
    finally:
        delete_event(test_db, event_id)


# Confirming saves a PENDING_PAY pledge with the name tidied, and never calls PayPal.
def test_confirm_pledge_saves_pending_pay(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token = confirm(test_db, event_id, "  Ana   Lee ", 4000)
        pledge = lifecycle.find_pledge_by_token(test_db, token)
        assert pledge["name"] == "Ana Lee"
        assert pledge["max_cents"] == 4000
        assert pledge["status"] == "PENDING_PAY"
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# A closed event refuses new pledges and new orders, whether its status says so or its deadline has
# passed while the status still says OPEN (settling hadn't run yet). PayPal is never called.
def test_closed_event_refuses_pledges_and_orders(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token = confirm(test_db, event_id, "Ana", 4000)
        after_deadline = NOW + timedelta(minutes=10)
        assert lifecycle.confirm_pledge(test_db, event_id, "Bo", 4000, after_deadline) == {"outcome": "CLOSED"}
        assert lifecycle.start_hold(test_db, token, after_deadline, fake_paypal) == {"outcome": "CLOSED"}
        set_event_status(test_db, event_id, "EXPIRED")
        assert lifecycle.confirm_pledge(test_db, event_id, "Bo", 4000, NOW) == {"outcome": "CLOSED"}
        assert lifecycle.start_hold(test_db, token, NOW, fake_paypal) == {"outcome": "CLOSED"}
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# D26 + D32: the same name again (any case, any spaces) reuses the unpaid pledge with the new max and
# a new token. The old token stops working, and the new order is for the new max.
def test_d26_reuse_gives_the_new_max_and_a_new_token(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        old_token = confirm(test_db, event_id, "Ana", 4000)
        first_id = pledge_for_event(test_db, event_id, "Ana")["id"]
        new_token = confirm(test_db, event_id, " ana ", 2500)
        pledge = lifecycle.find_pledge_by_token(test_db, new_token)
        assert new_token != old_token
        assert pledge["id"] == first_id
        assert pledge["max_cents"] == 2500
        assert pledge["status"] == "PENDING_PAY"
        assert lifecycle.start_hold(test_db, old_token, NOW, fake_paypal) == {"outcome": "NOT_FOUND"}
        assert lifecycle.start_hold(test_db, new_token, NOW, fake_paypal)["outcome"] == "ORDER_CREATED"
        assert calls_to("create_order")[0]["amount_cents"] == 2500
    finally:
        delete_event(test_db, event_id)


# D26: after "Card declined", the same person tries again: the pledge goes back to PENDING_PAY, gets a
# new hold row and a new order, and can then be HELD. Nothing is ever voided (a decline holds nothing).
def test_d26_retry_after_a_declined_card(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        fake_paypal.next_answers["authorize_order"] = [fake_paypal.authorized("DENIED", fake_paypal.new_id("AUTH"))]
        token, first_order, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        assert result == {"outcome": "DECLINED"}
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "DECLINED"

        token, second_order, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        assert result == {"outcome": "HELD", "held_cents": 4000}
        assert second_order != first_order
        assert hold_for_order(test_db, first_order)["status"] == "DENIED"
        assert hold_for_order(test_db, second_order)["status"] == "CREATED"
        assert calls_to("void_authorization") == []
    finally:
        delete_event(test_db, event_id)


# D26: once a pledge is HELD, the same name is refused with that person's saved name, and no second
# order is created for it.
def test_d26_refuses_a_name_that_already_holds(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        assert result["outcome"] == "HELD"
        refused = lifecycle.confirm_pledge(test_db, event_id, "ANA", 2500, NOW)
        assert refused == {"outcome": "ALREADY_PLEDGED", "name": "Ana"}
        assert lifecycle.start_hold(test_db, token, NOW, fake_paypal) == {"outcome": "ALREADY_PLEDGED", "name": "Ana"}
        assert len(calls_to("create_order")) == 1
    finally:
        delete_event(test_db, event_id)


# ---------- Holds (step 2.3) ----------

# Authorize CREATED: the pledge is HELD, and the order ID, auth ID, status, expiry and both request IDs
# are saved. The request IDs saved are exactly the ones PayPal was sent (rule 4).
def test_authorize_created_makes_the_pledge_held(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        assert result == {"outcome": "HELD", "held_cents": 4000}
        pledge = lifecycle.find_pledge_by_token(test_db, token)
        hold = hold_for_order(test_db, order_id)
        create_call = calls_to("create_order")[0]
        authorize_call = calls_to("authorize_order")[0]
        assert pledge["status"] == "HELD"
        assert pledge["max_cents"] == 4000
        assert hold["status"] == "CREATED"
        assert hold["amount_cents"] == 4000
        assert hold["auth_id"].startswith("AUTH")
        assert hold["expires_at"] == datetime(2026, 11, 25, 21, 4, 51, tzinfo=timezone.utc)
        assert hold["create_request_id"] == create_call["request_id"]
        assert hold["authorize_request_id"] == authorize_call["request_id"]
        assert create_call["amount_cents"] == 4000
        assert create_call["reference_id"] == "pledge-%d" % pledge["id"]
        assert fake_paypal.called_functions() == ["create_order", "authorize_order"]
    finally:
        delete_event(test_db, event_id)


# Authorize DENIED (HTTP 201, rule 5): the pledge is DECLINED, the auth ID is saved, and no void is
# attempted, because a declined card holds nothing (the server half of B2).
def test_authorize_denied_declines_without_a_void(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        auth_id = fake_paypal.new_id("AUTH")
        fake_paypal.next_answers["authorize_order"] = [fake_paypal.authorized("DENIED", auth_id)]
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        hold = hold_for_order(test_db, order_id)
        assert result == {"outcome": "DECLINED"}
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "DECLINED"
        assert hold["status"] == "DENIED"
        assert hold["auth_id"] == auth_id
        assert hold["void_request_id"] is None
        assert fake_paypal.called_functions() == ["create_order", "authorize_order"]
    finally:
        delete_event(test_db, event_id)


# No answer from authorize (a timeout): try once more with the SAME request ID (rule 4, section 5).
# Still no answer: not held, the pledge stays PENDING_PAY and the hold stays PENDING with no auth ID.
def test_authorize_no_answer_retries_once_then_is_not_held(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        fake_paypal.next_answers["authorize_order"] = [fake_paypal.no_answer(), fake_paypal.no_answer()]
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        hold = hold_for_order(test_db, order_id)
        tries = calls_to("authorize_order")
        assert result == {"outcome": "NOT_HELD"}
        assert len(tries) == 2
        assert tries[0]["request_id"] == hold["authorize_request_id"]
        assert tries[1]["request_id"] == hold["authorize_request_id"]
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "PENDING_PAY"
        assert hold["status"] == "PENDING"
        assert hold["auth_id"] is None
    finally:
        delete_event(test_db, event_id)


# No answer the first time, then the hold on the retry: HELD, with the one saved request ID.
def test_authorize_retry_after_no_answer_can_hold(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        fake_paypal.next_answers["authorize_order"] = [fake_paypal.no_answer()]
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        assert result == {"outcome": "HELD", "held_cents": 4000}
        assert len(calls_to("authorize_order")) == 2
    finally:
        delete_event(test_db, event_id)


# Authorizing the same order twice (a double click) gives the saved answer and never calls PayPal again.
def test_authorize_twice_never_authorizes_twice(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        again = lifecycle.authorize_hold(test_db, order_id, token, NOW, fake_paypal)
        assert again == {"outcome": "HELD", "held_cents": 4000}
        assert len(calls_to("authorize_order")) == 1
    finally:
        delete_event(test_db, event_id)


# Only the pledge's own token can authorize its order. A wrong token finds nothing and calls nothing.
def test_authorize_needs_the_pledges_own_token(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token = confirm(test_db, event_id, "Ana", 4000)
        order = lifecycle.start_hold(test_db, token, NOW, fake_paypal)
        result = lifecycle.authorize_hold(test_db, order["order_id"], "not-the-token", NOW, fake_paypal)
        assert result == {"outcome": "NOT_FOUND"}
        assert calls_to("authorize_order") == []
        assert hold_for_order(test_db, order["order_id"])["authorize_request_id"] is None
    finally:
        delete_event(test_db, event_id)


# An authorization status that is neither CREATED nor DENIED is never treated as held (section 4):
# the pledge stays PENDING_PAY, and the authorization is voided and read back.
def test_unexpected_authorization_status_is_voided(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        auth_id = fake_paypal.new_id("AUTH")
        fake_paypal.next_answers["authorize_order"] = [fake_paypal.authorized("PENDING", auth_id)]
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        hold = hold_for_order(test_db, order_id)
        assert result == {"outcome": "NOT_HELD"}
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "PENDING_PAY"
        assert calls_to("void_authorization")[0]["auth_id"] == auth_id
        assert calls_to("void_authorization")[0]["request_id"] == hold["void_request_id"]
        assert hold["status"] == "VOIDED"
    finally:
        delete_event(test_db, event_id)


# If the event closed after the order was created, authorize is refused BEFORE PayPal is asked, so no
# hold is ever placed. (Settling, in step 2.5, will drop the unpaid pledge.)
def test_authorize_is_refused_before_paypal_once_pledging_closed(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token = confirm(test_db, event_id, "Ana", 4000)
        order = lifecycle.start_hold(test_db, token, NOW, fake_paypal)
        set_event_status(test_db, event_id, "EXPIRED")
        result = lifecycle.authorize_hold(test_db, order["order_id"], token, NOW, fake_paypal)
        assert result == {"outcome": "CLOSED"}
        assert calls_to("authorize_order") == []
    finally:
        delete_event(test_db, event_id)


# F1: every PayPal-Request-Id is in the database before its call goes out, and the order ID and the
# auth ID are saved the moment PayPal returns them. The crash is simulated by making the very next step
# after saving (mark_held) raise an error. A second connection then shows what was really saved, not
# just what this connection remembers.
def test_f1_ids_are_saved_before_anything_else(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    other = db.connect(test_db_url)
    saved_before_call = []
    original_create_order = fake_paypal.create_order
    original_authorize_order = fake_paypal.authorize_order

    def checking_create_order(amount_cents, reference_id, request_id):
        row = db.fetch_one(other, "SELECT id FROM holds WHERE create_request_id = %s", (request_id,))
        saved_before_call.append(row is not None)
        return original_create_order(amount_cents, reference_id, request_id)

    def checking_authorize_order(order_id, request_id):
        row = db.fetch_one(other, "SELECT id FROM holds WHERE authorize_request_id = %s", (request_id,))
        saved_before_call.append(row is not None)
        return original_authorize_order(order_id, request_id)

    def crash(conn, hold, now):
        raise RuntimeError("simulated crash right after authorize")

    monkeypatch.setattr(fake_paypal, "create_order", checking_create_order)
    monkeypatch.setattr(fake_paypal, "authorize_order", checking_authorize_order)
    monkeypatch.setattr(lifecycle, "mark_held", crash)
    try:
        token = confirm(test_db, event_id, "Ana", 4000)
        order = lifecycle.start_hold(test_db, token, NOW, fake_paypal)
        with pytest.raises(RuntimeError):
            lifecycle.authorize_hold(test_db, order["order_id"], token, NOW, fake_paypal)
        hold = hold_for_order(other, order["order_id"])
        assert saved_before_call == [True, True]
        assert hold["order_id"] == order["order_id"]
        assert hold["auth_id"] is not None
        assert hold["status"] == "CREATED"
    finally:
        other.close()
        delete_event(test_db, event_id)


# F11: the event expires while PayPal is placing the hold. The hold comes back CREATED, but pledging
# closed, so the hold is voided at once (its void request ID saved first, then a GET to confirm) and
# the pledge is DROPPED. Nobody is left with a hold that would never be charged or cancelled.
def test_f11_hold_that_comes_back_after_pledging_closed_is_voided(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    other = db.connect(test_db_url)
    original_authorize_order = fake_paypal.authorize_order

    def authorize_while_the_event_expires(order_id, request_id):
        set_event_status(other, event_id, "EXPIRED")
        return original_authorize_order(order_id, request_id)

    monkeypatch.setattr(fake_paypal, "authorize_order", authorize_while_the_event_expires)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        hold = hold_for_order(test_db, order_id)
        void_call = calls_to("void_authorization")[0]
        assert result == {"outcome": "CLOSED_AND_VOIDED"}
        assert void_call["auth_id"] == hold["auth_id"]
        assert void_call["request_id"] == hold["void_request_id"]
        assert calls_to("get_authorization")[0]["auth_id"] == hold["auth_id"]
        assert hold["status"] == "VOIDED"
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "DROPPED"
    finally:
        other.close()
        delete_event(test_db, event_id)


# D32: while PayPal is placing Ana's hold, someone confirms "Ana" again, which gives the pledge a new
# token. The hold made with the old token can't make the pledge HELD, so it is voided at once, and the
# pledge waits under its new token with the new max.
def test_d32_hold_made_with_an_old_token_is_voided(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    other = db.connect(test_db_url)
    original_authorize_order = fake_paypal.authorize_order

    def authorize_while_the_name_is_reused(order_id, request_id):
        assert lifecycle.confirm_pledge(other, event_id, "Ana", 2500, NOW)["outcome"] == "CONFIRMED"
        return original_authorize_order(order_id, request_id)

    monkeypatch.setattr(fake_paypal, "authorize_order", authorize_while_the_name_is_reused)
    try:
        old_token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        pledge = pledge_for_event(test_db, event_id, "Ana")
        assert result == {"outcome": "NOT_HELD"}
        assert hold_for_order(test_db, order_id)["status"] == "VOIDED"
        assert pledge["status"] == "PENDING_PAY"
        assert pledge["max_cents"] == 2500
        assert pledge["pledger_token"] != old_token
    finally:
        other.close()
        delete_event(test_db, event_id)


# One hold per pledge: a double click made two orders. Once the first one is HELD, the second is
# refused before PayPal is asked to authorize it.
def test_second_order_is_not_authorized_once_held(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token = confirm(test_db, event_id, "Ana", 4000)
        first = lifecycle.start_hold(test_db, token, NOW, fake_paypal)
        second = lifecycle.start_hold(test_db, token, NOW, fake_paypal)
        assert lifecycle.authorize_hold(test_db, first["order_id"], token, NOW, fake_paypal)["outcome"] == "HELD"
        result = lifecycle.authorize_hold(test_db, second["order_id"], token, NOW, fake_paypal)
        assert result == {"outcome": "ALREADY_PLEDGED", "name": "Ana"}
        assert len(calls_to("authorize_order")) == 1
    finally:
        delete_event(test_db, event_id)


# One hold per pledge, the close race: the second order's authorize is already at PayPal when the first
# one makes the pledge HELD. The second hold loses the compare-and-set and is voided at once, and the
# pledge stays HELD by the first.
def test_second_hold_that_loses_the_race_is_voided(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    other = db.connect(test_db_url)
    original_authorize_order = fake_paypal.authorize_order

    def authorize_while_the_first_hold_wins(order_id, request_id):
        db.run(other, "UPDATE pledges SET status = 'HELD' WHERE event_id = %s", (event_id,))
        return original_authorize_order(order_id, request_id)

    monkeypatch.setattr(fake_paypal, "authorize_order", authorize_while_the_first_hold_wins)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        hold = hold_for_order(test_db, order_id)
        assert result == {"outcome": "ALREADY_PLEDGED", "name": "Ana"}
        assert calls_to("void_authorization")[0]["auth_id"] == hold["auth_id"]
        assert hold["status"] == "VOIDED"
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "HELD"
    finally:
        other.close()
        delete_event(test_db, event_id)


# The race mark_held's FOR SHARE is there for: an expiry (or, in step 2.5, a lock) has changed the
# event's status but hasn't been saved yet when a hold comes back CREATED. Without FOR SHARE, mark_held
# would read the old status OPEN and make the pledge HELD on an expired event. With it, mark_held waits
# for the expiry to be saved, then sees EXPIRED and refuses.
# The expiry runs inside "with other.transaction()", so it isn't saved until that block ends. mark_held
# runs in a second thread (a second line of work running at the same time) on its own connection.
def test_mark_held_waits_for_an_expiry_that_started_first(test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    other = db.connect(test_db_url)
    results = []
    try:
        token = confirm(test_db, event_id, "Ana", 4000)
        order = lifecycle.start_hold(test_db, token, NOW, fake_paypal)
        hold = lifecycle.find_hold_for_order(test_db, order["order_id"], token)

        def try_mark_held():
            results.append(lifecycle.mark_held(test_db, hold, NOW))

        with other.transaction():
            set_event_status(other, event_id, "EXPIRED")
            worker = threading.Thread(target=try_mark_held)
            worker.start()
            time.sleep(1)
            assert worker.is_alive()       # still waiting for the expiry to be saved
        worker.join(timeout=30)
        assert results == [False]
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "PENDING_PAY"
    finally:
        other.close()
        delete_event(test_db, event_id)


# ---------- Step 2.5: goal check, settle, lock and charge, expire ----------

# A moment after every test event's hard deadline (make_open_event: NOW + 10 minutes).
AFTER_DEADLINE = NOW + timedelta(minutes=11)


# Ana and Bo hold $10 each and Cy $15, on an event with a $30 deposit. Only Cy's hold brings the held
# total up to the fee-adjusted goal for three people, so Cy's is the hold that opens last call.
# Returns the three tokens in join order.
def three_holds_that_reach_the_goal(conn, event_id):
    tokens = []
    for name, max_cents in (("Ana", 1000), ("Bo", 1000), ("Cy", 1500)):
        token, order_id, result = pledge_and_authorize(conn, event_id, name, max_cents)
        assert result["outcome"] == "HELD"
        tokens.append(token)
    return tokens


# Every pledge of the event, in join order.
def pledges_of(conn, event_id):
    return db.fetch_all(conn, "SELECT * FROM pledges WHERE event_id = %s ORDER BY created_at, id", (event_id,))


# The authorization ID of a pledge's first hold.
def auth_id_of(conn, pledge_id):
    return db.fetch_one(conn, "SELECT auth_id FROM holds WHERE pledge_id = %s ORDER BY id LIMIT 1",
                        (pledge_id,))["auth_id"]


# The one capture row of a pledge, with its hold's auth ID and status. Fails if there isn't exactly one.
def only_capture_of(conn, pledge_id):
    rows = db.fetch_all(conn, "SELECT captures.*, holds.auth_id, holds.status AS hold_status "
                              "FROM captures JOIN holds ON holds.id = captures.hold_id "
                              "WHERE holds.pledge_id = %s", (pledge_id,))
    assert len(rows) == 1
    return rows[0]


# The fake PayPal calls to one function that name one of these authorization IDs. Filtering by ID keeps
# a test's counts right even if the test branch still holds some other due event.
def calls_for(function_name, auth_ids):
    found = []
    for call in calls_to(function_name):
        if call["auth_id"] in auth_ids:
            found.append(call)
    return found


# Point app.py at the test branch, the fake PayPal and a clock after the deadline, for one test.
# monkeypatch undoes all three afterwards.
def use_app_after_the_deadline(monkeypatch, app, test_db_url):
    def after_the_deadline():
        return AFTER_DEADLINE

    monkeypatch.setattr(config, "DATABASE_URL", test_db_url)
    monkeypatch.setattr(app, "paypal_client", fake_paypal)
    monkeypatch.setattr(app, "utc_now", after_the_deadline)


# D04: the hold that brings the held total up to the goal opens last call, which lasts 3 minutes in
# demo mode. The holds before it leave the event OPEN. (Until M2 this was the D25 test, where last call
# ran until the hard deadline.)
def test_d04_the_hold_that_reaches_the_goal_opens_last_call(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        pledge_and_authorize(test_db, event_id, "Bo", 1000)
        assert lifecycle.find_event(test_db, event_id)["status"] == "OPEN"
        pledge_and_authorize(test_db, event_id, "Cy", 1500)
        event = lifecycle.find_event(test_db, event_id)
        assert event["status"] == "LAST_CALL"
        assert event["last_call_ends"] == NOW + config.DEMO_LAST_CALL_WINDOW
        assert event["last_call_ends"] < event["hard_deadline"]
    finally:
        delete_event(test_db, event_id)


# E1: on a 48-hour event, the goal is reached at hour 10, so last call gets its full hour and ends at
# hour 11. One second before that, pledging is open and settling does nothing; at hour 11 pledging is
# closed and the next settle locks and charges.
def test_e1_goal_at_hour_10_gives_a_full_hour_of_last_call(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000, demo_mode=False)
    hour_10 = NOW + timedelta(hours=10)
    hour_11 = NOW + timedelta(hours=11)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        pledge_and_authorize(test_db, event_id, "Bo", 1000)
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Cy", 1500, hour_10)
        assert result["outcome"] == "HELD"
        event = lifecycle.find_event(test_db, event_id)
        assert event["status"] == "LAST_CALL"
        assert event["last_call_ends"] == hour_11

        just_before = hour_11 - timedelta(seconds=1)
        assert lifecycle.pledging_is_open(event, just_before)
        lifecycle.settle_due_events(test_db, just_before, fake_paypal)
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"
        assert calls_to("capture_authorization") == []

        assert not lifecycle.pledging_is_open(event, hour_11)
        lifecycle.settle_due_events(test_db, hour_11, fake_paypal)
        assert lifecycle.find_event(test_db, event_id)["status"] == "SETTLED"
        assert len(calls_to("capture_authorization")) == 3
    finally:
        delete_event(test_db, event_id)


# E2: on a 48-hour event, the goal is reached at hour 47. One more hour would pass the 48-hour cap, so
# last call ends at the hard deadline instead (D04).
def test_e2_goal_at_hour_47_ends_last_call_at_hour_48(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000, demo_mode=False)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        pledge_and_authorize(test_db, event_id, "Bo", 1000)
        pledge_and_authorize(test_db, event_id, "Cy", 1500, NOW + timedelta(hours=47))
        event = lifecycle.find_event(test_db, event_id)
        assert event["status"] == "LAST_CALL"
        assert event["hard_deadline"] == NOW + timedelta(hours=48)
        assert event["last_call_ends"] == event["hard_deadline"]
    finally:
        delete_event(test_db, event_id)


# E4: Dee joins one minute into a 3-minute demo last call. Her hold is taken, and at lock all four are
# charged, each a smaller share than the three would have paid without her. The expected shares come
# from money.py, as the lock works them out. Eve, who tries at the moment last call ends, is refused,
# even though the hard deadline is still 7 minutes away.
def test_e4_joining_during_last_call_lowers_shares(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    last_call_ends = NOW + config.DEMO_LAST_CALL_WINDOW
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Dee", 1500,
                                                       NOW + timedelta(minutes=1))
        assert result["outcome"] == "HELD"

        late = lifecycle.confirm_pledge(test_db, event_id, "Eve", 1500, last_call_ends)
        assert late["outcome"] == "CLOSED"
        assert last_call_ends < lifecycle.find_event(test_db, event_id)["hard_deadline"]

        lifecycle.settle_due_events(test_db, last_call_ends, fake_paypal)
        assert lifecycle.find_event(test_db, event_id)["status"] == "SETTLED"
        shares_without_dee = money.compute_shares_cents(money.fee_adjusted_goal_cents(3000, 3),
                                                        [1000, 1000, 1500])
        shares_with_dee = money.compute_shares_cents(money.fee_adjusted_goal_cents(3000, 4),
                                                     [1000, 1000, 1500, 1500])
        pledges = pledges_of(test_db, event_id)
        assert len(pledges) == 4
        for position in range(4):
            assert pledges[position]["status"] == "CHARGED"
            assert only_capture_of(test_db, pledges[position]["id"])["amount_cents"] == shares_with_dee[position]
        for position in range(3):
            assert shares_with_dee[position] < shares_without_dee[position]
    finally:
        delete_event(test_db, event_id)


# E7: settle on wake. The deadline passed while the app was "asleep", and the next page request settles
# it before the page is built: each share is worked out by money.py, saved, and charged once, with
# PayPal's fee and net saved. Flask's test client sends the request.
# app is imported here, not at the top of the file: importing it needs the sandbox PAYPAL_BASE_URL
# (rule 12), and the E10 tests above must run even without it.
def test_e7_next_page_request_charges_a_due_event(monkeypatch, test_db, test_db_url):
    import app
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        use_app_after_the_deadline(monkeypatch, app, test_db_url)
        assert app.app.test_client().get("/e/%d/pledge" % event_id).status_code == 200
        event = lifecycle.find_event(test_db, event_id)
        goal_cents = money.fee_adjusted_goal_cents(3000, 3)
        shares = money.compute_shares_cents(goal_cents, [1000, 1000, 1500])
        assert event["status"] == "SETTLED"
        assert event["goal_cents"] == goal_cents
        assert event["lock_started_at"] == AFTER_DEADLINE
        pledges = pledges_of(test_db, event_id)
        for position in range(3):
            capture = only_capture_of(test_db, pledges[position]["id"])
            assert pledges[position]["status"] == "CHARGED"
            assert pledges[position]["share_cents"] == shares[position]
            assert capture["amount_cents"] == shares[position]
            assert capture["status"] == "COMPLETED"
            assert capture["hold_status"] == "CAPTURED"
            assert capture["fee_cents"] == 62
            assert capture["net_cents"] == 438
            assert len(calls_for("capture_authorization", [capture["auth_id"]])) == 1
    finally:
        delete_event(test_db, event_id)


# E7 for a missed goal: the next page request after the deadline expires the event, voids the hold and
# drops the pledge.
def test_e7_next_page_request_expires_an_event_short_of_its_goal(monkeypatch, test_db, test_db_url):
    import app
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        token, order_id, result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        use_app_after_the_deadline(monkeypatch, app, test_db_url)
        app.app.test_client().get("/e/%d/pledge" % event_id)
        assert lifecycle.find_event(test_db, event_id)["status"] == "EXPIRED"
        assert hold_for_order(test_db, order_id)["status"] == "VOIDED"
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "DROPPED"
    finally:
        delete_event(test_db, event_id)


# E8: two requests settle the same event at the same moment, and only one charges. Two threads, each
# with its own connection (db.py promise 3), wait at a Barrier so they start together, then both run
# settle_due_events. Only one wins LAST_CALL -> LOCKING, so each share is captured exactly once.
def test_e8_two_settles_at_once_charge_each_share_once(test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    barrier = threading.Barrier(2)
    errors = []

    def settle_in_its_own_connection():
        try:
            conn = db.connect(test_db_url)
            try:
                barrier.wait(timeout=30)
                lifecycle.settle_due_events(conn, AFTER_DEADLINE, fake_paypal)
            finally:
                conn.close()
        except Exception as error:      # a thread's error is otherwise only printed, so keep it to check
            errors.append(error)

    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        workers = []
        for count in range(2):
            worker = threading.Thread(target=settle_in_its_own_connection)
            worker.start()
            workers.append(worker)
        for worker in workers:
            worker.join(timeout=60)
        assert errors == []
        assert lifecycle.find_event(test_db, event_id)["status"] == "SETTLED"
        for pledge in pledges_of(test_db, event_id):
            capture = only_capture_of(test_db, pledge["id"])
            assert pledge["status"] == "CHARGED"
            assert len(calls_for("capture_authorization", [capture["auth_id"]])) == 1
    finally:
        delete_event(test_db, event_id)


# E8, one after the other: lock_and_charge does nothing before last call ends, and once the event is
# locked, a second lock_and_charge changes nothing and makes no PayPal call.
def test_e8_a_second_lock_does_nothing(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        assert lifecycle.lock_and_charge(test_db, event_id, NOW, fake_paypal) == "NOT_LOCKED"
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "SETTLED"
        calls_before = len(fake_paypal.calls)
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "NOT_LOCKED"
        assert len(fake_paypal.calls) == calls_before
    finally:
        delete_event(test_db, event_id)


# Rule 3 for captures: when each capture call goes out, its capture row (PENDING, with this request ID
# and amount) and every share are already saved. The fake capture checks through a second connection.
def test_capture_rows_and_shares_are_saved_before_each_capture(monkeypatch, test_db, test_db_url):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    other = db.connect(test_db_url)
    original_capture = fake_paypal.capture_authorization
    checks = []

    def capture_after_checking(auth_id, amount_cents, request_id):
        row = db.fetch_one(other, "SELECT status, amount_cents FROM captures WHERE request_id = %s",
                           (request_id,))
        missing_shares = db.fetch_one(other, "SELECT count(*) AS missing FROM pledges "
                                             "WHERE event_id = %s AND share_cents IS NULL", (event_id,))
        checks.append(row == {"status": "PENDING", "amount_cents": amount_cents}
                      and missing_shares["missing"] == 0)
        return original_capture(auth_id, amount_cents, request_id)

    monkeypatch.setattr(fake_paypal, "capture_authorization", capture_after_checking)
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "SETTLED"
        assert checks == [True, True, True]
    finally:
        other.close()
        delete_event(test_db, event_id)


# E5: the deadline passes short of the goal. Every hold is voided (each void's request ID saved first),
# nobody is charged, and every pledge is DROPPED, including the one that never paid (D45).
def test_e5_missed_goal_voids_every_hold_and_charges_nobody(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        ana_token, ana_order, ana_result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        bo_token, bo_order, bo_result = pledge_and_authorize(test_db, event_id, "Bo", 2500)
        cy_token = confirm(test_db, event_id, "Cy", 2000)
        lifecycle.settle_due_events(test_db, AFTER_DEADLINE, fake_paypal)
        assert lifecycle.find_event(test_db, event_id)["status"] == "EXPIRED"
        for order_id in (ana_order, bo_order):
            hold = hold_for_order(test_db, order_id)
            void_calls = calls_for("void_authorization", [hold["auth_id"]])
            assert hold["status"] == "VOIDED"
            assert len(void_calls) == 1
            assert void_calls[0]["request_id"] == hold["void_request_id"]
            assert calls_for("capture_authorization", [hold["auth_id"]]) == []
        for token in (ana_token, bo_token, cy_token):
            assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "DROPPED"
    finally:
        delete_event(test_db, event_id)


# D45 (and D40): HELD pledges with no CREATED hold left are DROPPED at expiry with no PayPal call at all.
# Ana's hold was voided earlier. Bo is set up like Bo on the dev branch: one declined hold, then a retry
# hold that was voided later.
def test_d45_held_pledges_with_no_open_hold_are_dropped_without_paypal(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        ana_token, ana_order, ana_result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        fake_paypal.next_answers["authorize_order"] = [fake_paypal.authorized("DENIED", fake_paypal.new_id("AUTH"))]
        pledge_and_authorize(test_db, event_id, "Bo", 2500)
        bo_token, bo_order, bo_result = pledge_and_authorize(test_db, event_id, "Bo", 2500)
        assert bo_result["outcome"] == "HELD"
        db.run(test_db, "UPDATE holds SET status = 'VOIDED' WHERE order_id IN (%s, %s)", (ana_order, bo_order))
        fake_paypal.reset()
        assert lifecycle.expire_event(test_db, event_id, AFTER_DEADLINE, fake_paypal) is True
        assert lifecycle.find_pledge_by_token(test_db, ana_token)["status"] == "DROPPED"
        assert lifecycle.find_pledge_by_token(test_db, bo_token)["status"] == "DROPPED"
        assert fake_paypal.calls == []
    finally:
        delete_event(test_db, event_id)


# D45: a void that doesn't read back VOIDED leaves its hold CREATED and its pledge HELD, for M2's sweep.
# The event still ends EXPIRED, and the other pledge is voided and dropped as usual.
def test_d45_failed_void_keeps_the_pledge_held(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        ana_token, ana_order, ana_result = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        bo_token, bo_order, bo_result = pledge_and_authorize(test_db, event_id, "Bo", 2500)
        ana_auth = hold_for_order(test_db, ana_order)["auth_id"]
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", ana_auth)]
        assert lifecycle.expire_event(test_db, event_id, AFTER_DEADLINE, fake_paypal) is True
        assert lifecycle.find_event(test_db, event_id)["status"] == "EXPIRED"
        assert hold_for_order(test_db, ana_order)["status"] == "CREATED"
        assert lifecycle.find_pledge_by_token(test_db, ana_token)["status"] == "HELD"
        assert hold_for_order(test_db, bo_order)["status"] == "VOIDED"
        assert lifecycle.find_pledge_by_token(test_db, bo_token)["status"] == "DROPPED"
    finally:
        delete_event(test_db, event_id)


# F13 (D38): at lock the goal is somehow no longer reached. Here the deposit is raised by hand, the kind
# of bug the invariants rule out. Nobody is charged, every hold is voided, and the event ends EXPIRED.
def test_f13_goal_not_reached_at_lock_charges_nobody(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        tokens = three_holds_that_reach_the_goal(test_db, event_id)
        db.run(test_db, "UPDATE events SET deposit_cents = 30000 WHERE id = %s", (event_id,))
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "EXPIRED"
        assert lifecycle.find_event(test_db, event_id)["status"] == "EXPIRED"
        assert calls_to("capture_authorization") == []
        assert len(calls_to("void_authorization")) == 3
        for token in tokens:
            assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "DROPPED"
    finally:
        delete_event(test_db, event_id)


# D39: the second of three captures is refused. That pledge is FAILED, its capture row says why, and
# its hold's real status is read back and saved. The other two are still charged, the event ends
# NEEDS_ATTENTION, and there is no retry in M1 (one capture call per pledge).
def test_d39_refused_capture_fails_that_pledge_only(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        ana, bo, cy = pledges_of(test_db, event_id)
        fake_paypal.next_answers["capture_authorization"] = [
            fake_paypal.captured(fake_paypal.new_id("CAPTURE"), "COMPLETED"),
            fake_paypal.capture_refused("TRANSACTION_REFUSED")]
        fake_paypal.next_answers["get_authorization"] = [
            fake_paypal.hold_read_back("CREATED", auth_id_of(test_db, bo["id"]))]
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "NEEDS_ATTENTION"
        ana, bo, cy = pledges_of(test_db, event_id)
        bo_capture = only_capture_of(test_db, bo["id"])
        assert ana["status"] == "CHARGED"
        assert cy["status"] == "CHARGED"
        assert bo["status"] == "FAILED"
        assert bo_capture["status"] == "FAILED"
        assert bo_capture["error_code"] == "TRANSACTION_REFUSED"
        assert bo_capture["hold_status"] == "CREATED"
        assert len(calls_to("capture_authorization")) == 3
        assert lifecycle.find_event(test_db, event_id)["status"] == "NEEDS_ATTENTION"
    finally:
        delete_event(test_db, event_id)


# D39: a capture with no answer at all (a timeout) is a failure too, with no retry in M1. The hold
# reads back CREATED, so no money moved.
def test_d39_capture_with_no_answer_fails_without_a_retry(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        ana, bo, cy = pledges_of(test_db, event_id)
        fake_paypal.next_answers["capture_authorization"] = [fake_paypal.no_answer()]
        fake_paypal.next_answers["get_authorization"] = [
            fake_paypal.hold_read_back("CREATED", auth_id_of(test_db, ana["id"]))]
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "NEEDS_ATTENTION"
        ana_capture = only_capture_of(test_db, ana["id"])
        assert ana_capture["status"] == "FAILED"
        assert ana_capture["error_code"] == "NO_ANSWER"
        assert ana_capture["hold_status"] == "CREATED"
        assert len(calls_for("capture_authorization", [ana_capture["auth_id"]])) == 1
        assert pledges_of(test_db, event_id)[0]["status"] == "FAILED"
    finally:
        delete_event(test_db, event_id)


# D47: the capture answer was lost, but the hold reads back CAPTURED, so the money did move. In M1 the
# hold is saved as CAPTURED, the pledge is still FAILED, the event NEEDS_ATTENTION, and the log says so
# clearly. That capture row stays PENDING: its real result is unknown to us, not failed.
# caplog is pytest's built-in fixture that collects what the code logged.
def test_d47_lost_answer_but_captured_is_saved_and_logged(test_db, caplog):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        ana, bo, cy = pledges_of(test_db, event_id)
        fake_paypal.next_answers["capture_authorization"] = [fake_paypal.no_answer()]
        fake_paypal.next_answers["get_authorization"] = [
            fake_paypal.hold_read_back("CAPTURED", auth_id_of(test_db, ana["id"]))]
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "NEEDS_ATTENTION"
        ana_capture = only_capture_of(test_db, ana["id"])
        assert ana_capture["hold_status"] == "CAPTURED"
        assert ana_capture["status"] == "PENDING"
        assert pledges_of(test_db, event_id)[0]["status"] == "FAILED"
        assert "CAPTURED, so money moved" in caplog.text
        assert "D47" in caplog.text
    finally:
        delete_event(test_db, event_id)


# A HELD pledge with two CREATED holds (say a second hold whose void failed) is still charged once,
# from one hold only.
def test_pledge_with_two_open_holds_is_charged_once(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        three_holds_that_reach_the_goal(test_db, event_id)
        ana = pledges_of(test_db, event_id)[0]
        db.run(test_db, "INSERT INTO holds (pledge_id, create_request_id, order_id, auth_id, amount_cents, status) "
                        "VALUES (%s, %s, %s, %s, %s, 'CREATED')",
               (ana["id"], lifecycle.new_request_id(), fake_paypal.new_id("ORDER"), fake_paypal.new_id("AUTH"), 1000))
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "SETTLED"
        only_capture_of(test_db, ana["id"])
        assert len(calls_to("capture_authorization")) == 3
    finally:
        delete_event(test_db, event_id)


# Rule 6: the app makes exactly one capture call, in lifecycle.py (charge_one_pledge, which only
# lock_and_charge calls). This reads the app's own .py files in the repo folder (not tests/ or spikes/)
# and lists every file with a line that calls a capture.
def test_rule6_only_lifecycle_calls_capture():
    found = []
    for path in sorted(config.REPO_ROOT.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if ".capture_authorization(" in line:
                found.append(path.name)
    assert found == ["lifecycle.py"]


# ---------- Creating and opening an event (step 5b) ----------

# Make a DRAFT event the way S1 will, through lifecycle.create_event, and return its answer.
# The test fails here if it wasn't created.
def make_draft_event(conn, demo_mode=True, deposit_cents=30000):
    result = lifecycle.create_event(conn, "  Cabin deposit (made up)  ", deposit_cents, demo_mode)
    assert result["outcome"] == "CREATED"
    return result


# A blank title, a deposit under $20 (D61) and a deposit over $2,000 (D58) are refused before the
# database is touched (conn is None here).
def test_create_event_refuses_a_blank_title_and_bad_deposits():
    assert lifecycle.create_event(None, "   ", 30000, True) == {"outcome": "NO_TITLE"}
    assert lifecycle.create_event(None, "Cabin", 0, True) == {"outcome": "TOO_SMALL"}
    assert lifecycle.create_event(None, "Cabin", 1999, True) == {"outcome": "TOO_SMALL"}
    assert lifecycle.create_event(None, "Cabin", 200001, True) == {"outcome": "TOO_BIG"}


# Creating saves a DRAFT with the title tidied, the deposit in cents and a private admin_token, and no
# times yet: those are saved when the event opens.
def test_create_event_saves_a_draft(test_db):
    result = make_draft_event(test_db)
    try:
        event = lifecycle.find_event(test_db, result["event_id"])
        assert event["status"] == "DRAFT"
        assert event["title"] == "Cabin deposit (made up)"
        assert event["deposit_cents"] == 30000
        assert event["demo_mode"] is True
        assert event["admin_token"] == result["admin_token"]
        assert len(result["admin_token"]) == 32     # secrets.token_urlsafe(24) is 32 characters long
        assert event["opens_at"] is None
        assert event["hard_deadline"] is None
        assert lifecycle.find_event_by_admin_token(test_db, result["admin_token"])["id"] == event["id"]
    finally:
        delete_event(test_db, result["event_id"])


# D61: exactly $20.00 is the smallest deposit that can be saved.
def test_create_event_accepts_a_deposit_of_exactly_20_dollars(test_db):
    result = make_draft_event(test_db, deposit_cents=2000)
    try:
        assert lifecycle.find_event(test_db, result["event_id"])["deposit_cents"] == 2000
    finally:
        delete_event(test_db, result["event_id"])


# D58: exactly $2,000.00 is the biggest deposit that can be saved.
def test_create_event_accepts_a_deposit_of_exactly_2000_dollars(test_db):
    result = make_draft_event(test_db, deposit_cents=200000)
    try:
        assert lifecycle.find_event(test_db, result["event_id"])["deposit_cents"] == 200000
    finally:
        delete_event(test_db, result["event_id"])


# Demo mode counts in minutes, so a whole event fits in one sitting. Otherwise it's 48 hours (D04).
def test_pledging_window_is_minutes_in_demo_mode():
    assert lifecycle.pledging_window({"demo_mode": True}) == timedelta(minutes=10)
    assert lifecycle.pledging_window({"demo_mode": False}) == timedelta(hours=48)


# Opening in demo mode: DRAFT -> OPEN, opened now, pledging ends 10 minutes later, and the event
# now takes pledges.
def test_open_event_in_demo_mode(test_db):
    result = make_draft_event(test_db, demo_mode=True)
    try:
        assert lifecycle.open_event(test_db, result["admin_token"], NOW) == "OPENED"
        event = lifecycle.find_event(test_db, result["event_id"])
        assert event["status"] == "OPEN"
        assert event["opens_at"] == NOW
        assert event["hard_deadline"] == NOW + timedelta(minutes=10)
        assert lifecycle.pledging_is_open(event, NOW)
    finally:
        delete_event(test_db, result["event_id"])


# Outside demo mode, pledging stays open for 48 hours (D04).
def test_open_event_gives_48_hours(test_db):
    result = make_draft_event(test_db, demo_mode=False)
    try:
        assert lifecycle.open_event(test_db, result["admin_token"], NOW) == "OPENED"
        event = lifecycle.find_event(test_db, result["event_id"])
        assert event["hard_deadline"] == NOW + timedelta(hours=48)
    finally:
        delete_event(test_db, result["event_id"])


# A second "Open pledging" (a double click, or a click on an old page) changes nothing, even after
# the event has moved on: the compare-and-set only matches a DRAFT. An unknown token is NOT_FOUND.
def test_open_event_twice_keeps_the_first_times(test_db):
    result = make_draft_event(test_db)
    later = NOW + timedelta(minutes=5)
    try:
        lifecycle.open_event(test_db, result["admin_token"], NOW)
        assert lifecycle.open_event(test_db, result["admin_token"], later) == "ALREADY_OPENED"
        event = lifecycle.find_event(test_db, result["event_id"])
        assert event["opens_at"] == NOW
        assert event["hard_deadline"] == NOW + timedelta(minutes=10)
        set_event_status(test_db, result["event_id"], "EXPIRED")
        assert lifecycle.open_event(test_db, result["admin_token"], later) == "ALREADY_OPENED"
        assert lifecycle.find_event(test_db, result["event_id"])["status"] == "EXPIRED"
        assert lifecycle.open_event(test_db, "no-such-token", NOW) == "NOT_FOUND"
    finally:
        delete_event(test_db, result["event_id"])


# The whole S1 -> S2 path with the fake PayPal: a DRAFT takes no pledges, and once it's opened a
# friend can pledge and hold, just like on the events the other tests write by hand.
def test_created_and_opened_event_takes_a_hold(test_db):
    fake_paypal.reset()
    result = make_draft_event(test_db)
    event_id = result["event_id"]
    try:
        assert lifecycle.confirm_pledge(test_db, event_id, "Ana", 4000, NOW) == {"outcome": "CLOSED"}
        lifecycle.open_event(test_db, result["admin_token"], NOW)
        token, order_id, answer = pledge_and_authorize(test_db, event_id, "Ana", 4000)
        assert answer == {"outcome": "HELD", "held_cents": 4000}
        assert lifecycle.find_pledge_by_token(test_db, token)["status"] == "HELD"
    finally:
        delete_event(test_db, event_id)


# ---------- Step 5b C: the board facts ----------

# The board leaves out DROPPED pledges (D56) and keeps the rest in join order. The rows never carry a
# pledger_token.
def test_board_rows_leave_out_dropped_pledges(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        confirm(test_db, event_id, "Bo", 2000)
        pledge_and_authorize(test_db, event_id, "Cy", 1500)
        db.run(test_db, "UPDATE pledges SET status = 'DROPPED' WHERE event_id = %s AND name = 'Bo'", (event_id,))
        rows = lifecycle.board_facts(test_db, event_id)["rows"]
        assert [row["name"] for row in rows] == ["Ana", "Cy"]
        for row in rows:
            assert "pledger_token" not in row
        assert lifecycle.board_facts(test_db, 999999999) is None
    finally:
        delete_event(test_db, event_id)


# D43: the held total is one SQL SUM of HELD maxes. It is 0, not None, when nobody holds, and an
# unpaid pledge (PENDING_PAY) adds nothing.
def test_board_held_total_is_zero_until_someone_holds(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        assert lifecycle.board_facts(test_db, event_id)["held_total_cents"] == 0
        confirm(test_db, event_id, "Bo", 2000)
        assert lifecycle.board_facts(test_db, event_id)["held_total_cents"] == 0
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        assert lifecycle.board_facts(test_db, event_id)["held_total_cents"] == 1000
    finally:
        delete_event(test_db, event_id)


# Goal and progress while OPEN: the fee-adjusted goal for the people held now, and Malama's
# progress_percent (D54), below 100 while short. From LAST_CALL on, progress is 100, still 100 after
# settling, when nothing is HELD any more. After the lock, the goal is the saved one, and the club's
# net is the sum of PayPal's nets; a missing net gives None, never a made-up number.
def test_board_goal_progress_and_net(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        facts = lifecycle.board_facts(test_db, event_id)
        assert facts["goal_cents"] == money.fee_adjusted_goal_cents(3000, 1)
        assert facts["progress_percent"] == money.progress_percent(3000, [1000])
        assert facts["progress_percent"] < 100
        assert facts["club_net_cents"] is None

        pledge_and_authorize(test_db, event_id, "Bo", 1000)
        pledge_and_authorize(test_db, event_id, "Cy", 1500)
        assert lifecycle.board_facts(test_db, event_id)["progress_percent"] == 100

        lifecycle.settle_due_events(test_db, AFTER_DEADLINE, fake_paypal)
        facts = lifecycle.board_facts(test_db, event_id)
        assert facts["event"]["status"] == "SETTLED"
        assert facts["progress_percent"] == 100
        assert facts["held_total_cents"] == 0
        assert facts["goal_cents"] == facts["event"]["goal_cents"]
        assert facts["club_net_cents"] == money.club_net_cents([438, 438, 438])

        db.run(test_db, "UPDATE captures SET net_cents = NULL WHERE id = (SELECT captures.id FROM captures "
                        "JOIN holds ON holds.id = captures.hold_id JOIN pledges ON pledges.id = holds.pledge_id "
                        "WHERE pledges.event_id = %s ORDER BY captures.id LIMIT 1)", (event_id,))
        assert lifecycle.board_facts(test_db, event_id)["club_net_cents"] is None
    finally:
        delete_event(test_db, event_id)


# During LAST_CALL each counted pledge gets an estimated share, the same money.py numbers the lock
# would charge. Dee joining lowers everyone's estimate. While OPEN there are no estimates.
def test_board_estimated_shares_drop_when_someone_joins_last_call(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        assert lifecycle.board_facts(test_db, event_id)["estimated_shares"] == {}
        pledge_and_authorize(test_db, event_id, "Bo", 1000)
        pledge_and_authorize(test_db, event_id, "Cy", 1500)
        ids = [pledge["id"] for pledge in pledges_of(test_db, event_id)]
        before = lifecycle.board_facts(test_db, event_id)["estimated_shares"]
        expected = money.compute_shares_cents(money.fee_adjusted_goal_cents(3000, 3), [1000, 1000, 1500])
        assert before == {ids[0]: expected[0], ids[1]: expected[1], ids[2]: expected[2]}

        pledge_and_authorize(test_db, event_id, "Dee", 1500, NOW + timedelta(minutes=1))
        after = lifecycle.board_facts(test_db, event_id)["estimated_shares"]
        expected = money.compute_shares_cents(money.fee_adjusted_goal_cents(3000, 4), [1000, 1000, 1500, 1500])
        assert len(after) == 4
        for position in range(3):
            assert after[ids[position]] == expected[position]
            assert after[ids[position]] < before[ids[position]]
    finally:
        delete_event(test_db, event_id)


# D45: a hold that is still CREATED is reported, so the missed-goal banner can say "Cancelling holds…".
# Once the event expires and the hold is voided, nothing is CREATED and the dropped pledge leaves the board.
def test_board_reports_a_created_hold_until_it_is_voided(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        assert lifecycle.board_facts(test_db, event_id)["any_hold_created"] is True
        lifecycle.settle_due_events(test_db, AFTER_DEADLINE, fake_paypal)
        facts = lifecycle.board_facts(test_db, event_id)
        assert facts["event"]["status"] == "EXPIRED"
        assert facts["any_hold_created"] is False
        assert facts["rows"] == []
        assert facts["progress_percent"] == 0
    finally:
        delete_event(test_db, event_id)


# ---------- D70: conditions decide who is counted (TEST_PLAN D1-D7, C8, F9) ----------
# These tests save conditions straight into pledge_conditions, because the route that saves them at
# confirm is the next step (D77). Everything after that goes through the real lifecycle functions.

# Save condition names for one pledge, exactly as given (a test can pass an untidy name on purpose).
def add_conditions(conn, pledge_id, names):
    for name in names:
        db.run(conn, "INSERT INTO pledge_conditions (pledge_id, depends_on_name) VALUES (%s, %s)",
               (pledge_id, name))


# A HELD pledge with a CREATED hold, written straight into the database, for the tests that only need
# "who is counted". No fake PayPal round trip. Returns the pledge's id.
def add_held_pledge(conn, event_id, name, max_cents, condition_names=()):
    pledge = db.fetch_one(conn, "INSERT INTO pledges (event_id, name, max_cents, status, pledger_token) "
                                "VALUES (%s, %s, %s, 'HELD', %s) RETURNING id",
                          (event_id, name, max_cents, lifecycle.new_token()))
    db.run(conn, "INSERT INTO holds (pledge_id, create_request_id, auth_id, amount_cents, status) "
                 "VALUES (%s, %s, %s, %s, 'CREATED')",
           (pledge["id"], lifecycle.new_request_id(), fake_paypal.new_id("AUTH"), max_cents))
    add_conditions(conn, pledge["id"], condition_names)
    return pledge["id"]


# The real flow with conditions: confirm, save the conditions, then create the order and authorize, so
# the goal check after the hold already sees them. Returns the pledge's token.
def pledge_with_conditions(conn, event_id, name, max_cents, condition_names):
    token = confirm(conn, event_id, name, max_cents)
    add_conditions(conn, lifecycle.find_pledge_by_token(conn, token)["id"], condition_names)
    order = lifecycle.start_hold(conn, token, NOW, fake_paypal)
    assert order["outcome"] == "ORDER_CREATED"
    result = lifecycle.authorize_hold(conn, order["order_id"], token, NOW, fake_paypal)
    assert result["outcome"] == "HELD"
    return token


# The names of the counted pledges, in join order.
def counted_names(conn, event_id):
    names = []
    for pledge in lifecycle.counted_held_pledges(conn, event_id):
        names.append(pledge["name"])
    return names


# A $30 deposit event where Ana ("only if Kim's in", $10) joins first, then Bo, Cy and Dee at $15 each.
# Kim never pledges. Without conditions the four holds ($55) reach the goal, but the counted three
# ($45) reach it too, so last call opens at Dee's hold and Ana is the one who must not be charged.
# Returns the event id.
def event_where_ana_waits_for_kim(conn):
    event_id = make_open_event(conn, 3000)
    pledge_with_conditions(conn, event_id, "Ana", 1000, ["Kim"])
    for name in ("Bo", "Cy", "Dee"):
        token, order_id, result = pledge_and_authorize(conn, event_id, name, 1500)
        assert result["outcome"] == "HELD"
    return event_id


# D1 through lifecycle: Ana needs Bo, Bo needs Cy, and Cy never pledged, so the whole chain drops.
def test_d1_chain_with_an_absent_end_drops_everyone(test_db):
    event_id = make_open_event(test_db)
    try:
        add_held_pledge(test_db, event_id, "Ana", 1000, ["Bo"])
        add_held_pledge(test_db, event_id, "Bo", 1000, ["Cy"])
        assert counted_names(test_db, event_id) == []
    finally:
        delete_event(test_db, event_id)


# D2: Ana and Bo each need the other. Both are counted (the circle rule, D06).
def test_d2_mutual_circle_is_counted(test_db):
    event_id = make_open_event(test_db)
    try:
        add_held_pledge(test_db, event_id, "Ana", 1000, ["Bo"])
        add_held_pledge(test_db, event_id, "Bo", 1000, ["Ana"])
        assert counted_names(test_db, event_id) == ["Ana", "Bo"]
    finally:
        delete_event(test_db, event_id)


# D3: Ana and Bo are a circle, and Cy needs Ana. All three are counted.
def test_d3_circle_plus_a_dependent_is_counted(test_db):
    event_id = make_open_event(test_db)
    try:
        add_held_pledge(test_db, event_id, "Ana", 1000, ["Bo"])
        add_held_pledge(test_db, event_id, "Bo", 1000, ["Ana"])
        add_held_pledge(test_db, event_id, "Cy", 1000, ["Ana"])
        assert counted_names(test_db, event_id) == ["Ana", "Bo", "Cy"]
    finally:
        delete_event(test_db, event_id)


# D4: Ana needs Zed, who nobody pledged. Ana drops; Bo (no conditions) is still counted.
def test_d4_a_condition_on_nobody_drops_that_pledge(test_db):
    event_id = make_open_event(test_db)
    try:
        add_held_pledge(test_db, event_id, "Ana", 1000, ["Zed"])
        add_held_pledge(test_db, event_id, "Bo", 1000)
        assert counted_names(test_db, event_id) == ["Bo"]
    finally:
        delete_event(test_db, event_id)


# D5: Ana needs both Bo and Cy. With only Bo she isn't counted; once Cy holds too, she is.
def test_d5_all_of_a_pledges_conditions_are_needed(test_db):
    event_id = make_open_event(test_db)
    try:
        add_held_pledge(test_db, event_id, "Ana", 1000, ["Bo", "Cy"])
        add_held_pledge(test_db, event_id, "Bo", 1000)
        assert counted_names(test_db, event_id) == ["Bo"]
        add_held_pledge(test_db, event_id, "Cy", 1000)
        assert counted_names(test_db, event_id) == ["Ana", "Bo", "Cy"]
    finally:
        delete_event(test_db, event_id)


# D6: names match ignoring case and extra spaces. "  JAY " names the pledger "Jay".
def test_d6_condition_names_match_ignoring_case_and_spaces(test_db):
    event_id = make_open_event(test_db)
    try:
        add_held_pledge(test_db, event_id, "Ana", 1000, ["  JAY "])
        add_held_pledge(test_db, event_id, "Jay", 1000)
        assert counted_names(test_db, event_id) == ["Ana", "Jay"]
    finally:
        delete_event(test_db, event_id)


# D7 through the database: pledgers join one at a time in random groups (seed 7), with random
# conditions that sometimes name nobody. After every join, nobody counted before is dropped, and the
# counted names equal what Malama's circle rule gives for the same group. This covers loading the
# conditions and matching names back to pledges, which test_conditions.py (2,000 groups) cannot.
# Only 5 groups of 4, because every pledge is several database round trips.
def test_d7_adding_a_pledger_never_uncounts_anyone_through_lifecycle(test_db):
    rng = random.Random(7)
    pool = ["Ana", "Bo", "Cy", "Dee", "Eve"]
    for group in range(5):
        event_id = make_open_event(test_db)
        try:
            joined = []
            counted_before = []
            for name in rng.sample(pool, 4):
                others = [other for other in pool + ["Zed"] if other != name]
                wanted = rng.sample(others, rng.randint(0, 2))
                add_held_pledge(test_db, event_id, name, 1000, wanted)
                joined.append({"name": name, "conditions": wanted})
                counted_now = counted_names(test_db, event_id)
                for earlier in counted_before:
                    assert earlier in counted_now
                assert counted_now == conditions.counted_pledges(joined)
                counted_before = counted_now
        finally:
            delete_event(test_db, event_id)


# Someone is only "in" for a condition while they really hold. Jay's hold was voided by hand and Kim is
# still PENDING_PAY, so Ana ("if Jay's in") and Bo ("if Kim's in") are not counted.
def test_a_condition_needs_the_other_person_to_really_hold(test_db):
    event_id = make_open_event(test_db)
    try:
        jay_id = add_held_pledge(test_db, event_id, "Jay", 1000)
        db.run(test_db, "UPDATE holds SET status = 'VOIDED' WHERE pledge_id = %s", (jay_id,))
        confirm(test_db, event_id, "Kim", 1000)
        add_held_pledge(test_db, event_id, "Ana", 1000, ["Jay"])
        add_held_pledge(test_db, event_id, "Bo", 1000, ["Kim"])
        assert counted_names(test_db, event_id) == []
    finally:
        delete_event(test_db, event_id)


# The Ana <-> Jay run (M3 done-when), with the fake PayPal: Ana holds first and isn't counted, so last
# call stays closed. Jay's hold counts both of them, last call opens, and the lock charges both.
def test_ana_and_jay_are_counted_together_and_both_charged(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        pledge_with_conditions(test_db, event_id, "Ana", 2000, ["Jay"])
        assert counted_names(test_db, event_id) == []
        assert lifecycle.find_event(test_db, event_id)["status"] == "OPEN"
        pledge_with_conditions(test_db, event_id, "Jay", 2000, ["Ana"])
        assert counted_names(test_db, event_id) == ["Ana", "Jay"]
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"

        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "SETTLED"
        shares = money.compute_shares_cents(money.fee_adjusted_goal_cents(3000, 2), [2000, 2000])
        ana, jay = pledges_of(test_db, event_id)
        assert ana["status"] == "CHARGED"
        assert jay["status"] == "CHARGED"
        assert only_capture_of(test_db, ana["id"])["amount_cents"] == shares[0]
        assert only_capture_of(test_db, jay["id"])["amount_cents"] == shares[1]
    finally:
        delete_event(test_db, event_id)


# An unmet condition keeps the goal from being reached. Ana ($10, "if Kim's in"), Bo and Cy ($15 each)
# hold $40 in all, enough on its own, but the counted Bo and Cy ($30) are not. Last call opens only when
# Kim holds and Ana counts.
def test_an_unmet_condition_keeps_the_goal_from_being_reached(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        assert money.goal_is_reached(3000, [1000, 1500, 1500])
        assert not money.goal_is_reached(3000, [1500, 1500])
        pledge_with_conditions(test_db, event_id, "Ana", 1000, ["Kim"])
        pledge_and_authorize(test_db, event_id, "Bo", 1500)
        pledge_and_authorize(test_db, event_id, "Cy", 1500)
        assert counted_names(test_db, event_id) == ["Bo", "Cy"]
        assert lifecycle.find_event(test_db, event_id)["status"] == "OPEN"
        pledge_and_authorize(test_db, event_id, "Kim", 1000)
        assert counted_names(test_db, event_id) == ["Ana", "Bo", "Cy", "Kim"]
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"
    finally:
        delete_event(test_db, event_id)


# D70 at lock: Ana's condition never came true, so her hold is voided (the void's request ID saved, the
# hold read back as VOIDED), she is DROPPED with no share, and her authorization is never captured.
# Bo, Cy and Dee are charged shares worked out for three people, not four.
def test_d70_an_uncounted_hold_is_voided_at_lock_and_never_captured(test_db):
    fake_paypal.reset()
    event_id = event_where_ana_waits_for_kim(test_db)
    try:
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"
        ana, bo, cy, dee = pledges_of(test_db, event_id)
        ana_auth = auth_id_of(test_db, ana["id"])
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "SETTLED"

        goal_cents = money.fee_adjusted_goal_cents(3000, 3)
        shares = money.compute_shares_cents(goal_cents, [1500, 1500, 1500])
        ana, bo, cy, dee = pledges_of(test_db, event_id)
        assert ana["status"] == "DROPPED"
        assert ana["share_cents"] is None
        ana_hold = db.fetch_one(test_db, "SELECT * FROM holds WHERE pledge_id = %s", (ana["id"],))
        assert ana_hold["status"] == "VOIDED"
        voids = calls_for("void_authorization", [ana_auth])
        assert len(voids) == 1
        assert voids[0]["request_id"] == ana_hold["void_request_id"]
        assert calls_for("capture_authorization", [ana_auth]) == []
        assert len(calls_to("capture_authorization")) == 3
        assert lifecycle.find_event(test_db, event_id)["goal_cents"] == goal_cents
        for position, pledge in enumerate([bo, cy, dee]):
            assert pledge["status"] == "CHARGED"
            assert pledge["share_cents"] == shares[position]
            assert only_capture_of(test_db, pledge["id"])["amount_cents"] == shares[position]
    finally:
        delete_event(test_db, event_id)


# If the void of an uncounted hold doesn't read back VOIDED, the pledge stays HELD with its hold CREATED
# for the cleanup sweep (D45), the warning is logged, and she is still never charged.
def test_d70_a_failed_void_of_an_uncounted_hold_still_charges_nobody_extra(caplog, test_db):
    fake_paypal.reset()
    event_id = event_where_ana_waits_for_kim(test_db)
    try:
        ana, bo, cy, dee = pledges_of(test_db, event_id)
        ana_auth = auth_id_of(test_db, ana["id"])
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", ana_auth)]
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "SETTLED"
        ana = pledges_of(test_db, event_id)[0]
        assert ana["status"] == "HELD"
        assert ana["share_cents"] is None
        ana_hold = db.fetch_one(test_db, "SELECT * FROM holds WHERE pledge_id = %s", (ana["id"],))
        assert ana_hold["status"] == "CREATED"
        assert calls_for("capture_authorization", [ana_auth]) == []
        assert len(calls_to("capture_authorization")) == 3
        assert "did not read back VOIDED" in caplog.text
    finally:
        delete_event(test_db, event_id)


# C8 for lifecycle: while last call is open, the board's goal, progress and estimated shares use the
# same counted pledges the lock charges, with the same money.py numbers. Ana (not counted) has no
# estimate, but her $10 still counts in the held total (D43). After the lock, each charge equals the
# estimate the board showed.
def test_c8_the_board_and_the_lock_use_the_same_counted_set(test_db):
    fake_paypal.reset()
    event_id = event_where_ana_waits_for_kim(test_db)
    try:
        ana, bo, cy, dee = pledges_of(test_db, event_id)
        facts = lifecycle.board_facts(test_db, event_id)
        goal_cents = money.fee_adjusted_goal_cents(3000, 3)
        shares = money.compute_shares_cents(goal_cents, [1500, 1500, 1500])
        assert facts["estimated_shares"] == {bo["id"]: shares[0], cy["id"]: shares[1], dee["id"]: shares[2]}
        assert facts["goal_cents"] == goal_cents
        assert facts["progress_percent"] == 100
        assert facts["held_total_cents"] == 5500
        assert len(facts["rows"]) == 4

        lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal)
        for pledge in (bo, cy, dee):
            charged = only_capture_of(test_db, pledge["id"])["amount_cents"]
            assert charged == facts["estimated_shares"][pledge["id"]]
    finally:
        delete_event(test_db, event_id)


# F9: Ana joined "only if Kim's in", and Kim did join, so Ana was charged. Then Kim's capture is refused.
# The money already taken from Ana stays taken: no refund is called (rule 7). Kim is FAILED, the event is
# NEEDS_ATTENTION, and the treasurer's board says so. The "[Refund everyone]" button is M2 (F7), so
# only the flag and the absence of an automatic refund are tested here.
def test_f9_kim_fails_after_ana_was_charged_and_nothing_is_refunded(test_db):
    import app
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        pledge_with_conditions(test_db, event_id, "Ana", 1500, ["Kim"])
        pledge_and_authorize(test_db, event_id, "Kim", 1500)
        pledge_and_authorize(test_db, event_id, "Bo", 1500)
        assert lifecycle.find_event(test_db, event_id)["status"] == "LAST_CALL"
        ana, kim, bo = pledges_of(test_db, event_id)
        fake_paypal.next_answers["capture_authorization"] = [
            fake_paypal.captured(fake_paypal.new_id("CAPTURE"), "COMPLETED"),
            fake_paypal.capture_refused("TRANSACTION_REFUSED"),
            fake_paypal.captured(fake_paypal.new_id("CAPTURE"), "COMPLETED")]
        fake_paypal.next_answers["get_authorization"] = [
            fake_paypal.hold_read_back("CREATED", auth_id_of(test_db, kim["id"]))]
        assert lifecycle.lock_and_charge(test_db, event_id, AFTER_DEADLINE, fake_paypal) == "NEEDS_ATTENTION"

        ana, kim, bo = pledges_of(test_db, event_id)
        assert ana["status"] == "CHARGED"
        assert kim["status"] == "FAILED"
        assert bo["status"] == "CHARGED"
        ana_capture = only_capture_of(test_db, ana["id"])
        assert ana_capture["status"] == "COMPLETED"
        assert ana_capture["hold_status"] == "CAPTURED"
        for name in fake_paypal.called_functions():
            assert "refund" not in name
        assert lifecycle.find_event(test_db, event_id)["status"] == "NEEDS_ATTENTION"

        board = app.board_for_event(lifecycle.board_facts(test_db, event_id), AFTER_DEADLINE)
        assert board["banner_text"] == app.NEEDS_ATTENTION_TEXT
        words = {}
        for row in board["rows"]:
            words[row["name"]] = row["status_word"]
        assert words["Kim"] == "Charge failed"
        assert words["Ana"].startswith("Charged")
    finally:
        delete_event(test_db, event_id)
