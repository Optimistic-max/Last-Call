# D95: the receipt on the friend's own S6 page (/p/<pledger_token>) once the event is finished.
# Fake PayPal and the disposable local PostgreSQL only. Synthetic data only.
import re
import uuid

import pytest

import app
import db
import money
from tests import fake_paypal
from tests.test_refund_lifecycle import refund_case, insert_person
from tests.test_refund_web import web_case

ORIGIN = "https://refund.example"
PAID_TEXT = "You paid $10.77 (your max was $15.00). Nobody paid more than their max."


# ---------- helpers ----------

def set_event(case, status):
    db.run(case["conn"], "UPDATE events SET status = %s WHERE id = %s", (status, case["event_id"]))


def token_of(case, pledge_id):
    return db.fetch_one(case["conn"], "SELECT pledger_token FROM pledges WHERE id = %s", (pledge_id,))["pledger_token"]


def page(case, pledge_id):
    return app.app.test_client().get("/p/" + token_of(case, pledge_id), base_url=ORIGIN)


def message(response):
    found = re.search(r'id="leave-message"[^>]*>(.*?)</p>', response.get_data(as_text=True), re.S)
    assert found is not None
    return found.group(1).replace("&#39;", "'").replace("&amp;", "&").strip()


def trail(response):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", step).replace("&rarr;", "")).strip() for step in
            re.findall(r'<li class="money-trail-step">(.*?)</li>', response.get_data(as_text=True), re.S)]


# A friend charged $10.77 out of a $15.00 hold: the capture row and the saved share say $10.77.
def paid_person(case, max_cents=1500, paid_cents=1077):
    person = insert_person(case["conn"], case["event_id"], "CHARGED", "CAPTURED", "COMPLETED", max_cents)
    db.run(case["conn"], "UPDATE captures SET amount_cents = %s WHERE id = %s", (paid_cents, person["capture"]["id"]))
    db.run(case["conn"], "UPDATE pledges SET share_cents = %s WHERE id = %s", (paid_cents, person["pledge_id"]))
    return person


def add_refund(case, person, send_state, status, amount_cents=1077):
    refund_id = None if send_state == "READY" else fake_paypal.new_id("REFUND")
    return db.fetch_one(case["conn"], "INSERT INTO refunds (capture_id, request_id, amount_cents, refund_id, send_state, status, send_started_at) "
                                      "VALUES (%s, %s, %s, %s, %s, %s, now()) RETURNING *",
                        (person["capture"]["id"], uuid.uuid4().hex, amount_cents, refund_id, send_state, status))


def failed_attempts(case, hold_id):
    for attempt in (1, 2):
        db.run(case["conn"], "INSERT INTO captures (hold_id, request_id, attempt, amount_cents, status, error_code) "
                             "VALUES (%s, %s, %s, 1077, 'FAILED', 'TRANSACTION_REFUSED')", (hold_id, uuid.uuid4().hex, attempt))


def pledge_without_hold(case, status):
    key = uuid.uuid4().hex
    return db.fetch_one(case["conn"], "INSERT INTO pledges (event_id, name, max_cents, pledger_token, status) "
                                      "VALUES (%s, %s, 1500, %s, %s) RETURNING id",
                        (case["event_id"], "Synthetic " + key[:8], key, status))["id"]


# ---------- money.released_cents (Malama's money.py) ----------

def test_released_is_the_max_minus_what_was_paid():
    assert money.released_cents(1500, 1077) == 423
    assert money.released_cents(1500, 1500) == 0
    assert money.released_cents(1500, 0) == 1500


@pytest.mark.parametrize("max_cents,paid_cents", [(1500, 1501), (1500, -1), (-1, 0)])
def test_released_refuses_impossible_amounts(max_cents, paid_cents):
    with pytest.raises(ValueError):
        money.released_cents(max_cents, paid_cents)


@pytest.mark.parametrize("max_cents,paid_cents", [(15.0, 10), (1500, 10.77), (True, 0), ("1500", 1077)])
def test_released_refuses_anything_but_whole_cents(max_cents, paid_cents):
    with pytest.raises(TypeError):
        money.released_cents(max_cents, paid_cents)


# ---------- PAID ----------

@pytest.mark.parametrize("event_status", ["SETTLED", "NEEDS_ATTENTION"])
def test_paid_shows_the_saved_amounts_and_the_money_trail(web_case, event_status):
    person = paid_person(web_case)
    set_event(web_case, event_status)
    response = page(web_case, person["pledge_id"])
    assert response.status_code == 200
    assert message(response) == PAID_TEXT
    assert trail(response) == ["Held $15.00", "Charged $10.77", "Released $4.23"]
    assert 'id="leave-button"' not in response.get_data(as_text=True)


