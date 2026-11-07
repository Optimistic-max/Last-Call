# F7 Stage 2A: void ownership must survive races and uncertain external calls.
import threading
import time
import uuid
from datetime import timedelta

import psycopg
import pytest

import db
import lifecycle
from tests import fake_paypal
from tests.test_sweep import SWEEP_NOW


# Each test owns its event and removes it, including when setup or an assertion fails.
@pytest.fixture
def void_case(test_db, request):
    key = uuid.uuid4().hex
    event = db.fetch_one(test_db, "INSERT INTO events (title, deposit_cents, admin_token, status) "
                                 "VALUES (%s, %s, %s, 'NEEDS_ATTENTION') RETURNING id",
                         ("synthetic void ownership", 2000, key))

    def cleanup():
        db.run(test_db, "DELETE FROM holds WHERE pledge_id IN (SELECT id FROM pledges WHERE event_id = %s)",
               (event["id"],))
        db.run(test_db, "DELETE FROM pledges WHERE event_id = %s", (event["id"],))
        db.run(test_db, "DELETE FROM events WHERE id = %s", (event["id"],))

    request.addfinalizer(cleanup)
    pledge = db.fetch_one(test_db, "INSERT INTO pledges (event_id, name, max_cents, pledger_token, status) "
                                  "VALUES (%s, %s, %s, %s, 'HELD') RETURNING id",
                          (event["id"], "Synthetic", 500, key))
    hold = db.fetch_one(test_db, "INSERT INTO holds (pledge_id, create_request_id, amount_cents, auth_id, status) "
                                "VALUES (%s, %s, %s, %s, 'CREATED') RETURNING id",
                        (pledge["id"], key, 500, "FAKE" + key))
    fake_paypal.reset()
    return event["id"], pledge["id"], hold["id"]


