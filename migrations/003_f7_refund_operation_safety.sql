-- F7 Stage 2B safety. Run as one transaction only on a separately approved target.
-- Stop old application writers first. No startup migration, history repair, or retry unlock.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
LOCK TABLE public.events, public.pledges, public.holds, public.captures, public.refunds IN ACCESS EXCLUSIVE MODE;

-- Fail before changing anything if the approved Stage 1/2A prerequisites are absent.
DO $$
BEGIN
    PERFORM refund_run_token, refund_revision FROM public.events LIMIT 0;
    PERFORM void_run_token, refund_check_status FROM public.holds LIMIT 0;
    PERFORM send_state, send_started_at FROM public.refunds LIMIT 0;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger
                   WHERE tgrelid = 'public.refunds'::regclass AND tgname = 'refunds_protect_record' AND tgenabled = 'O')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger
                      WHERE tgrelid = 'public.events'::regclass AND tgname = 'events_protect_refund_handoff' AND tgenabled = 'O') THEN
        RAISE EXCEPTION 'F7 operation migration requires the approved existing guards';
    END IF;
END;
$$;

ALTER TABLE public.refunds
    ADD COLUMN operation_revision BIGINT NOT NULL DEFAULT 0 CHECK (operation_revision >= 0),
    ADD COLUMN first_send_started_at TIMESTAMPTZ;
ALTER TABLE public.refunds DROP CONSTRAINT refunds_send_state;
ALTER TABLE public.refunds ADD CONSTRAINT refunds_send_state
    CHECK (send_state IN ('READY', 'IN_FLIGHT', 'ANSWERED', 'UNCERTAIN', 'CHECK_ONLY'));

-- Preserve every historical value. In particular, unknown original sending times stay NULL.
CREATE FUNCTION public.protect_refund_operation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.operation_revision < OLD.operation_revision THEN
        RAISE EXCEPTION 'Refund operation revision cannot decrease' USING ERRCODE = '23514';
    END IF;
    IF OLD.first_send_started_at IS NOT NULL AND
       NEW.first_send_started_at IS DISTINCT FROM OLD.first_send_started_at THEN
        RAISE EXCEPTION 'Original refund sending time cannot change' USING ERRCODE = '23514';
    END IF;
    IF OLD.first_send_started_at IS NULL AND NEW.first_send_started_at IS NOT NULL AND NOT (
        OLD.send_state = 'READY' AND OLD.send_started_at IS NULL AND OLD.operation_revision = 0
        AND OLD.refund_id IS NULL AND OLD.status = 'PENDING'
        AND NEW.send_state = 'IN_FLIGHT' AND NEW.operation_revision > OLD.operation_revision
    ) THEN
        RAISE EXCEPTION 'Unknown original sending time cannot be invented' USING ERRCODE = '23514';
    END IF;
    IF NEW.send_state = 'IN_FLIGHT' AND OLD.send_state <> 'IN_FLIGHT' AND (
        OLD.send_state <> 'READY' OR NEW.first_send_started_at IS NULL
        OR NEW.operation_revision <= OLD.operation_revision
    ) THEN
        RAISE EXCEPTION 'Only a fresh first-send claim may POST; retries are disabled' USING ERRCODE = '23514';
    END IF;
    IF OLD.send_state IN ('IN_FLIGHT', 'UNCERTAIN', 'CHECK_ONLY') AND NEW.send_state = 'READY' THEN
        RAISE EXCEPTION 'Recovery cannot authorize another POST' USING ERRCODE = '23514';
    END IF;
    IF OLD.send_state = 'UNCERTAIN' AND NEW.send_state = 'ANSWERED' THEN
        RAISE EXCEPTION 'Uncertain operations require authorized CHECK_ONLY recovery' USING ERRCODE = '23514';
    END IF;
    IF OLD.send_state = 'CHECK_ONLY' AND NEW.send_state = 'ANSWERED' AND NEW.status <> 'COMPLETED' THEN
        RAISE EXCEPTION 'A recovery observation cannot enable a retry' USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'COMPLETED' AND NEW.status <> 'COMPLETED' THEN
        RAISE EXCEPTION 'Completed refund cannot regress' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER refunds_protect_operation BEFORE UPDATE ON public.refunds
FOR EACH ROW EXECUTE FUNCTION public.protect_refund_operation();
COMMIT;
