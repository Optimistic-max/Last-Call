# Test plan

**Rule:** change a status only after the test has actually run and you saw the result. The README claims (`docs/CLAIMS.md`) may never be stronger than this file.

Statuses: `VERIFIED` · `read in docs` · `NOT RUN` · `SIMULATED` · `designed, not tested` · `NOT CHECKED` (the test ran, but the dashboard row wasn't checked).

## How we test without real PayPal

- `money.py` and `conditions.py` tests use plain numbers. No database, no PayPal.
- `lifecycle.py` tests use the **test database** (`TEST_DATABASE_URL`, a Neon `test` branch) and a **fake PayPal**: a small module with the same function names as `paypal_client.py` that records every call and returns whatever the test tells it to (`CREATED`, `DENIED`, `TRANSACTION_REFUSED`, a timeout). Tests pass it in instead of the real client.
- Time is passed in as `now`, so a test can jump to "47 hours later" instantly.
- A few **manual sandbox checks** (marked "sandbox" below) use the real sandbox and are run by hand, with results logged in this file (date, IDs, who ran it).

## A. PayPal behavior (sandbox API, done before any app code)

| ID | Test | Status | Evidence |
|---|---|---|---|
| A1 | Hold, then charge or cancel | VERIFIED | see `docs/PAYPAL_INTEGRATION.md` §7 |
| A2 | `final_capture: true` closes the leftover (extra $1 capture rejected) | VERIFIED | auth `2GE429364G285520D` |
| A3 | Same `PayPal-Request-Id` returns the same capture | VERIFIED | capture `3BE29157T9509474D` |
| A4 | Fees match 2.59% + $0.49 on 7 amounts | VERIFIED (sandbox only) | `MONEY_RULES.md` §2 |
| A5 | Refund returns the share, PayPal keeps the fee | VERIFIED | capture `4A421246NB729070S` |
| A6 | Reauthorize in the first 3 days is rejected | VERIFIED | `REAUTHORIZATION_TOO_SOON` |
| A7 | Void after a partial capture | VERIFIED | auth `3HR288981H342254V` |
| A8 | A second capture on one hold pays its own $0.49 | VERIFIED | auth `0XX12917R7005063Y` |
| A9 | Decline at checkout (test card) returns 201 + `DENIED` | VERIFIED (API only) | 3 auths |
| A10 | Capture refused via mock: 422, hold stays `CREATED` | SIMULATED | — |
| A11 | Retry after a refused capture succeeds, one fee | VERIFIED (refusal simulated) | auth `9HL19283R07063645` |
| A12 | The dashboard can disagree with the API | VERIFIED | `PAYPAL_INTEGRATION.md` |
| A13 | Card authorize, then void (server API): `POST /v2/checkout/orders`, intent `AUTHORIZE`, $1.00, sandbox test card 4111…1111 (response showed VISA ending 1111) → 201; order `0WS94888ER0197534` `COMPLETED`; authorization `50694481WY916400J` `CREATED`; void → 204, authorization now `VOIDED`. Sandbox **test app**, Oct 25, run by steel hacks. PayPal Activity row: NOT CHECKED. Card fields in a real browser: NOT RUN | VERIFIED (server API only) | `docs/evidence/A13_card_authorize_void.md`. Repeat on the main app (`PAYPAL_INTEGRATION.md` §7) |

## B. Browser and app (PayPal in the real app)

| ID | Test | Milestone | Status |
|---|---|---|---|
| B1 | **Guest card hold through card fields with intent authorize, in a real browser** (sandbox) | M1 | VERIFIED (spike on localhost, Oct 26: hold `CREATED`, then `VOIDED`). Activity row: NOT CHECKED. In the app on the live Render URL: NOT RUN |
| B2 | Decline test card in the browser shows "Card declined", pledge `DECLINED`, no void attempted | M1 | NOT RUN |
| B3 | ACDC is enabled on our sandbox app | M1 | NOT RUN |
| B4 | PayPal-button pledger with intent authorize (stretch, but a must-have if B1 fails by Oct 28, D19) | — | NOT RUN |
| B5 | Full happy path on the live Render URL: create → 3 holds → goal → lock → charges → board shows real net (sandbox) | M1 | NOT RUN |

## C. Money math (`tests/test_money.py`, Malama)

| ID | Test | Status |
|---|---|---|
| C1 | `estimate_fee_cents` matches all 7 sandbox fees | NOT RUN |
| C2 | Goal for $300 at 1, 6, 12, 20 pledgers equals $308.49, $311.03, $314.08, $318.14 (D11, approved Oct 25) | NOT RUN |
| C3 | **Net ≥ deposit**: random deposits ($20–$2,000), group sizes 1–40 and random maxes, at least 10,000 cases, never short | NOT RUN |
| C4 | Plan example: goal $100, maxes 15/40/40/40 → 15.00, 28.33, 28.33, 28.34 | NOT RUN |
| C5 | Odd amounts: shares of $15.37, $28.33, $5.01 have correct estimated fees | NOT RUN |
| C6 | No share above its max, none below $5, sum = goal (unless the $5 floor applied) | NOT RUN |
| C7 | Same inputs give the same shares every time | NOT RUN |
| C8 | Goal check and lock use the same functions (one test calls both paths) | NOT RUN |

## D. Circle rule (`tests/test_conditions.py`, Malama)

| ID | Test | Status |
|---|---|---|
| D1 | Chain: A needs B needs C, C absent, so all drop | NOT RUN |
| D2 | Mutual circle A↔B, both in | NOT RUN |
| D3 | Circle plus a dependent (C needs A, A↔B), all in | NOT RUN |
| D4 | Depends on a name nobody pledged, so it drops | NOT RUN |
| D5 | Two conditions on one pledge, both needed | NOT RUN |
| D6 | Names match ignoring case and extra spaces | NOT RUN |
| D7 | Adding a pledger never un-counts anyone (invariant 1) | NOT RUN |

## E. Timing and lifecycle (`tests/test_lifecycle.py`, Emmanuel, fake PayPal)

| ID | Test | Status |
|---|---|---|
| E1 | Goal at hour 10 gives a full hour of last call | NOT RUN |
| E2 | Goal at hour 47 ends last call at hour 48 | NOT RUN |
| E3 | A counted pledger can't leave during last call | NOT RUN |
| E4 | Joining during last call lowers shares | NOT RUN |
| E5 | Missed goal voids every hold, nobody charged | NOT RUN |
| E6 | Leaving before last call voids that hold | NOT RUN |
| E7 | **Settle on wake:** deadline passed while "asleep", the next request settles it (formerly "test 28", must pass before submission) | NOT RUN |
| E8 | **Two requests settle at the same moment, so only one charges** (compare-and-set) | NOT RUN |
| E9 | Demo mode uses minute timers and shows the badge | NOT RUN |
| E10 | Startup refuses a non-sandbox `PAYPAL_BASE_URL` | NOT RUN |

## F. Cleanup and failure path (`tests/test_lifecycle.py`, Emmanuel)

| ID | Test | Status |
|---|---|---|
| F1 | Order ID and auth ID are saved before anything else (simulate a crash right after authorize) | NOT RUN |
| F2 | A stranded `CREATED` hold on a finished event is voided by the sweep | NOT RUN |
| F4 | A refused capture is retried once, then the event goes `NEEDS_ATTENTION` and the other charges stay | NOT RUN |
| F5 | A timeout on capture: `GET` first, no double charge | NOT RUN |
| F6 | `AUTHORIZATION_ALREADY_CAPTURED` is recorded as charged, not as failure | NOT RUN |
| F7 | Refund-all screen states that PayPal keeps fees, and refunds only on click | NOT RUN |
| F8 | "New pay link" goes only to the failed person (waits on D28) | NOT RUN |
| F9 | Kim fails after Ana ("if Kim's in") was charged: flagged on the treasurer view, no automatic refund | NOT RUN |
| F10 | Mock headers can never be sent outside tests | NOT RUN |
| F11 | A hold that comes back after the event left `OPEN`/`LAST_CALL` is voided at once and the pledge is `DROPPED` | NOT RUN |
| F12 | A void that doesn't return 204 is checked with a `GET`; if the hold is still `CREATED`, the next sweep voids it | NOT RUN |
| F13 | If the goal isn't reached at lock (should be impossible), nobody is charged and every hold is voided | NOT RUN |

## G. AI reader (`tests/test_ai_parser.py`, Malama)

| ID | Test | Status |
|---|---|---|
| G1 | Validator rejects bad JSON, wrong types and invented source lines | NOT RUN |
| G2 | Model failure shows "please retype" | NOT RUN |
| G3 | **Accuracy on the 50 frozen made-up messages: X/50** (report both scores if the prompt changed) | NOT RUN |

## Run log

| Date | ID | Who | Result | Evidence |
|---|---|---|---|---|
| Oct 26 | B1 | Emmanuel (typed the card in a real browser), Claude Code (server, void, checks) | VERIFIED (spike, `spikes/b1_card_fields/`, SDK v6 card fields, sandbox app last-call-test). Activity row: NOT CHECKED | `POST /v2/checkout/orders` body `{"intent": "AUTHORIZE", "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}]}` → 201, order `6Y19708071807635F` `CREATED`. `POST /v2/checkout/orders/6Y19708071807635F/authorize` body `{}` → 201, order `COMPLETED`, authorization `1FV797880C126320B` `CREATED`. Void → 204. `GET` authorization → 200, `VOIDED`. Card: VISA ending 1111. Secrets removed. Full log: `docs/evidence/B1_card_fields_spike.md` |
