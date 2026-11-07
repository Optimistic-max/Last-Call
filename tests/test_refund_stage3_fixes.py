# Stage 3 corrections (D93). Fake PayPal and the disposable local PostgreSQL only. Synthetic data only.
import re

import psycopg
import pytest

import app
import db
import lifecycle
import refund_web
from tests import fake_paypal
from tests.test_refund_lifecycle import refund_case, insert_person, refund_rows, posts
from tests.test_refund_safety import saved_refund, maintenance_connection
from tests.test_refund_web import web_case, unlock, get, post, field, path


# ---------- small helpers ----------

def preflight(client, case):
    page = get(client, path(case, "/confirm"))
    return post(client, path(case, "/preflight"), {"csrf_token": field(page, "csrf_token")})


def preflight_all(client, case):
    for _ in range(20):
        answer = preflight(client, case).get_json()
        if answer["done"] or answer["error"]:
            return answer
    raise AssertionError("preflight did not finish")


def start_form(client, case):
    page = get(client, path(case, "/confirm"))
    return {"csrf_token": field(page, "csrf_token"), "action_token": field(page, "action_token")}


def cancel_path(case, hold_id, suffix=""):
    return path(case, "/holds/" + str(hold_id) + "/cancel" + suffix)


def cancel_form(client, case, hold_id):
    page = get(client, cancel_path(case, hold_id))
    assert page.status_code == 200, page.status_code
    return {"csrf_token": field(page, "csrf_token"), "action_token": field(page, "action_token")}


def commands(conn, event_id):
    return db.fetch_all(conn, "SELECT * FROM refund_web_actions WHERE event_id = %s ORDER BY created_at, action_hash", (event_id,))


def hold_row(conn, hold_id):
    return db.fetch_one(conn, "SELECT * FROM holds WHERE id = %s", (hold_id,))


def open_hold(case):
    return insert_person(case["conn"], case["event_id"], "FAILED", "CREATED")


def captured_person(case, cents=640):
    return insert_person(case["conn"], case["event_id"], "CHARGED", "CAPTURED", "COMPLETED", cents)


# ---------- fix 1 and 2: a bounded, GET-only preflight, one authorization per request ----------

def test_preflight_uses_only_get_and_writes_only_the_check_result(web_case):
    paid = captured_person(web_case)
    open_one = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    answer = preflight_all(client, web_case)
    assert answer == {"checked": 2, "total": 2, "done": True, "error": False}
    assert fake_paypal.called_functions() == ["get_authorization", "get_authorization"]
    assert hold_row(web_case["conn"], paid["hold_id"])["refund_check_status"] == "RESOLVED"
    still_open = hold_row(web_case["conn"], open_one["hold_id"])
    assert still_open["refund_check_status"] == "PENDING"
    assert still_open["status"] == "CREATED" and still_open["void_run_token"] is None and still_open["void_request_id"] is None
    assert refund_rows(web_case["conn"], web_case["event_id"]) == []
    assert commands(web_case["conn"], web_case["event_id"]) == []


def test_each_preflight_request_checks_exactly_one_authorization(web_case):
    for _ in range(3):
        captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    first = preflight(client, web_case)
    assert first.status_code == 200
    assert first.get_json() == {"checked": 1, "total": 3, "done": False, "error": False}
    assert fake_paypal.called_functions() == ["get_authorization"]
    assert preflight(client, web_case).get_json()["checked"] == 2
    assert fake_paypal.called_functions() == ["get_authorization"] * 2


def test_a_request_never_calls_paypal_more_than_the_gunicorn_budget_allows(web_case):
    import config
    for _ in range(4):
        captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight(client, web_case)
    # One authorization at the longest PayPal wait, with room to spare inside gunicorn's 120 seconds.
    assert len(fake_paypal.calls) * config.PAYPAL_TIMEOUT_SECONDS * 3 < 120


def test_preflight_needs_authorization_csrf_and_origin(web_case):
    captured_person(web_case)
    anonymous = app.app.test_client()
    assert post(anonymous, path(web_case, "/preflight"), {}).status_code == 403
    client = app.app.test_client()
    unlock(client, web_case)
    page = get(client, path(web_case, "/confirm"))
    csrf = field(page, "csrf_token")
    assert post(client, path(web_case, "/preflight"), {"csrf_token": "wrong"}).status_code == 403
    assert post(client, path(web_case, "/preflight"), {"csrf_token": csrf}, origin="https://attacker.example").status_code == 403
    assert get(client, path(web_case, "/preflight")).status_code == 405
    assert fake_paypal.calls == []


