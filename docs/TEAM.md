# Team

## Who owns what

| Person | Owns | Files |
|---|---|---|
| **Emmanuel** (head) | The money flow: holds, charges, cancels, last call, 48-hour cutoff, settle-on-wake, cleanup sweep, failure policy. Final merges | `paypal_client.py`, `lifecycle.py`, `app.py` (routes), `config.py` |
| **Samuel** | Everything people see: screens, wording, motion, the demo video edit | `templates/`, `static/`, `docs/UI_DESIGN.md` |
| **Malama** | The pure math, the circle rule, the AI reader and its test, the database and deploy | `money.py`, `conditions.py`, `ai_parser.py`, `db.py`, `schema.sql`, `tests/test_money.py`, `tests/test_conditions.py`, `tests/test_ai_parser.py` |
| Grok Bot (assistant) | Writes and freezes the 50 AI test messages before any tuning | `tests/ai_test_messages.json` |

If you need to change a file someone else owns, ask in the group first, or say so clearly in your pull request.

Other names in these docs are assistant bots, not people (roles from the Oct 16 plan, section 11): **steel hacks** (state machine, tables, PayPal sandbox tests), **Warden** (test list, honesty review), **hackaton rank** (README claims table, score estimate), **Transport** (reminders, fact checks).

## Open to-dos

Agents check this list before editing a file and mention any open to-do on it (`AGENTS.md`). Delete a row when it's done.

| Who | File | To-do |
|---|---|---|
| Samuel | `docs/UI_DESIGN.md` | Add '[Name] has already pledged.' to UI_DESIGN (D26). |
| Malama | `docs/DATA_MODEL.md` | Confirm D24 and events.lock_started_at in docs/DATA_MODEL.md. |

## How we work (proposed by Emmanuel, agree as a team at the first check-in)

Change anything here that doesn't suit Samuel or Malama. The parts that protect the money and the secrets (`main` protected, every change merged through a pull request Emmanuel reviews, `.env` never committed) should stay. Whether you commit by hand or let your AI agent do it is your choice (D22).

1. **`main` is protected.** Nobody pushes to it directly.
2. **One branch per task**, named after the person and task: `emmanuel/m1-authorize`, `samuel/board`, `malama/money`.
3. **Pull request into `main`.** Emmanuel reviews and merges. Every PR says which tests ran and their result.
4. **Commit under your own GitHub account.** Your commits are your proof of what you built.
5. **10-minute check-in every day:** what I finished, what I'm doing next, what's blocking me.
6. **Never commit `.env`.** If a secret ever lands in a commit, tell Emmanuel right away and regenerate it. Deleting the commit isn't enough.

## Using AI coding agents

- Each person runs their own agent session on their own branch.
- Every agent must read `AGENTS.md` first (Claude Code reads `CLAUDE.md`, which loads it).
- Start each session by naming the milestone and your task, for example: "Milestone M1, my task: `money.py` and `tests/test_money.py`."
- **Git:** in Emmanuel's sessions, agents never run `git add`, `commit`, `push`, `merge` or `rebase`; the human does every git action after reading the change. Samuel and Malama choose their own workflow, including letting their agent commit, push or open pull requests. Either way, no agent pushes to `main` or merges a pull request: everything reaches `main` through a pull request Emmanuel reviews (D22).
- Read what the agent wrote and ask it to explain anything you don't understand. If you can't explain a line, it isn't done.

## Hackathon admin

- Everyone must register on the hackathon's Devpost page, then accept the team invite from the project page.
- The official rules require every member to be at least the age of majority where they live. read in docs (official rules §3 and Prize Delivery, read Oct 26): https://paypalaihackathon.devpost.com/rules
- Prizes are paid to one team Representative, who splits them. Agree on the split in writing now, while it's easy. read in docs (official rules §3 and Prize Delivery, read Oct 26): https://paypalaihackathon.devpost.com/rules
- Only listed team members count, so check the Devpost team list before submitting.

## What goes on whose resume

You can claim what your own commits show you built and tested. Emmanuel: the PayPal money flow and its failure handling. Malama: the AI reader with its accuracy test, the money math, the database and deploy. Samuel: the product design and front end.
