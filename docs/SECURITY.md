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

## F7 treasurer refund controls (D92)

The existing admin URL is not sufficient to send refunds. A separate high-entropy club approval key (32-256 characters) is provided to the treasurer outside that URL. Configure only its Werkzeug scrypt/pbkdf2 password hash as REFUND_APPROVAL_KEY_HASH. Never put the key into source, a URL, a shell argument, a screenshot, or a log. No enrollment or key reset is available through an admin link. This is a shared club credential, not personal accounts or MFA.

Refund controls fail closed unless FLASK_SECRET_KEY has at least 32 characters, Flask uses that key, the approval hash is configured, and APP_BASE_URL is a canonical HTTPS origin. An explicit REFUND_ALLOW_LOCAL_HTTP=true exception permits loopback HTTP only. This also permits the session cookie over local HTTP; never use that exception on a shared host. The actual .env was not changed. Verify HTTPS/proxy and cookie behavior before any deployment.

Important code, in execution order:

1. refund_request_refusal checks configuration, the configured host, form size, Origin/Referer and CSRF before a refund POST opens its database connection.
2. approve verifies the independent key, clears the old session, rotates CSRF, and saves only an event ID, credential fingerprints, issue time and random session nonce in the signed cookie. Signed Flask cookies are readable; no private credential goes there.
3. authorized_event checks the event ID and 15-minute expiry, then compares the current admin-token and approval-hash fingerprints. Credential rotation revokes an existing grant.
4. make_action signs a random form bound to the event, session, command, target and reviewed inventory. For a pending check it includes the exact reviewed operation revision. Unused forms expire after 10 minutes.
5. claim_command (D93) locks the event, rechecks authorization and current records, checks consumed/active commands, claims the payment or void the command needs, and inserts the durable action hash with a link to that claim. This is one transaction, and it commits before any PayPal work.
6. The partial unique index is a second guard: only one CLAIMED browser command per event can exist across processes.
7. run_refund_command invokes only the explicit start, continuation, cancel-one-hold or restricted GET integration. carry_out calls PayPal with no transaction open, then saves the result and finishes the command in one transaction. The previously checked form payload remains valid for that claimed invocation even if its unused-form deadline subsequently passes.
8. finish_action retains the consumed action as FINISHED after a returned command when no active/uncertain refund or void remains. New independent commands can then proceed; replay cannot execute the completed action again.
9. An exception, unresolved POST or uncertain void leaves CLAIMED evidence. No timer, refresh, new browser, session expiry or refund status page releases it. An inconclusive GET for a durably known pending refund can finish its read command; it does not authorize another POST for that refund.
10. claim_treasurer_refund_check locks event then refund and checks event association, ANSWERED/PENDING, a known ID and the exact operation revision. It commits before GET. Existing owner/revision fences control the result write.
11. Private responses use no-store, no-referrer, frame denial and form-action protections. Templates receive whitelisted fields, not raw payment records. Public pages receive only generic refund status words.

There is no browser maintenance, retry or claim-release endpoint. A crash can conservatively block otherwise unsent work. Releasing a browser command requires a separately reviewed offline procedure: establish that the original worker cannot resume, inspect exact command identity and payment/void evidence, reconcile known resources, and keep unknown POST outcomes blocked. Do not manually delete claims simply because they are old. Existing F7 maintenance authorization is not granted by the browser session.

These protections apply to the new refund interface. Existing non-refund admin actions retain their previous authorization design. Real browser, proxy and deployment verification remain NOT RUN; see TEST_PLAN.md for actual local results.

### D93 corrections

- **Preflight (`POST /refunds/preflight`):** same session, CSRF and exact-origin checks as every refund POST; it takes no action token and no command slot because it only reads. It makes at most one PayPal GET per request and saves only `refund_check_status`. It never voids, captures or refunds.
- **Cancelling a hold (`POST /refunds/holds/<id>/cancel`)** is a separate single-use command bound to that hold. A form for one hold, or for START, cannot be used for another. The void request id is saved before the call (rule 3), and the same id is reused on any retry (rule 4).
- **Atomicity:** a command and its payment/void claim are saved together; its result and its finish are saved together. A crash between leaves the command CLAIMED, never silently half-saved. The database enforces both directions (migration 006). Recovery stays GET-only: `reconcile_refund` or `reconcile_uncertain_void` saves the answer and finishes the command.
- **Totals:** when any captured-payment record is missing or unresolved the screen shows "total unknown", never $0.00 or a partial sum.
- Real browser, proxy and deployed-timeout behaviour of the preflight script is NOT RUN.
