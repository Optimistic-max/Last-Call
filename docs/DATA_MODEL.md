# Data model

> **D24 approved by Emmanuel Oct 26 (Malama delegated the decision to Emmanuel).**

All money columns are **integer cents**. All times are `TIMESTAMPTZ` stored in UTC. This is the starting `schema.sql`. Malama owns it, and any change gets a line in `docs/DECISIONS.md`.

```sql
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
    refund_run_token TEXT,                             -- durable refund owner, no automatic expiry (D87)
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
    void_run_token  TEXT,                              -- durable owner; uncertain calls need review (F7, D88)
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
    send_state TEXT NOT NULL DEFAULT 'READY',
    send_started_at TIMESTAMPTZ,
    operation_revision BIGINT NOT NULL DEFAULT 0 CHECK (operation_revision >= 0),
    first_send_started_at TIMESTAMPTZ,
    error_code TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT refunds_one_per_capture UNIQUE (capture_id),
    CONSTRAINT refunds_amount_positive CHECK (amount_cents > 0),
    CONSTRAINT refunds_request_not_blank CHECK (btrim(request_id) <> ''),
    CONSTRAINT refunds_send_state CHECK (send_state IN ('READY', 'IN_FLIGHT', 'ANSWERED', 'UNCERTAIN', 'CHECK_ONLY')),
    CONSTRAINT refunds_send_evidence CHECK (send_state <> 'IN_FLIGHT' OR send_started_at IS NOT NULL)
);
```

## Notes

- **F7 Stage 1 (D87): designed, not tested in PostgreSQL.** `schema.sql` also installs `public.protect_refund_record()` and the `refunds_protect_record` BEFORE INSERT OR UPDATE trigger. INSERT requires a recorded `COMPLETED` capture with a nonblank PayPal capture ID and matching full amount; a share lock keeps that capture stable through insertion. UPDATE cannot change the capture reference, original request ID, amount or creation time, or erase/replace an assigned refund ID. Updating result fields remains possible. These guards do not send payments or implement refund lifecycle.
- **Recovery fields are evidence for Stage 2, not a working recovery system.** A null `refund_run_token` means no owner; a nonnull owner never expires automatically. `refund_revision` will guard stale submitted actions. `send_state` separates never-started (`READY`), started (`IN_FLIGHT`), recorded response (`ANSWERED`) and uncertain (`UNCERTAIN`); `IN_FLIGHT` requires `send_started_at`. `error_code` is for sanitized codes. A null hold `refund_check_status` means not checked; `PENDING`, `RESOLVED` and `MANUAL_REVIEW` record F7 authorization checks.
- **Existing databases:** `migrations/001_f7_refund_all.sql` is prepared for separate review and execution approval; it has NOT RUN against Neon. It targets `public`, locks before checking conflicts, adds fields/constraints/trigger atomically, and does not rewrite existing IDs, amounts, statuses or timestamps. Existing refund rows get new send state `UNCERTAIN`, since their prior sending history is unknown; only future inserts default to `READY`. Do not rerun `schema.sql` on an existing database. Malama reviews this schema change.

- **`holds.void_run_token` is a durable void owner (D88).** Null means no owner. A non-null token, including migration 002's `legacy-<id>` marker, means a void may already have been sent. The cleanup sweep does not select that hold. The token is cleared when a confirmed terminal `GET` is saved for that same token, or when a definite authentication refusal is recorded. `CREATED`, a missing `GET`, a mismatched authorization id, and any other status leave it in place. `reconcile_uncertain_void` is an explicit `GET` and is not called by the sweep. This column is already in `schema.sql`. This note does not change the table.
- **Why `holds.status` starts at `PENDING` and `order_id` may be empty:** the row is saved with its `create_request_id` *before* the create-order call, and `order_id` is filled in the moment PayPal returns it. That is the "save before you send" rule (D24). A `PENDING` hold older than an hour with no `auth_id` is usually an abandoned checkout, with nothing to void. On a finished event, the cleanup sweep marks one whose `authorize_request_id` is empty `NOT_PLACED` (authorize was never sent, D80). If its `authorize_request_id` is set, authorize was sent and the answer never came: see `PAYPAL_INTEGRATION.md` §5.
- **`holds.status` can also hold PayPal's own word:** after a failed or resumed capture, `lifecycle.record_failed_charge` and `resend_pending_capture` save the status PayPal's `GET` returns, as is (for example `PARTIALLY_CAPTURED` or `EXPIRED`). PayPal also has a `PENDING` authorization status (`unverified`, TODO (source needed)). So a `PENDING` hold **with** an `auth_id` is PayPal's pending, not ours: ours always has an empty `auth_id`. Nothing in the code mixes the two today, because the sweep's `NOT_PLACED` step needs an empty `auth_id` (D80). Found in the review of D81, Nov 5.
- **Names are saved trimmed, with single spaces** (the same cleanup `conditions.py` uses for matching), so the unique index treats "Ana " and "ana" as the same person.
- **`goal_cents` and every counted pledge's `share_cents` are saved in one transaction (D81).** So a saved `goal_cents` means every share is saved, and a counted pledge is the one with a `share_cents`. The D27 resume uses that to tell a lock that died before its shares from one that died after. A capture row sent again by the resume keeps `attempt = 1` and its `request_id`; attempt 2 is F4's retry (D83): a new row with a new `request_id`, made inside the lock only after a failed attempt 1. There is never an attempt 3.
- **Why the capture `request_id` is unique:** it is the idempotency key. Reusing it on a retry returns the same capture instead of charging again (VERIFIED in sandbox).
- **The treasurer's real net** is `SUM(captures.net_cents) WHERE status = 'COMPLETED'`, read from PayPal's own numbers. Never compute it from the formula.
- **No email column and no stored "hold pending" (D62).** `pledges` has no `email` column before the freeze, so the pledge form asks for a name only. "Hold pending" (D31 #6) is never saved as a pledge status: it is worked out from `holds` when the board is built (Emmanuel's `board.json`, M4).
- **Admin and pledger tokens** are generated with `secrets.token_urlsafe(24)`. Never show one person's token to another.

- **Stage 2B corrections (D89):** operation_revision distinguishes individual refund operations within the same event owner/revision. Claims and accepted results increment it; stale writes change zero rows. first_send_started_at is set before the first POST and is immutable thereafter. Existing unknown times remain NULL. CHECK_ONLY is an explicitly authorized maintenance recovery state that permits GET only; a failed/pending observation never enables a POST. New operation guards prevent revision decreases, invented historical send times, retry transitions, and completion regression. Full accounting still belongs to lifecycle.py, not a column default.
- **Migration 003:** migrations/003_f7_refund_operation_safety.sql extends the existing schema transactionally, checks enabled prerequisite guards, and preserves historical identities, amounts, statuses and timestamps. Stop old workers before applying it on a separately approved target. It has no automatic startup caller. Migrations 001/002 are preserved. Application rollback to older refund code is unsafe after using CHECK_ONLY: stop refund processing and preserve recovery evidence instead of deleting the columns. Local validation evidence belongs in TEST_PLAN.md; no Neon execution is authorized.

- **Migration 004 (D90):** replaces only the operation guard function, transactionally with bounded lock waits and prerequisite checks. No columns or existing rows change. Only a fresh READY row with no sending history may enter IN_FLIGHT; no other state may reset to READY. An IN_FLIGHT revision increment remains valid for one-use dispatch. Migrations 001–003 remain unchanged. A late response's restricted ID-only save checks immutable identity, event ownership and the observed current revision without changing that revision or any outcome. Do not roll back to refund code that can reuse dispatch claims; stop refund processing and preserve evidence instead.
