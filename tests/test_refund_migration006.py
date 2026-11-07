# Migration 006 (D93): the schema changes behind the five Stage 3 corrections.
# Everything here runs on the disposable local PostgreSQL and rolls its changes back. Synthetic data only.
from pathlib import Path

import psycopg
import pytest

import db
import lifecycle
from tests import fake_paypal
from tests.test_refund_dispatch_migration import catalog
from tests.test_refund_lifecycle import refund_case, insert_person
from tests.test_refund_safety import saved_refund

ROOT = Path(__file__).resolve().parents[1]
FILE = "migrations/006_f7_bounded_refund_preflight.sql"
MARKER = "-- Stage 3 corrections (migration 006)"


def migration():
    file = ROOT / FILE
    assert file.exists(), "Stage 3 corrections require migration 006"
    return file.read_text(encoding="utf-8")


def body():
    return migration().split("BEGIN;", 1)[1].rsplit("COMMIT;", 1)[0]


# Put the database back the way migration 005 left it, so migration 006 can be applied again.
def downgrade_to_005(conn):
    text = (ROOT / "migrations/005_f7_refund_web_actions.sql").read_text(encoding="utf-8")
    old_function = text.split("CREATE FUNCTION public.protect_refund_web_action()", 1)[1].split("CREATE TRIGGER", 1)[0]
    conn.execute("ALTER TABLE public.refund_web_actions "
                 "DROP CONSTRAINT refund_web_actions_cancel_target, "
                 "DROP CONSTRAINT refund_web_actions_claim_kind, "
                 "DROP CONSTRAINT refund_web_actions_one_command_per_refund, "
                 "DROP CONSTRAINT refund_web_actions_action_type, "
                 "DROP COLUMN target_hold_id, DROP COLUMN claimed_refund_id, "
                 "ADD CONSTRAINT refund_web_actions_action_type_check "
                 "CHECK (action_type IN ('START', 'CONTINUE', 'CHECK'))")
    conn.execute("CREATE OR REPLACE FUNCTION public.protect_refund_web_action()" + old_function, prepare=False)


# A refund that is really IN_FLIGHT, claimed the way production claims it.
def claimed_refund(case):
    conn = case["conn"]
    person = insert_person(conn, case["event_id"], "CHARGED", "CAPTURED", "COMPLETED")
    db.run(conn, "UPDATE holds SET refund_check_status = 'RESOLVED' WHERE id = %s", (person["hold_id"],))
    opened = lifecycle.open_refunding(conn, case["event_id"])
    claim = lifecycle.claim_ready_refund(conn, case["event_id"], opened["owner"], opened["revision"])
    assert claim is not None
    return person, claim


def command(conn, event_id, kind, name="synthetic-cmd", refund=None, hold=None, claimed=None):
    return db.fetch_one(conn, "INSERT INTO refund_web_actions (action_hash, event_id, session_hash, action_type, "
                              "target_refund_id, target_hold_id, claimed_refund_id) "
                              "VALUES (%s, %s, 'synthetic-session', %s, %s, %s, %s) RETURNING *",
                        (name, event_id, kind, refund, hold, claimed))


def rejected(conn, error, event_id, kind, **links):
    with pytest.raises(error):
        with conn.transaction():
            command(conn, event_id, kind, **links)


# ---------- the file itself ----------

def test_migration_is_bounded_transactional_and_checks_prerequisites_first():
    sql = migration()
    assert sql.index("BEGIN;") < sql.index("LOCK TABLE") < sql.index("DO $$") < sql.index("ALTER TABLE")
    assert "SET LOCAL lock_timeout = '5s'" in sql
    assert "SET LOCAL statement_timeout = '30s'" in sql
    assert sql.rstrip().endswith("COMMIT;")
    assert "refund_web_actions_action_type_check" in sql.split("DO $$", 1)[1].split("$$;", 1)[0]


