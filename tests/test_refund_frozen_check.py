# D94: "Check with PayPal" for a frozen refund. Fake PayPal and the disposable local PostgreSQL only.
# It only ever sends GET, uses the saved ids, and finishes the EXISTING command once the result is saved.
import inspect
import threading
from datetime import timedelta

import psycopg
import pytest

import app
import config
import db
import lifecycle
from tests import fake_paypal
from tests.test_lifecycle import NOW
from tests.test_refund_lifecycle import refund_case, insert_person, refund_rows, posts
from tests.test_refund_safety import maintenance_connection
from tests.test_refund_stage3_fixes import preflight_all, start_form, commands, captured_person
from tests.test_refund_web import web_case, unlock, get, post, field, path


# ---------- helpers ----------

# A real START whose worker "dies" after PayPal answered: the refund id is saved, the result is not, and the
# START command is still CLAIMED, linked to its refund.
def frozen_after_crash(case, monkeypatch, state="IN_FLIGHT"):
    import refund_web
    captured_person(case)
    client = app.app.test_client()
    unlock(client, case)
    preflight_all(client, case)
    form = start_form(client, case)
    if state == "UNCERTAIN":
        fake_paypal.next_answers["refund_capture"] = [fake_paypal.answer(201, {"id": "REFUNDSYNTH0094", "status": "SOMETHING_ODD"})]
        assert post(client, path(case, "/start"), form).status_code == 303
    else:
        def crash(*args):
            raise psycopg.OperationalError("synthetic worker death before the result was saved")
        with monkeypatch.context() as patch:
            patch.setattr(refund_web, "finish_action", crash)
            assert post(client, path(case, "/start"), form).status_code == 503
    [refund] = refund_rows(case["conn"], case["event_id"])
    assert refund["send_state"] == state and refund["refund_id"] is not None
    # Old enough to be frozen at the test clock (NOW).
    db.run(case["conn"], "UPDATE refunds SET send_started_at = %s WHERE id = %s", (NOW - timedelta(minutes=10), refund["id"]))
    fake_paypal.calls.clear()
    return client, refund


def recheck_path(case, refund_id):
    return path(case, "/" + str(refund_id) + "/paypal-check")


def recheck_form(client, case):
    page = get(client, path(case))
    return {"csrf_token": field(page, "csrf_token"), "action_token": field(page, "action_token")}


def click(client, case, refund, form=None):
    return post(client, recheck_path(case, refund["id"]), form or recheck_form(client, case))


# This event's own captures, by event id. The test database may be shared and may hold other tests' leftovers,
# so a test must never read a whole table.
def own_capture_statuses(case):
    return [row["status"] for row in db.fetch_all(
        case["conn"], "SELECT captures.status FROM captures JOIN holds ON holds.id = captures.hold_id "
                      "JOIN pledges ON pledges.id = holds.pledge_id WHERE pledges.event_id = %s ORDER BY captures.id",
        (case["event_id"],))]


def snapshot(case):
    conn = case["conn"]
    return (refund_rows(conn, case["event_id"]),
            db.fetch_all(conn, "SELECT * FROM refund_web_actions WHERE event_id = %s ORDER BY action_hash", (case["event_id"],)),
            db.fetch_one(conn, "SELECT status, refund_run_token, refund_revision FROM events WHERE id = %s", (case["event_id"],)),
            own_capture_statuses(case),
            db.fetch_all(conn, "SELECT status FROM pledges WHERE event_id = %s ORDER BY id", (case["event_id"],)))


def get_answer(refund, status):
    return fake_paypal.refund_result(refund["refund_id"], status)


# ---------- it finishes the frozen refund and the existing command ----------

