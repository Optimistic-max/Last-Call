# CLAUDE.md

@AGENTS.md

The line above imports `AGENTS.md`. If it did not load, open `AGENTS.md` now and read all of it before doing anything. Every rule there applies to you.

## Pending decisions

Before working on `DATA_MODEL.md`, the database, or `lifecycle.py`, read `docs/DECISIONS.md`. A decision that is PROPOSED or awaiting a teammate's confirmation blocks only the work it covers. If it covers what you are about to do, stop, tell the user which one blocks the work, and ask before continuing.

Blocking right now: **D24** (waiting on Malama's confirmation) blocks the database tables and `lifecycle.py`, since both use the holds layout. Delete this line when Malama confirms.

## Open to-dos

Before editing any file, check `docs/TEAM.md` for open to-dos on that file and mention them to the user.

## Extra rules for Claude Code

- **Plan first for anything that touches money.** For work in `paypal_client.py`, `lifecycle.py` or `money.py`, show a short plan (files, functions, tests) and wait for the human to approve it before writing code.
- **One milestone at a time.** Work only on the milestone the human names, using its "Definition of done" in `docs/MVP_PLAN.md` as your checklist.
- **Git depends on whose session it is** (AGENTS.md rule 18, D22). In Emmanuel's sessions: never `add`, `commit`, `push`, `merge` or `rebase`, and never open pull requests; suggest the commit message and let the human run git. In Samuel's or Malama's sessions: follow the git workflow they choose, which may include committing, pushing or opening pull requests for them. In every session: never push to `main` and never merge a pull request. If you don't know whose session it is, ask first.
- **Don't call PayPal unless asked.** Unit tests use a fake PayPal (see `docs/TEST_PLAN.md`). Only run real sandbox calls when the human explicitly asks, and only with the keys in `.env`.
- **Never read `.env` aloud.** You may load it in code. Never print its values.
- **Explain like a teacher.** The human is a first-year student who wants to understand every line. Follow section 6 of `AGENTS.md` every time.
- **When you disagree with a doc**, say so and explain why, then follow the doc unless the human agrees to change it. If they agree, update `docs/DECISIONS.md` in the same change.
