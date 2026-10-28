# Tests for lifecycle.py and the app's startup rules (docs/TEST_PLAN.md sections E and F).
#
# The E10 tests and a few others need nothing. The pledge and hold tests (step 2.3) use the Neon test
# branch through Malama's test_db and test_db_url fixtures (tests/conftest.py), and tests/fake_paypal.py
# instead of PayPal. They are skipped, with the reason shown, while TEST_DATABASE_URL is empty.
# Every test makes its own event and deletes it at the end, so tests never see each other's rows.
# Settle, lock and charge (E5, E7, E8) come in step 2.5.

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
from tests import fake_paypal

# A fixed "now" for every test, so no result depends on the real clock.
NOW = datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc)


# Add one OPEN event whose pledging ends 10 minutes after NOW (demo mode), and return its id.
# Opening an event through the app comes in step 5b, so the test writes the row itself.
def make_open_event(conn):
    row = db.fetch_one(conn, "INSERT INTO events (title, deposit_cents, status, admin_token, demo_mode, "
                             "opens_at, hard_deadline) VALUES (%s, %s, 'OPEN', %s, TRUE, %s, %s) RETURNING id",
                       ("lifecycle test event", 30000, lifecycle.new_token(), NOW,
                        NOW + timedelta(minutes=10)))
    return row["id"]


# Delete everything a test made for one event. Children go first, because a hold can't outlive its
# pledge and a pledge can't outlive its event (the REFERENCES rules in schema.sql).
def delete_event(conn, event_id):
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
