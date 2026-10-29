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
| A13 | Card authorize, then void (server API): `POST /v2/checkout/orders`, intent `AUTHORIZE`, $1.00, sandbox test card 4111…1111 (response showed VISA ending 1111) → 201; order `0WS94888ER0197534` `COMPLETED`; authorization `50694481WY916400J` `CREATED`; void → 204, authorization now `VOIDED`. Oct 25, run by steel hacks. Which sandbox app was not recorded. PayPal Activity row: VERIFIED (Oct 28: ID `50694481WY916400J` matched on the Activity detail page; Authorization, $1.00, Cancelled). Card fields in a real browser: NOT RUN | VERIFIED (server API only; app unverified) | `docs/evidence/A13_card_authorize_void.md`. Not re-run: B1 (last-call-test) and the M1 card checks in the app cover it |

## B. Browser and app (PayPal in the real app)

| ID | Test | Milestone | Status |
|---|---|---|---|
| B1 | **Guest card hold through card fields with intent authorize, in a real browser** (sandbox) | M1 | VERIFIED (spike on localhost, Oct 26: hold `CREATED`, then `VOIDED`). Activity row: VERIFIED (Oct 28: ID `1FV797880C126320B` matched on the Activity detail page; Cancelled there, Voided in the list). In the app on localhost (Oct 28): VERIFIED, hold `CREATED` and its auth ID saved in our database, then voided (`GET`: `VOIDED`); Activity row seen (ID not compared); browser console lines: NOT CHECKED. In the app on the live Render URL: NOT RUN |
| B2 | Decline test card in the browser shows "Card declined", pledge `DECLINED`, no void attempted | M1 | In the app on localhost (Oct 28): VERIFIED, card submit `succeeded`, authorize came back `DENIED`, the screen showed "Card declined", no void attempted. Pledge `DECLINED`: unverified (not read back, because the optional retry reused the pledge right after, D26). Activity: no row for the decline. In the app on the live Render URL: NOT RUN |
| B3 | ACDC is enabled on our sandbox app | M1 | NOT RUN |
| B4 | PayPal-button pledger with intent authorize (stretch, but a must-have if B1 fails by Oct 28, D19) | — | NOT RUN |
| B5 | Full happy path on the live Render URL: create → 3 holds → goal → lock → charges → board shows real net (sandbox) | M1 | NOT RUN |

## C. Money math (`tests/test_money.py`, Malama)

