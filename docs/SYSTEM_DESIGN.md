# System design

## 1. The big picture

```
 Pledger's phone / Treasurer's laptop
 ┌──────────────────────────────────────────┐
 │ Jinja pages + plain JS                   │
 │ PayPal card fields (iframes from PayPal) │──── card details go straight to PayPal,
 └───────────────┬──────────────────────────┘     never through our server
                 │ HTTPS
 ┌───────────────▼──────────────────────────┐
 │ Flask app on Render (free web service)   │
 │                                          │
 │  app.py ─┬─ lifecycle.py ── paypal_client.py ───► PayPal sandbox REST API
 │          ├─ money.py      (pure math)    │
 │          ├─ conditions.py (pure rule)    │
 │          ├─ ai_parser.py ────────────────┼──────► AI model API
 │          └─ db.py ───────────────────────┼──────► Neon Postgres (free)
 └──────────────────────────────────────────┘
```

**Rule of thumb:** `money.py` and `conditions.py` know nothing about the database, PayPal or the clock. `paypal_client.py` knows nothing about events or shares. `lifecycle.py` is the only place that connects the pieces.

## 2. Hosting facts that shape the design

"Read in docs" means someone read the provider's page on that date. It is not a test we ran. Free tiers change, so **Malama re-reads each source on the day she sets up the service (M0)** and updates the date.

