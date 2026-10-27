# AGENTS.md: rules for any AI coding agent in this repo

Read this whole file before writing any code. Then open `docs/MVP_PLAN.md` to see which milestone is being built right now. Only build that milestone.

## Pending decisions

Before working on `DATA_MODEL.md`, the database, or `lifecycle.py`, read `docs/DECISIONS.md`. A decision that is PROPOSED or awaiting a teammate's confirmation blocks only the work it covers. If it covers what you are about to do, stop, tell the user which one blocks the work, and ask before continuing.

Blocking right now: **D24** (waiting on Malama's confirmation) blocks the database tables and `lifecycle.py`, since both use the holds layout. Delete this line when Malama confirms.

## Open to-dos

Before editing any file, check `docs/TEAM.md` for open to-dos on that file and mention them to the user.

---

## 1. What this project is (30 seconds)

**Last Call** (working name) is a group-payment web app for one club. A treasurer sets a goal, like a $300 cabin deposit. People pledge the most they would pay ("up to $40") and can add conditions ("only if Jay's in"). PayPal **holds** each person's max without charging it. If the goal is reached, a one-hour last call opens, shares lock, and everyone is **charged once** for their fair share. If the goal is missed, every hold is **cancelled** and nobody pays.

The AI only turns a pasted group chat into suggested pledge cards. Plain code makes every money decision.

It is built for the PayPal AI Hackathon (deadline Nov 12, 2026, 12:00 PM PT). **Everything runs in PayPal's sandbox, with fake money.**

## 2. Who you are working with

Three first-year college students: Emmanuel (head, owns all money code), Samuel (UI), Malama (AI reader, math, database). They are learning. They must be able to explain every line in an interview. So:

- Write the **simplest readable** code, not expert-looking code.
- After every task, **explain the important new code line by line** in plain English (see section 6).

## 3. Read before coding

| When you are about to... | Read first |
|---|---|
| Start any task | `docs/MVP_PLAN.md`, `docs/TEAM.md` |
| Touch money, shares, fees or goals | `docs/MONEY_RULES.md` |
| Change states or tables | `docs/STATE_MACHINE.md`, `docs/DATA_MODEL.md` |
| Call PayPal | `docs/PAYPAL_INTEGRATION.md` |
| Touch the AI reader | `docs/AI_PARSER.md` |
| Build a screen or write user-facing text | `docs/UI_DESIGN.md` |
| Add or run tests | `docs/TEST_PLAN.md` |
| Wonder "why is it done this way?" | `docs/DECISIONS.md` (do not re-open a decided item without saying so) |
| Touch keys, tokens, logging or card data | `docs/SECURITY.md` |
| Work on anything shown in the video | `docs/DEMO_SCRIPT.md` |
| Have an idea outside the milestone | `docs/LATER.md` (write it there, don't build it) |
| Meet an unfamiliar word | `docs/GLOSSARY.md` |

## 4. Hard rules (never break these)

### Money
1. **Money is integer cents everywhere.** `2500` means $25.00. Never use floats for money. Convert to a `"25.00"` string only at the PayPal boundary and in templates.
2. **All money math lives in `money.py`** as pure functions (no database, no PayPal, no clock). Routes and templates never do money math.
3. **Save before you send.** Generate a `PayPal-Request-Id`, save it in the database, *then* call PayPal. Save every order ID and authorization ID the moment PayPal returns it, before doing anything else.
4. **Every PayPal write sends the saved `PayPal-Request-Id`.** A retry of the *same* request reuses the same ID.
5. **Check the status field, not just the HTTP code.** A card decline comes back as HTTP 201 with authorization status `DENIED`.
6. **Only one function captures money:** `lifecycle.lock_and_charge()`. It may run only after it wins the database status change `LAST_CALL → LOCKING`, or wins the resume compare-and-set for a lock that died halfway (D27) (see "compare-and-set" in `docs/SYSTEM_DESIGN.md`). Nothing else ever calls capture.
7. **No automatic refunds.** A refund happens only when the treasurer clicks "refund everyone".
8. **The AI never decides money.** Its output is a suggestion. Plain code validates it and the treasurer confirms it.
9. **The PayPal dashboard is not the record.** Our database plus PayPal API `GET` calls are the source of truth.

### Secrets and safety
10. **Never commit secrets.** Keys come only from environment variables (`.env` locally, Render settings in production). `.env` is in `.gitignore`. Only `.env.example` (with empty values) is committed.
11. **Never print secrets.** No keys, tokens or `Authorization` headers in logs, error pages, test output or chat.
12. **Sandbox only.** At startup, if `PAYPAL_BASE_URL` is not `https://api-m.sandbox.paypal.com`, refuse to start.
13. **Never handle raw card numbers.** Card data goes only into PayPal's own card fields in the browser.

### Honesty
14. Use only these status labels: `VERIFIED` (we ran it and saw it pass), `read in docs` (a provider's page says so, with link and date), `NOT RUN`, `designed, not tested`, `SIMULATED`, `OPEN`, `unverified`, `NOT CHECKED` (the test ran, but the dashboard row wasn't checked). A fact with no source yet is marked **TODO (source needed)** and counts as `unverified` (D23).
15. Mark a test `VERIFIED` only if it ran and you saw it pass in this session.
16. Never write a README or UI claim stronger than `docs/TEST_PLAN.md` supports.
17. No invented numbers, quotes, users or testimonials. Test chat messages are synthetic and labeled as made up.

### Git
18. **In Emmanuel's sessions, never run `git add`, `git commit`, `git push`, `git merge` or `git rebase`**, and never open pull requests. The human does all git actions under their own account. You may run read-only commands (`git status`, `git diff`, `git log`) and suggest a commit message. **In Samuel's or Malama's sessions,** follow the git workflow that person chooses, which may include letting you commit, push or open pull requests (D22). **In every session:** never push to `main` and never merge a pull request. `main` is protected, and all work reaches it through a pull request that Emmanuel reviews. If you don't know whose session this is, ask before any git write command.

### Scope
19. Build only what the current milestone lists. If you think something else is needed, say so in your summary and stop. Don't add it. Ideas for later go in `docs/LATER.md`.
20. Ask before adding any dependency beyond: `Flask`, `psycopg[binary]`, `requests`, `python-dotenv`, `gunicorn`, `pytest`.
21. Don't edit a file another teammate owns (see `docs/TEAM.md`) without flagging it in your summary.

## 5. Code style (beginner-readable on purpose)

- **Plain functions.** No classes unless a doc asks for one. No metaclasses, no decorators beyond Flask's `@app.route` / `@app.before_request`, no clever one-liners.
- **Clear names:** `hold_amount_cents`, `hard_deadline`, not `amt`, `hd`.
- **Short functions** with one job each (aim for under ~30 lines).
- **A short comment above each function** saying what it does and *why*. Comment the why, not the obvious.
- **Time is passed in.** Functions that depend on time take a `now` argument instead of calling `datetime.now()` inside. Tests can then control time. All times are stored in UTC (`TIMESTAMPTZ`).
- **SQL:** plain SQL strings with `%s` parameters. Never build SQL with f-strings or string `+`.
- **Errors:** catch specific errors, show the user a friendly message, log details without secrets.
- **Front end:** Jinja templates, plain CSS, plain JavaScript. No frameworks, no build step.

## 6. How to finish every task

1. Run `pytest` and report exactly what passed and failed. Paste the summary line.
2. Update the status column in `docs/TEST_PLAN.md` only for tests that actually ran.
3. **Explain the change for a beginner:**
   - list each file you changed and why,
   - walk through the important new code **line by line** in plain English (what the line does and why it is needed),
   - point out anything that touches money and how it follows the hard rules above.
4. List anything you were unsure about or didn't verify.
5. Suggest a one-line commit message. In Emmanuel's sessions, **don't run any git write command**; in Samuel's or Malama's, follow the workflow they chose (rule 18). **Never deploy.**

## 7. Where things go

```
app.py              Flask routes only: read input, call other modules, render templates
config.py           every number and setting in one place (fees, minimum share, timers)
db.py               database connection + small query helpers
money.py            PURE math: fee estimate, fee-adjusted goal, shares        (Malama)
conditions.py       PURE circle rule: who is counted                           (Malama)
paypal_client.py    every PayPal HTTP call, nothing else                       (Emmanuel)
lifecycle.py        state changes: open, last call, lock + charge, expire,
                    cleanup, settle-on-wake                                    (Emmanuel)
ai_parser.py        group chat text -> suggested pledge cards                  (Malama)
schema.sql          all CREATE TABLE statements                                (Malama)
templates/          Jinja HTML                                                 (Samuel)
static/             CSS, JS, images                                            (Samuel)
tests/              pytest files + the frozen AI test messages
docs/               the design docs you are reading
```

## 8. Commands

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then fill in values, never commit .env

psql "$DATABASE_URL" -f schema.sql   # create tables
flask --app app run --debug          # run locally at http://localhost:5000
pytest                               # run tests
```
