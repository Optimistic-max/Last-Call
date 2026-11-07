# Synthetic treasurer-interface regressions. Fake PayPal and disposable PostgreSQL only.
import re
import threading
from datetime import timedelta

import psycopg
import pytest
from werkzeug.security import generate_password_hash

import app
import config
import db
import lifecycle
import money
from tests import fake_paypal
from tests.test_lifecycle import NOW
from tests.test_refund_lifecycle import refund_case, insert_person, refund_rows, posts, insert_event, delete_event
from tests.test_refund_safety import saved_refund

ORIGIN = "https://refund.example"
KEY = "synthetic-independent-treasurer-key-123456789"
KEY_HASH = generate_password_hash(KEY, method="pbkdf2:sha256:1000")


# Set all configuration explicitly; never use a real approval key or real PayPal.
@pytest.fixture
def web_case(refund_case, test_db_url, monkeypatch, request):
    monkeypatch.setattr(config, "DATABASE_URL", test_db_url)
    monkeypatch.setattr(config, "APP_BASE_URL", ORIGIN)
    monkeypatch.setattr(config, "FLASK_SECRET_KEY", "synthetic-session-secret-" * 3)
    monkeypatch.setattr(config, "REFUND_APPROVAL_KEY_HASH", KEY_HASH, raising=False)
    monkeypatch.setattr(config, "REFUND_ALLOW_LOCAL_HTTP", False, raising=False)
    monkeypatch.setattr(app, "paypal_client", fake_paypal)
    monkeypatch.setattr(app, "utc_now", lambda: NOW)
    monkeypatch.setitem(app.app.config, "SECRET_KEY", config.FLASK_SECRET_KEY)
    monkeypatch.setitem(app.app.config, "SESSION_COOKIE_SECURE", True)
    # Registered after refund_case's finalizer, so web records are removed first.
    def cleanup():
        if db.fetch_one(refund_case["conn"], "SELECT to_regclass('public.refund_web_actions') AS name")["name"]:
            db.run(refund_case["conn"], "DELETE FROM refund_web_actions WHERE event_id = %s", (refund_case["event_id"],))
    request.addfinalizer(cleanup)
    return refund_case


# Hidden inputs are parsed from rendered forms, as a browser would receive them.
def field(response, name):
    found = re.search('name="' + name + '" value="([^"]+)"', response.get_data(as_text=True))
    assert found is not None, response.status_code
    return found.group(1)


def get(client, path):
    return client.get(path, base_url=ORIGIN)


def post(client, path, data, origin=ORIGIN):
    headers = {} if origin is None else {"Origin": origin}
    return client.post(path, data=data, base_url=ORIGIN, headers=headers)


def path(case, suffix=""):
    return "/admin/events/" + str(case["event_id"]) + "/refunds" + suffix


def unlock(client, case):
    address = "/admin/" + case["token"] + "/refund-access"
    page = get(client, address)
    assert page.status_code == 200
    result = post(client, address, {"csrf_token": field(page, "csrf_token"), "approval_key": KEY})
    assert result.status_code == 303
    return result


def action_form(client, case, suffix="/confirm"):
    page = get(client, path(case, suffix))
    assert page.status_code == 200
    return {"csrf_token": field(page, "csrf_token"), "action_token": field(page, "action_token")}


def test_url_token_alone_cannot_send_and_refund_requests_never_settle(web_case, monkeypatch):
    settled = []
    monkeypatch.setattr(app, "settle_on_wake", lambda now: settled.append(now))
    client = app.app.test_client()
    assert post(client, path(web_case, "/start"), {}).status_code == 403
    assert get(client, path(web_case)).status_code == 403
    assert fake_paypal.calls == []
    assert settled == []


