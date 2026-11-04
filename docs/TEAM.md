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
| Samuel | `static/js/pledge_paypal.js` | The billing ZIP `95131` is PayPal's sample value (kept from the B1 spike) and needs a decision before real users. The file is Emmanuel's, so decide together (Oct 28). |
| Malama | `schema.sql`, `docs/DATA_MODEL.md` | D80 (Nov 3): `holds.void_tried_at` is added and `NOT_PLACED` is a new hold status. Emmanuel applied the `ALTER` to the test branch only. Run `ALTER TABLE holds ADD COLUMN IF NOT EXISTS void_tried_at TIMESTAMPTZ;` on `dev` and `main` before `emmanuel/m2-f2-sweep` is merged (the sweep reads the column), and review the pull request (it adds to `settle_due_events`, next to `lock_and_charge`) |
| Malama | `tests/ai_test_messages.json`, `docs/DECISIONS.md` | G3 (Nov 4, D74): write the 50 made-up messages by hand, in the format of `AI_PARSER.md` §7, without the AI agent that helps tune the prompt. `pytest tests/test_ai_accuracy.py` checks the file. Then freeze it (commit, and record the date, commit and SHA-256 in D74), run `.venv\Scripts\python -m tests.ai_accuracy` once, and record the score in `TEST_PLAN.md` and `CLAIMS.md` before changing the prompt. The README must say Malama wrote them. |
| Emmanuel | `app.py`, `lifecycle.py` | D81 (Nov 3): the leave route (M2, Sun Nov 8) must refuse while an event is `LOCKING` or `CHARGING`, not only during last call. The resume's case 1 (an event stuck in `LOCKING` before its shares were saved goes back to `LAST_CALL`) is safe only if nobody can leave in between. Add a test for each status (TEST_PLAN E3 and E6). |
| Malama | `lifecycle.py` | Review the pull request for `emmanuel/m2-e11-resume` (D81): it touches capture (`send_capture`, `resume_stuck_lock`) and changes `save_shares` and `AGENTS.md` rule 6. |
| Emmanuel | `config.py` | `FLASK_SECRET_KEY` is empty in Emmanuel's `.env` (config.py reads it). Nothing else uses it yet (Oct 28). |
| Emmanuel | `app.py` | `import app` refuses to start unless `.env` has the sandbox `PAYPAL_BASE_URL`. `.env.example` leaves it empty, so Samuel, Malama and Render each need it set before `app.py`, `tests/test_health.py` or `tests/test_routes.py` can run (Oct 28). |
| Samuel | `docs/UI_DESIGN.md` | Approve or replace D57's placeholder texts and labels in §4 (the DRAFT banner, "Charge failed", the S1 refusals including D61's "The smallest deposit is $20.00.", D58's two cap messages, the time formats and the bare S1–S3 labels), plus `money.py`'s "Type an amount like 40 or 40.50.", which isn't in §4 either. Step 5b uses the placeholders until then. Build S1–S3 against the §10 contract; the bare templates are `create_event.html`, `admin.html`, and (step C) `board.html` and `board_panel.html` (Oct 31). |
| Samuel | `static/style.css`, `templates/admin.html` | (1) Style S1's demo-mode checkbox: `style.css` makes every `input` full-width and at least 44px tall, so the checkbox is stretched too. (2) Add a warning on S2 that its address is private: it holds the treasurer's `admin_token` (D18, D59), so anyone given it gets the treasurer view. Share only the share link. The wording is Samuel's; add it to `UI_DESIGN.md` §4 (Nov 1). |
| Samuel | `docs/UI_DESIGN.md`, `templates/pledge.html` | The pledge page's privacy note ("What you type here is sent to [provider] to read it…", UI_DESIGN.md §4, `AI_PARSER.md` §6) was planned to name Groq. Once Malama confirms which provider is really used (D75: Azure OpenAI or Groq), make the note name that one. The note isn't in `pledge.html` yet (Nov 2). |
| Malama | `ai_parser.py`, `docs/TEST_PLAN.md` | Before the end of Tue Nov 3 (D75): make one real Azure OpenAI call with the strict `json_schema` mode `ai_parser.py` uses, with the key in the header Azure expects (the parser sends `Authorization: Bearer`; Azure's classic endpoint uses `api-key`, `unverified`). Record the result in the `TEST_PLAN.md` run log. If it doesn't work by then, stay on Groq. Also note `tests/test_ai_parser.py` checks for Groq's URL, so it fails if your `.env` sets `AI_BASE_URL` to Azure (Nov 2). |
| Samuel | `templates/pledge.html` | When you build the own-words box on S4, show the line **"AI reads. You confirm. Plain code handles the money."** with it. The text is already in `UI_DESIGN.md` §4 (S4 own-words box); the demo's "Own words" beat uses it as a caption too (Nov 2). |
| Malama | `ai_parser.py` | D73's 8-second timeout (`config.AI_TIMEOUT_SECONDS`) isn't a hard cap: `requests` applies `timeout=` to connecting and to each wait for data separately, not to the whole call, so an answer that keeps trickling in can take longer than 8 s. Decide whether that's fine or whether `call_model` needs a total limit (Nov 3). |
| Samuel | `docs/UI_DESIGN.md` | Approve or replace the parse route's two placeholder refusals (D57): "Type your pledge." (empty box) and "Keep it to 280 characters or fewer." (D73). The page shows them from the answer's `message` (UI_DESIGN.md §10, S4) (Nov 3). |
| Samuel | `docs/UI_DESIGN.md` | Approve or replace the confirm route's four placeholder refusals (D57, D77): "Your amount can't be more than your max.", "You can name up to 3 people.", "Keep your name to 40 characters or fewer." and "Keep each name to 40 characters or fewer." (UI_DESIGN.md §10, S4 `POST /api/pledges`). The boxes for the min and the condition names are yours to build on `pledge.html` (Nov 3). |
| Samuel | `docs/UI_DESIGN.md`, `templates/board_panel.html`, `static/js/board.js` | Approve or change the two board row keys added Nov 3 (D79): `rows[].counted` (for "the circle turns green together") and `rows[].waiting_on_text` ("Waiting on Jay", wording is a placeholder). The bare panel shows the text after the share; style it as the "Waiting on [name]" chip from UI_DESIGN.md §3 (Nov 3). |
| Samuel | `templates/pledge.html`, `docs/UI_DESIGN.md` | Style the Check button and the new boxes (Nov 3): `pledge-message`, `check-button`, `check-message`, `pledge-min` and `pledge-conditions` (UI_DESIGN.md §10, "S4 `pledge.html`"). Keep every older id. Approve or replace the four placeholder labels, and the two placeholder texts `REVIEW_TEXT` and `OUT_TEXT` at the top of `static/js/pledge_paypal.js` (ask Emmanuel to move them to `data-` attributes if you want them in the template). The AI line and the privacy note stay on your earlier to-dos; the note must be on the page before real people use Check, because their words are sent to the AI provider. |
| Samuel | `templates/board_panel.html`, `docs/UI_DESIGN.md` | Wording so friends understand **held** versus **counted** (Nov 3, seen live on localhost, event 24): after a sandbox hold the board showed "Held so far: $25.00" with an empty progress bar, because Ana was held but not counted yet ("Waiting on Jay", D70). "Held so far" adds every held max (D43); the bar counts only counted pledges. Suggested: also show a "Counted toward goal" line, and say what the bar measures. That line needs a new money key in `board.json`, so ask Emmanuel for it: money text comes only from the server (rule 2). |
| Samuel | `templates/admin.html` | On the treasurer page (S2), replace the plain share-link text box with a **"Copy link"** button, an **"Open in new tab"** link, and on phones a **"Share"** button that opens the phone's share menu (Web Share API, with the copy button as the fallback, as in D31 #4). Keep the page's private admin address off the share buttons: they use `share_link` only (Nov 3). |
| Samuel | `static/js/board.js` | Build the board's live update (Nov 3): fetch `GET /e/<id>/board.json` every 10 seconds and update the page key by key, and tick `seconds_left` down between refreshes. Until then the board changes only when the page is reloaded (seen on localhost, event 24). Specified in `UI_DESIGN.md` §7 ("The board refreshes every 10 seconds") and `MVP_PLAN.md` M1; this line is so it is also in TEAM.md. |
| Samuel | `docs/UI_DESIGN.md`, `templates/board_panel.html` | Consider a short line by the goal explaining that it rises a little with each person, because PayPal takes a fixed fee from each charge (D76: the goal uses the current held count) (Nov 2). |

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