| ID | Test | Status |
|---|---|---|
| C1 | `estimate_fee_cents` matches all 7 sandbox fees | VERIFIED (Oct 27, `tests/test_money.py`) |
| C2 | Goal for $300 at 1, 6, 12, 20 pledgers equals $308.49, $311.03, $314.08, $318.14 (D11, approved Oct 25) | VERIFIED (Oct 27, also the $300 / 4 people hand example: goal $310.01, club gets $300.01 with the fee estimate) |
| C3 | **Net ≥ deposit**: random deposits ($20–$2,000), group sizes 1–40 and random maxes, at least 10,000 cases, never short | VERIFIED with the fee estimate, not real captures (Oct 27, 10,000 cases, seed 3, 0 short). The same cases with the old 0.49 formula: 3,784 short, so the test does catch it |
| C4 | Plan example: goal $100, maxes 15/40/40/40 → 15.00, 28.33, 28.33, 28.34 | VERIFIED (Oct 27) |
| C5 | Odd amounts: shares of $15.37, $28.33, $5.01 have correct estimated fees | VERIFIED against the formula (Oct 27): $15.37 → 89¢ matches the sandbox; $28.33 → $1.22 and $5.01 → 62¢ were worked out by hand, never charged in the sandbox |
| C6 | No share above its max, none below $5, sum = goal (unless the $5 floor applied) | VERIFIED (Oct 27, 10,000 random cases, seed 6, plus a $20 / 40 people floor example) |
| C7 | Same inputs give the same shares every time | VERIFIED (Oct 27, also checks the input list isn't changed) |
| C8 | Goal check and lock use the same functions (one test calls both paths) | VERIFIED for `money.py` only (Oct 27): `goal_is_reached` uses `fee_adjusted_goal_cents`, and when it says reached, the shares add up to exactly that goal. That `lifecycle.py` calls these at the goal check and at lock: NOT RUN (Emmanuel's code) |

## D. Circle rule (`tests/test_conditions.py`, Malama)

| ID | Test | Status |
|---|---|---|
| D1 | Chain: A needs B needs C, C absent, so all drop | VERIFIED (Oct 27, `tests/test_conditions.py`; a one-pass version of the rule fails it) |
| D2 | Mutual circle A↔B, both in | VERIFIED (Oct 27) |
| D3 | Circle plus a dependent (C needs A, A↔B), all in | VERIFIED (Oct 27) |
| D4 | Depends on a name nobody pledged, so it drops | VERIFIED (Oct 27) |
| D5 | Two conditions on one pledge, both needed | VERIFIED (Oct 27) |
| D6 | Names match ignoring case and extra spaces | VERIFIED (Oct 27) |
| D7 | Adding a pledger never un-counts anyone (invariant 1) | VERIFIED for `conditions.py` (Oct 27: 2,000 random groups, seed 7, plus a hand example; an "only if X is not in" rule fails it). In the running app: NOT RUN (wired in at M3) |

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
| E10 | Startup refuses a non-sandbox `PAYPAL_BASE_URL` | VERIFIED (Oct 27, `tests/test_lifecycle.py`). The check function refuses the live, empty and lookalike URLs and accepts the exact sandbox URL. At startup, a separate Python that runs `import app` (what `flask run` and gunicorn do) with the live URL exits with "Refusing to start", and with the sandbox URL it starts. On Render: NOT RUN |

## F. Cleanup and failure path (`tests/test_lifecycle.py`, Emmanuel)

| ID | Test | Status |
|---|---|---|
| F1 | Order ID and auth ID are saved before anything else (simulate a crash right after authorize) | VERIFIED (Oct 27, fake PayPal + Neon test branch, `tests/test_lifecycle.py`). A second connection sees each request ID in `holds` before its call goes out, and the order ID and auth ID still saved after the step right after authorize raises an error. Mutation check: the test fails if the auth ID is saved late or the authorize request ID is saved after the call. With real PayPal: NOT RUN |
| F2 | A stranded `CREATED` hold on a finished event is voided by the sweep | NOT RUN |
| F4 | A refused capture is retried once, then the event goes `NEEDS_ATTENTION` and the other charges stay | NOT RUN |
| F5 | A timeout on capture: `GET` first, no double charge | NOT RUN |
| F6 | `AUTHORIZATION_ALREADY_CAPTURED` is recorded as charged, not as failure | NOT RUN |
| F7 | Refund-all screen states that PayPal keeps fees, and refunds only on click | NOT RUN |
| F8 | "New pay link" goes only to the failed person (waits on D28) | NOT RUN |
| F9 | Kim fails after Ana ("if Kim's in") was charged: flagged on the treasurer view, no automatic refund | NOT RUN |
| F10 | Mock headers can never be sent outside tests | NOT RUN |
| F11 | A hold that comes back after the event left `OPEN`/`LAST_CALL` is voided at once and the pledge is `DROPPED` | VERIFIED (Oct 27, fake PayPal + Neon test branch, `tests/test_lifecycle.py`). The event expires during the authorize call: the hold is voided (void request ID saved first, then a `GET` reads `VOIDED`) and the pledge is `DROPPED`. A second test holds an expiry unsaved while a hold comes back: `mark_held` waits for it, then refuses (it fails without `FOR SHARE`). Against a real lock (step 2.5) and with real PayPal: NOT RUN |
| F12 | A void that doesn't return 204 is checked with a `GET`; if the hold is still `CREATED`, the next sweep voids it | NOT RUN |
| F13 | If the goal isn't reached at lock (should be impossible), nobody is charged and every hold is voided | NOT RUN |

## G. AI reader (`tests/test_ai_parser.py`, Malama)

| ID | Test | Status |
|---|---|---|
| G1 | Validator rejects bad JSON and wrong types, and the parser doesn't invent an amount, cap or condition that's missing from the friend's message | NOT RUN |
| G2 | Model failure shows "please retype" | NOT RUN |
| G3 | **Accuracy on the 50 frozen made-up messages: X/50** (report both scores if the prompt changed) | NOT RUN |

## H. New users (after the Nov 3 freeze, D31)

| ID | Test | Status |
|---|---|---|
| H1 | 3–5 people who haven't used the app pledge on the live link (sandbox). Record where they got stuck, with no names or emails. Timing: NOT RUN until measured, and no timing claims before then | NOT RUN |

## Run log

| Date | ID | Who | Result | Evidence |
|---|---|---|---|---|
| Oct 26 | B1 | Emmanuel (typed the card in a real browser), Claude Code (server, void, checks) | VERIFIED (spike, `spikes/b1_card_fields/`, SDK v6 card fields, sandbox app last-call-test). Activity row: NOT CHECKED | `POST /v2/checkout/orders` body `{"intent": "AUTHORIZE", "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}]}` → 201, order `6Y19708071807635F` `CREATED`. `POST /v2/checkout/orders/6Y19708071807635F/authorize` body `{}` → 201, order `COMPLETED`, authorization `1FV797880C126320B` `CREATED`. Void → 204. `GET` authorization → 200, `VOIDED`. Card: VISA ending 1111. Secrets removed. Full log: `docs/evidence/B1_card_fields_spike.md` |
| Oct 27 | `paypal_client.py` smoke test (no TEST_PLAN ID) | Claude Code, in Emmanuel's session | VERIFIED: server token (asked twice, fetched once), client token, create order, authorize refused on an unapproved order, get authorization. Capture, get capture and void: NOT RUN (they need a real hold, steps 2.4–2.5). Keys from `.env` (sandbox app last-call-test). `PAYPAL_BASE_URL` was set to the sandbox URL on the command line, because the saved `.env` value was still empty | `python -m tests.sandbox_smoke`. `POST /v1/oauth2/token` → 200 twice (one server token, one client token; no token printed). `POST /v2/checkout/orders` $1.00 intent `AUTHORIZE` (PayPal-Request-Id `2ef0cefd-6661-4d07-b51f-b81c9cb3ed65`) → 201, PayPal-Debug-Id `f1961138d5642`, order `3FA86349EU814154U` `CREATED`, never approved, so nothing held. `POST /v2/checkout/orders/3FA86349EU814154U/authorize` (PayPal-Request-Id `633ec041-da6e-4c1d-8d27-a36fcfd79965`) → 422 `UNPROCESSABLE_ENTITY`, issue `ORDER_NOT_APPROVED`, PayPal-Debug-Id `f196113e01ad2`, no authorization in the answer. `GET /v2/payments/authorizations/1FV797880C126320B` (B1's) → 200 `VOIDED`, USD 1.00, PayPal-Debug-Id `f558267c155b0` |
| Oct 28 | B1 (in the app, localhost) | Emmanuel (typed the card in a real browser, read the screen and the PayPal Activity page), Claude Code (ran the server, read the database back) | VERIFIED on localhost: hold `CREATED`, auth ID saved in our database. Activity row: seen, matching name, amount and time (ID not compared). Browser console lines: NOT CHECKED. Live Render URL: NOT RUN | Event 1 on the Neon dev branch, inserted by hand (D35). Made-up pledger "Ana Test", max $5.00, sandbox app last-call-test. Server log (19:08 local): `POST /api/pledges` → 200, `POST /api/orders` → 200, `POST /api/orders/7VT12360ER502464P/authorize` → 200. Database: hold 1, create PayPal-Request-Id `6d0b05bb-32e7-4a08-b04b-2af4e0305c00`, authorize PayPal-Request-Id `54a7d8b1-7268-47f7-8d2a-8141b6877b5c`, order `7VT12360ER502464P`, authorization `0MT88984JM068535K` `CREATED`, $5.00, expires 2026-11-26 23:08:29 UTC; pledge `HELD`; no void sent. Screen (reported by Emmanuel): "Held. You'll pay only your share, at most $5.00, and only if the goal is reached." Activity page (Emmanuel's screenshot): 10/28/26, 7:08 PM · Authorization From · Ana Test · Pending · $5.00 USD · fee $0.00 USD. Card: the 4111…1111 test card was the instruction; which card was typed was not read back. Tokens and keys not printed |
| Oct 28 | B2 (in the app, localhost) | Emmanuel (typed the card in a real browser, read the screen, the console and the PayPal Activity page), Claude Code (ran the server, read the database back) | VERIFIED on localhost: the decline comes back at authorize, not in the browser; "Card declined" shown; no void attempted. Pledge `DECLINED`: unverified (not read back before the retry reused it). Activity: no row for the decline. Live Render URL: NOT RUN | Event 1, made-up pledger "Bo Test", max $5.00. Name on card `CCREJECT-REFUSED`, card `4012888888881881` (the instruction; not read back). Server log (19:25–19:26 local): `POST /api/pledges` → 200, `POST /api/orders` → 200, `POST /api/orders/4ES193114P812571E/authorize` → 200. Database: hold 2, create PayPal-Request-Id `9bc7fdb6-cc69-4201-a6c1-0145912dba20`, authorize PayPal-Request-Id `0da78ae5-ef6d-41d3-b94e-fe3f20528a1d`, order `4ES193114P812571E`, authorization `4DH312972C435991E` `DENIED`, no expiry, no void request ID. Console (Emmanuel): "Card submit: succeeded", then "Authorize answer: DECLINED". Screen (Emmanuel): "Card declined. Nothing was held. Try another card." Activity (Emmanuel's screenshot): no row for the decline. Tokens and keys not printed |
| Oct 28 | Retry after a decline (no TEST_PLAN ID; D26, D32) | Emmanuel (browser), Claude Code (server, database) | VERIFIED on localhost: same page, no reload; only the card fields were retyped. The page saved the same pledge again and the same v6 card-fields session submitted a second time. Hold placed. Activity row seen (ID not compared) | Name on card "Bo Test", card `4111111111111111` (the instruction; not read back). Server log (19:30 local): `POST /api/pledges` → 200, `POST /api/orders` → 200, `POST /api/orders/4K944182CY493301X/authorize` → 200. Database: hold 3 on the same pledge 2, create PayPal-Request-Id `8f256e33-7be0-4d71-a8ed-518ca5ceb35a`, authorize PayPal-Request-Id `2ecdadec-b531-4fb1-90ea-199fd7c60457`, order `4K944182CY493301X`, authorization `3P6535206K455364M` `CREATED`, $5.00, expires 2026-11-26 23:30:20 UTC; pledge `HELD`. Screen (Emmanuel): "Held. You'll pay only your share, at most $5.00, and only if the goal is reached." Activity (Emmanuel's screenshot): 10/28/26, 7:30 PM · Authorization From · Bo Test · Pending · $5.00 USD |
| Oct 28 | Void of the B1 and retry holds (no TEST_PLAN ID) | Claude Code, in Emmanuel's session, at his request | VERIFIED: both holds `VOIDED`. B2's `DENIED` hold was not touched. Activity rows after the void: NOT CHECKED | Through `lifecycle.void_hold` (void request ID saved before each call). Hold 1, authorization `0MT88984JM068535K`: void PayPal-Request-Id `e4e375bf-160c-4905-a8c6-31dce8ab7b2a` → 204, PayPal-Debug-Id `f6576306b2f3b`; `GET` → 200 `VOIDED`, USD 5.00, PayPal-Debug-Id `f2096002b8e5b`. Hold 3, authorization `3P6535206K455364M`: void PayPal-Request-Id `efcc818c-e13e-472d-af66-e0ffcd2c7e00` → 204, PayPal-Debug-Id `f2096007fa03e`; `GET` → 200 `VOIDED`, USD 5.00, PayPal-Debug-Id `f61215852b186`. Database read back: holds 1 and 3 `VOIDED`. Both pledges still say `HELD` (`void_hold` changes only the hold), on the dev branch only |
| Oct 28 | Activity rows for the B1 spike and A13 | Emmanuel (opened each detail page), Claude Code (compared the IDs in his screenshots) | VERIFIED: both IDs matched | B1 spike: Oct 26, 2026, 9:28:49 PM EDT, Authorization, ID `1FV797880C126320B`, $1.00, status Cancelled (the list shows Voided), authorization expiration Nov 24, 2026. A13: Oct 25, 2026, 11:28:21 PM EDT, Authorization, ID `50694481WY916400J`, $1.00, status Cancelled, authorization expiration Nov 23, 2026 |
