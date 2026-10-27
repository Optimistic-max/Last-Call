# Prompt: Emmanuel, milestones M0 and M1

Paste everything below the line into Claude Code (or Cursor) from the repo folder, on a branch like `emmanuel/m1-skeleton`.

---

Read `AGENTS.md` fully, then read these docs in order: `docs/MVP_PLAN.md` (milestones M0 and M1 only), `docs/SYSTEM_DESIGN.md`, `docs/STATE_MACHINE.md`, `docs/DATA_MODEL.md`, `docs/MONEY_RULES.md`, `docs/PAYPAL_INTEGRATION.md`, `docs/TEST_PLAN.md`.

I am Emmanuel. I own the money code (`paypal_client.py`, `lifecycle.py`, `app.py`, `config.py`). Malama owns `money.py`, `db.py` and `schema.sql`; Samuel owns `templates/` and `static/`. If those files don't exist yet, create minimal placeholder versions and tell me which ones, so the others can replace them.

**Step 1: plan only, no code yet.** Give me:
1. the list of files you'll create or change for M0 and the Emmanuel parts of M1,
2. every function name with a one-line description,
3. which tests from `docs/TEST_PLAN.md` you'll write (E7, E8, E10, F1, plus fake-PayPal tests for create/authorize/settle/charge/void),
4. anything in the docs you think is wrong or unclear, and check `docs/DECISIONS.md` first: D24–D27 and D31 were approved Oct 26,
5. the three checks for `docs/PAYPAL_INTEGRATION.md` §3 (SDK version, ACDC, decline behavior) and how I should do each one.

Wait for my approval before writing any code.

**Step 2, after I approve:** build it in small steps. In this order:
1. `config.py` with the startup sandbox guard,
2. `paypal_client.py`,
3. `lifecycle.py` (create pledge + order, record authorization, `settle_due_events` with compare-and-set, `lock_and_charge`, `expire_event`),
4. the routes in `app.py`,
5. the tests with a fake PayPal.

After each step: run `pytest`, show the result, and explain the new code to me line by line like I'm a first-year student. Stop after each step so I can read it.

Rules to repeat back to me before you start: integer cents only, save before you send, check the status not the HTTP code, one capture path guarded by compare-and-set, never print secrets.