def test_approval_requires_independent_key_and_csrf(web_case):
    client = app.app.test_client()
    address = "/admin/" + web_case["token"] + "/refund-access"
    page = get(client, address)
    assert page.status_code == 200
    csrf = field(page, "csrf_token")
    assert post(client, address, {"approval_key": KEY}).status_code == 403
    assert post(client, address, {"csrf_token": csrf, "approval_key": "wrong-independent-approval-key-123456789"}).status_code == 403
    assert get(client, path(web_case)).status_code == 403
    assert fake_paypal.calls == []


@pytest.mark.parametrize("setting,value", [("FLASK_SECRET_KEY", ""), ("REFUND_APPROVAL_KEY_HASH", ""),
                                           ("APP_BASE_URL", "http://refund.example")])
def test_missing_or_unsafe_configuration_fails_closed(web_case, monkeypatch, setting, value):
    monkeypatch.setattr(config, setting, value)
    assert get(app.app.test_client(), "/admin/" + web_case["token"] + "/refund-access").status_code == 503
    assert fake_paypal.calls == []


@pytest.mark.parametrize("origin", [None, "https://attacker.example", ORIGIN + ".attacker.example", "null"])
def test_origin_is_required_and_exact(web_case, origin):
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case)
    assert post(client, path(web_case, "/start"), form, origin).status_code == 403
    assert fake_paypal.calls == []


def test_captured_totals_xss_and_private_fields(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED", 641)
    db.run(web_case["conn"], "UPDATE pledges SET name = '<script>alert(1)</script>', max_cents = 9999 WHERE id = %s", (person["pledge_id"],))
    client = app.app.test_client()
    authorization = unlock(client, web_case)
    page = get(client, path(web_case, "/confirm"))
    text = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "$6.41" in text and "$99.99" not in text
    assert "&lt;script&gt;" in text and "<script>alert" not in text
    assert "Fee information unavailable" in text
    assert person["auth_id"] not in text and person["capture"]["capture_id"] not in text
    assert web_case["token"] not in text
    assert "no-store" in page.headers["Cache-Control"]
    assert page.headers["Referrer-Policy"] == "no-referrer"
    cookie = authorization.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie
    assert fake_paypal.calls == []


def test_start_replay_is_recorded_but_new_continue_can_proceed(web_case):
    for _ in range(2):
        insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case)
    assert post(client, path(web_case, "/start"), form).status_code == 303
    assert len(posts()) == 1
    assert post(client, path(web_case, "/start"), form).status_code == 303
    assert len(posts()) == 1
    assert db.fetch_one(web_case["conn"], "SELECT state FROM refund_web_actions WHERE event_id = %s", (web_case["event_id"],))["state"] == "FINISHED"
    continue_form = action_form(client, web_case, "")
    assert post(client, path(web_case, "/continue"), continue_form).status_code == 303
    assert len(posts()) == 2
    assert get(client, path(web_case)).status_code == 200
    assert len(posts()) == 2


def test_cross_event_expired_and_rotated_grants_are_rejected(web_case, monkeypatch):
    client = app.app.test_client()
    unlock(client, web_case)
    other = dict(web_case, event_id=web_case["event_id"] + 999999)
    assert get(client, path(other)).status_code == 403
    monkeypatch.setattr(app, "utc_now", lambda: NOW + timedelta(hours=1))
    assert get(client, path(web_case)).status_code == 403
    monkeypatch.setattr(app, "utc_now", lambda: NOW)
    db.run(web_case["conn"], "UPDATE events SET admin_token = 'synthetic-rotated-token' WHERE id = %s", (web_case["event_id"],))
    assert get(client, path(web_case)).status_code == 403


def test_d47_and_zero_payment_views_do_not_promise_refunds(web_case):
    insert_person(web_case["conn"], web_case["event_id"], "FAILED", "CAPTURED")
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case, "/confirm")).get_data(as_text=True)
    assert "captured money" in text
    assert 'name="action_token"' not in text
    assert "Everyone has been refunded" not in text
    assert fake_paypal.calls == []