| Fact | Status | Source (date read) | What it means for us |
|---|---|---|---|
| Render's free web service spins down after 15 minutes without traffic | Read in docs | [Render free tier](https://docs.render.com/free) (Oct 16) | First visit can take up to a minute. Nothing runs on a timer while asleep. |
| Render's free Postgres expires 30 days after creation (then 14 days' grace) | Read in docs | [Render free tier](https://docs.render.com/free), [changelog](https://render.com/changelog/free-postgresql-instances-now-expire-after-30-days-previously-90) (Oct 16) | We do **not** use it. It would die during judging (ends Dec 15). |
| Supabase free projects pause after a week idle | Read in third-party summaries, not Supabase's own page | [summary](https://automationatlas.io/answers/supabase-free-tier-limits-2026/) (Oct 16) | We do **not** use it. |
| Neon free: compute suspends after 5 minutes idle, data stays, wakes on connect. Free plan is permanent | Read in docs | [Neon free plan limits](https://neon.com/faqs/free-plan-limits-and-quotas), [Neon plans](https://neon.com/2024-plan-updates) (Oct 16) | The first connection after idle may be slow or fail once. `db.py` retries the first connection once. |
| Neon free plan includes 10 branches per project | Read in docs (Neon's pages disagree on how many *projects* are free, 10 or 100; we only need 1) | same as above (Oct 16) | Use a separate `test` branch for `TEST_DATABASE_URL`. |
| The app must stay live and testable until judging ends (Dec 15) | Read in official rules | [rules](https://paypalaihackathon.devpost.com/rules) (Oct 19) | Check the demo link weekly through Dec 15. |

## 3. Settle-on-wake (why there is no timer)

Because the server sleeps, deadlines are checked **whenever any request arrives**:

```python
@app.before_request
def settle_anything_due():
    lifecycle.settle_due_events(now=utc_now())
```

`settle_due_events(now)` looks for events where:
- status is `OPEN` and `now >= hard_deadline`, so it expires the event and voids every hold, or
- status is `LAST_CALL` and `now >= last_call_ends`, so it locks and charges, or
- status is `LOCKING` or `CHARGING` and `lock_started_at` is more than 5 minutes old, so it resumes a lock that died halfway (D27).

It also runs the cleanup sweep (void any hold that is still open on a finished event).

If settling raises an error, catch it, log it (no secrets) and still serve the page, so one PayPal problem can't take down every page.

**Known limit (be honest about it):** if nobody visits the app after a deadline, nothing settles until someone does. PayPal's honor period for a hold is 3 days, so an event left unvisited for more than about 3 days after its deadline may fail to capture. For the demo this never matters (we view the board). For real use, an optional free external pinger hitting `/health` every 10 minutes would fix it. That idea is `unverified`: check Render's monthly free hours and the pinger's terms first.

## 4. Compare-and-set: how we guarantee "charged once"

Two requests can arrive at the same moment and both see "last call is over". If both started charging, people could be charged twice. We prevent that in the database:

```sql
UPDATE events
SET status = 'LOCKING'
WHERE id = %s AND status = 'LAST_CALL';
```

Only the request whose `UPDATE` changed exactly **1 row** continues to `lock_and_charge()`. The other sees 0 rows changed and does nothing. The same pattern guards `OPEN → EXPIRED`, `OPEN → LAST_CALL` and the resume of a stuck lock (D27).

There are two more layers of protection:
- each capture has its own saved `PayPal-Request-Id`, so a retried request returns the same capture instead of a new one (VERIFIED in sandbox), and
- every capture uses `final_capture: true`, so PayPal rejects a second capture on the same hold with `AUTHORIZATION_ALREADY_CAPTURED` (VERIFIED in sandbox).

## 5. The main flows

### A. Pledge and hold (milestone M1, the riskiest step)

```
Browser                      Flask                         PayPal               DB
  │ name, email, pledge text   │                               │                   │
  │ "Check" ──────────────────►│ POST /api/pledges/parse       │                   │
  │                            │ ai_parser + AI model          │                   │
  │◄──── suggestion ───────────│ (nothing saved)               │                   │
  │ fix + confirm ────────────►│ POST /api/pledges             │                   │
  │                            │ save pledge (PENDING_PAY) ───────────────────────►│
  │◄──── pledger_token ────────│                               │                   │
  │ click "Hold my max" ──────►│ POST /api/orders              │                   │
  │                            │ save hold row + create request ID ───────────────►│
  │                            │ create order intent=AUTHORIZE►│                   │
  │                            │ save order_id ───────────────────────────────────►│
  │◄──── order_id ─────────────│                              │                   │
  │ card fields submit ───────────────────────────────────────►│ (card data)       │
  │ submit succeeded ─────────►│ POST /api/orders/<id>/authorize                   │
  │                            │ save authorize request ID ───────────────────────►│
  │                            │ authorize order ─────────────►│                   │
  │                            │◄──── auth_id + status ───────│                   │
  │                            │ save auth_id + status ───────────────────────────►│
  │                            │ status CREATED → pledge HELD                      │
  │                            │ status DENIED  → pledge DECLINED (nothing to void)│
  │◄──── "Held" or "Card declined"                            │                   │
```

D31: `POST /api/pledges/parse` sends the friend's message to the AI and returns a suggested amount, cap and condition; it saves nothing. `POST /api/pledges` creates the pledge row (`PENDING_PAY`) from what the friend confirmed and returns the pledge's private `pledger_token`. A second confirm with the same name follows D26: it reuses that person's unpaid pledge and is refused if they already hold. In M1, before the AI is wired in (M4), the page skips the parse and confirms the typed name and max directly.

From `POST /api/orders` on, the B1 order/authorize flow is unchanged. The page sends the `pledger_token`, and the server creates the hold row and order for that pledge. A retry after "Card declined" creates a new hold row and order for the same pledge. `POST /api/pledges` and `POST /api/orders` refuse unless the event is `OPEN` or `LAST_CALL`. If the event has left those states by the time the authorization comes back, void the hold at once, mark the pledge `DROPPED` and show the "pledging closed" message (`UI_DESIGN.md` §4). The cleanup sweep catches any hold that slips past this check.

### B. Goal check (every time a hold succeeds, and on wake)

1. Load all `HELD`/`COUNTED` pledges and their conditions.
2. `conditions.counted_pledges(...)` returns who is counted (the circle rule).
3. `n = number counted`, `goal = money.fee_adjusted_goal(deposit, n)`.
4. If the sum of counted maxes is at least `goal` and the event is `OPEN`: compare-and-set `OPEN → LAST_CALL`, set `last_call_ends = min(now + 1 hour, hard_deadline)`.

### C. Lock and charge (`lifecycle.lock_and_charge`, the only capture path)

1. Win compare-and-set `LAST_CALL → LOCKING`.
2. Recompute who is counted, the goal and every share. **Save every share** (`pledges.share_cents`) and save `events.goal_cents`. If the goal is no longer reached (the invariants say this can't happen, so it means a bug), charge nobody: void every hold and move the event `LOCKING → EXPIRED`.
3. Void holds of anyone not counted (their condition never came true). Any pledge still `PENDING_PAY` becomes `DROPPED` (no hold, nothing to void).
4. Set status `CHARGING`. For each counted pledge, one at a time:
   - create a capture row with a new `request_id`, status `PENDING`, attempt 1. **Save it first.**
   - call capture with `final_capture: true`.
   - on success, `GET` the capture, save `capture_id`, `fee_cents`, `net_cents`, and mark the pledge `CHARGED`.
   - on failure, retry once (see section 6), then mark the pledge `FAILED`.
5. All charged means `SETTLED`. Any failed means `NEEDS_ATTENTION`. Keep the successful charges.

### D. Expire and cleanup

- Compare-and-set `OPEN → EXPIRED`, then void every `CREATED` hold. Unpaid `PENDING_PAY` pledges become `DROPPED`.
- Cleanup sweep (runs on wake): void any hold still `CREATED` whose pledge is `DROPPED`, whose event is `SETTLED`, `EXPIRED` or `NEEDS_ATTENTION` (for pledges not counted), or whose hold is close to `expires_at`.

### E. AI reading (milestone M4)

D31: a friend types their pledge on the pledge page → `ai_parser.parse_pledge(text)` → JSON is validated by plain code (`validate_pledge`) → the result stays only in the page → the friend fixes and confirms the amount, cap and condition → the pledge row is created at confirm, in `PENDING_PAY` → the card step, which is the B1 flow, unchanged. A message the AI can't read becomes "please retype", and the friend can fill in the fields by hand. The treasurer chat paste is deferred (`docs/LATER.md`).

## 6. Failure handling at capture

The full list of PayPal responses and what we do lives in one place: `PAYPAL_INTEGRATION.md` §4 (status checks) and §5 (unknown results). In short: `COMPLETED` means `CHARGED`. `AUTHORIZATION_ALREADY_CAPTURED` isn't an error: find and save the existing capture. Refused or unknown: `GET` the authorization, then retry **once** with a **new** saved request ID. Still failing: pledge `FAILED`, event `NEEDS_ATTENTION`, no automatic refund. A refused attempt costs no fee (VERIFIED, refusal simulated). For every other way a step can fail, see the "Failure branches" table in `STATE_MACHINE.md`.

## 7. Environments

| | Local | Production (demo) |
|---|---|---|
| App | `flask run` | Render free web service, `gunicorn app:app` |
| Database | Neon `dev` branch | Neon `main` branch |
| Tests | Neon `test` branch (`TEST_DATABASE_URL`) + fake PayPal | n/a |
| PayPal | sandbox app keys in `.env` | same sandbox app, keys in Render settings |

## 8. Pages and routes (MVP set)

| Route | Who | Purpose |
|---|---|---|
| `GET /` | treasurer | create-event form |
| `POST /events` | treasurer | create event, redirect to admin page |
| `GET /admin/<admin_token>` | treasurer | treasurer view: open event, needs-attention actions |
| `POST /admin/<admin_token>/open` | treasurer | DRAFT → OPEN |
| `GET /e/<event_id>` | everyone | public board |
| `GET /e/<event_id>/board.json` | board JS | board data for the 10-second refresh (amounts pre-formatted) |
| `GET /e/<event_id>/pledge` | pledger | pledge form + card fields |
| `GET /api/client-token` | browser JS | browser-safe client token for the SDK v6 card fields (D16). Never logged |
| `POST /api/pledges/parse` | browser JS | D31: the AI reads one friend's message and returns a suggested amount, cap and condition. Saves nothing |
| `POST /api/pledges` | browser JS | D31: creates the pledge row (`PENDING_PAY`) from what the friend confirmed and returns its private `pledger_token`. D26 rules apply |
| `POST /api/orders` | browser JS | create the hold row + PayPal order (intent AUTHORIZE) for a confirmed pledge, sent with its `pledger_token` (D31; before D31 this route also created the pledge) |
| `POST /api/orders/<order_id>/authorize` | browser JS | authorize, save, report HELD or DECLINED |
| `POST /p/<pledger_token>/leave` | pledger | "actually I'm out" (M2) |
| `POST /admin/<admin_token>/refund-all` | treasurer | refund-all (M2) |
| `GET /health` | pinger, Render | returns `ok`, wakes the app |

The treasurer has no account. Their private `admin_token` link is the login. Each pledger gets a private `pledger_token` link for "I'm out". Both are long random strings (`secrets.token_urlsafe(24)`).
