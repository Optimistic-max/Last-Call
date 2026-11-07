-- Review this SQL before any shared deployment. Never applied automatically.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
LOCK TABLE public.events, public.refunds IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    PERFORM operation_revision, first_send_started_at FROM public.refunds LIMIT 0;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid = 'public.refunds'::regclass
                   AND tgname = 'refunds_protect_operation' AND tgenabled = 'O') THEN
        RAISE EXCEPTION 'Refund web actions require the approved refund operation guards';
    END IF;
END;
$$;

-- Browser commands are separate from PayPal identities. Finished rows prevent replay forever.
CREATE TABLE public.refund_web_actions (
    action_hash TEXT PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES public.events(id),
    session_hash TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('START', 'CONTINUE', 'CHECK')),
    target_refund_id INTEGER REFERENCES public.refunds(id),
    state TEXT NOT NULL DEFAULT 'CLAIMED' CHECK (state IN ('CLAIMED', 'FINISHED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    CHECK ((state = 'CLAIMED' AND finished_at IS NULL) OR (state = 'FINISHED' AND finished_at IS NOT NULL)),
    CHECK ((action_type = 'CHECK' AND target_refund_id IS NOT NULL) OR
           (action_type <> 'CHECK' AND target_refund_id IS NULL))
);
CREATE UNIQUE INDEX refund_web_one_active_event ON public.refund_web_actions(event_id) WHERE state = 'CLAIMED';

-- Neither a replay nor an expired browser session may reopen a consumed command.
CREATE FUNCTION public.protect_refund_web_action() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.action_hash IS DISTINCT FROM OLD.action_hash OR NEW.event_id IS DISTINCT FROM OLD.event_id
           OR NEW.session_hash IS DISTINCT FROM OLD.session_hash OR NEW.action_type IS DISTINCT FROM OLD.action_type
           OR NEW.target_refund_id IS DISTINCT FROM OLD.target_refund_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR OLD.state = 'FINISHED' AND (NEW.state IS DISTINCT FROM OLD.state OR NEW.finished_at IS DISTINCT FROM OLD.finished_at) THEN
            RAISE EXCEPTION 'Consumed browser command identity cannot change' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.state <> 'CLAIMED' THEN
        RAISE EXCEPTION 'Browser commands must begin claimed' USING ERRCODE = '23514';
    END IF;
    IF NEW.action_type = 'CHECK' AND NOT EXISTS (
        SELECT 1 FROM public.refunds JOIN public.captures ON captures.id = refunds.capture_id
        JOIN public.holds ON holds.id = captures.hold_id JOIN public.pledges ON pledges.id = holds.pledge_id
        WHERE refunds.id = NEW.target_refund_id AND pledges.event_id = NEW.event_id
    ) THEN
        RAISE EXCEPTION 'Browser command target must belong to its event' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER refund_web_actions_protect BEFORE INSERT OR UPDATE ON public.refund_web_actions
FOR EACH ROW EXECUTE FUNCTION public.protect_refund_web_action();
COMMIT;