def test_unknown_result_keeps_command_blocked(web_case):
    insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case)
    fake_paypal.next_answers["refund_capture"] = [fake_paypal.no_answer()]
    assert post(client, path(web_case, "/start"), form).status_code == 303
    row = db.fetch_one(web_case["conn"], "SELECT state FROM refund_web_actions WHERE event_id = %s", (web_case["event_id"],))
    assert row["state"] == "CLAIMED"
    text = get(client, path(web_case)).get_data(as_text=True)
    assert "investigation" in text and 'name="action_token"' not in text
    assert len(posts()) == 1


@pytest.mark.parametrize("copied", [False, True])
def test_same_and_independent_clicks_cannot_overlap(web_case, test_db_url, monkeypatch, copied):
    for _ in range(2):
        insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    first = app.app.test_client()
    second = app.app.test_client()
    unlock(first, web_case)
    unlock(second, web_case)
    form = action_form(first, web_case)
    other_form = action_form(second, web_case)
    if copied:
        second.set_cookie("session", first.get_cookie("session", domain="refund.example").value, domain="refund.example")
        other_form = dict(form)
    entered = threading.Event()
    release = threading.Event()
    outcomes = []
    def paused(capture_id, request_id):
        # A second connection must see the claim before external HTTP begins.
        with db.connect(test_db_url) as observer:
            assert db.fetch_one(observer, "SELECT state FROM refund_web_actions WHERE event_id = %s", (web_case["event_id"],))["state"] == "CLAIMED"
            with observer.transaction():
                # An HTTP call must not retain the event lock or any surrounding transaction.
                observer.execute("SELECT id FROM events WHERE id = %s FOR UPDATE NOWAIT", (web_case["event_id"],))
        entered.set()
        assert release.wait(10)
        return fake_paypal.record_and_answer("refund_capture", {}, fake_paypal.refund_result("SYNTHETICREFUND", "COMPLETED"))
    monkeypatch.setattr(fake_paypal, "refund_capture", paused)
    worker = threading.Thread(target=lambda: outcomes.append(post(first, path(web_case, "/start"), form).status_code))
    worker.start()
    try:
        assert entered.wait(10)
        assert post(second, path(web_case, "/start"), other_form).status_code == 409
        assert fake_paypal.calls[-1]["function"] != "refund_capture"
    finally:
        release.set()
        worker.join(10)
    assert outcomes == [303] and len(posts()) == 1


@pytest.mark.parametrize("state", ["IN_FLIGHT", "UNCERTAIN", "CHECK_ONLY"])
def test_browser_cannot_reconcile_recovery_states(web_case, state):
    _, row = saved_refund(web_case, state)
    fn = getattr(lifecycle, "reconcile_refund_for_treasurer", None)
    assert callable(fn), "Browser reconciliation needs a locked event-scoped eligibility check"
    assert fn(web_case["conn"], web_case["event_id"], row["id"], row["operation_revision"], fake_paypal) is None
    assert fake_paypal.calls == []


def test_browser_pending_reconciliation_checks_event_and_revision(web_case):
    _, row = saved_refund(web_case, "ANSWERED")
    fn = getattr(lifecycle, "reconcile_refund_for_treasurer", None)
    assert callable(fn)
    assert fn(web_case["conn"], web_case["event_id"] + 1, row["id"], row["operation_revision"], fake_paypal) is None
    assert fn(web_case["conn"], web_case["event_id"], row["id"], row["operation_revision"] + 1, fake_paypal) is None
    assert fake_paypal.calls == []
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(row["refund_id"], "PENDING")]
    assert fn(web_case["conn"], web_case["event_id"], row["id"], row["operation_revision"], fake_paypal) == "PENDING"
    assert fake_paypal.called_functions() == ["get_refund"]


def test_refund_summary_uses_captured_integer_cents_only():
    fn = getattr(money, "refund_summary_cents", None)
    assert callable(fn)
    assert fn([{"amount_cents": 641, "fee_cents": 62}, {"amount_cents": 842, "fee_cents": 71}]) == {"amount_cents": 1483, "fee_cents": 133}
    assert fn([{"amount_cents": 641, "fee_cents": None}])["fee_cents"] is None
    assert fn([]) == {"amount_cents": 0, "fee_cents": 0}


