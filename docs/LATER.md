# Later (not being built now)

Anything not in the current milestone goes here, not in the code. Nothing on this page may be claimed as built.

## Stretch goals (only if every must-have is done and tested before the Nov 8 freeze, D69)

| Idea | Note |
|---|---|
| PayPal-account pledgers through the PayPal button | Becomes a must-have if card fields fail by Oct 28 (D19, approved Oct 25) |
| Filling a gap from leftover holds after a failed charge | Each extra capture pays its own $0.49, and it breaks conditional pledges if someone was already charged |

## Cut for this hackathon (Oct 25)

| Idea | Why cut |
|---|---|
| PayPal Payouts to a venue | Must-haves can't be done by the Oct 27 checkpoint (D08) |

## Deferred (D31, Oct 26)

Not built before the Nov 8 freeze (D69). Research on each: `unverified`.

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
| F8 | "New pay link" goes only to the failed person (was waiting on D28 (b); D28 (b), Nov 4: not built before the freeze) | `NOT RUN` |

## Not built before the freeze (Oct 31, D60)

| Idea | Note |
|---|---|
| CSRF protection and rate limiting on `POST /events` | The S1 form has no CSRF token and no limit, so anyone could create many fake DRAFT events. `POST /admin/<admin_token>/open` already needs the secret token in its address |

## Not built before the freeze (Nov 1, D62)

| Idea | Note |
|---|---|
| Optional email on a pledge (D31: "name required, email optional") | Needs a `pledges.email` column in `schema.sql` and `DATA_MODEL.md`, an email field on S4 and in `POST /api/pledges`, and the `SECURITY.md` rules: never logged, never on the board or in `board.json` |

## Ideas from the team (add yours here)