# A candidate selected before refunding must be checked again before any PayPal call.
def test_stale_sweep_candidate_does_not_void_after_refunding(test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    candidates = lifecycle.stranded_created_holds(test_db, SWEEP_NOW)
    candidate = next(row for row in candidates if row["id"] == hold_id)
    db.run(test_db, "UPDATE events SET status = 'REFUNDING' WHERE id = %s", (event_id,))
    lifecycle.sweep_one_hold(test_db, candidate, SWEEP_NOW, fake_paypal)
    assert fake_paypal.called_functions() == []
    assert db.fetch_one(test_db, "SELECT status FROM holds WHERE id = %s", (hold_id,))["status"] == "CREATED"


# The dropped-pledge sweep must not start during the refund handoff.
def test_dropped_hold_is_not_swept_while_refunding(test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    db.run(test_db, "UPDATE pledges SET status = 'DROPPED' WHERE id = %s", (pledge_id,))
    db.run(test_db, "UPDATE events SET status = 'REFUNDING' WHERE id = %s", (event_id,))
    lifecycle.sweep_stranded_holds(test_db, SWEEP_NOW, fake_paypal)
    assert fake_paypal.called_functions() == []
    assert db.fetch_one(test_db, "SELECT status FROM holds WHERE id = %s", (hold_id,))["status"] == "CREATED"


# The sweep must also recheck pledge and event eligibility when neither is refunding.
def test_stale_sweep_candidate_is_rechecked_for_open_event(test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    candidates = lifecycle.stranded_created_holds(test_db, SWEEP_NOW)
    candidate = next(row for row in candidates if row["id"] == hold_id)
    db.run(test_db, "UPDATE events SET status = 'OPEN' WHERE id = %s", (event_id,))
    lifecycle.sweep_one_hold(test_db, candidate, SWEEP_NOW, fake_paypal)
    assert fake_paypal.called_functions() == []
    assert db.fetch_one(test_db, "SELECT status FROM holds WHERE id = %s", (hold_id,))["status"] == "CREATED"


# A second caller cannot issue a void while the first caller is waiting for PayPal.
def test_two_void_callers_do_not_overlap(monkeypatch, test_db, test_db_url, void_case):
    event_id, pledge_id, hold_id = void_case
    entered = threading.Event()
    release = threading.Event()
    calls = []
    errors = []

    def paused_void(auth_id, request_id):
        calls.append(request_id)
        if len(calls) == 1:
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test did not release first caller")
        return fake_paypal.answer(204, {})

    def first_caller():
        try:
            with db.connect(test_db_url) as connection:
                lifecycle.void_hold(connection, hold_id, fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "void_authorization", paused_void)
    worker = threading.Thread(target=first_caller)
    worker.start()
    try:
        assert entered.wait(10)
        lifecycle.void_hold(test_db, hold_id, fake_paypal)
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert errors == []
    assert len(calls) == 1


# An unanswered void and GET are uncertain even after the old five-minute retry interval.
def test_uncertain_void_is_not_retried_by_later_sweep(test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    fake_paypal.next_answers["void_authorization"] = [fake_paypal.no_answer()]
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.no_answer()]
    lifecycle.sweep_stranded_holds(test_db, SWEEP_NOW, fake_paypal)
    lifecycle.sweep_stranded_holds(test_db, SWEEP_NOW + timedelta(hours=1), fake_paypal)
    assert fake_paypal.called_functions().count("void_authorization") == 1


# A definite authentication refusal plus a matching CREATED GET can retry the saved request later.
def test_definite_authentication_refusal_can_retry_saved_void(test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    hold = db.fetch_one(test_db, "SELECT auth_id FROM holds WHERE id = %s", (hold_id,))
    fake_paypal.next_answers["void_authorization"] = [fake_paypal.answer(401, {"name": "AUTHENTICATION_FAILURE"})]
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", hold["auth_id"])]
    lifecycle.sweep_stranded_holds(test_db, SWEEP_NOW, fake_paypal)
    lifecycle.sweep_stranded_holds(test_db, SWEEP_NOW + timedelta(hours=1), fake_paypal)
    calls = [call for call in fake_paypal.calls if call["function"] == "void_authorization"]
    assert len(calls) == 2
    assert calls[0]["request_id"] == calls[1]["request_id"]
    assert db.fetch_one(test_db, "SELECT status FROM holds WHERE id = %s", (hold_id,))["status"] == "VOIDED"


# An HTTP error without the definite authentication failure must not unlock an uncertain call.
@pytest.mark.parametrize("answer", [fake_paypal.answer(401, {}),
                                    fake_paypal.answer(422, {"name": "UNPROCESSABLE_ENTITY"}),
                                    fake_paypal.no_answer()])
def test_unproven_void_refusal_stays_blocked(test_db, void_case, answer):
    event_id, pledge_id, hold_id = void_case
    hold = db.fetch_one(test_db, "SELECT auth_id FROM holds WHERE id = %s", (hold_id,))
    fake_paypal.next_answers["void_authorization"] = [answer]
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", hold["auth_id"])]
    lifecycle.sweep_stranded_holds(test_db, SWEEP_NOW, fake_paypal)
    lifecycle.sweep_stranded_holds(test_db, SWEEP_NOW + timedelta(hours=1), fake_paypal)
    assert fake_paypal.called_functions().count("void_authorization") == 1
    assert db.fetch_one(test_db, "SELECT void_run_token FROM holds WHERE id = %s", (hold_id,))["void_run_token"] is not None


# An exception while sending leaves possible external work; another caller must not send it again.
def test_interrupted_void_does_not_allow_another_send(monkeypatch, test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    calls = []

    def interrupted(auth_id, request_id):
        calls.append(request_id)
        raise psycopg.OperationalError("simulated lost connection")

    monkeypatch.setattr(fake_paypal, "void_authorization", interrupted)
    with pytest.raises(psycopg.OperationalError):
        lifecycle.void_hold(test_db, hold_id, fake_paypal)
    lifecycle.void_hold(test_db, hold_id, fake_paypal)
    assert len(calls) == 1


# Refund handoff must not pass while the first worker is still inside the void call.
def test_refund_handoff_is_blocked_by_active_void(monkeypatch, test_db, test_db_url, void_case):
    event_id, pledge_id, hold_id = void_case
    entered = threading.Event()
    release = threading.Event()
    errors = []

    def paused_void(auth_id, request_id):
        entered.set()
        if not release.wait(10):
            raise RuntimeError("test did not release void")
        return fake_paypal.answer(204, {})

    def worker_body():
        try:
            with db.connect(test_db_url) as connection:
                lifecycle.void_hold(connection, hold_id, fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "void_authorization", paused_void)
    worker = threading.Thread(target=worker_body)
    worker.start()
    try:
        assert entered.wait(10)
        try:
            db.run(test_db, "UPDATE events SET status = 'REFUNDING' WHERE id = %s AND status = 'NEEDS_ATTENTION'",
                   (event_id,))
        except psycopg.errors.CheckViolation:
            pass
        assert lifecycle.find_event(test_db, event_id)["status"] == "NEEDS_ATTENTION"
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert errors == []


# Both the saved idempotency key and the owner must be visible from a second connection before sending.
def test_void_request_and_owner_are_committed_before_send(monkeypatch, test_db, test_db_url, void_case):
    event_id, pledge_id, hold_id = void_case
    observed = []

    def check_saved(auth_id, request_id):
        with db.connect(test_db_url) as other:
            row = db.fetch_one(other, "SELECT void_request_id, void_run_token FROM holds WHERE id = %s", (hold_id,))
        observed.append((row["void_request_id"] == request_id, bool(row["void_run_token"])))
        return fake_paypal.answer(204, {})

    monkeypatch.setattr(fake_paypal, "void_authorization", check_saved)
    lifecycle.void_hold(test_db, hold_id, fake_paypal)
    assert observed == [(True, True)]


# A worker whose ownership was replaced must not save its delayed provider response.
def test_stale_void_owner_cannot_overwrite_status(monkeypatch, test_db, test_db_url, void_case):
    event_id, pledge_id, hold_id = void_case

    def replace_owner(auth_id):
        with db.connect(test_db_url) as other:
            db.run(other, "UPDATE holds SET status = 'VOIDED', void_run_token = %s WHERE id = %s",
                   ("replacement-owner", hold_id))
        return fake_paypal.hold_read_back("CAPTURED", auth_id)

    monkeypatch.setattr(fake_paypal, "get_authorization", replace_owner)
    lifecycle.void_hold(test_db, hold_id, fake_paypal)
    hold = db.fetch_one(test_db, "SELECT status, void_run_token FROM holds WHERE id = %s", (hold_id,))
    assert hold["status"] == "VOIDED"
    assert hold["void_run_token"] == "replacement-owner"


# A provider response about a different authorization cannot resolve this hold.
def test_void_get_must_match_authorization_id(test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", "FAKEDIFFERENT")]
    lifecycle.void_hold(test_db, hold_id, fake_paypal)
    hold = db.fetch_one(test_db, "SELECT status, void_run_token FROM holds WHERE id = %s", (hold_id,))
    assert hold["status"] == "CREATED"
    assert hold["void_run_token"] is not None


# A database disconnect during the external call must not release the committed owner.
def test_database_disconnect_during_void_keeps_claim(monkeypatch, test_db, test_db_url, void_case):
    event_id, pledge_id, hold_id = void_case
    connection = db.connect(test_db_url)
    calls = []

    def lose_connection(auth_id, request_id):
        calls.append(request_id)
        connection.close()
        return fake_paypal.answer(204, {})

    monkeypatch.setattr(fake_paypal, "void_authorization", lose_connection)
    with pytest.raises(psycopg.Error):
        lifecycle.void_hold(connection, hold_id, fake_paypal)
    row = db.fetch_one(test_db, "SELECT void_run_token FROM holds WHERE id = %s", (hold_id,))
    assert row["void_run_token"] is not None
    lifecycle.void_hold(test_db, hold_id, fake_paypal)
    assert len(calls) == 1


# Pause after the event lock but before the hold claim; the handoff must wait for that lock.
def test_event_lock_orders_void_claim_before_refund_handoff(monkeypatch, test_db, test_db_url, void_case):
    event_id, pledge_id, hold_id = void_case
    event_locked = threading.Event()
    release_claim = threading.Event()
    handoff_started = threading.Event()
    handoff_finished = threading.Event()
    errors = []
    worker_pid = []
    original_fetch = db.fetch_one

    def pause_after_event_read(conn, sql, params=()):
        result = original_fetch(conn, sql, params)
        if sql.startswith("SELECT status FROM events WHERE id = %s") and threading.current_thread().name == "void-worker":
            event_locked.set()
            if not release_claim.wait(10):
                raise RuntimeError("test did not release claim")
        return result

    def void_worker():
        try:
            with db.connect(test_db_url) as connection:
                lifecycle.void_hold(connection, hold_id, fake_paypal)
        except Exception as error:
            errors.append(error)

    def handoff_worker():
        try:
            with db.connect(test_db_url) as connection:
                worker_pid.append(original_fetch(connection, "SELECT pg_backend_pid() AS pid")["pid"])
                handoff_started.set()
                try:
                    db.run(connection, "UPDATE events SET status = 'REFUNDING' WHERE id = %s", (event_id,))
                except psycopg.errors.CheckViolation:
                    pass
        except Exception as error:
            errors.append(error)
        finally:
            handoff_finished.set()

    monkeypatch.setattr(db, "fetch_one", pause_after_event_read)
    first = threading.Thread(target=void_worker, name="void-worker")
    second = threading.Thread(target=handoff_worker)
    first.start()
    try:
        assert event_locked.wait(10)
        second.start()
        assert handoff_started.wait(10)
        deadline = time.monotonic() + 5
        blocked = False
        while time.monotonic() < deadline and not handoff_finished.is_set():
            result = original_fetch(test_db, "SELECT cardinality(pg_blocking_pids(%s)) AS n", (worker_pid[0],))
            if result["n"] > 0:
                blocked = True
                break
        assert blocked, "Refund handoff did not wait for the event lock"
    finally:
        release_claim.set()
        first.join(10)
        if second.ident is not None:
            second.join(10)
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []


def claim_fields(conn, hold_id):
    return db.fetch_one(conn, "SELECT status, auth_id, void_run_token, void_request_id, void_tried_at "
                              "FROM holds WHERE id = %s", (hold_id,))


def pledge_status_of(conn, pledge_id):
    return db.fetch_one(conn, "SELECT status FROM pledges WHERE id = %s", (pledge_id,))["status"]


# One sweep whose GET still says CREATED. The void POST has happened once and the claim must remain.
def leave_uncertain_void(conn, hold_id, auth_id):
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_id)]
    lifecycle.sweep_stranded_holds(conn, SWEEP_NOW, fake_paypal)
    fake_paypal.calls.clear()
    claim = claim_fields(conn, hold_id)
    assert claim["status"] == "CREATED"
    assert claim["void_run_token"] is not None
    return claim


def refund_handoff_is_blocked(conn, event_id):
    try:
        db.run(conn, "UPDATE events SET status = 'REFUNDING' WHERE id = %s AND status = 'NEEDS_ATTENTION'",
               (event_id,))
    except psycopg.errors.CheckViolation:
        return True
    return False


# HTTP 204, then CREATED, then a later GET that says VOIDED. The second look must not void again.
def test_reconcile_created_then_voided_sends_no_second_void(test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    auth_id = claim_fields(test_db, hold_id)["auth_id"]
    first = leave_uncertain_void(test_db, hold_id, auth_id)
    assert pledge_status_of(test_db, pledge_id) == "HELD"
    assert fake_paypal.called_functions().count("void_authorization") == 0

    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_id)]
    assert lifecycle.reconcile_uncertain_void(test_db, hold_id, fake_paypal) == "CREATED"
    again = claim_fields(test_db, hold_id)
    assert again["status"] == "CREATED"
    assert again["void_run_token"] == first["void_run_token"]
    assert again["void_request_id"] == first["void_request_id"]
    assert fake_paypal.called_functions() == ["get_authorization"]
    assert refund_handoff_is_blocked(test_db, event_id)
    assert lifecycle.find_event(test_db, event_id)["status"] == "NEEDS_ATTENTION"

    fake_paypal.calls.clear()
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("VOIDED", auth_id)]
    assert lifecycle.reconcile_uncertain_void(test_db, hold_id, fake_paypal) == "VOIDED"
    done = claim_fields(test_db, hold_id)
    assert done["status"] == "VOIDED"
    assert done["void_run_token"] is None
    assert done["void_request_id"] == first["void_request_id"]
    assert pledge_status_of(test_db, pledge_id) == "DROPPED"
    assert fake_paypal.called_functions() == ["get_authorization"]
    assert lifecycle.find_event(test_db, event_id)["status"] == "NEEDS_ATTENTION"
    changed = db.run(test_db, "UPDATE events SET status = 'REFUNDING' WHERE id = %s AND status = 'NEEDS_ATTENTION'",
                     (event_id,))
    assert changed == 1


# A confirmed close or a confirmed capture is saved from the GET alone.
@pytest.mark.parametrize("paypal_status, pledge_after", [
    ("EXPIRED", "DROPPED"),
    ("DENIED", "DROPPED"),
    ("CAPTURED", "FAILED"),
    ("PARTIALLY_CAPTURED", "FAILED"),
])
def test_reconcile_records_terminal_status_without_another_void(test_db, void_case, paypal_status, pledge_after):
    event_id, pledge_id, hold_id = void_case
    auth_id = claim_fields(test_db, hold_id)["auth_id"]
    first = leave_uncertain_void(test_db, hold_id, auth_id)
    fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back(paypal_status, auth_id)]
    assert lifecycle.reconcile_uncertain_void(test_db, hold_id, fake_paypal) == paypal_status
    done = claim_fields(test_db, hold_id)
    assert done["status"] == paypal_status
    assert done["void_run_token"] is None
    assert done["void_request_id"] == first["void_request_id"]
    assert pledge_status_of(test_db, pledge_id) == pledge_after
    assert lifecycle.find_event(test_db, event_id)["status"] == "NEEDS_ATTENTION"
    assert fake_paypal.called_functions() == ["get_authorization"]


# CREATED was already covered above. These answers must not release the claim or send a void.
@pytest.mark.parametrize("kind", ["missing", "mismatch", "unknown"])
def test_reconcile_inconclusive_get_keeps_the_claim(test_db, void_case, kind):
    event_id, pledge_id, hold_id = void_case
    auth_id = claim_fields(test_db, hold_id)["auth_id"]
    first = leave_uncertain_void(test_db, hold_id, auth_id)
    if kind == "missing":
        queued = fake_paypal.no_answer()
    elif kind == "mismatch":
        queued = fake_paypal.hold_read_back("VOIDED", "FAKEDIFFERENT")
    else:
        queued = fake_paypal.hold_read_back("NOT_A_STATUS", auth_id)
    fake_paypal.next_answers["get_authorization"] = [queued]
    lifecycle.reconcile_uncertain_void(test_db, hold_id, fake_paypal)
    again = claim_fields(test_db, hold_id)
    assert again["status"] == "CREATED"
    assert again["void_run_token"] == first["void_run_token"]
    assert again["void_request_id"] == first["void_request_id"]
    assert pledge_status_of(test_db, pledge_id) == "HELD"
    assert fake_paypal.called_functions() == ["get_authorization"]
    assert refund_handoff_is_blocked(test_db, event_id)


# A hold with no claim is not a reason to call PayPal.
def test_reconcile_without_a_claim_does_not_call_paypal(test_db, void_case):
    event_id, pledge_id, hold_id = void_case
    assert lifecycle.reconcile_uncertain_void(test_db, hold_id, fake_paypal) is None
    assert fake_paypal.called_functions() == []
    assert claim_fields(test_db, hold_id)["status"] == "CREATED"


# The GET's status belongs to whoever still owns the claim, not to a replaced token.
def test_reconcile_stale_owner_cannot_overwrite_status(monkeypatch, test_db, test_db_url, void_case):
    event_id, pledge_id, hold_id = void_case
    auth_id = claim_fields(test_db, hold_id)["auth_id"]
    leave_uncertain_void(test_db, hold_id, auth_id)

    def replace_owner(read_id):
        with db.connect(test_db_url) as other:
            db.run(other, "UPDATE holds SET status = 'VOIDED', void_run_token = %s WHERE id = %s",
                   ("replacement-owner", hold_id))
        return fake_paypal.hold_read_back("CAPTURED", read_id)

    monkeypatch.setattr(fake_paypal, "get_authorization", replace_owner)
    lifecycle.reconcile_uncertain_void(test_db, hold_id, fake_paypal)
    claim = claim_fields(test_db, hold_id)
    assert claim["status"] == "VOIDED"
    assert claim["void_run_token"] == "replacement-owner"
    assert pledge_status_of(test_db, pledge_id) == "HELD"


# A worker paused inside its void POST still owns the claim. A GET of CREATED must not void or unlock it.
def test_reconcile_while_void_worker_is_active(monkeypatch, test_db, test_db_url, void_case):
    event_id, pledge_id, hold_id = void_case
    auth_id = claim_fields(test_db, hold_id)["auth_id"]
    entered = threading.Event()
    release = threading.Event()
    void_calls = []
    errors = []

    def paused_void(read_id, request_id):
        void_calls.append(request_id)
        if len(void_calls) == 1:
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test did not release void")
        return fake_paypal.answer(204, {})

    def worker_body():
        try:
            with db.connect(test_db_url) as connection:
                lifecycle.void_hold(connection, hold_id, fake_paypal)
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(fake_paypal, "void_authorization", paused_void)
    worker = threading.Thread(target=worker_body)
    worker.start()
    try:
        assert entered.wait(10)
        fake_paypal.next_answers["get_authorization"] = [fake_paypal.hold_read_back("CREATED", auth_id)]
        assert lifecycle.reconcile_uncertain_void(test_db, hold_id, fake_paypal) == "CREATED"
        claim = claim_fields(test_db, hold_id)
        assert claim["status"] == "CREATED"
        assert claim["void_run_token"] is not None
        assert len(void_calls) == 1
        assert fake_paypal.called_functions() == ["get_authorization"]
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert errors == []
    assert len(void_calls) == 1
    assert claim_fields(test_db, hold_id)["status"] == "VOIDED"
    lifecycle.sweep_stranded_holds(test_db, SWEEP_NOW + timedelta(hours=1), fake_paypal)
    assert len(void_calls) == 1
    assert pledge_status_of(test_db, pledge_id) == "HELD"
