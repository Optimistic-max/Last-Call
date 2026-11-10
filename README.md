# Last Call

> **SANDBOX ONLY.** Everything here runs in PayPal's sandbox with fake money. No real payments are made, and the app refuses to start against any other PayPal address.

**Nobody pays unless the goal is reached.**

Last Call is a group-payment web app for one club. A treasurer sets a goal, like a $300 cabin deposit. Each friend pledges the most they would pay ("up to $40"), in their own words, and can add a condition ("only if Jay's in"). PayPal **holds** each person's maximum without charging it. If the goal is reached, a last call opens, shares lock, and everyone is **charged once** for their fair share. If the goal is missed, every hold is cancelled and nobody pays. An AI only reads a friend's message and suggests an amount, cap and condition, which the friend confirms. Plain code makes every money decision.

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/).

## Live demo

**https://last-call-cr7n.onrender.com**

It is **sandbox only** (fake money). It runs on free hosting, so **the first load can take about a minute** while the server wakes up.

## Try it in 60 seconds

1. Open the live demo and **create an event**: a title and an amount the group needs (say $100). Leave **Demo mode** ticked so the timers are minutes, not hours (10 minutes to pledge, 3 minutes of last call).
2. Copy the **share link** and open it in **2 or 3 private (incognito) windows**. Each window is a different friend.
3. In each window, **pledge in your own words**, for example "I'm in for up to 40" or "down if Jay goes, max 40". The AI shows the amount, cap and condition it understood. Fix anything that is wrong, then confirm.
4. Pay with PayPal's sandbox test card: **4111 1111 1111 1111**, expiry **12/30**, CVV **123**. This places a hold. Nothing is charged yet.
5. **Watch the board** change as holds come in. Once the pledges add up to the goal, the **last call** starts. A new friend can still join and everyone's share drops.
6. When the last call ends, shares **lock** and each person is **charged once**. Open your **receipt** to see Held, Charged and Released for your money.

To see the other ending, create an event and let it pass its deadline without reaching the goal: every hold is cancelled and nobody pays.

## How PayPal is used

- **Orders v2, intent `AUTHORIZE`:** a pledge places a hold on the friend's maximum through PayPal's card fields in the browser. We never see card numbers.
- **Capture only the share:** when the event locks, we capture each person's fair share from their hold. PayPal closes the rest of the hold.
- **Void:** if the goal is missed, or someone leaves before last call, the hold is voided.
- **Refunds:** only when the treasurer clicks "refund everyone". There are no automatic refunds. PayPal keeps its fees on a refund, and the screen says so.
- **Saved request IDs:** before every PayPal write, we save a `PayPal-Request-Id` in the database, and a retry of the same request reuses it, so a retry cannot charge twice. Order and authorization IDs are saved the moment PayPal returns them.
- **We check the status, not just the HTTP code.** A declined card comes back as HTTP 201 with authorization status `DENIED`.
- Our database plus PayPal `GET` calls are the record, not the PayPal dashboard.

## How the AI is used

Groq's `openai/gpt-oss-20b` reads one friend's pledge message and suggests an amount, a cap and a condition. **The friend confirms or fixes it before anything is saved.** The AI never decides money: its output is a suggestion that plain code checks.

We scored the reader on **50 made-up test messages**, written with an AI assistant and frozen before any scoring: **43/50** (Nov 8, first scored run, prompt not changed). A message counts as right only if the status, amount, cap and conditions all match. The known misses (amounts written as words like "forty", and "or" conditions) are listed in [`docs/LATER.md`](docs/LATER.md). The evidence is in [`docs/evidence/G3_first_scored_run.txt`](docs/evidence/G3_first_scored_run.txt).

## What we verified

[`docs/CLAIMS.md`](docs/CLAIMS.md) lists every claim with its evidence and status, and [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md) has the run log. In short:

- **Verified against PayPal's sandbox:** a hold with only the share charged, a hold cancelled after a partial charge, refunds that return shares while PayPal keeps its fees, and a declined card caught at checkout (also in the app in a browser, on localhost).
- **Verified with a fake PayPal in automated tests:** the retry and double-charge guards, a missed goal voiding every hold, the timed last call, the "only if Jay's in" rule, and cleanup of stranded holds.
- **Simulated locally:** a refused charge at lock. In the Nov 7 refund test, one friend's capture was answered by our own made-up refusal (`tests/sandbox_lock_with_one_refusal.py`), not by PayPal. PayPal's own refusal (its negative-testing header, F22) is NOT RUN.
- **Not yet run:** a full create-to-charge run on the live URL is not recorded in `CLAIMS.md`. Where a claim is untested, the docs say so.

## Tech stack

- Python and Flask, with Jinja templates, plain CSS and plain JavaScript (no front-end framework, no build step)
- PostgreSQL (Neon), through `psycopg`
- PayPal sandbox: Orders v2, Payments v2 and the JavaScript SDK card fields
- Groq for the AI reader
- Render for hosting, `gunicorn` as the server
- `pytest` for tests

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # fill in your own sandbox keys
psql "$DATABASE_URL" -f schema.sql
flask --app app run --debug        # http://localhost:5000
```

You need a free PayPal developer account with a sandbox app (Advanced Credit and Debit Card Payments enabled), a free Neon Postgres database, and an API key for the AI provider.

### Environment variables

Put these in `.env` on your laptop or in Render's settings. This repo holds the names only: never commit a value. `.env.example` lists the same names with empty values.

| Name | What it is |
|---|---|
| `PAYPAL_CLIENT_ID` | The sandbox app's client ID. |
| `PAYPAL_CLIENT_SECRET` | The sandbox app's secret. Stays on the server. |
| `PAYPAL_BASE_URL` | PayPal's address. The app refuses to start unless it is the sandbox address. |
| `DATABASE_URL` | The Postgres database the app runs on. |
| `TEST_DATABASE_URL` | The database the tests run on (see the warning below). |
| `FLASK_SECRET_KEY` | A long random string, reserved for sessions. |
| `APP_BASE_URL` | The site's own address, used to build the link the treasurer shares. |
| `AI_BASE_URL` | The AI provider's address. Empty means Groq's. |
| `AI_API_KEY` | The AI provider's key. |
| `AI_MODEL` | The AI model's name (`openai/gpt-oss-20b` for Groq). |
| `REFUND_APPROVAL_KEY_HASH` | The treasurer's refund key, stored as a hash. Without it the refund controls are off. |
| `REFUND_ALLOW_LOCAL_HTTP` | Set to true only for local development over plain HTTP. |

## Tests

```bash
pytest
```

There are **780+ automated tests** (782 collected at the time of writing). They use a fake PayPal, so a normal run makes no PayPal calls. The core money-safety tests were checked by deliberately putting the bug back (mutation checks), and we confirmed each test fails. Test messages are made up and labeled that way.

**Tests wipe their database.** `TEST_DATABASE_URL` must point to a separate database (we use a `test` branch on Neon), never the one in `DATABASE_URL`. A test refuses to run if the two are the same. Without `TEST_DATABASE_URL`, the database tests are skipped.

## AI tools used while building

AI coding assistants, including Claude Code, helped write code and docs. A human reviewed and ran every change, and the teammates have to be able to explain every line. Grok drafted the 50 made-up test messages.

## Team

- Emmanuel: lead, PayPal money flow
- Samuel: UI and design
- Malama: AI pledge reader, math, database

## License

MIT. See [`LICENSE`](LICENSE).
