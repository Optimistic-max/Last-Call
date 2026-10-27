# Later (not being built now)

Anything not in the current milestone goes here, not in the code. Nothing on this page may be claimed as built.

## Stretch goals (only if every must-have is done and tested before the Nov 3 freeze)

| Idea | Note |
|---|---|
| PayPal-account pledgers through the PayPal button | Becomes a must-have if card fields fail by Oct 28 (D19, approved Oct 25) |
| Filling a gap from leftover holds after a failed charge | Each extra capture pays its own $0.49, and it breaks conditional pledges if someone was already charged |
| Importing a chat by uploading an exported text file | Same AI reader, different input |

## Cut for this hackathon (Oct 25)

| Idea | Why cut |
|---|---|
| PayPal Payouts to a venue | Must-haves can't be done by the Oct 27 checkpoint (D08) |
| Live chat bots (Discord, GroupMe, Telegram) | Scope, free hosting sleeps, trademark risk in the video (D09) |

## Future work (may be mentioned in the README as future work only)

- Many clubs, each treasurer connecting their own PayPal account (PayPal's multiparty setup, partner approval needed).
- Paying the venue directly.
- Live (non-sandbox) payments, which would need live keys and PayPal's approval.
- An external pinger so deadlines settle on time even when nobody visits (see `SYSTEM_DESIGN.md` §3).

## Moved out of the MVP (Oct 26, D29)

Nothing uses these in any milestone, so they were taken out of the build docs. Our database plus API `GET` calls are the record (`AGENTS.md` rule 9).

**Webhooks** (`PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`) as an optional double-check: never trigger a charge, deduplicate by PayPal's event ID. Status: `NOT RUN`.

The table that was in `DATA_MODEL.md`:

```sql
CREATE TABLE webhook_events (
    event_id        TEXT        PRIMARY KEY,           -- PayPal's event ID, so duplicates are ignored
    type            TEXT        NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

The test that was F3 in `TEST_PLAN.md` (the ID isn't reused): "A duplicate webhook never causes a charge." Status: `NOT RUN`.

## Ideas from the team (add yours here)

| Date | Who | Idea |
|---|---|---|
| | | |
