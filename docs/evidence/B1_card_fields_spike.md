# B1: card hold through card fields in a real browser (spike)

**Status: VERIFIED (spike on localhost, not the app)**

Oct 26. Sandbox app: last-call-test. Code: `spikes/b1_card_fields/` (PayPal JavaScript SDK v6 card fields, server on `http://localhost:5000`). Emmanuel typed the sandbox test card into the card fields in a real browser. Claude Code ran the server, the void and the read-back checks.

Requests, with secrets removed (no `Authorization` header, no tokens):

| # | Request | Body | Result |
|---|---|---|---|
| 1 | `POST /v2/checkout/orders` (PayPal-Request-Id `1cf35b01-db60-4121-ad55-fdb2ab963557`) | `{"intent": "AUTHORIZE", "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}]}` | HTTP 201, PayPal-Debug-Id `ca50ded07edef`. Order `6Y19708071807635F`: `CREATED` |
| 2 | Card number, expiry and CVV typed into PayPal's card fields, sent to PayPal by `session.submit(orderId)` | (inside PayPal's fields, never through our server) | The page called step 3, which it does only after the submit result is `succeeded` |
| 3 | `POST /v2/checkout/orders/6Y19708071807635F/authorize` (PayPal-Request-Id `c5dceb1c-271f-43b5-b707-29cc7b4a288f`) | `{}` | HTTP 201, PayPal-Debug-Id `ca50ded16eb96`. Order `COMPLETED`. Authorization `1FV797880C126320B`: `CREATED` |
| 4 | `POST /v2/payments/authorizations/1FV797880C126320B/void` (PayPal-Request-Id `40539bf4-0e35-43db-a948-baeef05041a8`) | none | HTTP 204, PayPal-Debug-Id `ca50ded574856` |
| 5 | `GET /v2/payments/authorizations/1FV797880C126320B` | none | HTTP 200, PayPal-Debug-Id `ca50ded5e9faa`. Status `VOIDED` |
| 6 | `GET /v2/checkout/orders/6Y19708071807635F` | none | HTTP 200, PayPal-Debug-Id `ca50dee2cbcfa`. Intent `AUTHORIZE`, order `COMPLETED`, payment source `card`: VISA ending 1111. Authorization `1FV797880C126320B`: `VOIDED`, USD 1.00 |

| Check | Status |
|---|---|
| Final authorization status | `VOIDED` |
| PayPal sandbox Activity row | VERIFIED (Oct 28: ID `1FV797880C126320B` matched on the Activity detail page; Cancelled there, Voided in the list) |
| Browser page log (eligibility line, submit result text) | NOT CHECKED (not copied from the browser) |
| Same flow in the app, on the live Render URL, with the auth ID saved in our database | NOT RUN |
