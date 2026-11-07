# Migration 005 runs only on the verified disposable PostgreSQL target.
from pathlib import Path

import psycopg
import pytest

import db
from tests.test_refund_lifecycle import refund_case, insert_person, refund_rows
from tests.test_refund_dispatch_migration import catalog
from tests.test_refund_safety import saved_refund

ROOT = Path(__file__).resolve().parents[1]


def migration():
    file = ROOT / "migrations/005_f7_refund_web_actions.sql"
    assert file.exists(), "Durable browser replay protection requires migration 005"
    return file.read_text(encoding="utf-8")


def body():
    return migration().split("BEGIN;", 1)[1].rsplit("COMMIT;", 1)[0]


def insert_action(conn, event_id, action_hash="synthetic-one"):
    return db.fetch_one(conn, "INSERT INTO refund_web_actions (action_hash, event_id, session_hash, action_type) "
                             "VALUES (%s, %s, 'synthetic-session', 'START') RETURNING *", (action_hash, event_id))


def test_only_one_active_command_and_finished_history_is_retained(refund_case):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        first = insert_action(conn, refund_case["event_id"])
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                insert_action(conn, refund_case["event_id"], "synthetic-two")
        db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = now() WHERE action_hash = %s", (first["action_hash"],))
        insert_action(conn, refund_case["event_id"], "synthetic-two")
        assert db.fetch_one(conn, "SELECT count(*) AS n FROM refund_web_actions WHERE event_id = %s", (refund_case["event_id"],))["n"] == 2


@pytest.mark.parametrize("change", ["state = 'CLAIMED', finished_at = NULL", "action_type = 'CONTINUE'", "session_hash = 'different'"])
def test_finished_actions_cannot_reopen_or_change_identity(refund_case, change):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        first = insert_action(conn, refund_case["event_id"])
        db.run(conn, "UPDATE refund_web_actions SET state = 'FINISHED', finished_at = now() WHERE action_hash = %s", (first["action_hash"],))
        # Fixed synthetic mutation statements; application SQL never interpolates input.
        statements = {
            "state = 'CLAIMED', finished_at = NULL": "UPDATE refund_web_actions SET state = 'CLAIMED', finished_at = NULL WHERE action_hash = %s",
            "action_type = 'CONTINUE'": "UPDATE refund_web_actions SET action_type = 'CONTINUE' WHERE action_hash = %s",
            "session_hash = 'different'": "UPDATE refund_web_actions SET session_hash = 'different' WHERE action_hash = %s",
        }
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                db.run(conn, statements[change], (first["action_hash"],))


@pytest.mark.parametrize("state", ["READY", "IN_FLIGHT", "UNCERTAIN", "ANSWERED", "CHECK_ONLY"])
def test_migration005_preserves_records_and_late_failure_rolls_back(refund_case, state):
    conn = refund_case["conn"]
    saved_refund(refund_case, state)
    queries = ("SELECT * FROM events ORDER BY id", "SELECT * FROM pledges ORDER BY id",
               "SELECT * FROM pledge_conditions ORDER BY id", "SELECT * FROM holds ORDER BY id",
               "SELECT * FROM captures ORDER BY id", "SELECT * FROM refunds ORDER BY id")
    before_rows = [db.fetch_all(conn, query) for query in queries]
    with conn.transaction(force_rollback=True):
        conn.execute("DROP TABLE IF EXISTS refund_web_actions")
        conn.execute("DROP FUNCTION IF EXISTS public.protect_refund_web_action()")
        before = catalog(conn)
        with pytest.raises(psycopg.errors.UndefinedFunction):
            with conn.transaction():
                conn.execute(body(), prepare=False)
                assert db.fetch_one(conn, "SELECT to_regclass('public.refund_web_actions') AS name")["name"]
                assert [db.fetch_all(conn, query) for query in queries] == before_rows
                conn.execute("SELECT f7_deliberate_missing_function_005()")
        assert catalog(conn) == before
        assert db.fetch_one(conn, "SELECT to_regclass('public.refund_web_actions') AS name")["name"] is None


def test_migration005_failed_preflight_leaves_catalog_unchanged(refund_case):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        conn.execute("DROP TABLE IF EXISTS refund_web_actions")
        conn.execute("DROP FUNCTION IF EXISTS public.protect_refund_web_action()")
        conn.execute("ALTER TABLE refunds DISABLE TRIGGER refunds_protect_operation")
        before = catalog(conn)
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.transaction():
                conn.execute(body(), prepare=False)
        assert catalog(conn) == before


def test_migration005_matches_fresh_schema():
    sql = migration()
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    objects = sql.split("-- Browser commands", 1)[1].rsplit("COMMIT;", 1)[0].strip()
    # schema.sql ends with migration 006's block (test_refund_migration006.py checks that one).
    fresh = schema.split("-- Browser commands", 1)[1].split("-- Stage 3 corrections (migration 006)", 1)[0]
    assert fresh.strip() == objects
    assert sql.index("BEGIN;") < sql.index("LOCK TABLE") < sql.index("DO $$") < sql.index("CREATE TABLE")
    assert "SET LOCAL lock_timeout = '5s'" in sql and sql.rstrip().endswith("COMMIT;")


def test_migration005_lock_timeout_rolls_back(refund_case, test_db_url):
    conn = refund_case["conn"]
    before = catalog(conn)
    with db.connect(test_db_url) as other:
        with other.transaction():
            other.execute("SELECT id FROM events WHERE id = %s FOR UPDATE", (refund_case["event_id"],))
            try:
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    conn.execute(migration(), prepare=False)
            finally:
                conn.execute("ROLLBACK")
    assert catalog(conn) == before