| Date | Who | Idea |
|---|---|---|
| Nov 3 | Emmanuel | Rate limit on `POST /api/pledges/parse`. The route is public and each call uses our AI provider's quota, so anyone could use it up by sending many requests. Today only D73's 280-character limit applies |
| Nov 3 | Emmanuel | Cap the size of the `conditions` list in a request to `POST /api/pledges`. Today lifecycle refuses more than 3 names only after tidying the whole list, so a request with thousands of names is looped over before it is refused (no database use, but no limit on the request's size). Fix: refuse a list over a small number (for example 20) in `app.py` before any tidying, or set Flask's `MAX_CONTENT_LENGTH` |
| Nov 3 | Emmanuel | Treasurer dashboard: one page listing all of the treasurer's events with their status and progress (needs accounts and login) |
| Nov 3 | Emmanuel | `paypal_client.get_order(order_id)` (`GET /v2/checkout/orders/{id}`, `unverified`): lets the cleanup sweep look for the authorization of a `PENDING` hold whose authorize was sent but whose answer was lost (D80). Today those holds stay `PENDING` and log a warning |
| Nov 3 | Emmanuel | Stop retrying a definite authentication refusal after N tries (D80, D89): that is now the only void the sweep sends again, after 5 minutes, with the same saved request ID. An uncertain void is not retried. The refusal path still has no end |
| Nov 3 | Samuel | After submission: merge the plan docs into one PLAN.md and fold DECISIONS/TEAM into it (Samuel). |
| Nov 3 | Emmanuel | A per-pledge claim for the D27 resume (D81): if a first request is still charging when a resume starts (possible on a local server with no timeout; on Render gunicorn's 120 s timeout is shorter than `STUCK_LOCK_AFTER`), a pledge could be sent twice. PayPal's `final_capture: true` and the reused request ID already stop a double charge, so the worst case is a pledge marked `FAILED` that was charged once |
| Nov 4 | Emmanuel | Rejoin after leaving (D82): today a name that left stays `DROPPED` and can't confirm again, so people whose condition named it keep waiting. Allowing it means the D26 reuse rule also accepts `DROPPED` when no `CREATED` hold is left |
| Nov 4 | Emmanuel | Put the `pledger_token` after a `#` in the S6 address (D82), so browsers don't send it to the server and it stays out of Render's logs. Needs a little JavaScript on S6 |
| Nov 4 | Emmanuel | Optional email box so a friend can get their cancel link by email. Needs an email service, a `pledges.email` column and a privacy note update; blocked before the freeze by D62. |
| Nov 4 | Emmanuel | Longer default last call (e.g. 6 h) instead of 1 h. |
| Nov 4 | Emmanuel | Treasurer picks the last-call length (1 h / 6 h / 24 h) and the pledging length; anything past about 60 hours total needs reauthorizing old holds before lock (PayPal's honor period is 3 days). |
| Nov 4 | Emmanuel | $5 share floor: (a) a board line telling people shares are at the $5 minimum, and (b) a waitlist so extra people past the floor aren't charged. Why it came up: past the floor each new person adds about $0.49 in PayPal fees without lowering anyone's share, so the club collects more than it needs. (Emmanuel isn't a fan of either; the current rule of no cap and everyone paying at least $5 is fine for now. Revisit only if a real group hits the floor.) |
| Nov 4 | Emmanuel | A treasurer "Try the charge again" button on `NEEDS_ATTENTION` (D83): charge a `FAILED` pledge again later, from the admin page. Needs a new event compare-and-set (`NEEDS_ATTENTION` back to `CHARGING`) that also excludes refund-all, a reworded rule 6, a new screen, and a hold still `CREATED` inside PayPal's 3-day honor period. For now the only action after `NEEDS_ATTENTION` is refund-all (D49) |
| Nov 7 | Emmanuel | **007: require `claimed_refund_id` for CONTINUE once the new code is live** (D93, Malama's answer 2). Migration 006 leaves it optional so it cannot break code that is not yet deployed. The new code always sets it (`tests/test_refund_stage3_fixes.py::test_start_and_continue_always_record_the_refund_they_claimed`). Then add a CHECK that START/CONTINUE rows with a refund have one, backfilling nothing: old finished rows stay as they are. |
| Nov 7 | Emmanuel | Lost refund answer with no PayPal refund id: replay the refund POST with the same saved request id (PayPal accepts this for up to 45 days for refunds); needs a decision revising D89/D90's no-retry rule. (D94's "Check with PayPal" cannot help here, because a GET needs the PayPal refund id.) |
| Nov 7 | Emmanuel | Check whether `GET /v2/payments/captures/{id}` exposes the refund ids, which would allow a GET-only recovery when no refund id was saved (unverified). |

## Post-MVP Features

Both features are **High Priority** and **planned, not implemented** (`designed, not tested`). Work begins only after MVP completion and end-to-end PayPal Sandbox validation. Neither feature is part of the current F7 Stage 3 scope.

### AI Group Rescue - High Priority

An AI-powered assistant that helps a group consider voluntary ways to reach its funding goal when progress stalls.

- Detect how much funding is still needed using the application's confirmed funding calculation.
- Suggest realistic ways to close the gap, considering existing pledge amounts and unmet conditions.
- Suggest voluntary contributions or pledge adjustments without making changes itself.
- Generate friendly, shareable suggestions.
- Clearly distinguish hypothetical funding from confirmed pledges; suggestions do not count toward the goal.

**Example (fictional, hypothetical):** "You're $25 short. Five friends could voluntarily add $5 each to reach the goal."

**Safety:** The AI must never modify pledges, trigger payments, bypass conditions, or promise that a hypothetical suggestion will succeed. Plain code remains responsible for money calculations and eligibility; any participant action must follow the existing confirmation and payment safety rules.

### Interactive Pledge Dependency Map - High Priority

A mobile-friendly visual graph showing how participants' conditions connect.

- Show who is waiting on whom.
- Highlight the people whose decisions could unblock multiple pledges.
- Display dependency chains and cycles.
- Distinguish satisfied, waiting and unresolved conditions.
- Update from actual event data and the existing condition engine's results.
- Keep the layout clear on phones as well as larger screens.

**Example (fictional):** Ana depends on Bo, and Bo depends on Cy. The graph highlights Cy as the person currently blocking the chain.

**Accuracy:** The visualization must reflect the existing condition engine, including its handling of chains and cycles. It cannot change pledge eligibility or financial state. Highlighting a participant is explanatory, not a guarantee that their participation will satisfy every condition or reach the goal.
