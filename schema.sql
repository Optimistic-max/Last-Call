-- All CREATE TABLE statements for Last Call. Owner: Malama.
-- Copied from docs/DATA_MODEL.md. Any change here changes DATA_MODEL.md too, with a line in docs/DECISIONS.md.
-- Money columns are integer cents. Times are TIMESTAMPTZ, stored in UTC.
-- Run it once on each Neon branch (main, dev, test). Running it twice fails, because the tables already exist.

-- One plan to collect money for (one cabin deposit, one trip).
CREATE TABLE events (
    id              SERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    deposit_cents   INTEGER     NOT NULL CHECK (deposit_cents > 0),
    status          TEXT        NOT NULL DEFAULT 'DRAFT',
    admin_token     TEXT        NOT NULL UNIQUE,       -- the treasurer's private link
    demo_mode       BOOLEAN     NOT NULL DEFAULT FALSE,
    opens_at        TIMESTAMPTZ,
    hard_deadline   TIMESTAMPTZ,                       -- opens_at + 48h (minutes in demo mode)
    last_call_ends  TIMESTAMPTZ,                       -- min(goal time + 1h, hard_deadline); M1: hard_deadline (D25)
    goal_cents      INTEGER,                           -- fee-adjusted goal, saved at lock
    lock_started_at TIMESTAMPTZ,                       -- saved when LAST_CALL -> LOCKING wins; resumes a stuck lock (D27)
    refund_run_token TEXT,                             -- durable owner; never expires automatically (F7)
    refund_revision INTEGER NOT NULL DEFAULT 0 CHECK (refund_revision >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One person's pledge to one event.
CREATE TABLE pledges (
    id              SERIAL PRIMARY KEY,
    event_id        INTEGER     NOT NULL REFERENCES events(id),
    name            TEXT        NOT NULL,              -- shown on the board, used by conditions
    max_cents       INTEGER     NOT NULL CHECK (max_cents >= 500),
    min_cents       INTEGER,                           -- "in for $20": shown only (see DECISIONS D12)
    status          TEXT        NOT NULL DEFAULT 'PENDING_PAY',
    share_cents     INTEGER,                           -- saved at lock
    pledger_token   TEXT        NOT NULL UNIQUE,       -- private "I'm out" link
    source_message  TEXT,                              -- chat line the AI read it from (M4)
    ai_confidence   REAL,                              -- M4
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Names must be unique per event (ignoring case) so "if Jay's in" matches one person.
CREATE UNIQUE INDEX pledges_event_name ON pledges (event_id, lower(name));

-- "Only if Jay's in". One row per name. ALL of a pledge's conditions must hold.
CREATE TABLE pledge_conditions (
    id              SERIAL PRIMARY KEY,
    pledge_id       INTEGER     NOT NULL REFERENCES pledges(id),
    depends_on_name TEXT        NOT NULL
);

-- One PayPal hold (authorization) for one pledge.
CREATE TABLE holds (
    id              SERIAL PRIMARY KEY,
    pledge_id       INTEGER     NOT NULL REFERENCES pledges(id),
    create_request_id    TEXT   NOT NULL UNIQUE,       -- PayPal-Request-Id for create order, saved BEFORE the call
    order_id        TEXT        UNIQUE,                -- saved the moment PayPal returns it (empty until then)
    authorize_request_id TEXT   UNIQUE,                -- saved BEFORE the authorize call
    auth_id         TEXT        UNIQUE,                -- saved the moment authorize returns
    void_request_id TEXT        UNIQUE,                -- saved BEFORE the void call
    amount_cents    INTEGER     NOT NULL,              -- = pledge max
    status          TEXT        NOT NULL DEFAULT 'PENDING',  -- PENDING, CREATED, DENIED, CAPTURED, VOIDED, NOT_PLACED
    expires_at      TIMESTAMPTZ,                       -- from PayPal's expiration_time
    void_tried_at   TIMESTAMPTZ,                       -- the cleanup sweep's claim on this hold (D80)
    void_run_token  TEXT,                              -- durable owner; uncertain calls need review (F7)
    refund_check_status TEXT CHECK (refund_check_status IN ('PENDING', 'RESOLVED', 'MANUAL_REVIEW')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One capture attempt against one hold. A retry is a new row (attempt 2).
CREATE TABLE captures (
    id              SERIAL PRIMARY KEY,
    hold_id         INTEGER     NOT NULL REFERENCES holds(id),
    request_id      TEXT        NOT NULL UNIQUE,       -- saved BEFORE calling PayPal
    attempt         INTEGER     NOT NULL DEFAULT 1,
    amount_cents    INTEGER     NOT NULL,              -- = the pledge's share
    capture_id      TEXT        UNIQUE,
    fee_cents       INTEGER,                           -- from seller_receivable_breakdown.paypal_fee
    net_cents       INTEGER,                           -- from seller_receivable_breakdown.net_amount
    status          TEXT        NOT NULL DEFAULT 'PENDING',  -- PENDING, COMPLETED, FAILED, REFUNDED
    error_code      TEXT,                              -- e.g. TRANSACTION_REFUSED
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Only created when the treasurer clicks refund-all.
CREATE TABLE refunds (
    id              SERIAL PRIMARY KEY,
    capture_id      INTEGER     NOT NULL REFERENCES captures(id),
    request_id      TEXT        NOT NULL UNIQUE,
    refund_id       TEXT        UNIQUE,
    amount_cents    INTEGER     NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'PENDING',
    send_state TEXT NOT NULL DEFAULT 'READY',           -- separate sending evidence from PayPal outcome
    send_started_at TIMESTAMPTZ,
    operation_revision BIGINT NOT NULL DEFAULT 0 CHECK (operation_revision >= 0),
    first_send_started_at TIMESTAMPTZ,
    error_code TEXT,                                  -- sanitized code only, never a response body
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT refunds_one_per_capture UNIQUE (capture_id),
    CONSTRAINT refunds_amount_positive CHECK (amount_cents > 0),
    CONSTRAINT refunds_request_not_blank CHECK (btrim(request_id) <> ''),
    CONSTRAINT refunds_send_state CHECK (send_state IN ('READY', 'IN_FLIGHT', 'ANSWERED', 'UNCERTAIN', 'CHECK_ONLY')),
    CONSTRAINT refunds_send_evidence CHECK (send_state <> 'IN_FLIGHT' OR send_started_at IS NOT NULL)
);

-- Enforce immutable refund identity even if a future caller accidentally tries to replace it.
-- INSERT only accepts a recorded successful capture and its exact full amount; no money math.
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

-- The event row serializes this check with the event-then-hold void claim.
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
CREATE TRIGGER refunds_protect_operation BEFORE UPDATE ON public.refunds
FOR EACH ROW EXECUTE FUNCTION public.protect_refund_operation();
