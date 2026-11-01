# Later (not being built now)

Anything not in the current milestone goes here, not in the code. Nothing on this page may be claimed as built.

## Stretch goals (only if every must-have is done and tested before the Nov 5 freeze, D51)

| Idea | Note |
|---|---|
| PayPal-account pledgers through the PayPal button | Becomes a must-have if card fields fail by Oct 28 (D19, approved Oct 25) |
| Filling a gap from leftover holds after a failed charge | Each extra capture pays its own $0.49, and it breaks conditional pledges if someone was already charged |

## Cut for this hackathon (Oct 25)

| Idea | Why cut |
|---|---|
| PayPal Payouts to a venue | Must-haves can't be done by the Oct 27 checkpoint (D08) |

## Deferred (D31, Oct 26)

Not built before the Nov 5 freeze (D51). Research on each: `unverified`.

| Idea | Note |
|---|---|
| Treasurer chat paste (S7) | Left M4 under D31. Was: paste box, privacy note, editable cards, follow-up questions |
| Importing a chat from an exported text file | Deferred with the S7 paste (D31). Same AI reader, different input |
| One-sentence setup | — |
| Drafted nudges | — |
| "Who's missing?" | — |
| Venmo and wallets | — |
| Live chat bots (Discord, GroupMe, Telegram) | Was "cut" (Oct 25), now "deferred" (D09). Scope, free hosting sleeps, trademark risk in the video |

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

## Moved out before the freeze (Oct 30, D49)

Not built before the freeze. D47's safe ending stands instead: hold `CAPTURED`, pledge `FAILED`, event `NEEDS_ATTENTION`, error logged.

| Test | Idea | Status |
|---|---|---|
| F5 | A timeout on capture: `GET` first, then find and save the capture, no double charge | `NOT RUN` |
| F6 | `AUTHORIZATION_ALREADY_CAPTURED` is recorded as charged, not as failure | `NOT RUN` |
| F8 | "New pay link" goes only to the failed person (was waiting on D28 (b)) | `NOT RUN` |

## Not built before the freeze (Oct 31, D60)

| Idea | Note |
|---|---|
| CSRF protection and rate limiting on `POST /events` | The S1 form has no CSRF token and no limit, so anyone could create many fake DRAFT events. `POST /admin/<admin_token>/open` already needs the secret token in its address |

## Ideas from the team (add yours here)

| Date | Who | Idea |
|---|---|---|
| | | |