@pytest.mark.parametrize("state,status,label", [
    ("READY", "PENDING", "Not sent yet"), ("IN_FLIGHT", "PENDING", "result not yet confirmed"),
    ("UNCERTAIN", "PENDING", "Result unknown"), ("CHECK_ONLY", "PENDING", "Maintenance status check"),
    ("ANSWERED", "PENDING", "PayPal is processing"), ("ANSWERED", "FAILED", "review required"),
    ("ANSWERED", "CANCELLED", "review required"), ("ANSWERED", "COMPLETED", "Payment records require investigation"),
])
def test_payment_states_are_honest_and_never_offer_retry(web_case, state, status, label):
    _, row = saved_refund(web_case, state, status)
    if state == "READY":
        # Build an actually unsent row; saved_refund otherwise models historical send evidence.
        db.run(web_case["conn"], "UPDATE refunds SET send_started_at = NULL WHERE id = %s", (row["id"],))
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case)).get_data(as_text=True)
    assert label in text
    assert "Try again" not in text and "/retry" not in text and "Fully refunded" not in text
    assert row["request_id"] not in text
    if row["refund_id"]:
        assert row["refund_id"] not in text
    if state != "ANSWERED" or status != "PENDING":
        assert "Check PayPal status" not in text


def test_pending_check_timeout_finishes_read_command_without_blocking_independent_work(web_case):
    _, row = saved_refund(web_case, "ANSWERED")
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case, "")
    fake_paypal.next_answers["get_refund"] = [fake_paypal.no_answer()]
    response = post(client, path(web_case, "/" + str(row["id"]) + "/check"), form)
    assert response.status_code == 503
    assert fake_paypal.called_functions() == ["get_refund"]
    assert db.fetch_one(web_case["conn"], "SELECT state FROM refund_web_actions WHERE event_id = %s", (web_case["event_id"],))["state"] == "FINISHED"
    assert "Check PayPal status" in get(client, path(web_case)).get_data(as_text=True)


def test_crash_after_web_claim_before_lifecycle_stays_blocked(web_case, monkeypatch):
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case)
    def stopped(*args):
        raise RuntimeError("synthetic worker interruption")
    monkeypatch.setattr(lifecycle, "begin_refund_all", stopped)
    assert post(client, path(web_case, "/start"), form).status_code == 503
    assert db.fetch_one(web_case["conn"], "SELECT state FROM refund_web_actions WHERE event_id = %s", (web_case["event_id"],))["state"] == "CLAIMED"
    assert post(client, path(web_case, "/start"), form).status_code == 409
    assert fake_paypal.calls == []


def test_stale_tampered_wrong_action_and_csrf_forms_do_not_execute(web_case, monkeypatch):
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case)
    assert post(client, path(web_case, "/start"), dict(form, csrf_token="wrong")).status_code == 403
    assert post(client, path(web_case, "/continue"), form).status_code == 409
    assert post(client, path(web_case, "/start"), dict(form, action_token=form["action_token"] + "x")).status_code == 409
    db.run(web_case["conn"], "UPDATE events SET title = 'changed after confirmation' WHERE id = %s", (web_case["event_id"],))
    assert post(client, path(web_case, "/start"), form).status_code == 409
    fresh = action_form(client, web_case)
    monkeypatch.setattr(app, "utc_now", lambda: NOW + timedelta(minutes=11))
    assert post(client, path(web_case, "/start"), fresh).status_code == 409
    assert fake_paypal.calls == []


