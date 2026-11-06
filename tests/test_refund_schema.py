# Local source checks only: these do NOT execute or prove PostgreSQL constraints/triggers.
# Runtime coverage is in test_refund_database.py, pending an approved migrated test target.
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_FILES = ["schema.sql", "migrations/001_f7_refund_all.sql"]


# Ignore comments and whitespace so these checks name the safety clauses, not their formatting.
def sql_text(filename):
    path = ROOT / filename
    assert path.exists(), "The reviewed F7 SQL file must exist"
    text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    return " ".join(text.split())


# Both installation paths need one refund per capture and positive integer cents.
@pytest.mark.parametrize("filename", SQL_FILES)
def test_refund_sql_declares_capture_uniqueness_and_positive_cents(filename):
    text = sql_text(filename)
    assert "CONSTRAINT refunds_one_per_capture UNIQUE (capture_id)" in text
    assert "CONSTRAINT refunds_amount_positive CHECK (amount_cents > 0)" in text


# UPDATE must not change the operation's identity or erase an assigned PayPal refund ID.
@pytest.mark.parametrize("filename", SQL_FILES)
def test_refund_sql_declares_immutable_identity_trigger(filename):
    text = sql_text(filename)
    for column in ("capture_id", "request_id", "amount_cents", "created_at"):
        assert "NEW.%s IS DISTINCT FROM OLD.%s" % (column, column) in text
    assert "OLD.refund_id IS NOT NULL" in text
    assert "NEW.refund_id IS DISTINCT FROM OLD.refund_id" in text
    assert "CREATE TRIGGER refunds_protect_record BEFORE INSERT OR UPDATE ON" in text
    assert "EXECUTE FUNCTION public.protect_refund_record()" in text


# Creating a refund requires a recorded completed capture with the same full amount.
@pytest.mark.parametrize("filename", SQL_FILES)
def test_refund_sql_checks_recorded_capture_before_insert(filename):
    text = sql_text(filename)
    assert "WHERE id = NEW.capture_id FOR SHARE" in text
    assert "payment.status <> 'COMPLETED'" in text
    assert "payment.capture_id IS NULL" in text
    assert "btrim(payment.capture_id) = ''" in text
    assert "NEW.amount_cents IS DISTINCT FROM payment.amount_cents" in text


# Store evidence for Stage 2, with no expiry or recovery worker hidden in the schema.
@pytest.mark.parametrize("filename", SQL_FILES)
def test_refund_sql_declares_durable_recovery_fields(filename):
    text = sql_text(filename)
    for declaration in ("refund_run_token TEXT", "refund_revision INTEGER", "send_state TEXT",
                        "send_started_at TIMESTAMPTZ", "error_code TEXT", "refund_check_status TEXT"):
        assert declaration in text
    assert "CHECK (send_state IN ('READY', 'IN_FLIGHT', 'ANSWERED', 'UNCERTAIN'))" in text
    assert "CHECK (send_state <> 'IN_FLIGHT' OR send_started_at IS NOT NULL)" in text


# Lock before inspecting old rows, and reject conflicts before any ALTER; never repair user data.
def test_refund_migration_checks_conflicts_atomically_without_deleting_data():
    text = sql_text(SQL_FILES[1])
    assert text.startswith("BEGIN;") and text.endswith("COMMIT;")
    assert text.index("LOCK TABLE") < text.index("DO $$") < text.index("ALTER TABLE")
    assert "GROUP BY capture_id HAVING COUNT(*) > 1" in text
    assert "refund.amount_cents IS DISTINCT FROM payment.amount_cents" in text
    assert "RAISE EXCEPTION" in text
    assert not re.search(r"\b(DELETE|TRUNCATE|DROP|UPDATE)\b", text.split("CREATE FUNCTION")[0])


# Old rows have no send history. Never label them READY merely because new fields were added.
def test_refund_migration_preserves_uncertainty_for_existing_rows():
    text = sql_text(SQL_FILES[1])
    assert "ADD COLUMN send_state TEXT NOT NULL DEFAULT 'UNCERTAIN'" in text
    assert "ALTER COLUMN send_state SET DEFAULT 'READY'" in text


# Fresh and upgraded databases must install exactly the same trigger implementation.
def test_refund_trigger_matches_between_schema_and_migration():
    fresh = sql_text(SQL_FILES[0]).split("CREATE FUNCTION public.protect_refund_record()", 1)
    upgrade = sql_text(SQL_FILES[1]).split("CREATE FUNCTION public.protect_refund_record()", 1)
    assert len(fresh) == len(upgrade) == 2
    assert fresh[1].split("CREATE TRIGGER", 1)[0] == upgrade[1].split("CREATE TRIGGER", 1)[0]
