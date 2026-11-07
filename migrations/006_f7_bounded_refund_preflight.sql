-- Review this SQL before any shared deployment. Never applied automatically.
-- Never applied to a Neon branch from this task (D93). Additive: current code on the 005 schema keeps working.
BEGIN;
SET LOCAL search_path = pg_catalog, public;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
LOCK TABLE public.events, public.holds, public.refunds, public.refund_web_actions IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid = 'public.refund_web_actions'::regclass
                   AND tgname = 'refund_web_actions_protect' AND tgenabled = 'O') THEN
        RAISE EXCEPTION 'Migration 006 requires the enabled migration 005 command guard';
    END IF;
    -- Migration 005 left this constraint unnamed, so PostgreSQL chose its name. Stop if it is not what we expect.
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint WHERE conrelid = 'public.refund_web_actions'::regclass
                   AND conname = 'refund_web_actions_action_type_check'
                   AND pg_get_constraintdef(oid) = $c$CHECK ((action_type = ANY (ARRAY['START'::text, 'CONTINUE'::text, 'CHECK'::text])))$c$) THEN
        RAISE EXCEPTION 'Migration 006 requires the migration 005 action-type constraint';
    END IF;
END;
$$;

-- Objects:
ALTER TABLE public.refund_web_actions
    ADD COLUMN target_hold_id INTEGER CONSTRAINT refund_web_actions_target_hold_fkey REFERENCES public.holds(id),
    ADD COLUMN claimed_refund_id INTEGER CONSTRAINT refund_web_actions_claimed_refund_fkey REFERENCES public.refunds(id),
    ADD CONSTRAINT refund_web_actions_one_command_per_refund UNIQUE (claimed_refund_id),
    DROP CONSTRAINT refund_web_actions_action_type_check,
    ADD CONSTRAINT refund_web_actions_action_type CHECK (action_type IN ('START', 'CONTINUE', 'CHECK', 'CANCEL_HOLD')),
    ADD CONSTRAINT refund_web_actions_cancel_target CHECK (
        (action_type = 'CANCEL_HOLD' AND target_hold_id IS NOT NULL) OR
        (action_type <> 'CANCEL_HOLD' AND target_hold_id IS NULL)),
    ADD CONSTRAINT refund_web_actions_claim_kind CHECK (claimed_refund_id IS NULL OR action_type IN ('START', 'CONTINUE'));

-- Every rule from migration 005 stays. New rules: the links never change; a cancel command exists only
-- after its void claim is committed; a start or continue command exists only after its refund is
-- claimed; and a command finishes only after what it started has a saved result (D93).
CREATE OR REPLACE FUNCTION public.protect_refund_web_action() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.action_hash IS DISTINCT FROM OLD.action_hash OR NEW.event_id IS DISTINCT FROM OLD.event_id
           OR NEW.session_hash IS DISTINCT FROM OLD.session_hash OR NEW.action_type IS DISTINCT FROM OLD.action_type
           OR NEW.target_refund_id IS DISTINCT FROM OLD.target_refund_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.target_hold_id IS DISTINCT FROM OLD.target_hold_id
           OR NEW.claimed_refund_id IS DISTINCT FROM OLD.claimed_refund_id
           OR OLD.state = 'FINISHED' AND (NEW.state IS DISTINCT FROM OLD.state OR NEW.finished_at IS DISTINCT FROM OLD.finished_at) THEN
            RAISE EXCEPTION 'Consumed browser command identity cannot change' USING ERRCODE = '23514';
        END IF;
        IF OLD.state = 'CLAIMED' AND NEW.state = 'FINISHED' THEN
            IF EXISTS (SELECT 1 FROM public.refunds WHERE refunds.id IN (NEW.claimed_refund_id, NEW.target_refund_id)
                       AND refunds.send_state IN ('IN_FLIGHT', 'UNCERTAIN', 'CHECK_ONLY')) THEN
                RAISE EXCEPTION 'A browser command cannot finish while its refund is unresolved' USING ERRCODE = '23514';
            END IF;
            IF EXISTS (SELECT 1 FROM public.holds WHERE holds.id = NEW.target_hold_id AND holds.void_run_token IS NOT NULL) THEN
                RAISE EXCEPTION 'A browser command cannot finish while its void is unresolved' USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSE
        IF NEW.state <> 'CLAIMED' THEN
            RAISE EXCEPTION 'Browser commands must begin claimed' USING ERRCODE = '23514';
        END IF;
        IF NEW.action_type = 'CANCEL_HOLD' AND NOT EXISTS (
            SELECT 1 FROM public.holds JOIN public.pledges ON pledges.id = holds.pledge_id
            WHERE holds.id = NEW.target_hold_id AND pledges.event_id = NEW.event_id
              AND holds.void_run_token IS NOT NULL AND holds.void_request_id IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'A cancel command requires its committed void claim on this event' USING ERRCODE = '23514';
        END IF;
        IF NEW.claimed_refund_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.refunds JOIN public.captures ON captures.id = refunds.capture_id
            JOIN public.holds ON holds.id = captures.hold_id JOIN public.pledges ON pledges.id = holds.pledge_id
            WHERE refunds.id = NEW.claimed_refund_id AND pledges.event_id = NEW.event_id
              AND refunds.send_state = 'IN_FLIGHT' AND refunds.first_send_started_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'A refund command requires its committed refund claim on this event' USING ERRCODE = '23514';
        END IF;
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
COMMIT;
