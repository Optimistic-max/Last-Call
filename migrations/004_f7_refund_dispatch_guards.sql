-- Final F7 dispatch guards. Separately approved targets only; stop old writers first.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
LOCK TABLE public.events, public.pledges, public.holds, public.captures, public.refunds IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    PERFORM operation_revision, first_send_started_at, send_started_at FROM public.refunds LIMIT 0;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger
                   WHERE tgrelid = 'public.refunds'::regclass AND tgname = 'refunds_protect_record' AND tgenabled = 'O')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger
                      WHERE tgrelid = 'public.refunds'::regclass AND tgname = 'refunds_protect_operation' AND tgenabled = 'O')
       OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger
                      WHERE tgrelid = 'public.events'::regclass AND tgname = 'events_protect_refund_handoff' AND tgenabled = 'O') THEN
        RAISE EXCEPTION 'F7 dispatch migration requires the approved existing guards';
    END IF;
END;
$$;

-- No historical row is rewritten, including anomalous READY rows. Such rows cannot send.
CREATE OR REPLACE FUNCTION public.protect_refund_operation() RETURNS trigger
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
        OLD.send_state <> 'READY' OR OLD.first_send_started_at IS NOT NULL
        OR OLD.send_started_at IS NOT NULL OR OLD.operation_revision <> 0
        OR OLD.refund_id IS NOT NULL OR OLD.status <> 'PENDING'
        OR NEW.first_send_started_at IS NULL
        OR NEW.operation_revision <= OLD.operation_revision
    ) THEN
        RAISE EXCEPTION 'Only a fresh first-send claim may POST; retries are disabled' USING ERRCODE = '23514';
    END IF;
    IF OLD.send_state <> 'READY' AND NEW.send_state = 'READY' THEN
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
COMMIT;