def test_preflight_with_no_answer_stops_and_writes_nothing(web_case):
    person = captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.no_answer()]
    answer = preflight(client, web_case).get_json()
    assert answer["error"] is True and answer["done"] is False
    assert hold_row(web_case["conn"], person["hold_id"])["refund_check_status"] is None


def test_preflight_unknown_authorization_status_is_not_saved(web_case):
    person = captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("SOMETHING_NEW", person["auth_id"])]
    assert preflight(client, web_case).get_json()["error"] is True
    assert hold_row(web_case["conn"], person["hold_id"])["refund_check_status"] is None


def test_preflight_is_refused_when_the_event_is_not_waiting_for_review(web_case):
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    csrf = field(get(client, path(web_case, "/confirm")), "csrf_token")
    db.run(web_case["conn"], "UPDATE events SET status = 'SETTLED' WHERE id = %s", (web_case["event_id"],))
    response = post(client, path(web_case, "/preflight"), {"csrf_token": csrf})
    assert response.status_code == 409
    assert fake_paypal.calls == []


def test_confirm_page_shows_checked_n_of_m_and_start_waits_for_the_check(web_case):
    captured_person(web_case)
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case, "/confirm")).get_data(as_text=True)
    assert "Checked 0 of 2" in text and 'name="action_token"' not in text
    preflight(client, web_case)
    text = get(client, path(web_case, "/confirm")).get_data(as_text=True)
    assert "Checked 1 of 2" in text and 'name="action_token"' not in text
    preflight(client, web_case)
    text = get(client, path(web_case, "/confirm")).get_data(as_text=True)
    assert "Checked 2 of 2" in text and 'name="action_token"' in text


def test_start_does_not_check_or_cancel_holds_itself(web_case):
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = start_form(client, web_case)
    fake_paypal.calls.clear()
    assert post(client, path(web_case, "/start"), form).status_code == 303
    assert fake_paypal.called_functions() == ["refund_capture"]


def test_the_status_page_and_the_confirm_page_send_nothing_to_paypal(web_case):
    captured_person(web_case)
    open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    get(client, path(web_case, "/confirm"))
    get(client, path(web_case))
    assert fake_paypal.calls == []


# ---------- fix 3: cancelling holds needs its own explicit, single-use confirmation ----------

def test_an_open_hold_blocks_start_and_nothing_cancels_it_automatically(web_case):
    captured_person(web_case)
    open_one = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    text = get(client, path(web_case, "/confirm")).get_data(as_text=True)
    assert 'name="action_token"' not in text
    assert cancel_path(web_case, open_one["hold_id"]) in text
    assert "void_authorization" not in fake_paypal.called_functions()
    assert hold_row(web_case["conn"], open_one["hold_id"])["void_run_token"] is None


def test_cancel_has_its_own_confirmation_and_names_the_hold(web_case):
    person = open_hold(web_case)
    db.run(web_case["conn"], "UPDATE pledges SET name = '<b>Synthetic Pat</b>', max_cents = 1234 WHERE id = %s", (person["pledge_id"],))
    db.run(web_case["conn"], "UPDATE holds SET amount_cents = 1234 WHERE id = %s", (person["hold_id"],))
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    page = get(client, cancel_path(web_case, person["hold_id"]))
    text = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "&lt;b&gt;Synthetic Pat" in text and "<b>Synthetic Pat" not in text and "$12.34" in text
    assert person["auth_id"] not in text and web_case["token"] not in text
    assert "no-store" in page.headers["Cache-Control"]
    assert fake_paypal.called_functions() == ["get_authorization"]


