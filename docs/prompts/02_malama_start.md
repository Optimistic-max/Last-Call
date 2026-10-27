# Prompt: Malama, M0 setup + money math + circle rule + AI model choice

Paste everything below the line into your AI coding tool from the repo folder, on a branch like `malama/m0-setup`.

---

Read `AGENTS.md` fully, then `docs/TEAM.md` (my open to-dos), `docs/MVP_PLAN.md`, `docs/DECISIONS.md`, `docs/DATA_MODEL.md`, `docs/MONEY_RULES.md`, `docs/STATE_MACHINE.md` (the invariants section) and `docs/TEST_PLAN.md` (sections C, D and G).

I am Malama. I own `money.py`, `conditions.py`, `ai_parser.py`, `db.py`, `schema.sql` and their tests. Don't touch `paypal_client.py`, `lifecycle.py`, `config.py`, `templates/` or `static/`. Git: I choose my own workflow (D22), but never push to `main` and never merge a pull request. Everything reaches `main` through a pull request Emmanuel reviews.

**Every APPROVED decision in `docs/DECISIONS.md` applies. These are the ones that touch my files:**
- **D11:** the fee-adjusted goal uses 0.495 per pledger, not 0.49 (`MONEY_RULES.md` §3). PayPal's fee is still $0.49; the extra half cent is padding because each fee is rounded to the nearest cent.
- **D12 and D13:** `min_cents` is shown only and never changes a share. Leftover cents go to the last-joined open pledgers.
- **D24:** `holds` has `create_request_id`, an `order_id` that stays empty until PayPal returns it, `authorize_request_id` and `void_request_id` (I delegated this decision to Emmanuel on Oct 26). D27 adds `events.lock_started_at`.
- **D29:** there is no `webhook_events` table (it moved to `docs/LATER.md`).
- **D31:** the own-words pledge flow. Each friend types their own pledge, the AI reads that one message, and nothing is saved until the friend confirms. The treasurer chat paste is deferred.

**Task 1 (M0, first): database, Neon and Render.**
- A Neon project with three branches: `main` (production), `dev`, `test`.
- `schema.sql`: copy the tables from `docs/DATA_MODEL.md` exactly. That layout already includes D24 and D27, and has no webhook table. Apply it to all three branches.
- `db.py`: connect with `psycopg` using `DATABASE_URL`. Retry the very first connection once after 2 seconds, because Neon's free database may be waking up. Add small helpers for running a query and fetching rows. Never print the connection string.
- `requirements.txt` (the six packages in `AGENTS.md` rule 20). If `app.py` doesn't exist yet, create a minimal one with only `GET /health`, which pings the database and returns `ok`. `app.py` belongs to Emmanuel, so keep it to that one route and say so in my pull request.
- A Render free web service connected to the repo (start command `gunicorn app:app`), with the environment variable names from `.env.example`. Then re-read the Render and Neon free-tier pages linked in `docs/SYSTEM_DESIGN.md` §2 and update the dates there.
- M0 is done when the live Render URL answers `/health` with `ok` and the database connected, `pytest` runs, and `.env` is not in the repo.

**Task 2 (M1): `money.py` + `tests/test_money.py`.**
- Implement `estimate_fee_cents`, `fee_adjusted_goal_cents` (D11) and `compute_shares_cents` (D13) exactly as described in `docs/MONEY_RULES.md`, as pure functions with integer cents.
- Write tests C1–C8 from `docs/TEST_PLAN.md`. C3 must try at least 10,000 random cases and assert the club is never short.

**Task 3 (parallel lane): `conditions.py` + `tests/test_conditions.py`.**
- One function: `counted_pledges(pledges)` where each pledge has a `name` and a list of `conditions` (names). It returns the names that are counted, using the rule: assume everyone is in, remove anyone with a condition naming someone not in the set, repeat until nothing changes. Match names ignoring case and extra spaces.
- Write tests D1–D7.

**Task 4 (before Oct 29): choose the AI model (D15). Research only, no code.**
- Compare free models that could read one short pledge message and return the JSON in `docs/AI_PARSER.md` §3.
- Record the choice in `docs/DECISIONS.md` (D15): model name, provider, free-tier limits (requests per minute and per day), whether typed text is used for training, the date I checked, and links. Anything I couldn't confirm on the provider's own page is `unverified`.

**Not yet: no `ai_parser.py` code until M4.** In M4 the parser reads one friend's message and suggests one pledge, checked by `validate_pledge` (`docs/AI_PARSER.md`). The validator rule in my TEAM.md to-do also lands in M4.

**My open to-dos in `docs/TEAM.md` (none of them block other work):**
- Approve or reject the optional `pledges.email` column (D31; name stays required). If I approve it, change `docs/DATA_MODEL.md` and `schema.sql` together, record it in `docs/DECISIONS.md`, and remember an email is never logged and never appears on the public board or in `board.json` (`docs/SECURITY.md`).
- Approve or reject dropping the `PARSED` state from the main flow (`docs/STATE_MACHINE.md`).
- The validator rule: reject any amount, cap or condition that doesn't appear in the friend's message (enforces G1). M4.

Do one task at a time. Before writing code, show me a short plan and wait. After writing code, run `pytest`, show the result, and explain every function line by line in plain English. Update the statuses in `docs/TEST_PLAN.md` only for tests that actually ran.
