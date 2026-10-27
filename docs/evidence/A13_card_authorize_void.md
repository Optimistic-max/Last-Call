# A13: card authorize, then void (server API)

**Status: VERIFIED (server API only; app unverified)**

Oct 25, run by steel hacks. Which sandbox app was not recorded, so the app is unverified. Not re-run (Emmanuel, Oct 27): B1 on last-call-test and the M1 card checks in the app cover it.

- `POST /v2/checkout/orders`, intent `AUTHORIZE`, $1.00, sandbox test card 4111…1111 (response showed VISA ending 1111) → **201**
- Order `0WS94888ER0197534`: `COMPLETED`
- Authorization `50694481WY916400J`: `CREATED`
- Void → **204**, authorization now `VOIDED`

| Check | Status |
|---|---|
| PayPal Activity row | NOT CHECKED |
| Card fields in a real browser | NOT RUN |