def test_cancel_runs_once_with_the_saved_request_id_and_finishes_its_command(web_case):
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = cancel_form(client, web_case, person["hold_id"])
    fake_paypal.calls.clear()
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", person["auth_id"])]
    assert post(client, cancel_path(web_case, person["hold_id"]), form).status_code == 303
    assert fake_paypal.called_functions() == ["void_authorization", "get_authorization"]
    hold = hold_row(web_case["conn"], person["hold_id"])
    assert hold["status"] == "VOIDED" and hold["void_run_token"] is None
    assert hold["refund_check_status"] == "RESOLVED"
    assert fake_paypal.calls[0]["request_id"] == hold["void_request_id"]
    [row] = commands(web_case["conn"], web_case["event_id"])
    assert row["action_type"] == "CANCEL_HOLD" and row["target_hold_id"] == person["hold_id"] and row["state"] == "FINISHED"
    # Replaying the same form changes nothing and sends nothing.
    assert post(client, cancel_path(web_case, person["hold_id"]), form).status_code == 303
    assert len(fake_paypal.calls) == 2


def test_after_the_cancel_start_becomes_available(web_case):
    captured_person(web_case)
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", person["auth_id"])]
    assert post(client, cancel_path(web_case, person["hold_id"]), cancel_form(client, web_case, person["hold_id"])).status_code == 303
    assert 'name="action_token"' in get(client, path(web_case, "/confirm")).get_data(as_text=True)


def test_a_cancel_form_works_only_for_its_own_hold_and_action(web_case):
    first = open_hold(web_case)
    second = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = cancel_form(client, web_case, first["hold_id"])
    fake_paypal.calls.clear()
    assert post(client, cancel_path(web_case, second["hold_id"]), form).status_code == 409
    assert post(client, cancel_path(web_case, first["hold_id"]), dict(form, action_token=form["action_token"] + "x")).status_code == 409
    assert post(client, path(web_case, "/start"), form).status_code == 409
    assert post(client, path(web_case, "/continue"), form).status_code == 409
    assert fake_paypal.calls == []
    assert get(client, cancel_path(web_case, first["hold_id"], "/x")).status_code == 404


def test_cancel_needs_csrf_origin_and_a_checked_open_hold(web_case):
    resolved = captured_person(web_case)
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = cancel_form(client, web_case, person["hold_id"])
    fake_paypal.calls.clear()
    assert post(client, cancel_path(web_case, person["hold_id"]), dict(form, csrf_token="wrong")).status_code == 403
    assert post(client, cancel_path(web_case, person["hold_id"]), form, origin="https://attacker.example").status_code == 403
    assert get(client, cancel_path(web_case, resolved["hold_id"])).status_code == 409
    assert post(app.app.test_client(), cancel_path(web_case, person["hold_id"]), form).status_code == 403
    assert fake_paypal.calls == []


def test_an_unchecked_hold_cannot_be_cancelled(web_case):
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    assert get(client, cancel_path(web_case, person["hold_id"])).status_code == 409
    assert fake_paypal.calls == []


# The locked lifecycle check is the final authority; the web layer's own check is only a first layer.
def test_the_locked_claim_refuses_a_hold_the_preflight_has_not_seen_open(web_case):
    conn = web_case["conn"]
    person = open_hold(web_case)
    assert lifecycle.claim_cancel_hold(conn, web_case["event_id"], person["hold_id"]) is None
    assert hold_row(conn, person["hold_id"])["void_run_token"] is None
    db.run(conn, "UPDATE holds SET refund_check_status = 'PENDING' WHERE id = %s", (person["hold_id"],))
    assert lifecycle.claim_cancel_hold(conn, web_case["event_id"] + 1, person["hold_id"]) is None
    db.run(conn, "UPDATE events SET status = 'SETTLED' WHERE id = %s", (web_case["event_id"],))
    assert lifecycle.claim_cancel_hold(conn, web_case["event_id"], person["hold_id"]) is None
    assert hold_row(conn, person["hold_id"])["void_run_token"] is None
    db.run(conn, "UPDATE events SET status = 'NEEDS_ATTENTION' WHERE id = %s", (web_case["event_id"],))
    claim = lifecycle.claim_cancel_hold(conn, web_case["event_id"], person["hold_id"])
    assert claim["id"] == person["hold_id"] and hold_row(conn, person["hold_id"])["void_request_id"] == claim["void_request_id"]
    assert fake_paypal.calls == []


