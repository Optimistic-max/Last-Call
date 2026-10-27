# MVP plan

Written **Sunday, Oct 25**. Feature freeze is **Tuesday, Nov 3**. Submit by **Tuesday, Nov 10** (official deadline Nov 12, 12:00 PM PT). The app must stay live through **Dec 15** (end of judging).

**The MVP is milestone M1:** one event, card holds in a real browser, a live board, and settle-on-wake that charges or cancels correctly, deployed on the real URL. Everything after M1 is added on top, one milestone at a time. **Don't start a milestone until the previous one's "definition of done" is met**, except for the parallel lanes marked below.

## The one date to guard

**Oct 28: guest card hold in a real browser (test B1).** Every score estimate depends on it. If it isn't working by the end of Oct 28, tell the whole team that day and decide together. The approved default (D19) is to switch to the PayPal button with intent authorize (test B4, NOT RUN), which then becomes a must-have.

---

## M0: Setup (Mon Oct 26)

| Who | Task |
|---|---|
| Emmanuel | Create the public GitHub repo with an **MIT license** (pick it when creating the repo so it shows in the About section). Add this starter kit. **Regenerate the sandbox client secret** before the first commit, since the old one was shared with bots. Put the new keys only in `.env` and Render. Protect `main` on GitHub (require a pull request before merging), so all work merges through a pull request Emmanuel reviews (D22). |
| Malama | Neon project with three branches: `main` (production), `dev`, `test`. Write `schema.sql` from `DATA_MODEL.md` and apply it to all three. Render free web service connected to the repo, with `GET /health` returning `ok` and a database ping (`/health` and `requirements.txt` are the first code in Emmanuel's `app.py`: keep it to that one route and say so in the pull request). Re-read the Render and Neon free-tier pages linked in `SYSTEM_DESIGN.md` §2 and update the dates there. |
| Samuel | `templates/base.html` with the sandbox banner, the fonts and the color tokens. Sketch S3 (board) and S4 (pledge) on paper or in a design tool. |
| Everyone | Register on the hackathon's Devpost page, then accept the team invite. |

**Done when:** the live Render URL shows the base page with the sandbox banner, `/health` returns ok with the database connected, `pytest` runs (even with zero tests), and `.env` is not in the repo.

## M1: Walking skeleton, the MVP (Oct 26–28)

Simplification for M1 only: there is **no last call yet**. At the hard deadline, the event either locks and charges (goal reached) or expires (goal missed). Everyone is counted (no conditions yet). Use demo-mode timers (minutes) so you can test it quickly. A failed capture marks the pledge `FAILED` and the event `NEEDS_ATTENTION`, with no retry yet (M2 adds the retry and the treasurer's buttons). The M1 lock still goes through `LAST_CALL → LOCKING` (rule 6): reaching the goal opens a last call that runs until the hard deadline (D25, an M1 shortcut; M2 restores the 1-hour window). D24–D27 were approved Oct 26; **Malama confirms the table layout (D24) before the tables are built.**

| Who | Task |
|---|---|
| Emmanuel | `paypal_client.py` (token, create order, authorize, get authorization, capture, get capture, void). `lifecycle.py`: create pledge + order, authorize result, `settle_due_events` with compare-and-set, `lock_and_charge`, `expire_event`. Startup sandbox guard. |
| Emmanuel + Samuel | **Card fields with intent authorize in a real browser** (S4, S5), together. |
| Malama | `money.py` (`estimate_fee_cents`, `fee_adjusted_goal_cents`, `compute_shares_cents`) + `tests/test_money.py` (C1–C8). `db.py` with a one-time retry on the first connection. |
| Samuel | S1 create event, S2 treasurer view (share link + open button), S3 board with the 10-second refresh. |

**Done when** (all on the live Render URL, sandbox):
- [ ] B1: a guest card hold works in a real browser, and the auth ID is in our database
- [ ] B2: the decline test card shows "Card declined" and nothing is voided
- [ ] B5: create event → 3 pledgers hold → deadline passes → next page visit charges each share once → board shows the real net from PayPal
- [ ] E5: a missed goal voids every hold
- [ ] E7, E8, E10, F1 pass with the fake PayPal
- [ ] C1–C8 pass
- [ ] `docs/TEST_PLAN.md` statuses updated for everything that ran

## M2: Last call, leaving and failures (Oct 29–30)

| Who | Task |
|---|---|
| Emmanuel | `LAST_CALL` state with `last_call_ends = min(now + 1h, hard_deadline)`. Leave rules. Cleanup sweep. Capture retry → `NEEDS_ATTENTION`. Refund-all action. New pay link action (waits on D28). |
| Samuel | S6 I'm out page, last call banner + countdown, needs-attention panel, refund-all confirmation. |
| Malama | Keep building `conditions.py` and `ai_parser.py` (parallel lane). |

**Done when:** E1–E6, F2, F4–F7, F11–F13 pass (F8 waits on D28), and a sandbox run on the live URL shows last call → a late joiner → shares drop → lock → charges.

## M3: Conditional pledges and the circle rule (Oct 30–31)

| Who | Task |
|---|---|
| Malama | `conditions.py` (`counted_pledges`) + D1–D7 (written in the parallel lane, wired in now). |
| Emmanuel | Use `counted_pledges` in the goal check and at lock. Void uncounted holds at lock. F9. |
| Samuel | "Only if ___ is in" on the pledge form. "Waiting on Jay" chips. The circle turns green together. |

**Done when:** D1–D7 and F9 pass, and a sandbox run shows Ana ↔ Jay counted together.

## M4: AI reader in the app (Nov 1)

| Who | Task |
|---|---|
| Malama | `ai_parser.py` + validator + G1–G3 (the 50 messages frozen by Grok Bot **before** any tuning). Wire it into S7. |
| Samuel | S7: paste box, privacy note, editable cards, follow-up questions. |

**Done when:** G1–G3 pass, and the real X/50 score is recorded in `TEST_PLAN.md` and `CLAIMS.md`.

## M5: Demo polish → FREEZE (Nov 2–3)

Demo mode badge (E9), the three video moments, the slow-load screen, README draft, `CLAIMS.md` synced with `TEST_PLAN.md`, final project name. **Freeze at the end of Nov 3: after this, no new features and no new APIs.** Only bug fixes, README and video.

## After the freeze (Nov 4–10)

Record the video (under 3 minutes, see `docs/DEMO_SCRIPT.md`), write the README, add judge test logins, submit by **Nov 10**. Then check the live link once a week until **Dec 15**.

---

## If you're behind on Oct 31, cut in this order

1. PayPal-button pledgers (already a stretch goal), unless B1 failed and it became the main path.
2. AI follow-up questions (keep "please retype").
3. The polished needs-attention screen (keep a plain message and the two buttons).

**Never cut:** hold → charge → void, settle-on-wake, the cleanup sweep, compare-and-set, the tests.

## Other dates that land in this window

- Internship applications closing this week: block an hour or two so the build doesn't swallow them.
