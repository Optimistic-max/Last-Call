-- F7 Stage 2A: review only. Stop all application workers before running this file.
-- Run once as a whole transaction, with stop-on-error enabled, on an explicitly approved target.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
LOCK TABLE public.events, public.pledges, public.holds IN ACCESS EXCLUSIVE MODE;

ALTER TABLE public.holds ADD COLUMN void_run_token TEXT;

-- An old attempted void with no confirmed terminal hold status has unknown history.
-- Its marker is never a PayPal request ID and cannot expire automatically.
UPDATE public.holds SET void_run_token = 'legacy-' || id::text
WHERE void_request_id IS NOT NULL AND status NOT IN ('VOIDED', 'EXPIRED', 'DENIED', 'CAPTURED', 'PARTIALLY_CAPTURED');

CREATE FUNCTION public.protect_refund_handoff() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.status = 'REFUNDING' AND OLD.status IS DISTINCT FROM NEW.status AND EXISTS (
        SELECT 1 FROM public.holds JOIN public.pledges ON pledges.id = holds.pledge_id
        WHERE pledges.event_id = NEW.id AND holds.void_run_token IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Refund handoff blocked by unresolved void' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER events_protect_refund_handoff BEFORE UPDATE OF status ON public.events
FOR EACH ROW EXECUTE FUNCTION public.protect_refund_handoff();
COMMIT;