@pytest.mark.parametrize("state", ["IN_FLIGHT", "UNCERTAIN", "CHECK_ONLY"])
def test_completed_answer_finishes_the_refund_and_the_existing_command(web_case, monkeypatch, maintenance_connection, state):
    client, refund = frozen_after_crash(web_case, monkeypatch, "UNCERTAIN" if state == "UNCERTAIN" else "IN_FLIGHT")
    event = db.fetch_one(web_case["conn"], "SELECT * FROM events WHERE id = %s", (web_case["event_id"],))
    if state == "CHECK_ONLY":
        assert lifecycle.recover_refund_check_only(maintenance_connection, web_case["token"], refund["id"],
                                                   event["refund_run_token"], event["refund_revision"], refund["operation_revision"])
    [command_before] = commands(web_case["conn"], web_case["event_id"])
    assert command_before["state"] == "CLAIMED"
    form = recheck_form(client, web_case)
    fake_paypal.calls.clear()
    fake_paypal.next_answers["get_refund"] = [get_answer(refund, "COMPLETED")]
    assert click(client, web_case, refund, form).status_code == 303
    assert fake_paypal.called_functions() == ["get_refund"]
    assert posts() == []
    [after] = refund_rows(web_case["conn"], web_case["event_id"])
    assert (after["send_state"], after["status"]) == ("ANSWERED", "COMPLETED")
    assert after["request_id"] == refund["request_id"] and after["refund_id"] == refund["refund_id"]
    assert len(refund_rows(web_case["conn"], web_case["event_id"])) == 1
    [command] = commands(web_case["conn"], web_case["event_id"])
    assert command["action_hash"] == command_before["action_hash"] and command["state"] == "FINISHED"
    assert db.fetch_one(web_case["conn"], "SELECT status FROM events WHERE id = %s", (web_case["event_id"],))["status"] == "REFUNDED"
    assert own_capture_statuses(web_case) == ["REFUNDED"]