def test_cancel_with_an_unconfirmed_read_back_keeps_the_claim_blocked(web_case):
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = cancel_form(client, web_case, person["hold_id"])
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.no_answer()]
    post(client, cancel_path(web_case, person["hold_id"]), form)
    hold = hold_row(web_case["conn"], person["hold_id"])
    assert hold["void_run_token"] is not None and hold["status"] == "CREATED"
    assert [row["state"] for row in commands(web_case["conn"], web_case["event_id"])] == ["CLAIMED"]
    assert post(client, cancel_path(web_case, person["hold_id"]), form).status_code == 409


# ---------- fix 4: the claim and the command, and the result and the finish, commit together ----------

def test_start_claim_and_command_are_committed_together_before_paypal(web_case, test_db_url):
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = start_form(client, web_case)
    seen = []
    def paused(capture_id, request_id):
        with db.connect(test_db_url) as other:
            [row] = commands(other, web_case["event_id"])
            refund = refund_rows(other, web_case["event_id"])[0]
            seen.append((row["state"], row["claimed_refund_id"] == refund["id"], refund["send_state"]))
            with other.transaction():
                other.execute("SELECT id FROM events WHERE id = %s FOR UPDATE NOWAIT", (web_case["event_id"],))
        return fake_paypal.record_and_answer("refund_capture", {}, fake_paypal.refund_result("SYNTHETICREFUND", "COMPLETED"))
    original = fake_paypal.refund_capture
    fake_paypal.refund_capture = paused
    try:
        assert post(client, path(web_case, "/start"), form).status_code == 303
    finally:
        fake_paypal.refund_capture = original
    assert seen == [("CLAIMED", True, "IN_FLIGHT")]


def test_failed_command_insert_rolls_back_the_payment_claim(web_case, monkeypatch):
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = start_form(client, web_case)
    fake_paypal.calls.clear()
    def refuse(*args, **kwargs):
        raise psycopg.errors.UniqueViolation("synthetic duplicate command")
    monkeypatch.setattr(refund_web, "insert_command", refuse)
    assert post(client, path(web_case, "/start"), form).status_code == 503
    assert refund_rows(web_case["conn"], web_case["event_id"]) == []
    assert db.fetch_one(web_case["conn"], "SELECT status FROM events WHERE id = %s", (web_case["event_id"],))["status"] == "NEEDS_ATTENTION"
    assert commands(web_case["conn"], web_case["event_id"]) == []
    assert fake_paypal.calls == []


def test_failed_finish_rolls_back_the_saved_result_with_it(web_case, monkeypatch):
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = start_form(client, web_case)
    def unavailable(*args):
        raise psycopg.OperationalError("synthetic local disconnect")
    monkeypatch.setattr(refund_web, "finish_action", unavailable)
    assert post(client, path(web_case, "/start"), form).status_code == 503
    [refund] = refund_rows(web_case["conn"], web_case["event_id"])
    # The answer and the finish are one transaction, so neither was saved. The saved refund id stays.
    assert refund["send_state"] == "IN_FLIGHT" and refund["status"] == "PENDING" and refund["refund_id"] is not None
    assert [row["state"] for row in commands(web_case["conn"], web_case["event_id"])] == ["CLAIMED"]
    assert len(posts()) == 1
    assert post(client, path(web_case, "/start"), form).status_code == 409
    assert len(posts()) == 1


def test_failed_command_insert_rolls_back_the_void_claim(web_case, monkeypatch):
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = cancel_form(client, web_case, person["hold_id"])
    fake_paypal.calls.clear()
    def refuse(*args, **kwargs):
        raise psycopg.errors.UniqueViolation("synthetic duplicate command")
    monkeypatch.setattr(refund_web, "insert_command", refuse)
    assert post(client, cancel_path(web_case, person["hold_id"]), form).status_code == 503
    hold = hold_row(web_case["conn"], person["hold_id"])
    assert hold["void_run_token"] is None and hold["void_request_id"] is None
    assert fake_paypal.calls == []


def test_cancel_claim_and_command_are_committed_together_before_paypal(web_case, test_db_url):
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = cancel_form(client, web_case, person["hold_id"])
    seen = []
    def paused(auth_id, request_id):
        with db.connect(test_db_url) as other:
            [row] = commands(other, web_case["event_id"])
            hold = hold_row(other, person["hold_id"])
            seen.append((row["state"], row["target_hold_id"] == person["hold_id"], hold["void_run_token"] is not None, hold["void_request_id"] == request_id))
            with other.transaction():
                other.execute("SELECT id FROM events WHERE id = %s FOR UPDATE NOWAIT", (web_case["event_id"],))
        return fake_paypal.record_and_answer("void_authorization", {}, fake_paypal.answer(204, {}))
    original = fake_paypal.void_authorization
    fake_paypal.void_authorization = paused
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", person["auth_id"])]
    try:
        assert post(client, cancel_path(web_case, person["hold_id"]), form).status_code == 303
    finally:
        fake_paypal.void_authorization = original
    assert seen == [("CLAIMED", True, True, True)]