def test_fresh_schema_contains_the_migration_objects_verbatim():
    objects = migration().split("-- Objects:", 1)[1].rsplit("COMMIT;", 1)[0].strip()
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert MARKER in schema
    assert schema.split(MARKER, 1)[1].strip() == objects


def test_migration_applied_on_005_gives_exactly_the_current_schema(refund_case):
    conn = refund_case["conn"]
    final = catalog(conn)
    with conn.transaction(force_rollback=True):
        downgrade_to_005(conn)
        assert catalog(conn) != final
        conn.execute(body(), prepare=False)
        assert catalog(conn) == final


def test_migration_keeps_every_existing_row_unchanged(refund_case):
    conn = refund_case["conn"]
    rows = ("SELECT action_hash, event_id, session_hash, action_type, target_refund_id, state "
            "FROM refund_web_actions WHERE event_id = %s ORDER BY action_hash")
    with conn.transaction(force_rollback=True):
        downgrade_to_005(conn)
        db.run(conn, "INSERT INTO refund_web_actions (action_hash, event_id, session_hash, action_type) "
                     "VALUES ('synthetic-old-row', %s, 'synthetic-session', 'START')", (refund_case["event_id"],))
        before = db.fetch_all(conn, rows, (refund_case["event_id"],))
        conn.execute(body(), prepare=False)
        assert db.fetch_all(conn, rows, (refund_case["event_id"],)) == before
        links = db.fetch_one(conn, "SELECT target_hold_id, claimed_refund_id FROM refund_web_actions WHERE action_hash = 'synthetic-old-row'")
        assert links == {"target_hold_id": None, "claimed_refund_id": None}


# ---------- wrong prerequisites abort and change nothing ----------

def test_missing_table_aborts_and_changes_nothing(refund_case):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        downgrade_to_005(conn)
        conn.execute("DROP TABLE public.refund_web_actions")
        before = catalog(conn)
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute(body(), prepare=False)
        assert catalog(conn) == before


def test_disabled_trigger_aborts_and_changes_nothing(refund_case):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        downgrade_to_005(conn)
        conn.execute("ALTER TABLE public.refund_web_actions DISABLE TRIGGER refund_web_actions_protect")
        before = catalog(conn)
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.transaction():
                conn.execute(body(), prepare=False)
        assert catalog(conn) == before


def test_unexpected_action_type_list_aborts_and_changes_nothing(refund_case):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        downgrade_to_005(conn)
        conn.execute("ALTER TABLE public.refund_web_actions DROP CONSTRAINT refund_web_actions_action_type_check, "
                     "ADD CONSTRAINT refund_web_actions_action_type_check "
                     "CHECK (action_type IN ('START', 'CONTINUE', 'CHECK', 'SOMETHING_ELSE'))")
        before = catalog(conn)
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.transaction():
                conn.execute(body(), prepare=False)
        assert catalog(conn) == before


def test_late_failure_rolls_back_the_whole_migration(refund_case):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        downgrade_to_005(conn)
        before = catalog(conn)
        with pytest.raises(psycopg.errors.UndefinedFunction):
            with conn.transaction():
                conn.execute(body(), prepare=False)
                assert catalog(conn) != before
                conn.execute("SELECT f7_deliberate_missing_function_006()")
        assert catalog(conn) == before


def test_lock_wait_is_bounded(refund_case, test_db_url):
    conn = refund_case["conn"]
    before = catalog(conn)
    with db.connect(test_db_url) as blocker:
        with blocker.transaction():
            blocker.execute("SELECT id FROM events WHERE id = %s FOR UPDATE", (refund_case["event_id"],))
            try:
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    conn.execute(migration(), prepare=False)
            finally:
                conn.execute("ROLLBACK")
    assert catalog(conn) == before


# ---------- each constraint rejects bad rows (rolled back) ----------