def test_maintenance_fence_after_browser_web_claim_cannot_be_adopted(web_case, monkeypatch):
    _, row = saved_refund(web_case, "ANSWERED")
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case, "")
    import refund_web
    original = refund_web.claim_action
    def fenced(*args, **kwargs):
        result = original(*args, **kwargs)
        db.run(web_case["conn"], "UPDATE refunds SET send_state = 'CHECK_ONLY', operation_revision = operation_revision + 1 WHERE id = %s", (row["id"],))
        return result
    monkeypatch.setattr(refund_web, "claim_action", fenced)
    assert post(client, path(web_case, "/" + str(row["id"]) + "/check"), form).status_code == 503
    assert fake_paypal.calls == []
    assert refund_rows(web_case["conn"], web_case["event_id"])[0]["send_state"] == "CHECK_ONLY"


def test_changed_revision_after_web_claim_is_not_adopted(web_case, monkeypatch):
    _, row = saved_refund(web_case, "ANSWERED")
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case, "")
    import refund_web
    original = refund_web.claim_action
    def newer(*args, **kwargs):
        result = original(*args, **kwargs)
        db.run(web_case["conn"], "UPDATE refunds SET operation_revision = operation_revision + 1 WHERE id = %s", (row["id"],))
        return result
    monkeypatch.setattr(refund_web, "claim_action", newer)
    assert post(client, path(web_case, "/" + str(row["id"]) + "/check"), form).status_code == 503
    assert fake_paypal.calls == []


def test_missing_refund_inventory_blocks_continue(web_case):
    _, row = saved_refund(web_case, "READY")
    insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case)).get_data(as_text=True)
    assert "missing" in text and 'name="action_token"' not in text


def test_zero_capture_completion_is_explicit_and_refresh_sends_nothing(web_case):
    client = app.app.test_client()
    unlock(client, web_case)
    assert post(client, path(web_case, "/start"), action_form(client, web_case)).status_code == 303
    text = get(client, path(web_case)).get_data(as_text=True)
    assert "No captured payments required refunds" in text
    assert fake_paypal.calls == []


def test_get_cannot_execute_and_oversized_post_is_refused(web_case):
    client = app.app.test_client()
    unlock(client, web_case)
    for suffix in ("/start", "/continue", "/1/check", "/retry", "/recover"):
        assert get(client, path(web_case, suffix)).status_code in (404, 405)
    assert post(client, path(web_case, "/start"), {"padding": "x" * 9000}).status_code == 413
    assert fake_paypal.calls == []


def test_non_ascii_csrf_is_refused_without_server_error(web_case):
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case)
    assert post(client, path(web_case, "/start"), dict(form, csrf_token="\u00e9")).status_code == 403


def test_pending_get_reconciles_to_completion_without_post(web_case):
    _, row = saved_refund(web_case, "ANSWERED")
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case, "")
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(row["refund_id"], "COMPLETED")]
    assert post(client, path(web_case, "/" + str(row["id"]) + "/check"), form).status_code == 303
    text = get(client, path(web_case)).get_data(as_text=True)
    assert "Refunded - confirmed by PayPal" in text
    assert fake_paypal.called_functions() == ["get_refund"]
    assert post(client, path(web_case, "/" + str(row["id"]) + "/check"), form).status_code == 303
    assert fake_paypal.called_functions() == ["get_refund"]


def test_worker_exception_after_payment_preserves_command_and_does_not_resend(web_case, monkeypatch):
    import refund_web
    insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case)
    def unavailable(*args):
        raise psycopg.OperationalError("synthetic local disconnect")
    monkeypatch.setattr(refund_web, "finish_action", unavailable)
    assert post(client, path(web_case, "/start"), form).status_code == 503
    assert len(posts()) == 1
    assert post(client, path(web_case, "/start"), form).status_code == 409
    assert len(posts()) == 1


def test_bad_referer_is_rejected_and_same_origin_fallback_is_accepted(web_case):
    client = app.app.test_client()
    address = "/admin/" + web_case["token"] + "/refund-access"
    page = get(client, address)
    form = {"csrf_token": field(page, "csrf_token"), "approval_key": KEY}
    response = client.post(address, data=form, base_url=ORIGIN, headers={"Referer": "http://[invalid"})
    assert response.status_code == 403
    response = client.post(address, data=form, base_url=ORIGIN, headers={"Referer": ORIGIN + "/treasurer"})
    assert response.status_code == 303