def test_failed_finish_rolls_back_the_cancel_result_with_it(web_case, monkeypatch):
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = cancel_form(client, web_case, person["hold_id"])
    fake_paypal.calls.clear()
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", person["auth_id"])]
    def unavailable(*args):
        raise psycopg.OperationalError("synthetic local disconnect")
    monkeypatch.setattr(refund_web, "finish_action", unavailable)
    assert post(client, cancel_path(web_case, person["hold_id"]), form).status_code == 503
    hold = hold_row(web_case["conn"], person["hold_id"])
    assert hold["status"] == "CREATED" and hold["void_run_token"] is not None
    assert [row["state"] for row in commands(web_case["conn"], web_case["event_id"])] == ["CLAIMED"]
    assert fake_paypal.called_functions() == ["void_authorization", "get_authorization"]


# Crash recovery: the command is left CLAIMED, and the existing GET-only recovery finishes it.

def test_crash_after_a_start_payment_is_recovered_with_get_only_and_the_command_finishes(web_case, monkeypatch, maintenance_connection):
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = start_form(client, web_case)
    def crash(*args):
        raise psycopg.OperationalError("synthetic worker death before the result was saved")
    with monkeypatch.context() as patch:
        patch.setattr(refund_web, "finish_action", crash)
        assert post(client, path(web_case, "/start"), form).status_code == 503
    event = db.fetch_one(web_case["conn"], "SELECT * FROM events WHERE id = %s", (web_case["event_id"],))
    [refund] = refund_rows(web_case["conn"], web_case["event_id"])
    assert [row["state"] for row in commands(web_case["conn"], web_case["event_id"])] == ["CLAIMED"]
    assert lifecycle.recover_refund_check_only(maintenance_connection, web_case["token"], refund["id"], event["refund_run_token"],
                                               event["refund_revision"], refund["operation_revision"])
    fake_paypal.calls.clear()
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(refund["refund_id"], "COMPLETED")]
    assert lifecycle.reconcile_refund(web_case["conn"], refund["id"], fake_paypal) == "COMPLETED"
    assert fake_paypal.called_functions() == ["get_refund"]
    [command] = commands(web_case["conn"], web_case["event_id"])
    assert command["state"] == "FINISHED"
    assert refund_rows(web_case["conn"], web_case["event_id"])[0]["status"] == "COMPLETED"
    assert len(posts()) == 0


def test_crash_after_a_pending_check_is_recovered_with_get_only_and_the_command_finishes(web_case, monkeypatch):
    _, row = saved_refund(web_case, "ANSWERED")
    client = app.app.test_client()
    unlock(client, web_case)
    page = get(client, path(web_case))
    form = {"csrf_token": field(page, "csrf_token"), "action_token": field(page, "action_token")}
    def crash(*args):
        raise psycopg.OperationalError("synthetic worker death before the result was saved")
    with monkeypatch.context() as patch:
        patch.setattr(refund_web, "finish_action", crash)
        assert post(client, path(web_case, "/" + str(row["id"]) + "/check"), form).status_code == 503
    assert [command["state"] for command in commands(web_case["conn"], web_case["event_id"])] == ["CLAIMED"]
    fake_paypal.calls.clear()
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(row["refund_id"], "COMPLETED")]
    assert lifecycle.reconcile_refund(web_case["conn"], row["id"], fake_paypal) == "COMPLETED"
    assert fake_paypal.called_functions() == ["get_refund"]
    assert [command["state"] for command in commands(web_case["conn"], web_case["event_id"])] == ["FINISHED"]


