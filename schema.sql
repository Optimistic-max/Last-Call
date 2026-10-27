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
    status          TEXT        NOT NULL DEFAULT 'PENDING',  -- PENDING, CREATED, DENIED, CAPTURED, VOIDED
    expires_at      TIMESTAMPTZ,                       -- from PayPal's expiration_time
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
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
