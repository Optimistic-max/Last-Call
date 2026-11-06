# Team

## Who owns what

| Person | Owns | Files |
|---|---|---|
| **Emmanuel** (head) | The money flow: holds, charges, cancels, last call, 48-hour cutoff, settle-on-wake, cleanup sweep, failure policy. Final merges | `paypal_client.py`, `lifecycle.py`, `app.py` (routes), `config.py`, `static/js/pledge_paypal.js` (the PayPal card-field wiring, inside Samuel's `static/`) |
| **Samuel** | Everything people see: screens, wording, motion, the demo video edit | `templates/`, `static/`, `docs/UI_DESIGN.md` |
| **Malama** | The pure math, the circle rule, the AI reader and its test, the database and deploy | `money.py`, `conditions.py`, `ai_parser.py`, `db.py`, `schema.sql`, `tests/test_money.py`, `tests/test_conditions.py`, `tests/test_ai_parser.py` |
| Grok Bot (assistant) | Was to write and freeze the 50 AI test messages before any tuning. Didn't deliver by Nov 3, so Malama writes them (D74) | `tests/ai_test_messages.json` (now Malama's) |

If you need to change a file someone else owns, ask in the group first, or say so clearly in your pull request.

In M1, Emmanuel creates a bare `templates/pledge.html` for Samuel to restyle; like the rest of `templates/`, it's Samuel's after that.

## Live app

**Live URL:** https://last-call-cr7n.onrender.com (sandbox only; Render deploys `main`, so run `pytest` before merging). The first deploy passed on Oct 30 at 10:24 PM ET with Python 3.14.7 and the pinned `requirements.txt` (D52), and `/health` returned 200 with the database connected. B1, B2 and B5 on the live URL: NOT RUN. Free hosting sleeps after 15 minutes, so the first visit can take up to a minute. Details: `docs/SYSTEM_DESIGN.md` §2.

Other names in these docs are assistant bots, not people (roles from the Oct 16 plan, section 11): **steel hacks** (state machine, tables, PayPal sandbox tests), **Warden** (test list, honesty review), **hackaton rank** (README claims table, score estimate), **Transport** (reminders, fact checks).

## Open to-dos

Agents check this list before editing a file and mention any open to-do on it (`AGENTS.md`). Delete a row when it's done.

