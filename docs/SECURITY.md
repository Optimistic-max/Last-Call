# Security

Everything is sandbox and fake money, but we treat keys as if they were real. Judges, GitHub's secret scanning and possibly an automated reviewer will read this public repo.

## Secrets

| Secret | Where it lives | Never |
|---|---|---|
| PayPal client secret | `.env` on your machine, Render environment settings | in git, in chat, in logs, in screenshots |
| Neon `DATABASE_URL` (contains a password) | same | same |
| AI API key (`AI_API_KEY`, for the AI provider set in `AI_BASE_URL`: Azure OpenAI or Groq, D75) | same | same |
| `FLASK_SECRET_KEY` | same | same |

- The PayPal **client ID** is public (the browser needs it). The **secret** is not.
- `.env` is in `.gitignore`. Only `.env.example` with empty values is committed.
- **Regenerate the sandbox secret before the first commit.** The old one was shared with assistant bots during testing.
- The app uses the sandbox app **last-call-test**. Its keys go only in `.env` and Render's settings.
- Assistant bots that run sandbox tests use a **separate sandbox test app**, never last-call-test's keys.
- Before making the repo public and again before submitting, search the history: `git log -p | grep -i -E "secret|client_secret|postgres://|postgresql://"` should find nothing.

## If a secret leaks

1. Regenerate it immediately (PayPal Developer Dashboard / Neon / the AI provider set in `AI_BASE_URL`: Azure portal or Groq console).
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
- The `pledger_token` is part of the friend's own "I'm out" address (`/p/<pledger_token>`, D82), so it can appear in Render's request logs, like the `admin_token`. Accepted for the hackathon, because only the team can read those logs (D59). The `admin_token` never works as a pledger's. Our own log lines name the route and IDs, never a token.
- The `admin_token` is part of the treasurer's address (`/admin/<admin_token>`, D18), so it can appear in Render's request logs. Accepted for the hackathon, because only the team can read those logs (D59). Whether Render's logs show the full path: unverified. Our own log lines name the route, never the token.

## Sandbox guard

The app refuses to start unless `PAYPAL_BASE_URL` is exactly `https://api-m.sandbox.paypal.com`. Test-only mock headers (`PayPal-Mock-Response`) can never be sent outside tests (test F10).

## Privacy

The pledge a friend types is sent to a third-party AI model, the AI provider set in `AI_BASE_URL` (Azure OpenAI or Groq, D75), and the pledge page says so, naming that provider (D31). The demo uses only a fictional chat and made-up pledges. No real names or phone numbers go in the repo, the test messages or the video.

**Email is optional; name is required (D31).** If a friend gives an email, it is never logged and never goes in the repo, the tests or the video. It never appears on the public board or in `board.json`.

## Known limits

- After refund-all, the treasurer's account is short by the original processing fees, because PayPal keeps them on refunds (read in docs: PayPal US fees page, Nov 4 2026). Sandbox behavior is `NOT RUN`.
- `money.py` uses the sandbox fee rate (2.59% + $0.49, checked against real sandbox captures Nov 4 2026). PayPal's live US Advanced card rate on Nov 4 2026 was 2.89% + $0.29, so a live launch must re-check the rate.
- The `pledger_token` is kept in the browser's `localStorage` after a hold. On a shared computer, the next person could open that friend's cancel page.