def test_locked_browser_check_observes_maintenance_change(web_case, test_db_url, monkeypatch):
    _, row = saved_refund(web_case, "ANSWERED")
    waiting = threading.Event()
    outcomes = []
    errors = []
    original = db.fetch_one
    def observed(conn, sql, params=()):
        if threading.current_thread().name == "browser-check" and sql == "SELECT * FROM events WHERE id = %s FOR UPDATE":
            waiting.set()
        return original(conn, sql, params)
    monkeypatch.setattr(db, "fetch_one", observed)
    def worker():
        try:
            with db.connect(test_db_url) as other:
                outcomes.append(lifecycle.reconcile_refund_for_treasurer(other, web_case["event_id"], row["id"], row["operation_revision"], fake_paypal))
        except Exception as error:
            errors.append(error)
    with web_case["conn"].transaction():
        web_case["conn"].execute("SELECT id FROM events WHERE id = %s FOR UPDATE", (web_case["event_id"],))
        thread = threading.Thread(target=worker, name="browser-check")
        thread.start()
        assert waiting.wait(10)
        db.run(web_case["conn"], "UPDATE refunds SET send_state = 'CHECK_ONLY', operation_revision = operation_revision + 1 WHERE id = %s", (row["id"],))
    thread.join(10)
    assert not thread.is_alive() and errors == [] and outcomes == [None]
    assert fake_paypal.calls == []


@pytest.mark.parametrize("status,word", [("REFUNDING", "Refunds are in progress"), ("REFUNDED", "Refunds complete")])
def test_public_board_refund_status_is_generic(status, word):
    assert app.banner_text({"event": {"status": status}}, None) == word
    assert app.status_word({"status": "REFUNDED"}) == "Refunded"


def test_inconsistent_completed_event_does_not_claim_financial_resolution(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    client = app.app.test_client()
    unlock(client, web_case)
    assert post(client, path(web_case, "/start"), action_form(client, web_case)).status_code == 303
    db.run(web_case["conn"], "INSERT INTO captures (hold_id, request_id, amount_cents, status) VALUES (%s, %s, 640, 'PENDING')",
           (person["hold_id"], "synthetic-unknown-" + str(person["hold_id"])))
    text = get(client, path(web_case)).get_data(as_text=True)
    assert "Fully refunded" not in text
    assert "The event's refunds and authorizations are resolved" not in text
    assert "investigation" in text


def test_web_claim_is_durable_before_lifecycle(web_case, test_db_url, monkeypatch):
    observed = []
    def inspect_claim(*args):
        with db.connect(test_db_url) as other:
            row = db.fetch_one(other, "SELECT state FROM refund_web_actions WHERE event_id = %s", (web_case["event_id"],))
            observed.append(None if row is None else row["state"])
    monkeypatch.setattr(lifecycle, "begin_refund_all", inspect_claim)
    client = app.app.test_client()
    unlock(client, web_case)
    assert post(client, path(web_case, "/start"), action_form(client, web_case)).status_code == 303
    assert observed == ["CLAIMED"]


def test_event_scope_is_checked_even_with_correct_admin_binding(web_case):
    client = app.app.test_client()
    unlock(client, web_case)
    with client.session_transaction(base_url=ORIGIN) as saved:
        grant = dict(saved["refund_grant"])
        grant["event_id"] += 1
        saved["refund_grant"] = grant
    assert get(client, path(web_case)).status_code == 403


def test_check_rejects_real_other_event_even_when_both_are_refunding(web_case):
    _, row = saved_refund(web_case, "ANSWERED")
    other_id, _ = insert_event(web_case["conn"], "REFUNDING")
    try:
        db.run(web_case["conn"], "UPDATE events SET refund_run_token = 'synthetic-other-owner' WHERE id = %s", (other_id,))
        assert lifecycle.reconcile_refund_for_treasurer(web_case["conn"], other_id, row["id"], row["operation_revision"], fake_paypal) is None
        assert fake_paypal.calls == []
    finally:
        delete_event(web_case["conn"], other_id)


def test_changed_captured_amount_requires_fresh_confirmation(web_case):
    person = insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED", 641)
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case)
    db.run(web_case["conn"], "UPDATE captures SET amount_cents = 642 WHERE id = %s", (person["capture"]["id"],))
    assert post(client, path(web_case, "/start"), form).status_code == 409
    assert fake_paypal.calls == []