def test_crash_after_a_cancel_is_recovered_with_get_only_and_the_command_finishes(web_case, monkeypatch):
    person = open_hold(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    form = cancel_form(client, web_case, person["hold_id"])
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", person["auth_id"])]
    def crash(*args):
        raise psycopg.OperationalError("synthetic worker death before the result was saved")
    with monkeypatch.context() as patch:
        patch.setattr(refund_web, "finish_action", crash)
        assert post(client, cancel_path(web_case, person["hold_id"]), form).status_code == 503
    assert [command["state"] for command in commands(web_case["conn"], web_case["event_id"])] == ["CLAIMED"]
    fake_paypal.calls.clear()
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", person["auth_id"])]
    assert lifecycle.reconcile_uncertain_void(web_case["conn"], person["hold_id"], fake_paypal) == "VOIDED"
    assert fake_paypal.called_functions() == ["get_authorization"]
    hold = hold_row(web_case["conn"], person["hold_id"])
    assert hold["status"] == "VOIDED" and hold["void_run_token"] is None
    assert [command["state"] for command in commands(web_case["conn"], web_case["event_id"])] == ["FINISHED"]
    # The next preflight request re-reads the cancelled hold and marks it checked.
    assert preflight_all(client, web_case)["done"] is True
    assert hold_row(web_case["conn"], person["hold_id"])["refund_check_status"] == "RESOLVED"


def test_an_unresolved_refund_keeps_its_command_open(web_case):
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    fake_paypal.next_answers["refund_capture"] = [fake_paypal.no_answer()]
    assert post(client, path(web_case, "/start"), start_form(client, web_case)).status_code == 303
    assert [command["state"] for command in commands(web_case["conn"], web_case["event_id"])] == ["CLAIMED"]
    assert refund_rows(web_case["conn"], web_case["event_id"])[0]["send_state"] == "UNCERTAIN"
    assert len(posts()) == 1


# New code always links the payment claim to its command (007 will make this a database rule).

def test_start_and_continue_always_record_the_refund_they_claimed(web_case):
    for _ in range(2):
        captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    assert post(client, path(web_case, "/start"), start_form(client, web_case)).status_code == 303
    page = get(client, path(web_case))
    assert post(client, path(web_case, "/continue"),
                {"csrf_token": field(page, "csrf_token"), "action_token": field(page, "action_token")}).status_code == 303
    refunds = refund_rows(web_case["conn"], web_case["event_id"])
    rows = commands(web_case["conn"], web_case["event_id"])
    assert sorted(row["action_type"] for row in rows) == ["CONTINUE", "START"]
    assert sorted(row["claimed_refund_id"] for row in rows) == sorted(refund["id"] for refund in refunds)
    assert all(row["claimed_refund_id"] is not None for row in rows)


# ---------- fix 5: no misleading $0.00 when captured-payment records are incomplete ----------

def total_line(text):
    found = re.search(r"Recorded captured payments[^<]*", text)
    return found.group(0) if found else ""


@pytest.mark.parametrize("page", ["/confirm", ""])
def test_missing_capture_record_does_not_show_a_zero_total(web_case, page):
    person = insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED")
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case, page)).get_data(as_text=True)
    assert "$0.00" not in text
    assert "incomplete" in total_line(text)


@pytest.mark.parametrize("page", ["/confirm", ""])
def test_partial_records_do_not_present_a_partial_sum_as_the_total(web_case, page):
    captured_person(web_case, 641)
    insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED")
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case, page)).get_data(as_text=True)
    assert "$6.41" not in total_line(text)
    assert "incomplete" in total_line(text)


def test_an_unresolved_capture_attempt_makes_the_total_unknown(web_case):
    person = captured_person(web_case, 641)
    db.run(web_case["conn"], "INSERT INTO captures (hold_id, request_id, amount_cents, status) VALUES (%s, 'synthetic-unknown-cap', 641, 'PENDING')",
           (person["hold_id"],))
    client = app.app.test_client()
    unlock(client, web_case)
    assert "incomplete" in total_line(get(client, path(web_case, "/confirm")).get_data(as_text=True))


def test_complete_records_and_a_true_zero_still_show_their_totals(web_case):
    client = app.app.test_client()
    unlock(client, web_case)
    assert "$0.00" in total_line(get(client, path(web_case, "/confirm")).get_data(as_text=True))
    captured_person(web_case, 641)
    assert "$6.41" in total_line(get(client, path(web_case, "/confirm")).get_data(as_text=True))
