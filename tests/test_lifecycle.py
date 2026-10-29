# Tests for lifecycle.py and the app's startup rules (docs/TEST_PLAN.md sections E and F).
#
# The E10 tests and a few others need nothing. The pledge and hold tests (step 2.3) use the Neon test
# branch through Malama's test_db and test_db_url fixtures (tests/conftest.py), and tests/fake_paypal.py
# instead of PayPal. They are skipped, with the reason shown, while TEST_DATABASE_URL is empty.
# Every test makes its own event and deletes it at the end, so tests never see each other's rows.
# Step 2.5 added the goal check, settle, lock and charge, and expire tests (E5, E7, E8, F13, D25, D39,
# D45, D47) at the end of the file.

import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import config
import db
import lifecycle
import money
from tests import fake_paypal

# A fixed "now" for every test, so no result depends on the real clock.
NOW = datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc)


# Add one OPEN event whose pledging ends 10 minutes after NOW (demo mode), and return its id.
# Opening an event through the app comes in step 5b, so the test writes the row itself.
# The deposit is $300 unless a test asks for another one (a small one makes the goal easy to reach).
def make_open_event(conn, deposit_cents=30000):
    row = db.fetch_one(conn, "INSERT INTO events (title, deposit_cents, status, admin_token, demo_mode, "
                             "opens_at, hard_deadline) VALUES (%s, %s, 'OPEN', %s, TRUE, %s, %s) RETURNING id",
                       ("lifecycle test event", deposit_cents, lifecycle.new_token(), NOW,
                        NOW + timedelta(minutes=10)))
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
def confirm(conn, event_id, name, max_cents):
    result = lifecycle.confirm_pledge(conn, event_id, name, max_cents, NOW)
    assert result["outcome"] == "CONFIRMED"
    return result["pledger_token"]


# Do what the pledge page does: confirm, create the order, then authorize it.
# Returns the token, the order ID and what authorize_hold answered.
def pledge_and_authorize(conn, event_id, name, max_cents):
    token = confirm(conn, event_id, name, max_cents)
    order = lifecycle.start_hold(conn, token, NOW, fake_paypal)
    assert order["outcome"] == "ORDER_CREATED"
    result = lifecycle.authorize_hold(conn, order["order_id"], token, NOW, fake_paypal)
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

# Pledges are taken only while the event is OPEN or LAST_CALL and before the hard deadline.
def test_pledging_is_open_checks_status_and_clock():
    deadline = NOW + timedelta(minutes=10)
    assert lifecycle.pledging_is_open({"status": "OPEN", "hard_deadline": deadline}, NOW)
    assert lifecycle.pledging_is_open({"status": "LAST_CALL", "hard_deadline": deadline}, NOW)
    assert not lifecycle.pledging_is_open({"status": "OPEN", "hard_deadline": deadline}, deadline)
    assert not lifecycle.pledging_is_open({"status": "DRAFT", "hard_deadline": None}, NOW)
    for status in ["LOCKING", "CHARGING", "SETTLED", "NEEDS_ATTENTION", "EXPIRED"]:
        assert not lifecycle.pledging_is_open({"status": status, "hard_deadline": deadline}, NOW)
    assert not lifecycle.pledging_is_open(None, NOW)


# A blank name or a max under $5 is refused before the database is touched (conn is None here).
def test_confirm_pledge_refuses_blank_name_and_small_max():
    assert lifecycle.confirm_pledge(None, 1, "   ", 4000, NOW) == {"outcome": "NO_NAME"}
    assert lifecycle.confirm_pledge(None, 1, "Ana", 499, NOW) == {"outcome": "TOO_SMALL"}


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


# D25 (M1): the hold that brings the held total up to the goal opens last call, which runs until the
# hard deadline. The holds before it leave the event OPEN.
def test_d25_the_hold_that_reaches_the_goal_opens_last_call(test_db):
    fake_paypal.reset()
    event_id = make_open_event(test_db, 3000)
    try:
        pledge_and_authorize(test_db, event_id, "Ana", 1000)
        pledge_and_authorize(test_db, event_id, "Bo", 1000)
        assert lifecycle.find_event(test_db, event_id)["status"] == "OPEN"
        pledge_and_authorize(test_db, event_id, "Cy", 1500)
        event = lifecycle.find_event(test_db, event_id)
        assert event["status"] == "LAST_CALL"
        assert event["last_call_ends"] == event["hard_deadline"]
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
