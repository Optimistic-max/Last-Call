# D97: after the lock the board's first card shows what was charged (and refunded) instead of "Held so far $0.00".
# The amounts are SQL sums of saved capture and refund rows, never recomputed from shares. Fake PayPal and the
# disposable local database. Synthetic data only.
import json
import uuid
from datetime import timedelta

import pytest

import app
import db
import lifecycle
from tests import fake_paypal
from tests.test_lifecycle import NOW
from tests.test_refund_lifecycle import refund_case, insert_person
from tests.test_routes import use_test_setup

CHECKING = "Total being checked"


@pytest.fixture(autouse=True)
def do_not_settle(monkeypatch):
    monkeypatch.setattr(app, "settle_on_wake", lambda now: None)


@pytest.fixture
def case(refund_case, monkeypatch, test_db_url):
    use_test_setup(monkeypatch, test_db_url)
    db.run(refund_case["conn"], "UPDATE events SET opens_at = %s, hard_deadline = %s, last_call_ends = %s WHERE id = %s",
           (NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(minutes=5), refund_case["event_id"]))
    return refund_case


def set_event(case, status):
    db.run(case["conn"], "UPDATE events SET status = %s WHERE id = %s", (status, case["event_id"]))


def board(case):
    response = app.app.test_client().get("/e/%d/board.json" % case["event_id"])
    assert response.status_code == 200
    return response.get_json()


# A friend who was charged `cents`: pledge CHARGED with its saved share, a CAPTURED hold, a COMPLETED capture.
def charged(case, cents, share_cents=None):
    person = insert_person(case["conn"], case["event_id"], "CHARGED", "CAPTURED", "COMPLETED", 1500)
    db.run(case["conn"], "UPDATE captures SET amount_cents = %s WHERE id = %s", (cents, person["capture"]["id"]))
    db.run(case["conn"], "UPDATE pledges SET share_cents = %s WHERE id = %s", (cents if share_cents is None else share_cents, person["pledge_id"]))
    return person


def confirmed_refund(case, person, cents, send_state="ANSWERED", status="COMPLETED"):
    refund_id = None if send_state == "READY" else fake_paypal.new_id("REFUND")
    return db.fetch_one(case["conn"], "INSERT INTO refunds (capture_id, request_id, amount_cents, refund_id, send_state, status, send_started_at) "
                                      "VALUES (%s, %s, %s, %s, %s, %s, now()) RETURNING *",
                        (person["capture"]["id"], uuid.uuid4().hex, cents, refund_id, send_state, status))


# ---------- the numbers ----------

def test_settled_shows_the_sum_of_the_saved_charges(case):
    for cents in (1077, 1078, 1078):
        charged(case, cents)
    set_event(case, "SETTLED")
    answer = board(case)
    assert answer["charged_total_text"] == "$32.33" and answer["refunded_total_text"] == ""
    assert answer["held_total_text"] == "$0.00"                      # still HELD money only


def test_a_partly_failed_event_counts_only_the_charges_that_happened(case):
    charged(case, 1077)
    charged(case, 1078)
    failed = insert_person(case["conn"], case["event_id"], "FAILED", "CREATED")
    for attempt in (1, 2):
        db.run(case["conn"], "INSERT INTO captures (hold_id, request_id, attempt, amount_cents, status, error_code) "
                             "VALUES (%s, %s, %s, 1078, 'FAILED', 'TRANSACTION_REFUSED')", (failed["hold_id"], uuid.uuid4().hex, attempt))
    set_event(case, "NEEDS_ATTENTION")
    answer = board(case)
    assert answer["charged_total_text"] == "$21.55" and answer["refunded_total_text"] == ""


def test_refunds_keep_the_charged_total_and_show_the_refunded_amount(case):
    people = [charged(case, 1077), charged(case, 1078), charged(case, 1078)]
    db.run(case["conn"], "UPDATE events SET status = 'REFUNDING', refund_run_token = 'synthetic-owner', refund_revision = 1 WHERE id = %s", (case["event_id"],))
    confirmed_refund(case, people[0], 1077)
    db.run(case["conn"], "UPDATE captures SET status = 'REFUNDED' WHERE id = %s", (people[0]["capture"]["id"],))
    answer = board(case)
    assert answer["charged_total_text"] == "$32.33" and answer["refunded_total_text"] == "$10.77"
    for person, cents in zip(people[1:], (1078, 1078)):
        confirmed_refund(case, person, cents)
        db.run(case["conn"], "UPDATE captures SET status = 'REFUNDED' WHERE id = %s", (person["capture"]["id"],))
    set_event(case, "REFUNDED")
    answer = board(case)
    assert answer["charged_total_text"] == "$32.33" and answer["refunded_total_text"] == "$32.33"


@pytest.mark.parametrize("send_state,status", [("READY", "PENDING"), ("IN_FLIGHT", "PENDING"), ("UNCERTAIN", "PENDING"),
                                               ("CHECK_ONLY", "PENDING"), ("ANSWERED", "PENDING"), ("ANSWERED", "FAILED"),
                                               ("ANSWERED", "CANCELLED")])
