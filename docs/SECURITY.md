# Security

Everything is sandbox and fake money, but we treat keys as if they were real. Judges, GitHub's secret scanning and possibly an automated reviewer will read this public repo.

## Secrets

| Secret | Where it lives | Never |
|---|---|---|
| PayPal client secret | `.env` on your machine, Render environment settings | in git, in chat, in logs, in screenshots |
| Neon `DATABASE_URL` (contains a password) | same | same |
| AI API key | same | same |
| `FLASK_SECRET_KEY` | same | same |

- The PayPal **client ID** is public (the browser needs it). The **secret** is not.
- `.env` is in `.gitignore`. Only `.env.example` with empty values is committed.
- **Regenerate the sandbox secret before the first commit.** The old one was shared with assistant bots during testing.
- Assistant bots that run sandbox tests use a **separate sandbox test app**, never the main app's keys.
- Before making the repo public and again before submitting, search the history: `git log -p | grep -i -E "secret|client_secret|postgres://|postgresql://"` should find nothing.

## If a secret leaks

1. Regenerate it immediately (PayPal Developer Dashboard / Neon / AI provider).
2. Update `.env` and Render.
3. Tell the team. Deleting the commit isn't enough, because the old value stays in git history and may already be copied.

## Card data

- Card numbers go **only** into PayPal's card fields (iframes served by PayPal). Our server never sees, stores or logs a card number, expiry or CVV.
- The README may list PayPal's **public sandbox test cards** (like `4111111111111111`). Never anything else.

## Logging

- Log PayPal **IDs** (order, authorization, capture) and status codes. They are needed for debugging and evidence.
- Never log `Authorization` headers, access tokens, email addresses, full request bodies with personal data, or `.env` values.
- Error pages shown to users never include stack traces.

## Links that act as logins

- The treasurer's `admin_token` link and each pledger's `pledger_token` link are long random strings (`secrets.token_urlsafe(24)`).
- Never show one person's token to someone else. Never put tokens in the README or the video.

## Sandbox guard

The app refuses to start unless `PAYPAL_BASE_URL` is exactly `https://api-m.sandbox.paypal.com`. Test-only mock headers (`PayPal-Mock-Response`) can never be sent outside tests (test F10).

## Privacy

The pledge a friend types is sent to a third-party AI model, and the pledge page says so (D31). The demo uses only a fictional chat and made-up pledges. No real names or phone numbers go in the repo, the test messages or the video.

**Email is optional; name is required (D31).** If a friend gives an email, it is never logged and never goes in the repo, the tests or the video. It never appears on the public board or in `board.json`.