| Who | File | To-do |
|---|---|---|
| Emmanuel | `app.py` | New values for Samuel's pages (Nov 5). `counted_total_text` implemented for OPEN/LAST_CALL (D86; database integration NOT RUN). Still needed in `board.json`: `goal_amount_text` (finished money text; the board shows a percent until then), `held_percent` (the ring's grey arc and its legend item wait for it), `demo_mode` (the E9 badge, already in `board_panel.html`: add `"demo_mode": event["demo_mode"]` to `board_for_event` and it appears), and a way to tell "Hold pending" apart (D31). `leave.html`: `event_id`, so S6 can have the menu. `pledge.html`: `QUICK_AMOUNTS` from `config.py`, for the pill buttons (D31 #3). S1's refusals still say "deposit", while the field now says "How much does the group need?" Add `app.errorhandler` for 404, 405 and 500, using `templates/404.html` and `templates/500.html`, and decide if "Nothing was charged." on the 500 page is always true: an error can happen partway through a lock. Check `APP_BASE_URL` on Render matches the live URL, and leave it empty locally, so local share links stay local. |
| Samuel | `static/js/pledge_paypal.js` | The billing ZIP `95131` is PayPal's sample value (kept from the B1 spike) and needs a decision before real users. The file is Emmanuel's, so decide together (Oct 28). |
| Malama | `tests/ai_test_messages.json`, `docs/DECISIONS.md` | G3 (Nov 4, D74): write the 50 made-up messages by hand, in the format of `AI_PARSER.md` §7, without the AI agent that helps tune the prompt. `pytest tests/test_ai_accuracy.py` checks the file. Then freeze it (commit, and record the date, commit and SHA-256 in D74), run `.venv\Scripts\python -m tests.ai_accuracy` once, and record the score in `TEST_PLAN.md` and `CLAIMS.md` before changing the prompt. The README must say Malama wrote them. |
| Emmanuel (with Samuel for `board.js`) | `static/js/pledge_paypal.js`, `static/js/board.js` | Target Sat Nov 7, after F7; otherwise it moves to `docs/LATER.md`. Remember the friend in the browser: after a successful hold, `pledge_paypal.js` saves the event id and `pledger_token` in `localStorage` (wrapped in try/catch; the page must work without it). When that browser opens the board or pledge page for the same event again, show "You're in for up to $X. Cancel my pledge" linking to their S6 page. Clear it after they leave or the event ends. No server change. Copy/Send-to-myself stays as the backup for other devices. |
| Emmanuel | `app.py`, `lifecycle.py`, `templates/leave.html` | Target Sat Nov 7. Receipt on the friend's S6 page after lock: "You paid $X (your max was $Y). Nobody paid more than their max." Money texts from the server. |
| Malama | `lifecycle.py` | Review the pull request for `emmanuel/m2-capture-retry` (D83): it touches capture (`charge_one_pledge`, `send_capture`, `record_failed_charge`) and changes three older tests (D39 refused, D39 no answer, F9) to the retry behavior. |
| Emmanuel | `config.py` | `FLASK_SECRET_KEY` is empty in Emmanuel's `.env` (config.py reads it). Nothing else uses it yet (Oct 28). |
| Emmanuel | `app.py` | `import app` refuses to start unless `.env` has the sandbox `PAYPAL_BASE_URL`. `.env.example` leaves it empty, so Samuel, Malama and Render each need it set before `app.py`, `tests/test_health.py` or `tests/test_routes.py` can run (Oct 28). |
| Samuel | `docs/UI_DESIGN.md` | Approve or replace D57's placeholder texts and labels in §4 (the DRAFT banner, "Charge failed", the S1 refusals including D61's "The smallest deposit is $20.00.", D58's two cap messages, the time formats and the bare S1–S3 labels), plus `money.py`'s "Type an amount like 40 or 40.50.", which isn't in §4 either. Step 5b uses the placeholders until then. Build S1–S3 against the §10 contract; the bare templates are `create_event.html`, `admin.html`, and (step C) `board.html` and `board_panel.html` (Oct 31). |
| Samuel | `docs/UI_DESIGN.md` | Approve or replace the parse route's two placeholder refusals (D57): "Type your pledge." (empty box) and "Keep it to 280 characters or fewer." (D73). The page shows them from the answer's `message` (UI_DESIGN.md §10, S4) (Nov 3). |
| Samuel | `docs/UI_DESIGN.md` | Approve or replace the confirm route's four placeholder refusals (D57, D77): "Your amount can't be more than your max.", "You can name up to 3 people.", "Keep your name to 40 characters or fewer." and "Keep each name to 40 characters or fewer." (UI_DESIGN.md §10, S4 `POST /api/pledges`). The boxes for the min and the condition names are yours to build on `pledge.html` (Nov 3). |
| Samuel | `docs/UI_DESIGN.md`, `static/js/pledge_paypal.js` | Approve or replace the pledge page's four placeholder labels (§10, "S4 `pledge.html`"), and the two placeholder texts `REVIEW_TEXT` and `OUT_TEXT` at the top of `static/js/pledge_paypal.js`. Ask Emmanuel to move them to `data-` attributes if you want them in the template. The styling is done (Nov 5). |
| Samuel | `docs/UI_DESIGN.md`, `templates/board_panel.html` | Consider a short line by the goal explaining that it rises a little with each person, because PayPal takes a fixed fee from each charge (D76: the goal uses the current held count) (Nov 2). |
| Samuel | `templates/pledge.html`, `docs/UI_DESIGN.md` | Approve or replace `leave.html`'s four placeholder texts (D57). On the pledge page after 'Held', add a 'Copy link' button next to the friend's own link (changes to 'Copied ✓'), and on phones a 'Send to myself' button using navigator.share; fall back to copy. The styling is done (Nov 5). |

Emmanuel is over capacity through Nov 8 (about 14 h over). Revisit Wed Nov 4, 9 PM ET.

## How we work (proposed by Emmanuel, agree as a team at the first check-in)

Change anything here that doesn't suit Samuel or Malama. The parts that protect the money and the secrets (all code merged through pull requests once coding starts, Samuel's and Malama's reviewed by Emmanuel, `pytest` before merging into `main`, Malama's review of any pull request touching capture or `lock_and_charge`, only bug fixes, docs (README, Devpost text) and judge test logins after the Nov 8 freeze (D69), `.env` never committed) should stay. Whether you commit by hand or let your AI agent do it is your choice (D22).

1. **`main` (D22).** Emmanuel pushes directly to `main` only during the docs and planning phase. Once coding starts, everyone works on branches and merges through pull requests; Emmanuel reviews and merges Samuel's and Malama's. Run `pytest` before merging into `main`, because Render deploys `main` to the live URL. `main` is never locked (changed Oct 26). After the Nov 8 freeze (D69), only bug fixes, docs (README, Devpost text) and judge test logins merge into `main`.
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
