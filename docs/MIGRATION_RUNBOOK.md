# Migration runbook: applying the F7 migrations to Neon

Status of this document: written Nov 7 from the repo. **Nothing in it has been run against Neon.** Every block marked `sql` below was run on the disposable local PostgreSQL (all six migrations applied there) in a session set to read-only, and returned the expected rows (VERIFIED, local only). The Step 0 probe was run once on that cluster and left nothing behind (VERIFIED for PostgreSQL's behaviour only). How the Neon SQL Editor itself treats `BEGIN`/`COMMIT` is `unverified`; Step 0 tests that on a throwaway branch before you trust it.

**This runbook applies nothing. Do not run any migration until the two gates below are met.**

## Gates (both must be true)

1. **Malama has reviewed the actual SQL** of `migrations/005_f7_refund_web_actions.sql` and `migrations/006_f7_bounded_refund_preflight.sql` (D92 and D93 both say "actual SQL review still required"; `docs/TEAM.md` has the to-do).
2. **Emmanuel approves the target and the time** for each branch. The headers of the migration files say the same ("REVIEW ONLY until Emmanuel separately approves the target and execution").

Migration files are the source of truth. Paste them exactly as committed. Never edit one to make it pass.

## 1. What each Neon branch has right now

**Unknown. Nothing in the repo records it.** What the repo does say:

- `main`, `dev` and `test` were created from the M0 `schema.sql` (`docs/MVP_PLAN.md`, Malama). That schema already has an empty `refunds` table with the original columns, and `holds.void_request_id` and `void_tried_at`.
- `docs/DATA_MODEL.md` says migration 001 "has NOT RUN against Neon". Nothing says 002 to 006 ever ran there.
- Nov 3 to 4 test results ran on the Neon `test` branch, before any F7 table existed. All F7 results (Nov 5 to 7) ran on a local disposable PostgreSQL, never Neon.

So the **expected** state of all three branches is "base schema only, none of 001 to 006". Treat that as a guess until this query says so.

### The status query (read-only, safe to run any time)

Open the Neon SQL Editor, pick the branch, paste, run. It changes nothing.

```sql
WITH checks AS (
  SELECT '000 base schema' AS migration, 1 AS n, 'refunds table with request_id, amount_cents, refund_id, status' AS part,
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'refunds'
            AND column_name IN ('request_id', 'amount_cents', 'refund_id', 'status', 'capture_id')) = 5 AS present
  UNION ALL SELECT '000 base schema', 2, 'holds: void_request_id, void_tried_at, auth_id',
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'holds'
            AND column_name IN ('void_request_id', 'void_tried_at', 'auth_id')) = 3
  UNION ALL SELECT '000 base schema', 3, 'captures: capture_id, status, amount_cents',
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'captures'
            AND column_name IN ('capture_id', 'status', 'amount_cents')) = 3
  UNION ALL SELECT '001', 1, 'events: refund_run_token, refund_revision',
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'events'
            AND column_name IN ('refund_run_token', 'refund_revision')) = 2
  UNION ALL SELECT '001', 2, 'holds: refund_check_status',
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'holds'
            AND column_name = 'refund_check_status') = 1
  UNION ALL SELECT '001', 3, 'refunds: send_state, send_started_at, error_code',
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'refunds'
            AND column_name IN ('send_state', 'send_started_at', 'error_code')) = 3
  UNION ALL SELECT '001', 4, 'trigger refunds_protect_record',
         EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'refunds_protect_record' AND NOT tgisinternal)
  UNION ALL SELECT '002', 1, 'holds: void_run_token',
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'holds'
            AND column_name = 'void_run_token') = 1
  UNION ALL SELECT '002', 2, 'trigger events_protect_refund_handoff',
         EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'events_protect_refund_handoff' AND NOT tgisinternal)
  UNION ALL SELECT '003', 1, 'refunds: operation_revision, first_send_started_at',
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'refunds'
            AND column_name IN ('operation_revision', 'first_send_started_at')) = 2
  UNION ALL SELECT '003', 2, 'trigger refunds_protect_operation',
         EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'refunds_protect_operation' AND NOT tgisinternal)
  UNION ALL SELECT '003', 3, 'refunds_send_state allows CHECK_ONLY',
         EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'refunds_send_state' AND pg_get_constraintdef(oid) LIKE '%CHECK_ONLY%')
  UNION ALL SELECT '004', 1, 'guard function has the dispatch rules',
         COALESCE((SELECT pg_get_functiondef(p.oid) FROM pg_proc p WHERE p.proname = 'protect_refund_operation'
            AND p.pronamespace = 'public'::regnamespace) LIKE '%OLD.send_state <> ''READY'' AND NEW.send_state = ''READY''%', false)
  UNION ALL SELECT '005', 1, 'table refund_web_actions',
         to_regclass('public.refund_web_actions') IS NOT NULL
  UNION ALL SELECT '005', 2, 'trigger refund_web_actions_protect',
         EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'refund_web_actions_protect' AND NOT tgisinternal)
  UNION ALL SELECT '006', 1, 'refund_web_actions: target_hold_id, claimed_refund_id',
         (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'refund_web_actions'
            AND column_name IN ('target_hold_id', 'claimed_refund_id')) = 2
  UNION ALL SELECT '006', 2, 'constraint refund_web_actions_one_command_per_refund',
         EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'refund_web_actions_one_command_per_refund')
  UNION ALL SELECT '006', 3, 'guard function knows CANCEL_HOLD',
         COALESCE((SELECT pg_get_functiondef(p.oid) FROM pg_proc p WHERE p.proname = 'protect_refund_web_action'
            AND p.pronamespace = 'public'::regnamespace) LIKE '%CANCEL_HOLD%', false)
)
SELECT migration,
       CASE WHEN bool_and(present) THEN 'APPLIED'
            WHEN NOT bool_or(present) THEN 'not applied'
            ELSE 'PARTIAL - STOP' END AS state,
       count(*) FILTER (WHERE present) || ' of ' || count(*) AS parts
FROM checks GROUP BY migration ORDER BY migration;
```

**How to read it.** One row per migration.

| You see | Meaning | Do |
|---|---|---|
| `000 base schema` = APPLIED | The branch has the tables the migrations build on. | Continue. |
| `000 base schema` is anything else | The branch is not the schema this runbook expects. | **Stop.** Ask Malama. |
| `001`..`006` = `not applied` | Not there yet. | It is a candidate for the steps below. |
| `001`..`006` = `APPLIED` | Already there. | **Skip it. Never run a migration twice** (it would fail, or worse, half-match). |
| any row = `PARTIAL - STOP` | Some parts exist and some don't. Each migration is one transaction, so this should be impossible. | **Stop.** Go to section 6. |

To see the detail behind a row, change the last `SELECT` (everything after the closing `)` of the `WITH`) to `SELECT * FROM checks ORDER BY migration, n;`.

**Record the answer.** Write each branch's result (date, branch, the 7 rows) in this file under "Results log" at the bottom, so this question is never "unknown" again.

## 2. The order

Always **001, 002, 003, 004, 005, 006**, one at a time, and only the ones the status query shows as `not applied`. Never skip a number, and never run them out of order: each one checks that the earlier ones exist and stops if they don't.

Branches: **test first, then dev, then production (`main`)**. Do not start the next branch until the current one is fully verified (section 4) and logged.

| # | File | Needs first | Why that order |
|---|---|---|---|
| 001 | `migrations/001_f7_refund_all.sql` | base schema | Adds the refund columns and the refund guard trigger. |
| 002 | `migrations/002_f7_void_claim.sql` | base schema | Adds `holds.void_run_token` and the refund-handoff trigger. |
| 003 | `migrations/003_f7_refund_operation_safety.sql` | 001 and 002 | Refuses to run unless their columns and triggers exist. |
| 004 | `migrations/004_f7_refund_dispatch_guards.sql` | 001 and 003 (and 002's trigger) | Replaces one guard function from 003. |
| 005 | `migrations/005_f7_refund_web_actions.sql` | 003 | New table for browser commands. |
| 006 | `migrations/006_f7_bounded_refund_preflight.sql` | 005 | Adds columns, `CANCEL_HOLD` and the stricter guard to 005's table. |

## 3. Is each migration safe to run before the deploy?

**The question:** after a migration, does the code that is live today (`main`) still work? If yes, the order "migrate first, then deploy" is safe, and there is no moment when the site is broken.

How this was checked: I read the migration SQL, and searched every non-test Python file on `origin/main` (`app.py`, `lifecycle.py`, `money.py`, `db.py`, `config.py`, `paypal_client.py`, `ai_parser.py`, `conditions.py`). Result: **`main` never reads or writes the `refunds` table, any column these migrations add, or the `REFUNDING` status.** Its only `SELECT *` calls are on `events` and `pledges`, and the rows are read as dicts, so extra columns are ignored. (Reading code is not the same as running it: this is `read in the code`, not a live test. Section 5 has the live check.)

| # | Additive? | Does today's `main` still run? | Anything to know |
|---|---|---|---|
| 001 | **Yes** for columns and the trigger. It also adds constraints on `refunds`; it checks existing rows first and aborts if any would break. | **Yes.** `main` never touches `refunds`. New `events` columns have defaults (`refund_revision` defaults to 0). | Run the preview query P1 first. On a branch that never had refund rows it returns `0, 0, 0`. |
| 002 | **No, not purely.** It adds a column **and rewrites rows**: every hold with a `void_request_id` and a non-final status gets `void_run_token = 'legacy-<id>'`. | **Yes.** `main`'s cleanup sweep (D80) does not read `void_run_token`, so it behaves exactly as before. | The F7 code treats those legacy markers as "a void may already have been sent" and blocks on them. Run P2 first to see how many rows it will mark. Its trigger fires only when an event moves to `REFUNDING`, which `main` never does. |
| 003 | **Yes.** Adds two columns, widens one CHECK (adds `CHECK_ONLY`), adds a trigger on `refunds` updates. | **Yes.** `main` never updates `refunds`. | Stops with an error if 001 or 002 is missing. That is the safe outcome. |
| 004 | **Yes.** Replaces one trigger function; no table or row changes. | **Yes.** | Nothing to preview. |
| 005 | **Yes.** One new table, one index, one function and trigger. No existing table changes. | **Yes.** Nothing on `main` uses the new table. | It adds foreign keys to `events`, `holds` and `refunds`. Once rows exist in it, deleting those parents would fail. `main` never creates such rows. Tests on a shared test branch that clean up by `DELETE` are only affected if F7 tests have left rows behind. |
| 006 | **Yes.** Adds two nullable columns and constraints to 005's table, and replaces its guard function. Every existing row stays valid. | **Yes.** | Needs 005. Verified on the local cluster that 006 applied over 005 gives exactly the fresh schema, and that existing rows are unchanged. |

**The reverse is not safe, and this is the reason for the order.** The F7 code (`emmanuel/f7-refund-all`) needs these migrations. For example its void claim writes `holds.void_run_token` (migration 002), so it would fail on the void paths of leave and the cleanup sweep, not only on the refund pages, if it were deployed to a database that lacks 002. **So: migrate production first, deploy (merge to `main`) second, never the other way round.**

## 4. Per-branch procedure

Do this for **test**, then **dev**, then **production**. Each step is read-only unless it says RUN.

### Before you start (each branch)

1. Confirm the Neon console shows the branch you intend (name at the top of the SQL Editor). Wrong-branch mistakes are the most likely accident.
2. Run the **status query** (section 1). Note which migrations are `not applied`.
3. **Production only:** make a backup branch first. In the Neon console, create a branch from `main` named like `backup-before-f7-2026-11-XX`. Neon's free plan allows 10 branches per project (`read in docs`, `docs/SYSTEM_DESIGN.md`), and you use 3 plus this one. Delete it only after the deploy is verified and a few days have passed.
4. **Production only:** check nothing is mid-flight. Run:

```sql
SELECT id, status, title FROM events WHERE status IN ('LAST_CALL', 'LOCKING', 'CHARGING') ORDER BY id;
```

   Expect **no rows**. If there are rows, wait (or end the event) and run the migration later. The migrations take short exclusive locks and give up after 5 seconds rather than wait, so they cannot hang the site, but you should not change tables under a live charge.

### Step 0 (once): rehearse and probe on a throwaway branch

Do this once, on a **throwaway branch created from `test`** (Neon branching copies the data; it does not touch `test`). It does two jobs: you practise the exact steps, and you learn whether the SQL Editor honours `BEGIN`/`COMMIT`, which is `unverified` for Neon.

Probe (paste exactly, run once, on the throwaway branch only):

```text
BEGIN;
CREATE TABLE zz_probe (x integer);
SELECT 1 / 0;
COMMIT;
```

Then run: `SELECT to_regclass('public.zz_probe');`

- Result is **empty/NULL**: the editor treated the script as one transaction and rolled it back. **The SQL Editor is safe for the migrations.** Continue.
- Result shows **zz_probe**: the editor ran the statements separately, so a failed migration could be left half-applied. **Do not use the SQL Editor.** Use `psql` instead (see "psql fallback" below). Drop the probe table (`DROP TABLE zz_probe;`) or just delete the throwaway branch.

Then rehearse 001 to 006 on that branch exactly as in "For each migration" below. Delete the throwaway branch when done.

### For each migration (001, then 002, ...)

1. **Preview** (only where listed). Read the result; if it is not what the table in section 3 says to expect, **stop and ask Malama**.

   **P1, before 001** (read-only). Expect `0, 0, 0` on a branch that never had refund rows:

```sql
SELECT 'refund rows' AS what, count(*) AS n FROM refunds
UNION ALL SELECT 'captures with more than one refund', count(*) FROM (SELECT capture_id FROM refunds GROUP BY capture_id HAVING count(*) > 1) AS x
UNION ALL SELECT 'refund rows 001 would block', count(*)
  FROM refunds r LEFT JOIN captures c ON c.id = r.capture_id
  WHERE r.amount_cents <= 0 OR btrim(r.request_id) = '' OR c.id IS NULL OR c.capture_id IS NULL
     OR btrim(c.capture_id) = '' OR c.status NOT IN ('COMPLETED', 'REFUNDED') OR r.amount_cents IS DISTINCT FROM c.amount_cents;
```

   **P2, before 002** (read-only). This is how many holds will get a `legacy-` marker. Write the number down; verification V2 must show the same number:

```sql
SELECT count(*) AS holds_that_get_a_legacy_marker FROM holds
WHERE void_request_id IS NOT NULL AND status NOT IN ('VOIDED', 'EXPIRED', 'DENIED', 'CAPTURED', 'PARTIALLY_CAPTURED');
```

2. **RUN the migration.** Open the file from the repo (on GitHub, on the F7 branch or on `main` after the merge), copy **the whole file** (it starts with `BEGIN;` and ends with `COMMIT;`), paste it into the SQL Editor on the correct branch, and run it **once**. Do not run it in pieces and do not edit it. Success shows no error.
3. **Verify** with the migration's query below, then run the **status query** again. The migration's row must now say `APPLIED` and the others must be unchanged.
4. **Log it** in "Results log".
5. Only then go to the next migration.

### Verification queries (read-only)

Each should return what is stated. If not, section 6.

**V1, after 001.** Expect 5 rows, then default `'READY'::text`:

```sql
SELECT conname FROM pg_constraint WHERE conrelid = 'public.refunds'::regclass
  AND conname IN ('refunds_one_per_capture', 'refunds_amount_positive', 'refunds_request_not_blank',
                  'refunds_send_state', 'refunds_send_evidence') ORDER BY conname;
SELECT column_default FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'refunds' AND column_name = 'send_state';
```

**V2, after 002.** `legacy_markers` must equal the number P2 gave you:

```sql
SELECT count(*) FILTER (WHERE void_run_token LIKE 'legacy-%') AS legacy_markers, count(*) AS holds FROM holds;
```

**V3, after 003.** Expect `refunds_protect_operation` and `refunds_protect_record` both `O` (enabled), and the constraint text to contain `CHECK_ONLY`:

```sql
SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'public.refunds'::regclass AND NOT tgisinternal ORDER BY tgname;
SELECT pg_get_constraintdef(oid) AS refunds_send_state_rule FROM pg_constraint WHERE conname = 'refunds_send_state';
```

**V4, after 004.** The status query row `004` must say `APPLIED`. Nothing else changes, so there is nothing more to see.

**V5, after 005.** Expect indexes `refund_web_actions_pkey` and `refund_web_one_active_event` (after 006 a third one, `refund_web_actions_one_command_per_refund`, appears), trigger enabled `O`, and 0 rows in the table:

```sql
SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'refund_web_actions' ORDER BY indexname;
SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'public.refund_web_actions'::regclass AND NOT tgisinternal;
SELECT count(*) AS rows_in_table FROM refund_web_actions;
```

**V6, after 006.** Expect these six constraint names, and both new columns nullable (`YES`):

```sql
SELECT conname FROM pg_constraint WHERE conrelid = 'public.refund_web_actions'::regclass
  AND conname IN ('refund_web_actions_action_type', 'refund_web_actions_cancel_target', 'refund_web_actions_claim_kind',
                  'refund_web_actions_claimed_refund_fkey', 'refund_web_actions_one_command_per_refund',
                  'refund_web_actions_target_hold_fkey') ORDER BY conname;
SELECT column_name, is_nullable FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'refund_web_actions'
    AND column_name IN ('target_hold_id', 'claimed_refund_id') ORDER BY column_name;
```

### After the last migration on a branch

Run the **status query** one final time. Expected: all seven rows `APPLIED`.

- **test branch:** this is the branch the project's `pytest` was built for (`TEST_DATABASE_URL`). Running the full suite against it is a good extra check, but it runs real database writes on a shared branch, so it needs Emmanuel's separate go-ahead and is not part of this runbook's required steps.
- **dev and production:** also confirm the live site still works with the old code (section 5).

## 5. Deploy order and the live check

1. Test, dev and production migrations all `APPLIED` and logged.
2. Confirm today's site still works **on the new schema, with the old code**: open `https://last-call-cr7n.onrender.com/health` (it pings the database; expect 200), then open one existing event's public board page. Both are read-only. This is the live proof for the "main still runs" claims in section 3. If either fails, section 6.
3. Only now merge the F7 pull request into `main` (Emmanuel merges; Render then deploys `main`). Run `pytest` first, as the project rules say.
4. Before the F7 deploy, set the refund settings in Render so the refund pages are not just "unavailable": `FLASK_SECRET_KEY`, `REFUND_APPROVAL_KEY_HASH`, `APP_BASE_URL` (see `docs/SECURITY.md`). Without them the refund controls fail closed and the rest of the site is unaffected. Never paste these values into chat, a file in the repo, or the Neon editor.
5. After the deploy, open the same `/health` and board page again.

## 6. If something fails halfway

First rule: **stop, and do not run the same migration a second time "to see".** Then:

1. **Read the exact error text** and copy it (error text contains no password; do not copy any connection string).
2. **Run the status query.** Because each migration is one transaction, the normal result is that the migration you ran is `not applied` (the failure rolled everything back) or `APPLIED` (it finished). Both are fine states.

| What you see | What it means | What to do |
|---|---|---|
| Error `lock timeout` / `canceling statement due to lock timeout` (code `55P03`) | Something was using the table; the migration gave up after 5 seconds, by design. | Nothing changed. Wait a minute, check the quiet-time query, run the same file again. |
| Error text starting with `F7 migration blocked`, `requires the approved existing guards`, `requires the enabled migration 005 …` or similar | A safety check found a problem and stopped before changing anything. | **Do not bypass it.** Run the status query: an earlier migration is missing or out of order, or P1 data needs review. Fix the cause (run the missing earlier migration, or ask Malama about the data). Then run the same file again. |
| `statement timeout` (30 s) | Unexpectedly slow. | Nothing changed. Check what is running on the branch in the Neon console, try again later. If it repeats, ask Malama. |
| Any error, and the status query shows the migration as `not applied` | It rolled back cleanly. | Safe to try again after the cause is fixed. |
| Any error, and the status query shows `PARTIAL - STOP` for that migration | The transaction was not honoured (for example the editor ran statements separately). | **Stop. Change nothing else.** On the throwaway branch this just means "use `psql`". On a real branch, tell Malama and Emmanuel; do not try to patch it by hand. If it is production, restore from the backup branch made before you started (section 4). How to point the app at a restored branch is `unverified` here; read Neon's branch-restore documentation first. |
| Verification (V1..V6) shows something different from "expect" | The migration ran but the result is not what the review expected. | Stop. Do not run the next migration. Tell Malama with the query and its result. |

**There is no "undo" script, on purpose.** Writing destructive `DROP` statements for a production database is riskier than leaving an applied additive migration in place, and an applied migration does not break `main` (section 3). The only down-step that exists, for 006, lives inside the test suite for the local database. Do not use it on Neon.

## psql fallback (if Step 0 says the SQL Editor is not safe)

On your own computer, with the Neon **direct** connection string for the branch kept in an environment variable (never typed into a file, a chat, or the repo):

```text
psql "$NEON_BRANCH_URL" -v ON_ERROR_STOP=1 -f migrations/00X_name.sql
```

`ON_ERROR_STOP=1` makes `psql` stop at the first error, as the headers of the migration files require. The URL contains the password; do not print or log it. Which URL form (direct or pooled) to use for DDL is `unverified` here: use the direct one, and confirm in Neon's documentation.

## Results log

Fill in as you go. Nothing has been run yet.

| Date | Branch | Status query result (before) | Migrations run | Verified (V1..V6) | By |
|---|---|---|---|---|---|
| | test | | | | |
| | dev | | | | |
| | production | | | | |

## Files this runbook depends on

`migrations/001_f7_refund_all.sql` to `migrations/006_f7_bounded_refund_preflight.sql`, `schema.sql` (for fresh databases only: **never re-run `schema.sql` on an existing database**), `docs/DATA_MODEL.md`, `docs/SECURITY.md`, `docs/TEAM.md`.
