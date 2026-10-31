# State machine

Every status change in code goes through `lifecycle.py`. Event status changes use compare-and-set (`UPDATE ... WHERE status = <expected>`) so two requests can never both make the same change.

## Event states

```
DRAFT ──open──► OPEN ──goal reached──► LAST_CALL ──last_call_ends──► LOCKING ──► CHARGING ──┬──► SETTLED
                  │                                                                         └──► NEEDS_ATTENTION
                  └──hard_deadline, goal not reached──► EXPIRED
```

Failure branches aren't drawn here. They are all in the "Failure branches" table below.

| State | Meaning | What must be saved before showing it |
|---|---|---|
| `DRAFT` | Treasurer is setting up (deposit, title, AI cards in M4) | `admin_token` |
| `OPEN` | Pledging is open | `opens_at`, `hard_deadline = opens_at + 48h` (demo mode: minutes, see `config.py`) |
| `LAST_CALL` | Goal reached, people can still join, counted people can't leave | `last_call_ends = min(now + 1h, hard_deadline)` |
| `LOCKING` | Shares are being computed and saved | every `share_cents`, `goal_cents` |
| `CHARGING` | Captures running one at a time | each capture row before its PayPal call |
| `SETTLED` | Every counted pledge charged | — |
| `NEEDS_ATTENTION` | At least one capture failed twice | which pledges failed |
| `EXPIRED` | Deadline passed without the goal; all holds voided | — |

## Pledge states

```
(M4 only) PARSED ──treasurer confirms──► PENDING_PAY ──authorize CREATED──► HELD ◄──► COUNTED
                                              │                              │            │
                                     authorize DENIED                  I'm out / never     lock
                                              ▼                        counted at lock     ▼
                                          DECLINED                         DROPPED      CHARGED ──refund-all──► REFUNDED
                                                                                        or FAILED (what comes next: D28)
```

