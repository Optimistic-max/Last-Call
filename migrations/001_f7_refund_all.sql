-- F7 Stage 1. REVIEW ONLY until Emmanuel separately approves the target and execution.
-- Run once, on the intended database, in maintenance with application writers stopped.
-- public is the application's schema. No database/role provisioning; no data cleanup.
-- Execute the WHOLE file in one session with stop-on-error enabled (psql: -v ON_ERROR_STOP=1).
-- Any conflict, timeout or repeat execution aborts the transaction. Do not bypass a failed check.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

-- Hold these locks through COMMIT: rows cannot change between inspection and constraint creation.
LOCK TABLE public.events, public.holds, public.captures, public.refunds IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.refunds GROUP BY capture_id HAVING COUNT(*) > 1) THEN
        RAISE EXCEPTION 'F7 migration blocked: multiple refunds reference one capture';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.refunds AS refund
        LEFT JOIN public.captures AS payment ON payment.id = refund.capture_id
        WHERE refund.amount_cents <= 0 OR btrim(refund.request_id) = ''
           OR payment.id IS NULL OR payment.capture_id IS NULL OR btrim(payment.capture_id) = ''
           OR payment.status NOT IN ('COMPLETED', 'REFUNDED')
           OR refund.amount_cents IS DISTINCT FROM payment.amount_cents
    ) THEN
        RAISE EXCEPTION 'F7 migration blocked: refund records require manual review';
    END IF;
END;
$$;

ALTER TABLE public.events
    ADD COLUMN refund_run_token TEXT,
    ADD COLUMN refund_revision INTEGER NOT NULL DEFAULT 0 CHECK (refund_revision >= 0);
ALTER TABLE public.holds
    ADD COLUMN refund_check_status TEXT CHECK (refund_check_status IN ('PENDING', 'RESOLVED', 'MANUAL_REVIEW'));

-- Old records have no reliable send history: preserve that uncertainty, never imply never-sent.
ALTER TABLE public.refunds
    ADD COLUMN send_state TEXT NOT NULL DEFAULT 'UNCERTAIN',
    ADD COLUMN send_started_at TIMESTAMPTZ,
    ADD COLUMN error_code TEXT,
    ADD CONSTRAINT refunds_one_per_capture UNIQUE (capture_id),
    ADD CONSTRAINT refunds_amount_positive CHECK (amount_cents > 0),
    ADD CONSTRAINT refunds_request_not_blank CHECK (btrim(request_id) <> ''),
    ADD CONSTRAINT refunds_send_state CHECK (send_state IN ('READY', 'IN_FLIGHT', 'ANSWERED', 'UNCERTAIN')),
    ADD CONSTRAINT refunds_send_evidence CHECK (send_state <> 'IN_FLIGHT' OR send_started_at IS NOT NULL);
ALTER TABLE public.refunds ALTER COLUMN send_state SET DEFAULT 'READY';

-- Same guard as schema.sql. Historical IDs, amounts, statuses and timestamps are not rewritten.
CREATE FUNCTION public.protect_refund_record() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    payment public.captures%ROWTYPE;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.capture_id IS DISTINCT FROM OLD.capture_id
           OR NEW.request_id IS DISTINCT FROM OLD.request_id
           OR NEW.amount_cents IS DISTINCT FROM OLD.amount_cents
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'Refund identity cannot change' USING ERRCODE = '23514';
        END IF;
        IF OLD.refund_id IS NOT NULL AND NEW.refund_id IS DISTINCT FROM OLD.refund_id THEN
            RAISE EXCEPTION 'Assigned refund ID cannot change' USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO payment FROM public.captures WHERE id = NEW.capture_id FOR SHARE;
        IF NOT FOUND OR payment.status <> 'COMPLETED' OR payment.capture_id IS NULL
           OR btrim(payment.capture_id) = ''
           OR NEW.amount_cents IS DISTINCT FROM payment.amount_cents THEN
            RAISE EXCEPTION 'Refund requires a recorded completed capture and its full amount'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER refunds_protect_record BEFORE INSERT OR UPDATE ON public.refunds
FOR EACH ROW EXECUTE FUNCTION public.protect_refund_record();
COMMIT;
