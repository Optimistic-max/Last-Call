# Team

## Who owns what

| Person | Owns | Files |
|---|---|---|
| **Emmanuel** (head) | The money flow: holds, charges, cancels, last call, 48-hour cutoff, settle-on-wake, cleanup sweep, failure policy. Final merges | `paypal_client.py`, `lifecycle.py`, `app.py` (routes), `config.py`, `static/js/pledge_paypal.js` (the PayPal card-field wiring, inside Samuel's `static/`) |
| **Samuel** | Everything people see: screens, wording, motion, the demo video edit | `templates/`, `static/`, `docs/UI_DESIGN.md` |
| **Malama** | The pure math, the circle rule, the AI reader and its test, the database and deploy | `money.py`, `conditions.py`, `ai_parser.py`, `db.py`, `schema.sql`, `tests/test_money.py`, `tests/test_conditions.py`, `tests/test_ai_parser.py` |
| Grok Bot (assistant) | Writes and freezes the 50 AI test messages before any tuning | `tests/ai_test_messages.json` |

If you need to change a file someone else owns, ask in the group first, or say so clearly in your pull request.

In M1, Emmanuel creates a bare `templates/pledge.html` for Samuel to restyle; like the rest of `templates/`, it's Samuel's after that.

Other names in these docs are assistant bots, not people (roles from the Oct 16 plan, section 11): **steel hacks** (state machine, tables, PayPal sandbox tests), **Warden** (test list, honesty review), **hackaton rank** (README claims table, score estimate), **Transport** (reminders, fact checks).

## Open to-dos

Agents check this list before editing a file and mention any open to-do on it (`AGENTS.md`). Delete a row when it's done.

| Who | File | To-do |
|---|---|---|
| Samuel | `docs/UI_DESIGN.md` | In §5, the status list in "Each pledger row shows…" (line 69 today) must include Pledged and Hold pending (M4, D31). Also add the pledge page's four new labels to §4, or change them in `templates/pledge.html`: "Your name", "Your max ($)", "Continue", "Name on card" (step 2.4, Oct 28). |
| Malama | `docs/DATA_MODEL.md` | Approve or reject the database values D31 needs: an optional `pledges.email` column (name stays required), and a `HOLD_PENDING` pledge status only if the team wants it stored instead of worked out from `holds`. DATA_MODEL isn't changed yet. Doesn't block other work (Oct 26). |
| Malama | `docs/STATE_MACHINE.md` | Approve or reject the change D31 needs: no `PARSED` state in the main flow, because nothing is saved before the friend confirms (the parse result stays in the page; the pledge row is created at confirm). STATE_MACHINE isn't changed yet. Doesn't block other work (Oct 26). |
| Malama | `docs/AI_PARSER.md` | Add a validator rule: reject any amount, cap or condition that doesn't appear in the friend's message (enforces G1). Doesn't block other work (Oct 26). |
| Samuel | `static/js/pledge_paypal.js` | The billing ZIP `95131` is PayPal's sample value (kept from the B1 spike) and needs a decision before real users. The file is Emmanuel's, so decide together (Oct 28). |
| Emmanuel | `config.py` | `FLASK_SECRET_KEY` is empty in Emmanuel's `.env` (config.py reads it). Nothing else uses it yet (Oct 28). |
| Emmanuel | `lifecycle.py` | A pledge's max has no upper limit. `confirm_pledge` and `schema.sql` (Malama's) check only the $5 minimum (Oct 28). |
| Emmanuel | `app.py` | `import app` refuses to start unless `.env` has the sandbox `PAYPAL_BASE_URL`. `.env.example` leaves it empty, so Samuel, Malama and Render each need it set before `app.py`, `tests/test_health.py` or `tests/test_routes.py` can run (Oct 28). |
| Samuel | `docs/UI_DESIGN.md` | Add "Cancelling holds…" to the §4 wording table: the missed-goal board line shown while any hold of that event is still CREATED, instead of "Every hold was cancelled" (D45, used in step 5b, Oct 28). |
| Malama | `docs/STATE_MACHINE.md` | Update the DROPPED definition (pledge states table, line 43 today) per D45: a pledge that was HELD when its event expired becomes DROPPED once its hold is voided, or at once if it has no CREATED hold left; a pledge whose void failed stays HELD (Oct 28). |

## How we work (proposed by Emmanuel, agree as a team at the first check-in)

Change anything here that doesn't suit Samuel or Malama. The parts that protect the money and the secrets (all code merged through pull requests once coding starts, Samuel's and Malama's reviewed by Emmanuel, `pytest` before merging into `main`, Malama's review of any pull request touching capture or `lock_and_charge`, only bug fixes, docs (README, Devpost text) and judge test logins after the Nov 5 freeze (D51), `.env` never committed) should stay. Whether you commit by hand or let your AI agent do it is your choice (D22).

1. **`main` (D22).** Emmanuel pushes directly to `main` only during the docs and planning phase. Once coding starts, everyone works on branches and merges through pull requests; Emmanuel reviews and merges Samuel's and Malama's. Run `pytest` before merging into `main`, because Render deploys `main` to the live URL. `main` is never locked (changed Oct 26). After the Nov 5 freeze (D51), only bug fixes, docs (README, Devpost text) and judge test logins merge into `main`.
2. **One branch per task** for everyone once coding starts, named after the person and task: `emmanuel/m1-authorize`, `samuel/board`, `malama/money`.
3. **Pull request into `main`** for all code. Emmanuel reviews and merges Samuel's and Malama's. Emmanuel merges Emmanuel's own pull requests after `pytest` passes, but Malama reviews any pull request that touches capture or `lock_and_charge`. Every PR says which tests ran and their result.
4. **Commit under your own GitHub account.** Your commits are your proof of what you built.
5. **10-minute check-in every day:** what I finished, what I'm doing next, what's blocking me.
6. **Never commit `.env`.** If a secret ever lands in a commit, tell Emmanuel right away and regenerate it. Deleting the commit isn't enough.

## Using AI coding agents

- Each person runs their own agent session on their own branch (once coding starts; docs and planning changes may go straight to `main`).
- Every agent must read `AGENTS.md` first (Claude Code reads `CLAUDE.md`, which loads it).
- Start each session by naming the milestone and your task, for example: "Milestone M1, my task: `money.py` and `tests/test_money.py`."
- **Git:** in Emmanuel's sessions, agents never run `git add`, `commit`, `push`, `merge` or `rebase`; the human does every git action after reading the change. Samuel and Malama choose their own workflow, including letting their agent commit, push or open pull requests. Either way, no agent pushes to `main` or merges a pull request. Once coding starts, all work reaches `main` through pull requests, after `pytest` passes; Emmanuel reviews Samuel's and Malama's. Only docs and planning changes go straight to `main`, by Emmanuel (D22).
- Read what the agent wrote and ask it to explain anything you don't understand. If you can't explain a line, it isn't done.

## Hackathon admin

- Everyone must register on the hackathon's Devpost page, then accept the team invite from the project page.
- The official rules require every member to be at least the age of majority where they live. read in docs (official rules §3 and Prize Delivery, read Oct 26): https://paypalaihackathon.devpost.com/rules
- Prizes are paid to one team Representative, who splits them. Agree on the split in writing now, while it's easy. read in docs (official rules §3 and Prize Delivery, read Oct 26): https://paypalaihackathon.devpost.com/rules
- Only listed team members count, so check the Devpost team list before submitting.

## What goes on whose resume

You can claim what your own commits show you built and tested. Emmanuel: the PayPal money flow and its failure handling. Malama: the AI reader with its accuracy test, the money math, the database and deploy. Samuel: the product design and front end.
