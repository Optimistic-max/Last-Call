# Claims table

Every claim the README, video or Devpost description makes must appear here with its evidence. A claim may never be stronger than its status in `docs/TEST_PLAN.md`. Update both together.

| # | Claim | Status | Evidence / test |
|---|---|---|---|
| 1 | Each person's max is held, and only their share is charged. PayPal closes the rest of the hold | VERIFIED (API) | A1, A2 |
| 2 | A hold can be cancelled even after a partial charge | VERIFIED (API) | A7 |
| 3 | A retried charge never charges twice | VERIFIED (API), app NOT RUN | A3, E8, F5 |
| 4 | The treasurer's net comes from PayPal's own fee numbers | VERIFIED (sandbox fees), app NOT RUN | A4, B5 |
| 5 | Refund-all returns everyone's share, but PayPal keeps its fees | VERIFIED (API) | A5, F7 |
| 6 | A declined card at checkout is caught and nothing is held | VERIFIED (API), browser NOT RUN | A9, B2 |
| 7 | A failed charge at lock marks the event "needs attention" | SIMULATED (mock), app NOT RUN | A10, F4 |
| 8 | Pledgers can pay by card with no PayPal account | Only a hold and void through browser card fields are VERIFIED (spike on localhost, Oct 26: [`docs/evidence/B1_card_fields_spike.md`](evidence/B1_card_fields_spike.md)). Activity row: NOT CHECKED. Charging a card-fields hold: NOT RUN. In the app on the live Render URL: NOT RUN. Server API only: VERIFIED Oct 25 (A13, app unverified), see the notes below | B1, A13 |
| 9 | Nobody is charged unless the goal is reached | NOT RUN | E5, B5 |
| 10 | The club receives at least the full deposit after fees | NOT RUN in app. Formula SIMULATED (200,000 random events, 0 short: `docs/evidence/goal_formula_check.py`) | C3, B5 |
| 11 | "Only if Jay's in" pledges, including circles, work | NOT RUN | D1–D7 |
| 12 | Stranded holds are cleaned up automatically | NOT RUN | F2 |
| 13 | AI reading accuracy: X/50 on 50 made-up test messages | NOT RUN | G3 |
| 14 | Holds stay valid for the event (48-hour cap inside PayPal's 3-day honor period) | read in docs ([PayPal authorization guide](https://developer.paypal.com/docs/checkout/standard/customize/authorization/), Oct 26: 3-day honor period, valid 29 days) | D05 |
| 15 | The PayPal dashboard can disagree with the API, so our database plus API `GET` calls are the record, not the dashboard | VERIFIED (the disagreement) | A12 |

## Evidence notes

**A13 (Oct 25, run by steel hacks; which sandbox app was not recorded, so the app is unverified):** `POST /v2/checkout/orders`, intent `AUTHORIZE`, $1.00, sandbox test card 4111…1111 (response showed VISA ending 1111) → 201; order `0WS94888ER0197534` `COMPLETED`; authorization `50694481WY916400J` `CREATED`; void → 204, authorization now `VOIDED`. **VERIFIED (server API only).** PayPal Activity row: NOT CHECKED. Card fields in a real browser: **NOT RUN**. Record: `docs/evidence/A13_card_authorize_void.md`. Not re-run (Emmanuel, Oct 27): B1 on last-call-test and the M1 card checks in the app cover it. This doesn't upgrade claim 8, because the app takes cards only through PayPal's card fields (B1).

**B1 (sandbox app last-call-test, Oct 26, spike on localhost):** the sandbox test card was typed into PayPal's v6 card fields in a real browser. Order `6Y19708071807635F` (intent `AUTHORIZE`) → authorization `1FV797880C126320B` `CREATED` → void 204 → `VOIDED`. **VERIFIED: the hold and the void only.** PayPal Activity row: NOT CHECKED. Charging a card-fields hold: NOT RUN. In the app on the live Render URL: NOT RUN. Record: [`docs/evidence/B1_card_fields_spike.md`](evidence/B1_card_fields_spike.md).

## Wording rules

| Say | Don't say |
|---|---|
| "PayPal closes the rest of the hold" | "released instantly" |
| "we keep deadlines inside the 3-day honor period" | "reauthorization doesn't work" |
| "designed, not tested" | an untested feature described as working |
| "simulated" for a capture decline | "we tested real capture declines" |
| "first load may take up to a minute (free hosting)" | — |
| "everything runs in PayPal's sandbox" | anything implying real money |
