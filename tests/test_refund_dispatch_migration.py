# PostgreSQL migration tests use the configured disposable target and roll back their DDL.
from pathlib import Path

import psycopg
import pytest

import db
from tests.test_refund_lifecycle import refund_case, refund_rows
from tests.test_refund_safety import saved_refund

ROOT = Path(__file__).resolve().parents[1]


# Run the migration body inside a test-owned transaction, never committing test DDL.
def migration_body():
    text = (ROOT / "migrations/004_f7_refund_dispatch_guards.sql").read_text(encoding="utf-8")
    return text.split("BEGIN;", 1)[1].rsplit("COMMIT;", 1)[0]


# Capture the complete user catalog, including triggers and constraints, for rollback comparison.
def catalog(conn):
    return [db.fetch_all(conn, query) for query in (
        "SELECT pg_get_functiondef(oid) AS definition FROM pg_proc WHERE pronamespace = 'public'::regnamespace ORDER BY proname",
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY conname",
        "SELECT tgname, tgenabled, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid IN (SELECT oid FROM pg_class WHERE relnamespace = 'public'::regnamespace) AND NOT tgisinternal ORDER BY tgname",
        "SELECT table_name, column_name, data_type, column_default, is_nullable FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, ordinal_position",
    )]


@pytest.mark.parametrize("state", ["READY", "IN_FLIGHT", "UNCERTAIN", "ANSWERED", "CHECK_ONLY"])
def test_migration004_preserves_every_existing_field(refund_case, state):
    _, row = saved_refund(refund_case, state)
    conn = refund_case["conn"]
    before = refund_rows(conn, refund_case["event_id"])
    with conn.transaction(force_rollback=True):
        conn.execute(migration_body(), prepare=False)
        assert refund_rows(conn, refund_case["event_id"]) == before
        if state != "READY":
            with pytest.raises(psycopg.errors.CheckViolation):
                with conn.transaction():
                    db.run(conn, "UPDATE refunds SET send_state = 'READY' WHERE id = %s", (row["id"],))


def test_migration004_late_ddl_error_rolls_back_function_replacement(refund_case):
    conn = refund_case["conn"]
    old_sql = (ROOT / "migrations/003_f7_refund_operation_safety.sql").read_text(encoding="utf-8")
    old_function = old_sql.split("CREATE FUNCTION public.protect_refund_operation()", 1)[1].split("CREATE TRIGGER", 1)[0]
    with conn.transaction(force_rollback=True):
        conn.execute("CREATE OR REPLACE FUNCTION public.protect_refund_operation()" + old_function, prepare=False)
        before = catalog(conn)
        with pytest.raises(psycopg.errors.UndefinedFunction):
            with conn.transaction():
                conn.execute(migration_body(), prepare=False)
                assert catalog(conn) != before
                conn.execute("SELECT f7_deliberate_missing_function_004()")
        assert catalog(conn) == before


def test_migration004_failed_preflight_changes_nothing(refund_case):
    conn = refund_case["conn"]
    with conn.transaction(force_rollback=True):
        conn.execute("ALTER TABLE refunds DISABLE TRIGGER refunds_protect_record")
        before = catalog(conn)
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.transaction():
                conn.execute(migration_body(), prepare=False)
        assert catalog(conn) == before
        assert db.fetch_one(conn, "SELECT tgenabled FROM pg_trigger WHERE tgname = 'refunds_protect_record'")["tgenabled"] == "D"


def test_migration004_lock_wait_is_bounded(refund_case, test_db_url):
    conn = refund_case["conn"]
    before = catalog(conn)
    migration = (ROOT / "migrations/004_f7_refund_dispatch_guards.sql").read_text(encoding="utf-8")
    with db.connect(test_db_url) as blocker:
        with blocker.transaction():
            blocker.execute("SELECT id FROM events WHERE id = %s FOR UPDATE", (refund_case["event_id"],))
            try:
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    conn.execute(migration, prepare=False)
            finally:
                conn.execute("ROLLBACK")
    assert catalog(conn) == before


def test_migration004_matches_fresh_schema_and_is_transactional():
    migration = (ROOT / "migrations/004_f7_refund_dispatch_guards.sql").read_text(encoding="utf-8")
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    fresh = schema.split("CREATE FUNCTION public.protect_refund_operation()", 1)[1].split("CREATE TRIGGER", 1)[0]
    upgrade = migration.split("CREATE OR REPLACE FUNCTION public.protect_refund_operation()", 1)[1].rsplit("COMMIT;", 1)[0]
    assert fresh.strip() == upgrade.strip()
    assert migration.index("BEGIN;") < migration.index("LOCK TABLE") < migration.index("DO $$") < migration.index("CREATE OR REPLACE FUNCTION")
    assert "SET LOCAL lock_timeout = '5s'" in migration
    assert "SET LOCAL statement_timeout = '30s'" in migration
    assert migration.rstrip().endswith("COMMIT;")