def test_cancel_hold_is_a_valid_action_with_a_claimed_hold(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    with conn.transaction(force_rollback=True):
        db.run(conn, "UPDATE holds SET void_run_token = 'owner', void_request_id = 'request' WHERE id = %s", (person["hold_id"],))
        row = command(conn, refund_case["event_id"], "CANCEL_HOLD", hold=person["hold_id"])
        assert row["target_hold_id"] == person["hold_id"] and row["state"] == "CLAIMED"


def test_cancel_hold_without_a_hold_is_rejected(refund_case):
    with refund_case["conn"].transaction(force_rollback=True):
        rejected(refund_case["conn"], psycopg.errors.CheckViolation, refund_case["event_id"], "CANCEL_HOLD")


def test_other_actions_cannot_carry_a_hold(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    with conn.transaction(force_rollback=True):
        rejected(conn, psycopg.errors.CheckViolation, refund_case["event_id"], "START", hold=person["hold_id"])


def test_unknown_action_type_is_rejected(refund_case):
    with refund_case["conn"].transaction(force_rollback=True):
        rejected(refund_case["conn"], psycopg.errors.CheckViolation, refund_case["event_id"], "VOID_EVERYTHING")


def test_cancel_hold_needs_the_void_claim_committed_first(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    with conn.transaction(force_rollback=True):
        rejected(conn, psycopg.errors.CheckViolation, refund_case["event_id"], "CANCEL_HOLD", hold=person["hold_id"])


def test_cancel_hold_must_belong_to_the_event(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    with conn.transaction(force_rollback=True):
        db.run(conn, "UPDATE holds SET void_run_token = 'owner', void_request_id = 'request' WHERE id = %s", (person["hold_id"],))
        event = db.fetch_one(conn, "INSERT INTO events (title, deposit_cents, admin_token) "
                                   "VALUES ('other', 2000, 'synthetic-other-006') RETURNING id")
        rejected(conn, psycopg.errors.CheckViolation, event["id"], "CANCEL_HOLD", hold=person["hold_id"])


def test_claimed_refund_must_be_in_flight_and_belong_to_the_event(refund_case):
    conn = refund_case["conn"]
    person, claim = claimed_refund(refund_case)
    with conn.transaction(force_rollback=True):
        ok = command(conn, refund_case["event_id"], "START", "synthetic-link", claimed=claim["id"])
        assert ok["claimed_refund_id"] == claim["id"]
    with conn.transaction(force_rollback=True):
        event = db.fetch_one(conn, "INSERT INTO events (title, deposit_cents, admin_token) VALUES ('other', 2000, 'synthetic-other-006b') RETURNING id")
        rejected(conn, psycopg.errors.CheckViolation, event["id"], "START", claimed=claim["id"])
    with conn.transaction(force_rollback=True):
        # The refund guards would stop this setup step, so they are switched off for the setup only.
        conn.execute("ALTER TABLE public.refunds DISABLE TRIGGER refunds_protect_operation")
        db.run(conn, "UPDATE refunds SET send_state = 'UNCERTAIN' WHERE id = %s", (claim["id"],))
        conn.execute("ALTER TABLE public.refunds ENABLE TRIGGER refunds_protect_operation")
        rejected(conn, psycopg.errors.CheckViolation, refund_case["event_id"], "START", claimed=claim["id"])


def test_only_start_and_continue_may_claim_a_refund(refund_case):
    person, claim = claimed_refund(refund_case)
    with refund_case["conn"].transaction(force_rollback=True):
        rejected(refund_case["conn"], psycopg.errors.CheckViolation, refund_case["event_id"], "CHECK",
                 refund=claim["id"], claimed=claim["id"])


def test_one_command_per_claimed_refund_is_declared_and_enforced(refund_case):
    conn = refund_case["conn"]
    person, claim = claimed_refund(refund_case)
    definition = db.fetch_one(conn, "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint "
                                    "WHERE conname = 'refund_web_actions_one_command_per_refund'")["d"]
    assert definition == "UNIQUE (claimed_refund_id)"
    with conn.transaction(force_rollback=True):
        # The trigger would reject a second link first, so switch it off to prove the constraint itself.
        conn.execute("ALTER TABLE public.refund_web_actions DISABLE TRIGGER refund_web_actions_protect")
        command(conn, refund_case["event_id"], "START", "synthetic-first", claimed=claim["id"])
        db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = now() WHERE event_id = %s", (refund_case["event_id"],))
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                command(conn, refund_case["event_id"], "CONTINUE", "synthetic-second", claimed=claim["id"])


def test_link_columns_cannot_change_after_insert(refund_case):
    conn = refund_case["conn"]
    person, claim = claimed_refund(refund_case)
    other = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    with conn.transaction(force_rollback=True):
        command(conn, refund_case["event_id"], "START", "synthetic-link", claimed=claim["id"])
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                db.run(conn, "UPDATE refund_web_actions SET claimed_refund_id = NULL WHERE event_id = %s", (refund_case["event_id"],))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                db.run(conn, "UPDATE refund_web_actions SET target_hold_id = %s WHERE event_id = %s", (other["hold_id"], refund_case["event_id"]))


@pytest.mark.parametrize("state", ["IN_FLIGHT", "UNCERTAIN", "CHECK_ONLY"])
def test_command_cannot_finish_while_its_refund_is_unresolved(refund_case, state):
    conn = refund_case["conn"]
    person, claim = claimed_refund(refund_case)
    with conn.transaction(force_rollback=True):
        command(conn, refund_case["event_id"], "START", "synthetic-link", claimed=claim["id"])
        if state != "IN_FLIGHT":
            # The refund guards would stop this test setup, so they are switched off for the setup only.
            conn.execute("ALTER TABLE public.refunds DISABLE TRIGGER refunds_protect_operation")
            db.run(conn, "UPDATE refunds SET send_state = %s WHERE id = %s", (state, claim["id"]))
            conn.execute("ALTER TABLE public.refunds ENABLE TRIGGER refunds_protect_operation")
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = now() WHERE event_id = %s", (refund_case["event_id"],))


def test_command_finishes_once_its_result_is_saved(refund_case):
    conn = refund_case["conn"]
    person, claim = claimed_refund(refund_case)
    with conn.transaction(force_rollback=True):
        command(conn, refund_case["event_id"], "START", "synthetic-link", claimed=claim["id"])
        assert lifecycle.remember_refund_id(conn, claim, "REFUNDSYNTH0006")
        assert lifecycle.record_refund_answer(conn, claim, "COMPLETED", "REFUNDSYNTH0006")
        assert db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = now() WHERE event_id = %s", (refund_case["event_id"],)) == 1


def test_cancel_command_cannot_finish_while_the_void_owner_remains(refund_case):
    conn = refund_case["conn"]
    person = insert_person(conn, refund_case["event_id"], "FAILED", "CREATED")
    with conn.transaction(force_rollback=True):
        db.run(conn, "UPDATE holds SET void_run_token = 'owner', void_request_id = 'request' WHERE id = %s", (person["hold_id"],))
        command(conn, refund_case["event_id"], "CANCEL_HOLD", hold=person["hold_id"])
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = now() WHERE event_id = %s", (refund_case["event_id"],))
        db.run(conn, "UPDATE holds SET status = 'VOIDED', void_run_token = NULL WHERE id = %s", (person["hold_id"],))
        assert db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = now() WHERE event_id = %s", (refund_case["event_id"],)) == 1


def test_005_behaviour_is_unchanged_for_commands_without_links(refund_case):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        first = command(conn, refund_case["event_id"], "START", "synthetic-plain")
        assert first["claimed_refund_id"] is None and first["target_hold_id"] is None
        assert db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = now() WHERE event_id = %s", (refund_case["event_id"],)) == 1