def test_released_on_the_page_comes_from_money_py(web_case, monkeypatch):
    person = paid_person(web_case)
    set_event(web_case, "SETTLED")
    monkeypatch.setattr(money, "released_cents", lambda max_cents, paid_cents: 1)
    assert trail(page(web_case, person["pledge_id"]))[2] == "Released $0.01"


# ---------- refunds ----------

def test_refunded_shows_the_refund_amount_and_no_trail(web_case):
    person = paid_person(web_case)
    add_refund(web_case, person, "ANSWERED", "COMPLETED")
    db.run(web_case["conn"], "UPDATE captures SET status = 'REFUNDED' WHERE id = %s", (person["capture"]["id"],))
    db.run(web_case["conn"], "UPDATE pledges SET status = 'REFUNDED' WHERE id = %s", (person["pledge_id"],))
    set_event(web_case, "REFUNDED")
    response = page(web_case, person["pledge_id"])
    assert message(response) == "You were charged $10.77, and it was refunded in full."
    assert trail(response) == []


@pytest.mark.parametrize("send_state,status", [("READY", "PENDING"), ("IN_FLIGHT", "PENDING"), ("UNCERTAIN", "PENDING"),
                                               ("CHECK_ONLY", "PENDING"), ("ANSWERED", "PENDING")])
def test_a_refund_in_progress_says_so_and_never_says_refunded(web_case, send_state, status):
    person = paid_person(web_case)
    add_refund(web_case, person, send_state, status)
    set_event(web_case, "REFUNDING")
    response = page(web_case, person["pledge_id"])
    assert message(response) == "You were charged $10.77. Your refund is in progress."
    assert trail(response) == []


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_a_failed_or_cancelled_refund_goes_to_the_treasurer(web_case, status):
    person = paid_person(web_case)
    add_refund(web_case, person, "ANSWERED", status)
    set_event(web_case, "REFUNDING")
    assert message(page(web_case, person["pledge_id"])) == "You were charged $10.77. The treasurer is looking into your refund."


# ---------- FAILED ----------

def test_failed_shows_that_nothing_was_paid(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "FAILED", "CREATED")
    failed_attempts(web_case, person["hold_id"])
    response = page(web_case, person["pledge_id"])
    assert message(response) == "Your card couldn't be charged, so you paid nothing. The treasurer has been told."
    assert trail(response) == []


def test_failed_with_a_captured_hold_never_says_nothing_was_paid(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "FAILED", "CAPTURED")
    text = message(page(web_case, person["pledge_id"]))
    assert text == "We're checking what happened to your payment. The treasurer has been told."
    assert "paid nothing" not in text


# ---------- not charged ----------

def test_not_counted_with_a_cancelled_hold(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "DROPPED", "VOIDED")
    set_event(web_case, "SETTLED")
    assert message(page(web_case, person["pledge_id"])) == "You weren't charged. Your hold was cancelled."


@pytest.mark.parametrize("pledge_status", ["DROPPED", "HELD"])
def test_not_charged_with_a_hold_still_open_says_it_is_being_cancelled(web_case, pledge_status):
    person = insert_person(web_case["conn"], web_case["event_id"], pledge_status, "CREATED")
    set_event(web_case, "SETTLED")
    assert message(page(web_case, person["pledge_id"])) == "You weren't charged. Your hold is being cancelled."


@pytest.mark.parametrize("pledge_status", ["PENDING_PAY", "DECLINED"])
def test_not_charged_without_a_hold(web_case, pledge_status):
    pledge_id = pledge_without_hold(web_case, pledge_status)
    set_event(web_case, "SETTLED")
    assert message(page(web_case, pledge_id)) == "You weren't charged."


def test_a_declined_card_hold_counts_as_no_hold(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "DECLINED", "DENIED")
    set_event(web_case, "SETTLED")
    assert message(page(web_case, person["pledge_id"])) == "You weren't charged."


# ---------- EXPIRED ----------

def test_expired_with_a_cancelled_hold(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "DROPPED", "VOIDED")
    set_event(web_case, "EXPIRED")
    assert message(page(web_case, person["pledge_id"])) == "The goal wasn't reached, so nobody paid. Your hold was cancelled."


def test_expired_with_a_hold_still_open(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "HELD", "CREATED")
    set_event(web_case, "EXPIRED")
    assert message(page(web_case, person["pledge_id"])) == "The goal wasn't reached, so nobody paid. Your hold is being cancelled."


def test_expired_without_a_hold(web_case):
    pledge_id = pledge_without_hold(web_case, "PENDING_PAY")
    set_event(web_case, "EXPIRED")
    assert message(page(web_case, pledge_id)) == "The goal wasn't reached, so nobody paid."


