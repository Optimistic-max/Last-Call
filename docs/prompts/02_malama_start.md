# Prompt: Malama, setup + money math + circle rule

Paste everything below the line into your AI coding tool from the repo folder, on a branch like `malama/money`.

---

Read `AGENTS.md` fully, then `docs/MVP_PLAN.md`, `docs/DATA_MODEL.md`, `docs/MONEY_RULES.md`, `docs/STATE_MACHINE.md` (the invariants section) and `docs/TEST_PLAN.md` (sections C and D).

I am Malama. I own `money.py`, `conditions.py`, `ai_parser.py`, `db.py`, `schema.sql` and their tests. Don't touch `paypal_client.py`, `lifecycle.py`, `templates/` or `static/`.

**Task 1 (M0): `schema.sql` and `db.py`.**
- `schema.sql`: copy the tables from `docs/DATA_MODEL.md` exactly.
- `db.py`: connect with `psycopg` using `DATABASE_URL`. Retry the very first connection once after 2 seconds, because Neon's free database may be waking up. Add small helpers for running a query and fetching rows. Never print the connection string.
- `requirements.txt` (the six packages in `AGENTS.md` rule 20) and a minimal `app.py` with only `GET /health`, which pings the database and returns `ok`. `app.py` belongs to Emmanuel, so keep it to that one route and say so in your pull request.

**Task 2 (M1): `money.py` + `tests/test_money.py`.**
- Implement `estimate_fee_cents`, `fee_adjusted_goal_cents`, `compute_shares_cents` exactly as described in `docs/MONEY_RULES.md`, as pure functions with integer cents.
- Write tests C1–C8 from `docs/TEST_PLAN.md`. C3 must try at least 10,000 random cases and assert the club is never short.

**Task 3 (parallel lane): `conditions.py` + `tests/test_conditions.py`.**
- One function: `counted_pledges(pledges)` where each pledge has a `name` and a list of `conditions` (names). It returns the names that are counted, using the rule: assume everyone is in, remove anyone with a condition naming someone not in the set, repeat until nothing changes. Match names ignoring case and extra spaces.
- Write tests D1–D7.

Do one task at a time. Before writing code, show me a short plan and wait. After writing code, run `pytest`, show the result, and explain every function line by line in plain English. Update the statuses in `docs/TEST_PLAN.md` only for tests that actually ran.
