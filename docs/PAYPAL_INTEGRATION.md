# PayPal integration

Owner: **Emmanuel**. All of this lives in `paypal_client.py`. That file only makes HTTP calls and returns plain Python dicts. It knows nothing about events, shares or the database.

## 1. Basics

- **Base URL:** `https://api-m.sandbox.paypal.com` (the app refuses to start with anything else).
- **Access token:** `POST /v1/oauth2/token` with HTTP Basic auth (client ID + secret) and body `grant_type=client_credentials`. Cache the token until shortly before it expires.
- **Every write call** sends `PayPal-Request-Id: <id saved in our DB first>`.
- **Timeouts:** every request uses `timeout=20` seconds. A timeout means "result unknown". See section 5.

## 2. The calls we use

| Purpose | Call | Body / notes | Status |
|---|---|---|---|
| Create a hold order | `POST /v2/checkout/orders` | see 2a | VERIFIED (API) |
| Authorize after the card is approved | `POST /v2/checkout/orders/{order_id}/authorize` | returns `purchase_units[0].payments.authorizations[0]` with `id`, `status`, `expiration_time` | VERIFIED (API) |
| Read a hold | `GET /v2/payments/authorizations/{auth_id}` | `status`: `CREATED`, `CAPTURED`, `VOIDED`, `DENIED` | VERIFIED |
| Charge a share | `POST /v2/payments/authorizations/{auth_id}/capture` | see 2b | VERIFIED |
| Read a charge's real fee | `GET /v2/payments/captures/{capture_id}` | `seller_receivable_breakdown.paypal_fee.value` and `.net_amount.value` | VERIFIED |
| Cancel a hold | `POST /v2/payments/authorizations/{auth_id}/void` | returns 204 with no body. Confirm with a `GET` | VERIFIED |
| Refund a charge | `POST /v2/payments/captures/{capture_id}/refund` | empty body means a full refund. PayPal keeps its fee | VERIFIED |

### 2a. Create order body

```json
{
  "intent": "AUTHORIZE",
  "purchase_units": [
    {
      "reference_id": "pledge-123",
      "custom_id": "pledge-123",
      "amount": { "currency_code": "USD", "value": "40.00" }
    }
  ]
}
```

`value` is a string with exactly two decimals. Convert from cents with one helper (`cents_to_paypal_string(4000)` → `"40.00"`). Never format money anywhere else.

### 2b. Capture body

```json
{
  "amount": { "currency_code": "USD", "value": "25.00" },
  "final_capture": true
}
```

`final_capture: true` makes PayPal close the rest of the hold. A later capture on the same hold is rejected with `AUTHORIZATION_ALREADY_CAPTURED` (VERIFIED: $40 hold, $25 capture, $1 extra capture rejected).

## 3. Browser card fields (milestone M1, the riskiest unknown)

