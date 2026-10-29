# Prompt: Emmanuel, milestones M0 and M1

Paste everything below the line into Claude Code (or Cursor) from the repo folder, on a branch like `emmanuel/m1-config`. This is coding, so it goes through a pull request (D22).

---

Read `AGENTS.md` fully, then read these docs in order: `docs/MVP_PLAN.md` (milestones M0 and M1 only), `docs/DECISIONS.md`, `docs/SYSTEM_DESIGN.md`, `docs/STATE_MACHINE.md`, `docs/DATA_MODEL.md`, `docs/MONEY_RULES.md`, `docs/PAYPAL_INTEGRATION.md`, `docs/TEST_PLAN.md`. The working B1 spike is in `spikes/b1_card_fields/` (evidence: `docs/evidence/B1_card_fields_spike.md`).

I am Emmanuel. I own the money code (`paypal_client.py`, `lifecycle.py`, `app.py`, `config.py`). Malama owns `money.py`, `db.py` and `schema.sql`; Samuel owns `templates/` and `static/`. In step 4 I create a bare `templates/pledge.html` and `static/js/pledge_paypal.js`: Samuel restyles the page, and the PayPal JavaScript stays mine. If a step needs a file a teammate owns and it isn't in the repo yet (Malama's `db.py`, `schema.sql` or `money.py`), stop and tell me instead of writing your own version.

**Approved decisions that shape these steps:** D16 (SDK v6 card fields; only the server's create-order call sets intent `AUTHORIZE`), D24 (save each PayPal request ID before the call; `holds.order_id` may be empty until PayPal returns it), D25 (in M1, reaching the goal opens a last call that runs until the hard deadline), D26 (a second confirm with the same name reuses an unpaid pledge), D27 (resume a lock that died halfway), D31 (the pledge row is created at confirm by `POST /api/pledges`; in M1 the page confirms the typed name and max directly, with no AI). Nothing is blocking right now.

**Step 1: plan only, no code yet.** Give me:
1. the list of files you'll create or change for the steps below,
2. every function name with a one-line description,
3. which tests from `docs/TEST_PLAN.md` you'll write in each step (E10, F1, E7, E8, plus fake-PayPal tests for create, authorize, settle, charge and void),
4. anything in the docs you think is wrong or unclear,
5. how B2 (the decline test card in the browser) will be checked in step 4.

Wait for my approval before writing any code.

**Step 2, after I approve:** build it in this order. **Stop after each step.**
1. `config.py` with the startup sandbox guard (test E10).
2. `paypal_client.py`: token, client token, create order (intent `AUTHORIZE`), authorize, get authorization, capture, get capture, void. Then a sandbox smoke test.
3. The pledge and order steps in `lifecycle.py`, plus the routes `GET /api/client-token`, `POST /api/pledges`, `POST /api/orders` and `POST /api/orders/<id>/authorize`, and test F1. This step needs Malama's `db.py` and `schema.sql`. `POST /api/pledges` accepts no email field until Malama approves the `pledges.email` column.
4. Copy and adapt the v6 card fields from the spike into a bare `templates/pledge.html` and `static/js/pledge_paypal.js`. Run B1 and B2 on localhost.
5. `settle_due_events`, `lock_and_charge` and `expire_event`, with fake-PayPal tests E7 and E8.

Step 5b (Emmanuel): create event, open it (DRAFT → OPEN), the treasurer view, and the board with board.json. Done after 2.5, before 2.6.

6. B1, B2 and B5 on the live Render URL.

Real sandbox calls (the step 2 smoke test, B1, B2, B5) use only the keys in `.env` or Render's settings, and never print them. Record each result in the `docs/TEST_PLAN.md` run log with its evidence, and mark anything not checked as `NOT RUN` or `NOT CHECKED`.

After each step: run `pytest`, show the result, and explain the new code to me line by line like I'm a first-year student.

I merge each step into `main` myself through a pull request (D22). Render deploys `main` to the live URL, so `pytest` must pass before merging.

Rules to repeat back to me before you start: integer cents only, save before you send, check the status not the HTTP code, one capture path guarded by compare-and-set, never print secrets, no git write commands in my session.
