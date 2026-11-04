# State machine

Every status change in code goes through `lifecycle.py`. Event status changes use compare-and-set (`UPDATE ... WHERE status = <expected>`) so two requests can never both make the same change.

## Event states

```
DRAFT ──open──► OPEN ──goal reached──► LAST_CALL ──last_call_ends──► LOCKING ──► CHARGING ──┬──► SETTLED
                  │                                                                         └──► NEEDS_ATTENTION
                  └──hard_deadline, goal not reached──► EXPIRED

NEEDS_ATTENTION ──refund-all (D28)──► REFUNDING ──every refund succeeds──► REFUNDED
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
| `REFUNDING` | The treasurer clicked refund-all (D28). Refunds go out one at a time and stay here until every refund succeeds | each refund row, with its request ID, before its PayPal call |
| `REFUNDED` | Every refund succeeded | — |
| `EXPIRED` | Deadline passed without the goal. Every `CREATED` hold is voided; one whose void failed stays `CREATED`, its pledge stays `HELD`, and the event stays `EXPIRED` until M2's cleanup sweep voids it (D45) | — |

## Pledge states

```
friend confirms, row created ──────────► PENDING_PAY ──authorize CREATED──► HELD ◄──► COUNTED
                                              │                              │            │
                                     authorize DENIED                  I'm out / never     lock
                                              ▼                        counted at lock     ▼
                                          DECLINED                         DROPPED      CHARGED ──refund-all──► REFUNDED
                                                                                        or FAILED (D28: refund-all reads its hold first)