- **SDK v6 (D16).** The page gets a browser-safe client token from our server (`GET /api/client-token`, which asks PayPal's `/v1/oauth2/token` with `response_type=client_token`) and starts PayPal's JavaScript SDK v6 with the `card-fields` component. The page sets no intent: only our server's create-order call sets intent **`AUTHORIZE`**. The token is never logged, and the secret never leaves the server.
- When the pledger presses the button, the page calls our `POST /api/orders`, which creates the order on the server and returns its ID. The page then sends the card to PayPal with `session.submit(orderId)`.
- Only if the submit result is `succeeded` does the page call our `POST /api/orders/<order_id>/authorize`, which authorizes on the server, saves the result and returns `HELD` or `DECLINED`.

**Already known:** the server half (create an order with intent `AUTHORIZE`, then void) works with a direct card payment on the sandbox test app (§7, Oct 25). Browser card fields placed a hold that was then voided, in a spike on localhost (B1, Oct 26, VERIFIED: [`docs/evidence/B1_card_fields_spike.md`](evidence/B1_card_fields_spike.md)). In the app on the live Render URL: `NOT RUN`.

**Before writing it, check three things and record the answers in `docs/DECISIONS.md`:**
1. **Which SDK version.** Answered: SDK v6 card fields (D16, approved Oct 26). Neither PayPal guide shows card fields with intent `AUTHORIZE`; the B1 spike placed and voided one ([`docs/evidence/B1_card_fields_spike.md`](evidence/B1_card_fields_spike.md)).
2. **Advanced Credit and Debit Card Payments is enabled** for the sandbox app: Developer Dashboard → Apps & Credentials → Sandbox → your app → Features → Accept payments (`not yet checked`).
3. **What the card fields do on a decline**, using the decline test card in section 6.

**If card fields can't make a hold in a real browser by the end of Oct 28,** tell the whole team that day and decide together. The approved default (D19) is to switch to the PayPal button with intent authorize (test B4, NOT RUN), which then becomes a must-have. PayPal's standard-checkout authorization page says to add `&intent=authorize` to the JavaScript SDK script tag (read in docs, [authorization guide](https://developer.paypal.com/docs/checkout/standard/customize/authorization/), Oct 26).

## 4. Status checks (never trust the HTTP code alone)

| Response | Meaning | Our action |
|---|---|---|
| authorize: 201 with authorization `CREATED` | hold placed | pledge `HELD` (then the goal check runs) |
| authorize: 201 with authorization `DENIED` | card declined | pledge `DECLINED`. Nothing to void. Show "Card declined" |
| authorize: anything else (another status, an error) | not held | Save any IDs that came back, leave the pledge `PENDING_PAY`, show "Something went wrong. Nothing was charged." If an `auth_id` came back, void it. A timeout: see §5 |
| capture: 201 `COMPLETED` | charged | `GET` the capture, save fee + net, pledge `CHARGED` |
| capture: 422 `AUTHORIZATION_ALREADY_CAPTURED` | already charged earlier | `GET` the authorization, find and save the existing capture |
| capture: 422 `AUTHORIZATION_VOIDED` | hold was cancelled | pledge `FAILED`, event `NEEDS_ATTENTION` |
| capture: 422 `TRANSACTION_REFUSED` | refused (we've only seen it via the mock) | retry once with a new saved request ID |
| capture: anything else (another status or error code, a 5xx, a timeout) | result unknown | follow §5 |
| void: 204 | cancelled | `GET` to confirm `VOIDED` |
| void: anything other than 204 | not confirmed | `GET` the authorization and save PayPal's status. If it is still `CREATED`, the cleanup sweep tries again on the next wake |
| reauthorize in the first 3 days | `REAUTHORIZATION_TOO_SOON` | we never reauthorize. Deadlines stay inside the 3-day honor period |

## 5. Unknown results (timeouts)

If a capture call times out (or returns anything not in the table above), **don't guess**:
1. `GET` the authorization.
2. If `CAPTURED`: find the capture, save it, done.
3. If still `CREATED`: retry once with a new saved request ID (attempt 2). PayPal itself rejects a second capture on a fully captured hold, so this can't double-charge.
4. Anything else: pledge `FAILED`, event `NEEDS_ATTENTION`.

If an **authorize** call times out:
1. Retry once with the same saved authorize request ID (rule 4). Whether PayPal returns the same authorization on that retry is `unverified`: only capture retries were tested (A3).
2. If it still fails, show "Something went wrong. Nothing was charged." and leave the hold `PENDING`.
3. This is the one gap in "every authorization ID is in our database" (`STATE_MACHINE.md` invariant 6): PayPal may have placed a hold whose ID we never saw. We never capture it, so nobody is charged, but the pledger's card may show a pending hold until PayPal expires it (29 days). A possible fix, `unverified`: `GET /v2/checkout/orders/{order_id}` and look for the authorization.

## 6. Testing tools (sandbox only)

| Tool | How | What it gives | Status |
|---|---|---|---|
| Decline at checkout | card `4012888888881881`, cardholder name `CCREJECT-REFUSED` (also `CCREJECT-IF`, `CCREJECT-BANK_ERROR`) | 201 with authorization `DENIED` | VERIFIED (API), browser `NOT RUN` |
| Refuse a capture | header `PayPal-Mock-Response: {"mock_application_codes":"TRANSACTION_REFUSED"}` on the capture call | 422, hold stays `CREATED` | SIMULATED |
| `INSTRUMENT_DECLINED` on capture | same header | empty 403 (reason `unverified`). Don't rely on it | — |
| Normal test card | `4111111111111111` | normal hold | VERIFIED |

The mock header must **never** be sent outside tests. Put it behind a `test_mock_code` argument that defaults to `None`.

## 7. Evidence on file (sandbox, Oct 15–16 and Oct 25)

Logs `pp_verify*.log`, `pp_recheck.log`, `pp_void10.log` and `pp_retry.log` live outside the repo with steel hacks (an assistant bot, see `TEAM.md`). Key IDs:

- Partial capture closes the hold: auth `2GE429364G285520D`, capture `3BE29157T9509474D` (idempotent retry).
- Void after partial: auth `3HR288981H342254V`.
- Second capture pays its own fee: auth `0XX12917R7005063Y`.
- Refund keeps the fee: capture `4A421246NB729070S`.
- Real declines: auths `2FL36771CJ213463E`, `5ET87355255867257`, `0KJ691043N1833446`.
- Retry after refused capture: auth `9HL19283R07063645`, capture `89G27304WY275041M`.
- **A13 (sandbox test app, Oct 25, run by steel hacks):** `POST /v2/checkout/orders`, intent `AUTHORIZE`, $1.00, sandbox test card 4111…1111 (response showed VISA ending 1111) → 201; order `0WS94888ER0197534` `COMPLETED`; authorization `50694481WY916400J` `CREATED`; void → 204, authorization now `VOIDED`. **VERIFIED (server API only). Card fields in a real browser: NOT RUN.** PayPal Activity row: NOT CHECKED. Record: `docs/evidence/A13_card_authorize_void.md`. If the build uses a different sandbox app than the test app, it needs the same check. `SECURITY.md` says the build uses the main app, not the test app, so repeat it with the main app's keys.

## 8. Still unverified / not run

Card fields in the app on the live Render URL (M1, `NOT RUN`) · charging a hold placed through card fields (`NOT RUN`) · the B1 Activity row (`NOT CHECKED`) · PayPal-button authorize in a browser · reauthorizing after day 3 · live (non-sandbox) fees · how fast a card issuer clears the leftover pending amount · whether ACDC is on for our app · the Oct 25 direct-card check on the main app (it ran on the test app).