def test_old_uncertain_web_claim_never_expires(web_case):
    db.run(web_case["conn"], "INSERT INTO refund_web_actions (action_hash, event_id, session_hash, action_type, created_at) "
                            "VALUES ('synthetic-old-command', %s, 'synthetic-session', 'START', %s)",
           (web_case["event_id"], NOW - timedelta(days=30)))
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case, "/confirm")).get_data(as_text=True)
    assert "investigation" in text and 'name="action_token"' not in text
    assert fake_paypal.calls == []


@pytest.mark.parametrize("status", ["PENDING", "FAILED"])
def test_known_answer_allows_next_independent_refund_but_never_retries_it(web_case, status):
    for _ in range(2):
        insert_person(web_case["conn"], web_case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    client = app.app.test_client()
    unlock(client, web_case)
    fake_paypal.next_answers["refund_capture"] = [fake_paypal.refund_result("SYNTHETICKNOWN", status)]
    assert post(client, path(web_case, "/start"), action_form(client, web_case)).status_code == 303
    assert post(client, path(web_case, "/continue"), action_form(client, web_case, "")).status_code == 303
    rows = refund_rows(web_case["conn"], web_case["event_id"])
    assert [row["status"] for row in rows] == [status, "COMPLETED"]
    assert len(posts()) == 2
    assert posts()[0]["request_id"] != posts()[1]["request_id"]


def test_form_from_another_authorized_session_is_rejected(web_case):
    first = app.app.test_client()
    second = app.app.test_client()
    unlock(first, web_case)
    unlock(second, web_case)
    form = action_form(first, web_case)
    second_form = action_form(second, web_case)
    form["csrf_token"] = second_form["csrf_token"]
    assert post(second, path(web_case, "/start"), form).status_code == 409
    assert fake_paypal.calls == []


def test_dropped_pledge_with_unrecorded_capture_is_explained(web_case):
    insert_person(web_case["conn"], web_case["event_id"], "DROPPED", "CAPTURED")
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case, "/confirm")).get_data(as_text=True)
    assert "captured money" in text and 'name="action_token"' not in text


def test_form_expiry_after_successful_claim_does_not_break_pending_check(web_case, monkeypatch):
    _, row = saved_refund(web_case, "ANSWERED")
    client = app.app.test_client()
    unlock(client, web_case)
    form = action_form(client, web_case, "")
    import refund_web
    original = refund_web.claim_action
    def claimed(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(app, "utc_now", lambda: NOW + timedelta(minutes=11))
        return result
    monkeypatch.setattr(refund_web, "claim_action", claimed)
    fake_paypal.next_answers["get_refund"] = [fake_paypal.refund_result(row["refund_id"], "PENDING")]
    assert post(client, path(web_case, "/" + str(row["id"]) + "/check"), form).status_code == 303
    assert fake_paypal.called_functions() == ["get_refund"]


def test_ready_with_sending_history_is_not_presented_as_unsent(web_case):
    saved_refund(web_case, "READY")
    client = app.app.test_client()
    unlock(client, web_case)
    text = get(client, path(web_case)).get_data(as_text=True)
    assert "sending history" in text and "investigation" in text
    assert "Not sent yet" not in text and 'name="action_token"' not in text