| State | Meaning |
|---|---|
| `PARSED` | Created from the chat by the AI, not yet confirmed (M4) |
| `PENDING_PAY` | Waiting for this person to hold their max |
| `HELD` | PayPal hold in place, but not counted (their condition isn't met yet) |
| `COUNTED` | Held and counted toward the goal by the circle rule. Can't leave during last call |
| `DROPPED` | Left before last call, never counted at lock, or still unpaid (`PENDING_PAY`) when the event locked or expired. Hold voided, if there was one |
| `DECLINED` | Authorization came back `DENIED`. Nothing to void (trying again: D26) |
| `CHARGED` | Share captured |
| `FAILED` | Capture failed twice |
| `REFUNDED` | Refunded because the treasurer chose refund-all |

`HELD` and `COUNTED` are recomputed by the circle rule every time the goal is checked.

## Hold states (PayPal's own names)

`CREATED` (active hold), `CAPTURED`, `VOIDED`, `DENIED`. `PARTIALLY_CAPTURED` only appears in the gap-fill stretch goal, which we are not building.

## Transitions and the PayPal call behind each

| Transition | PayPal call | Rules |
|---|---|---|
| pledge `PENDING_PAY` → `HELD` / `DECLINED` | `POST /v2/checkout/orders` (intent `AUTHORIZE`), then `POST /v2/checkout/orders/{id}/authorize` | Save each call's `PayPal-Request-Id` before sending it (rule 3). Save `order_id` immediately, then `auth_id`, status, `expiration_time`. `DENIED` means declined |
| pledge → `DROPPED` | `POST /v2/payments/authorizations/{id}/void` | Returns 204. Confirm with a `GET` showing `VOIDED` |
| pledge `COUNTED` → `CHARGED` | `POST /v2/payments/authorizations/{id}/capture` with `final_capture: true` | Save the capture's `request_id` first. Afterwards `GET /v2/payments/captures/{id}` and save the fee and net |
| pledge `CHARGED` → `REFUNDED` | `POST /v2/payments/captures/{id}/refund` | Only from the treasurer's refund-all button |
| event → `EXPIRED` | void every `CREATED` hold | — |

Webhooks are not used. Nothing in any milestone needs them, so they moved to `docs/LATER.md` (D29). Our database plus API `GET` calls are the record.

## Rules for "leaving"

- Before last call: anyone can leave. Their hold is voided and their pledge becomes `DROPPED`.
- During last call: a `COUNTED` pledger **cannot** leave. Show: "You're counted, so you can't leave during last call." A `HELD` pledger who isn't counted can still leave.

## Failure branches

Every way a step can go wrong, and where its handling is written down. All of it is `designed, not tested` unless a test ID says otherwise.

| What goes wrong | What happens | Details |
|---|---|---|
| Card declined at authorize (201 + `DENIED`) | Pledge `DECLINED`, nothing to void, "Card declined" (B2) | `PAYPAL_INTEGRATION.md` §4 |
| The same person tries again (after a decline, a closed tab or a reload) | Reuse that person's unpaid pledge with a new hold row and order; refuse if they already hold ("[Name] has already pledged.") | `DECISIONS.md` D26 |
| Authorize times out or returns something unexpected | Retry once with the same request ID, then a generic error. Never treated as held | `PAYPAL_INTEGRATION.md` §4–5 |
| A hold comes back after the event left `OPEN`/`LAST_CALL` | Void it at once, pledge `DROPPED`, show the "pledging closed" message (F11). The sweep catches any that slip through | `SYSTEM_DESIGN.md` §5A |
| A void doesn't return 204 | `GET` the authorization and save its real status. Still `CREATED`: the sweep retries on the next wake (F12) | `PAYPAL_INTEGRATION.md` §4 |
| Two requests try the same status change | Compare-and-set: only one wins (E8) | `SYSTEM_DESIGN.md` §4 |
| Settling raises an error | Log it and still serve the page | `SYSTEM_DESIGN.md` §3 |
| At lock, the goal is no longer reached (the invariants say this can't happen) | Charge nobody: void every hold, event `LOCKING → EXPIRED` (F13) | `SYSTEM_DESIGN.md` §5C |
| A capture is refused, times out, or hits a voided hold | Retry once (M2), only if the `GET` shows the hold still `CREATED` (F14), then pledge `FAILED`, event `NEEDS_ATTENTION`. M1 has no retry | `PAYPAL_INTEGRATION.md` §4–5 |
| A capture returns `AUTHORIZATION_ALREADY_CAPTURED`, or the `GET` after a failed capture shows `CAPTURED` | The money moved, but we don't look for the capture: hold `CAPTURED`, pledge `FAILED`, event `NEEDS_ATTENTION`, logged, never retried. Finding it (F5, F6) is in `docs/LATER.md` | `DECISIONS.md` D47, D49 |
| The request running the lock dies partway | After 5 minutes, `settle_due_events` wins a resume compare-and-set and continues the lock (M2, E11). A pledge whose capture row is still `PENDING` and whose hold is `CAPTURED` follows D47 | `DECISIONS.md` D27, D49, D50 |
| After `NEEDS_ATTENTION` | The only action is refund-all (designed, not tested). The new pay link moved to `docs/LATER.md` (D49). Still **OPEN** for M2: the event's status after refund-all, a `FAILED` pledge's hold, a refund that fails | `DECISIONS.md` D28, D49 |
| Nobody visits after a deadline | Nothing settles until someone does. After about 3 days, captures may fail | `SYSTEM_DESIGN.md` §3 (known limit) |

## Invariants (the tests should prove these)

1. **Joining never un-counts anyone.** Conditions only ever require someone to be *present*, so adding a pledger can only grow the counted set.
2. **An uncounted pledger leaving never un-counts anyone.** If B is counted, everyone B depends on is also counted. So only counted people matter to counted people.
3. **Once the goal is reached, joining keeps it reached.** Each new pledger adds a max of at least $5.00, but raises the fee-adjusted goal by only about $0.51.
4. **Together, 1–3 mean the board can never flip from "goal reached" back to "short" during last call.**
5. **Each counted pledge is captured at most once** (compare-and-set + saved request IDs + `final_capture: true`).
6. **Every authorization ID in PayPal also exists in our `holds` table**, because we save it before doing anything else. The one gap: an authorize call whose answer never arrives (`PAYPAL_INTEGRATION.md` §5).