```

| State | Meaning |
|---|---|
| `PENDING_PAY` | The first state. The pledge row is created here, when the friend confirms (D31). Waiting for this person to hold their max. There is no `PARSED` state: the AI's suggestion stays only in the page and is never saved (D62) |
| `HELD` | PayPal hold in place. Whether this pledge is counted is worked out each time by the circle rule and never stored (D70, D78) |
| `COUNTED` | Not a stored status (D78): a `HELD` pledge that the circle rule counts toward the goal. Can't leave during last call |
| `DROPPED` | Left before last call, never counted at lock, or still unpaid (`PENDING_PAY`) when the event locked or expired. Hold voided, if there was one. **When an event expires (D45):** a pledge that was `HELD` becomes `DROPPED` once its hold is voided, or at once (no PayPal call) if it has no `CREATED` hold left, for example a hold voided or declined earlier. A pledge whose void failed stays `HELD`, with its hold still `CREATED`, until M2's cleanup sweep voids it |
| `DECLINED` | Authorization came back `DENIED`. Nothing to void (trying again: D26) |
| `CHARGED` | Share captured |
| `FAILED` | Capture failed twice |
| `REFUNDED` | Refunded because the treasurer chose refund-all |

Who is counted is recomputed by the circle rule every time the goal is checked, at lock and on the board, always by `lifecycle.counted_held_pledges` (D70, D78). At lock, a `HELD` pledge that is not counted has its hold voided and becomes `DROPPED`; it is never charged. If that void does not read back `VOIDED`, the pledge stays `HELD` with its hold `CREATED` until M2's cleanup sweep voids it (D45).

## Hold states (PayPal's own names)

`CREATED` (active hold), `CAPTURED`, `VOIDED`, `DENIED`, plus `EXPIRED` when PayPal says so (saved as read). `NOT_PLACED` is our own: a `PENDING` hold whose authorize was never sent, closed by the cleanup sweep (D80). `PARTIALLY_CAPTURED` only appears in the gap-fill stretch goal, which we are not building.

## Transitions and the PayPal call behind each

| Transition | PayPal call | Rules |
|---|---|---|
| pledge `PENDING_PAY` → `HELD` / `DECLINED` | `POST /v2/checkout/orders` (intent `AUTHORIZE`), then `POST /v2/checkout/orders/{id}/authorize` | Save each call's `PayPal-Request-Id` before sending it (rule 3). Save `order_id` immediately, then `auth_id`, status, `expiration_time`. `DENIED` means declined |
| pledge → `DROPPED` | `POST /v2/payments/authorizations/{id}/void` | Returns 204. Confirm with a `GET` showing `VOIDED` |
| pledge `COUNTED` → `CHARGED` | `POST /v2/payments/authorizations/{id}/capture` with `final_capture: true` | Save the capture's `request_id` first. Afterwards `GET /v2/payments/captures/{id}` and save the fee and net |
| event `NEEDS_ATTENTION` → `REFUNDING` → `REFUNDED` | none for the first step | Refund-all button. Compare-and-set `NEEDS_ATTENTION → REFUNDING` first, so two clicks can't refund twice. `REFUNDED` only once every refund succeeded (D28 a) |
| pledge `CHARGED` → `REFUNDED` | `POST /v2/payments/captures/{id}/refund` | Only from refund-all. One capture at a time, no automatic retries (rule 7). The refund's `PayPal-Request-Id` is saved before the call and two calls with the same ID are never in flight at once. A failed refund is marked `FAILED`; the treasurer's "try again" reuses the same request ID (D28 d) |
| `FAILED` pledge's hold, on refund-all | `GET /v2/payments/authorizations/{id}`, then void if `CREATED` | `CREATED`: void it. `CAPTURED` (D47): not handled automatically; shown to the treasurer and logged as an error (D28 c) |
| event → `EXPIRED` | void every `CREATED` hold | Compare-and-set `OPEN → EXPIRED` first. Then every `HELD` or `PENDING_PAY` pledge with no `CREATED` hold left becomes `DROPPED`; a failed void leaves its pledge `HELD` (D45) |

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
| The sweep finds a hold PayPal already closed (void refused, `GET` shows `VOIDED` or `EXPIRED`) | Save the real status; on a finished event the pledge becomes `DROPPED`. If the `GET` shows `CAPTURED`, the pledge is `FAILED` and an error is logged; the sweep never captures (D80) | `DECISIONS.md` D80 |
| Two requests try the same status change | Compare-and-set: only one wins (E8) | `SYSTEM_DESIGN.md` §4 |
| Settling raises an error | Log it and still serve the page | `SYSTEM_DESIGN.md` §3 |
| At lock, the goal is no longer reached (the invariants say this can't happen) | Charge nobody: void every hold, event `LOCKING → EXPIRED` (F13) | `SYSTEM_DESIGN.md` §5C |
| A capture is refused, times out, or hits a voided hold | Retry once (M2), only if the `GET` shows the hold still `CREATED` (F14), then pledge `FAILED`, event `NEEDS_ATTENTION`. M1 has no retry | `PAYPAL_INTEGRATION.md` §4–5 |
| A capture returns `AUTHORIZATION_ALREADY_CAPTURED`, or the `GET` after a failed capture shows `CAPTURED` | The money moved, but we don't look for the capture: hold `CAPTURED`, pledge `FAILED`, event `NEEDS_ATTENTION`, logged, never retried. Finding it (F5, F6) is in `docs/LATER.md` | `DECISIONS.md` D47, D49 |
| The request running the lock dies partway | After 5 minutes, `settle_due_events` wins a resume compare-and-set (`resume_stuck_lock`) and finishes the lock. It charges only pledges with a saved share and never works out who is counted again. A `PENDING` capture row gets a `GET` first: `CREATED` is sent again with the same saved request ID, `CAPTURED` follows D47. Died before the shares were saved: back to `LAST_CALL` and the normal lock. A hold it can't read keeps the event `CHARGING` until the next resume | `DECISIONS.md` D27, D49, D50, D81 |
| After `NEEDS_ATTENTION` | The only action is refund-all (designed, not tested): the event goes `REFUNDING`, then `REFUNDED` when every refund has succeeded. The new pay link moved to `docs/LATER.md` (D49, D28 b) | `DECISIONS.md` D28, D49 |
| A refund fails | That refund is marked `FAILED` and not retried automatically (rule 7). The event stays `REFUNDING`. The treasurer's page lists each person's name, amount and status (refunded / failed, try again / pending), and "try again" reuses the same request ID (PayPal accepts a retry with the same refund request ID for up to 45 days, read in docs Nov 4 2026) | `DECISIONS.md` D28 d |
| Nobody visits after a deadline | Nothing settles until someone does. After about 3 days, captures may fail | `SYSTEM_DESIGN.md` §3 (known limit) |

## Invariants (the tests should prove these)

1. **Joining never un-counts anyone.** Conditions only ever require someone to be *present*, so adding a pledger can only grow the counted set.
2. **An uncounted pledger leaving never un-counts anyone.** If B is counted, everyone B depends on is also counted. So only counted people matter to counted people.
3. **Once the goal is reached, joining keeps it reached.** Each new pledger adds a max of at least $5.00, but raises the fee-adjusted goal by only about $0.51.
4. **Together, 1–3 mean the board can never flip from "goal reached" back to "short" during last call.**
5. **Each counted pledge is captured at most once** (compare-and-set + saved request IDs + `final_capture: true`).
6. **Every authorization ID in PayPal also exists in our `holds` table**, because we save it before doing anything else. The one gap: an authorize call whose answer never arrives (`PAYPAL_INTEGRATION.md` §5).