def test_no_new_browser_command_is_created(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    before = len(commands(web_case["conn"], web_case["event_id"]))
    fake_paypal.next_answers["get_refund"] = [get_answer(refund, "COMPLETED")]
    assert click(client, web_case, refund).status_code == 303
    assert len(commands(web_case["conn"], web_case["event_id"])) == before == 1


# ---------- if PayPal has no final answer, nothing changes ----------

def test_pending_changes_nothing(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    before = snapshot(web_case)
    fake_paypal.next_answers["get_refund"] = [get_answer(refund, "PENDING")]
    response = click(client, web_case, refund, form)
    assert response.status_code == 200 and "no final answer" in response.get_data(as_text=True)
    assert fake_paypal.called_functions() == ["get_refund"]
    assert snapshot(web_case) == before


def test_no_answer_changes_nothing(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    before = snapshot(web_case)
    fake_paypal.next_answers["get_refund"] = [fake_paypal.no_answer()]
    assert click(client, web_case, refund, form).status_code == 503
    assert fake_paypal.called_functions() == ["get_refund"]
    assert snapshot(web_case) == before


def test_answer_about_a_different_refund_changes_nothing(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    before = snapshot(web_case)
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result("SOMEOTHERREFUND1", "COMPLETED")]
    assert click(client, web_case, refund, form).status_code == 503
    assert snapshot(web_case) == before


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_failed_or_cancelled_writes_nothing_and_says_review_required(web_case, monkeypatch, status):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    before = snapshot(web_case)
    fake_paypal.next_answers["get_refund"] = [get_answer(refund, status)]
    response = click(client, web_case, refund, form)
    assert response.status_code == 200 and "review required" in response.get_data(as_text=True)
    assert snapshot(web_case) == before
    assert posts() == []


def test_a_crash_before_anything_is_saved_changes_nothing(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    before = snapshot(web_case)
    def dies(refund_id):
        fake_paypal.record_and_answer("get_refund", {"refund_id": refund_id}, None)
        raise RuntimeError("synthetic worker death during the GET")
    monkeypatch.setattr(fake_paypal, "get_refund", dies)
    assert click(client, web_case, refund, form).status_code == 503
    assert snapshot(web_case) == before


# ---------- only a refund that is really frozen, with a saved PayPal refund id, qualifies ----------

def test_a_frozen_refund_with_no_saved_refund_id_is_left_to_a_developer(web_case):
    captured_person(web_case)
    client = app.app.test_client()
    unlock(client, web_case)
    preflight_all(client, web_case)
    fake_paypal.next_answers["refund_capture"] = [fake_paypal.no_answer()]
    assert post(client, path(web_case, "/start"), start_form(client, web_case)).status_code == 303
    [refund] = refund_rows(web_case["conn"], web_case["event_id"])
    assert refund["send_state"] == "UNCERTAIN" and refund["refund_id"] is None
    fake_paypal.calls.clear()
    text = get(client, path(web_case)).get_data(as_text=True)
    assert "No PayPal refund id was saved" in text and "a developer must investigate" in text
    assert "Check with PayPal" not in text and "paypal-check" not in text
    assert post(client, recheck_path(web_case, refund["id"]), {"csrf_token": "x", "action_token": "x"}).status_code in (403, 409)
    assert lifecycle.recheck_frozen_refund(web_case["conn"], web_case["event_id"], refund["id"], refund["operation_revision"], NOW, fake_paypal) == "NOT_ELIGIBLE"
    assert fake_paypal.calls == []


def test_a_fresh_in_flight_refund_is_not_offered_and_not_checked(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    db.run(web_case["conn"], "UPDATE refunds SET send_started_at = %s WHERE id = %s", (NOW - timedelta(seconds=config.REFUND_FROZEN_AFTER_SECONDS - 30), refund["id"]))
    assert "Check with PayPal" not in get(client, path(web_case)).get_data(as_text=True)
    assert lifecycle.recheck_frozen_refund(web_case["conn"], web_case["event_id"], refund["id"], refund["operation_revision"], NOW, fake_paypal) == "NOT_ELIGIBLE"
    db.run(web_case["conn"], "UPDATE refunds SET send_started_at = %s WHERE id = %s", (NOW - timedelta(seconds=config.REFUND_FROZEN_AFTER_SECONDS + 1), refund["id"]))
    assert "Check with PayPal" in get(client, path(web_case)).get_data(as_text=True)
    assert fake_paypal.calls == []


def test_the_threshold_is_five_minutes():
    assert config.REFUND_FROZEN_AFTER_SECONDS == 300


def test_a_normal_pending_refund_is_not_a_frozen_refund(web_case):
    from tests.test_refund_safety import saved_refund
    saved_refund(web_case, "ANSWERED")
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case)).get_data(as_text=True)
    assert "Check with PayPal" not in text and "Check PayPal status" in text


# ---------- clicks and tabs ----------

def test_a_second_click_after_success_is_refused_without_a_get(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    fake_paypal.next_answers["get_refund"] = [get_answer(refund, "COMPLETED")]
    assert click(client, web_case, refund, form).status_code == 303
    assert click(client, web_case, refund, form).status_code == 409
    assert fake_paypal.called_functions() == ["get_refund"]


@pytest.mark.parametrize("two_tabs", [False, True])
def test_two_concurrent_clicks_only_one_acts(web_case, monkeypatch, two_tabs):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    other = app.app.test_client() if two_tabs else client
    if two_tabs:
        unlock(other, web_case)
    first_form = recheck_form(client, web_case)
    second_form = recheck_form(other, web_case)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def paused(refund_id):
        calls.append(refund_id)
        fake_paypal.record_and_answer("get_refund", {"refund_id": refund_id}, None)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return get_answer(refund, "COMPLETED")
    monkeypatch.setattr(fake_paypal, "get_refund", paused)
    outcomes = []
    worker = threading.Thread(target=lambda: outcomes.append(click(client, web_case, refund, first_form).status_code))
    worker.start()
    try:
        assert entered.wait(10)
        outcomes.append(click(other, web_case, refund, second_form).status_code)
    finally:
        release.set()
        worker.join(10)
    assert sorted(outcomes) == [303, 409]
    assert posts() == []
    [after] = refund_rows(web_case["conn"], web_case["event_id"])
    assert (after["send_state"], after["status"]) == ("ANSWERED", "COMPLETED")
    assert [row["state"] for row in commands(web_case["conn"], web_case["event_id"])] == ["FINISHED"]


def test_a_form_for_an_older_revision_is_refused_before_any_get(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    # Still frozen, but something else moved the refund on since this form was shown.
    db.run(web_case["conn"], "UPDATE refunds SET operation_revision = operation_revision + 1 WHERE id = %s", (refund["id"],))
    assert click(client, web_case, refund, form).status_code == 409
    assert fake_paypal.calls == []
    assert lifecycle.recheck_frozen_refund(web_case["conn"], web_case["event_id"], refund["id"], refund["operation_revision"], NOW, fake_paypal) == "NOT_ELIGIBLE"
    assert fake_paypal.calls == []


def test_a_refund_of_another_event_is_never_checked_even_if_both_are_refunding(web_case, monkeypatch):
    from tests.test_refund_lifecycle import insert_event, delete_event
    client, refund = frozen_after_crash(web_case, monkeypatch)
    other_id, _ = insert_event(web_case["conn"], "REFUNDING")
    try:
        db.run(web_case["conn"], "UPDATE events SET refund_run_token = 'synthetic-other-owner' WHERE id = %s", (other_id,))
        assert lifecycle.recheck_frozen_refund(web_case["conn"], other_id, refund["id"], refund["operation_revision"], NOW, fake_paypal) == "NOT_ELIGIBLE"
        assert fake_paypal.calls == []
    finally:
        delete_event(web_case["conn"], other_id)


# ---------- a crash in the middle of the check ----------

def test_a_crash_inside_the_final_transaction_rolls_everything_back_and_a_retry_works(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    before = snapshot(web_case)
    fake_paypal.next_answers["get_refund"] = [get_answer(refund, "COMPLETED")]
    def dies(*args, **kwargs):
        raise psycopg.OperationalError("synthetic disconnect inside the final transaction")
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle, "finish_web_command", dies)
        assert click(client, web_case, refund, form).status_code == 503
    assert snapshot(web_case) == before
    fake_paypal.next_answers["get_refund"] = [get_answer(refund, "COMPLETED")]
    assert click(client, web_case, refund, form).status_code == 303
    assert [row["state"] for row in commands(web_case["conn"], web_case["event_id"])] == ["FINISHED"]


# ---------- same session, CSRF and origin checks as the other refund actions ----------

def test_session_csrf_origin_and_form_checks(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    url = recheck_path(web_case, refund["id"])
    assert post(app.app.test_client(), url, form).status_code == 403
    assert post(client, url, dict(form, csrf_token="wrong")).status_code == 403
    assert post(client, url, form, origin="https://attacker.example").status_code == 403
    assert post(client, url, dict(form, action_token=form["action_token"] + "x")).status_code == 409
    assert get(client, url).status_code == 405
    assert post(client, recheck_path(web_case, refund["id"] + 999), form).status_code == 409
    other_event = dict(web_case, event_id=web_case["event_id"] + 999999)
    assert post(client, path(other_event, "/" + str(refund["id"]) + "/paypal-check"), form).status_code == 403
    monkeypatch.setattr(app, "utc_now", lambda: NOW + timedelta(minutes=11))
    assert post(client, url, form).status_code in (403, 409)
    assert fake_paypal.calls == []


def test_a_check_form_cannot_be_used_for_another_action(web_case, monkeypatch):
    client, refund = frozen_after_crash(web_case, monkeypatch)
    form = recheck_form(client, web_case)
    assert post(client, path(web_case, "/continue"), form).status_code == 409
    assert post(client, path(web_case, "/" + str(refund["id"]) + "/check"), form).status_code == 409
    assert fake_paypal.calls == []


# ---------- it can never send money ----------

def test_the_recheck_code_cannot_post_or_mint_a_request_id():
    source = inspect.getsource(lifecycle.recheck_frozen_refund) + inspect.getsource(lifecycle.fence_to_check_only)
    for forbidden in ("refund_capture", "new_request_id", "capture_authorization", "void_authorization", "post_refund"):
        assert forbidden not in source


def test_maintenance_recovery_still_needs_its_dedicated_connection(web_case):
    from tests.test_refund_safety import saved_refund
    _, row = saved_refund(web_case, "IN_FLIGHT")
    with pytest.raises(PermissionError):
        lifecycle.recover_refund_check_only(web_case["conn"], web_case["token"], row["id"], "audit-owner", 1, row["operation_revision"])