def test_a_refund_that_is_not_confirmed_is_not_counted_as_refunded(case, send_state, status):
    person = charged(case, 1077)
    confirmed_refund(case, person, 1077, send_state, status)
    set_event(case, "REFUNDING")
    answer = board(case)
    assert answer["charged_total_text"] == "$10.77" and answer["refunded_total_text"] == ""


def test_the_total_follows_the_capture_rows_not_the_saved_shares(case):
    charged(case, 1077, share_cents=1000)
    set_event(case, "SETTLED")
    assert board(case)["charged_total_text"] == "$10.77"


# ---------- never a number we cannot stand behind ----------

def test_an_unresolved_capture_shows_total_being_checked_never_a_number(case):
    person = charged(case, 1077)
    db.run(case["conn"], "INSERT INTO captures (hold_id, request_id, attempt, amount_cents, status) VALUES (%s, %s, 2, 1077, 'PENDING')",
           (person["hold_id"], uuid.uuid4().hex))
    set_event(case, "SETTLED")
    answer = board(case)
    assert answer["charged_total_text"] == CHECKING and answer["refunded_total_text"] == ""
    assert "$0.00" not in answer["charged_total_text"]


def test_a_failed_pledge_whose_hold_paypal_says_is_captured_is_being_checked(case):
    charged(case, 1077)
    insert_person(case["conn"], case["event_id"], "FAILED", "CAPTURED")
    set_event(case, "NEEDS_ATTENTION")
    assert board(case)["charged_total_text"] == CHECKING


def test_a_charged_pledge_with_no_recorded_payment_is_being_checked(case):
    insert_person(case["conn"], case["event_id"], "CHARGED", "CAPTURED")
    db.run(case["conn"], "UPDATE pledges SET share_cents = 1077 WHERE event_id = %s", (case["event_id"],))
    set_event(case, "SETTLED")
    assert board(case)["charged_total_text"] == CHECKING


@pytest.mark.parametrize("status", ["PENDING", "COMPLETED", "REFUNDED", "FAILED"])
@pytest.mark.parametrize("capture_id", [None, "", "   ", "CAPTURESYNTH"])
@pytest.mark.parametrize("amount_cents", [0, 1077])
def test_the_sql_unresolved_rule_agrees_with_capture_is_unknown(case, status, capture_id, amount_cents):
    person = insert_person(case["conn"], case["event_id"], "HELD", "VOIDED")
    if capture_id == "CAPTURESYNTH":
        capture_id = "CAPTURESYNTH" + uuid.uuid4().hex[:8]              # capture ids are unique
    row = db.fetch_one(case["conn"], "INSERT INTO captures (hold_id, request_id, amount_cents, capture_id, status) "
                                     "VALUES (%s, %s, %s, %s, %s) RETURNING *",
                       (person["hold_id"], uuid.uuid4().hex, amount_cents, capture_id, status))
    set_event(case, "SETTLED")
    expected_unknown = lifecycle.capture_is_unknown(row)
    assert (board(case)["charged_total_text"] == CHECKING) is expected_unknown


# ---------- before the lock nothing changes, and nothing private appears ----------

@pytest.mark.parametrize("status", ["DRAFT", "OPEN", "LAST_CALL", "LOCKING", "CHARGING", "EXPIRED"])
def test_before_the_lock_the_card_is_unchanged(case, status):
    insert_person(case["conn"], case["event_id"], "HELD", "CREATED", None, 1500)
    set_event(case, status)
    answer = board(case)
    assert answer["charged_total_text"] == "" and answer["refunded_total_text"] == ""
    assert answer["held_total_text"] == "$15.00"


def test_no_paypal_id_or_request_id_reaches_the_board(case):
    person = charged(case, 1077)
    refund = confirmed_refund(case, person, 1077)
    set_event(case, "REFUNDING")
    text = app.app.test_client().get("/e/%d/board.json" % case["event_id"]).get_data(as_text=True)
    capture = db.fetch_one(case["conn"], "SELECT capture_id, request_id FROM captures WHERE id = %s", (person["capture"]["id"],))
    hold = db.fetch_one(case["conn"], "SELECT auth_id, create_request_id FROM holds WHERE id = %s", (person["hold_id"],))
    for secret in (capture["capture_id"], capture["request_id"], hold["auth_id"], hold["create_request_id"], refund["request_id"], refund["refund_id"]):
        assert secret not in text
    assert json.loads(text)["charged_total_text"] == "$10.77"


# ---------- the page (S2 and S3) ----------

def test_the_card_switches_to_charged_on_s3_and_keeps_held_before_the_lock(case):
    people = [charged(case, 1077), charged(case, 1078)]
    set_event(case, "SETTLED")
    text = app.app.test_client().get("/e/%d" % case["event_id"]).get_data(as_text=True)
    assert "Charged" in text and "$21.55" in text and "Charged once." in text
    assert "Held so far" not in text
    confirmed_refund(case, people[0], 1077)
    set_event(case, "REFUNDING")
    assert "Refunded $10.77" in app.app.test_client().get("/e/%d" % case["event_id"]).get_data(as_text=True)
    set_event(case, "OPEN")
    before = app.app.test_client().get("/e/%d" % case["event_id"]).get_data(as_text=True)
    assert "Held so far" in before and "Refunded" not in before