# ---------- charging now, and anything not proven ----------

@pytest.mark.parametrize("event_status", ["LOCKING", "CHARGING"])
def test_while_charging_it_says_check_back(web_case, event_status):
    person = insert_person(web_case["conn"], web_case["event_id"], "HELD", "CREATED")
    set_event(web_case, event_status)
    assert message(page(web_case, person["pledge_id"])) == "Shares are being charged now. Check back in a minute."


REVIEW_TEXT = "We're checking what happened to your payment. The treasurer has been told."


def test_an_unresolved_capture_attempt_is_under_review(web_case):
    person = paid_person(web_case)
    db.run(web_case["conn"], "INSERT INTO captures (hold_id, request_id, attempt, amount_cents, status) VALUES (%s, %s, 2, 1077, 'PENDING')",
           (person["hold_id"], uuid.uuid4().hex))
    set_event(web_case, "SETTLED")
    response = page(web_case, person["pledge_id"])
    assert message(response) == REVIEW_TEXT and trail(response) == []


def test_a_capture_that_differs_from_the_saved_share_is_under_review(web_case):
    person = paid_person(web_case)
    db.run(web_case["conn"], "UPDATE pledges SET share_cents = 1076 WHERE id = %s", (person["pledge_id"],))
    set_event(web_case, "SETTLED")
    assert message(page(web_case, person["pledge_id"])) == REVIEW_TEXT


def test_a_capture_above_the_max_is_under_review(web_case):
    person = paid_person(web_case, max_cents=1500, paid_cents=1501)
    set_event(web_case, "SETTLED")
    response = page(web_case, person["pledge_id"])
    assert message(response) == REVIEW_TEXT and trail(response) == []


def test_charged_with_no_recorded_capture_is_under_review(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED")
    set_event(web_case, "SETTLED")
    assert message(page(web_case, person["pledge_id"])) == REVIEW_TEXT


# ---------- the GET is read-only, and no id or token is shown ----------

def test_the_receipt_request_writes_nothing_and_calls_no_paypal(web_case, monkeypatch):
    person = paid_person(web_case)
    set_event(web_case, "SETTLED")
    token = token_of(web_case, person["pledge_id"])
    # Option A keeps settle-on-wake on S6; that hook has its own tests. Here only the route itself is checked.
    def no_writes(*args, **kwargs):
        raise AssertionError("the S6 receipt must not write")
    with monkeypatch.context() as patch:
        patch.setattr(app, "settle_on_wake", lambda now: None)
        patch.setattr(db, "run", no_writes)
        response = app.app.test_client().get("/p/" + token, base_url=ORIGIN)
    assert response.status_code == 200 and message(response) == PAID_TEXT
    assert fake_paypal.calls == []


def test_no_paypal_id_request_id_or_token_is_shown(web_case):
    person = paid_person(web_case)
    refund = add_refund(web_case, person, "IN_FLIGHT", "PENDING")
    set_event(web_case, "REFUNDING")
    token = token_of(web_case, person["pledge_id"])
    text = page(web_case, person["pledge_id"]).get_data(as_text=True)
    capture = db.fetch_one(web_case["conn"], "SELECT capture_id, request_id FROM captures WHERE id = %s", (person["capture"]["id"],))
    hold = db.fetch_one(web_case["conn"], "SELECT auth_id, create_request_id FROM holds WHERE id = %s", (person["hold_id"],))
    for secret in (token, web_case["token"], capture["capture_id"], capture["request_id"], hold["auth_id"],
                   hold["create_request_id"], refund["request_id"], refund["refund_id"]):
        assert secret not in text


# ---------- the leave flow before lock is unchanged, and the back link ----------

def test_before_lock_there_is_no_receipt_and_the_leave_button_still_shows(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "HELD", "CREATED")
    from tests.test_lifecycle import NOW
    from datetime import timedelta
    db.run(web_case["conn"], "UPDATE events SET status = 'OPEN', opens_at = %s, hard_deadline = %s WHERE id = %s",
           (NOW - timedelta(hours=1), NOW + timedelta(days=1), web_case["event_id"]))
    response = page(web_case, person["pledge_id"])
    text = response.get_data(as_text=True)
    assert message(response) == app.LEAVE_ASK_TEXT
    assert 'id="leave-button"' in text and trail(response) == []
    assert "/e/%d" % web_case["event_id"] in text and "Back to board" in text


def test_the_receipt_page_links_back_to_the_board(web_case):
    person = paid_person(web_case)
    set_event(web_case, "SETTLED")
    text = page(web_case, person["pledge_id"]).get_data(as_text=True)
    assert re.search(r'<a [^>]*href="/e/%d"[^>]*>[^<]*Back to board' % web_case["event_id"], text)
