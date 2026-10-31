# MVP plan

Written **Sunday, Oct 25**. Feature freeze is **Thursday, Nov 5** (moved from Nov 3 on Oct 30, D51; the M1 to M5 dates were re-dated the same day to match where the work really is). Submit by **Tuesday, Nov 10** (official deadline Nov 12, 12:00 PM PT). The app must stay live through **Dec 15** (end of judging).

**The MVP is milestone M1:** one event, card holds in a real browser, a live board, and settle-on-wake that charges or cancels correctly, deployed on the real URL. Everything after M1 is added on top, one milestone at a time. **Don't start a milestone until the previous one's "definition of done" is met**, except for the parallel lanes marked below.

Malama's and Samuel's lanes (conditions, ai_parser, screens) run in parallel throughout and are not blocked by Emmanuel's milestone order.

## The one date to guard

**Oct 28: guest card hold in a real browser (test B1).** Every score estimate depends on it. If it isn't working by the end of Oct 28, tell the whole team that day and decide together. The approved default (D19) is to switch to the PayPal button with intent authorize (test B4, NOT RUN), which then becomes a must-have.

---

## M0: Setup (Mon Oct 26)

| Who | Task |
|---|---|
| Emmanuel | Create the public GitHub repo with an **MIT license** (pick it when creating the repo so it shows in the About section). Add this starter kit. **Regenerate the sandbox client secret** before the first commit, since the old one was shared with bots. Put the new keys only in `.env` and Render. |
| Malama | Neon project with three branches: `main` (production), `dev`, `test`. Write `schema.sql` from `DATA_MODEL.md` and apply it to all three. Render free web service connected to the repo, with `GET /health` returning `ok` and a database ping (`/health` and `requirements.txt` are the first code in Emmanuel's `app.py`: keep it to that one route and say so in the pull request). Re-read the Render and Neon free-tier pages linked in `SYSTEM_DESIGN.md` §2 and update the dates there. |
| Samuel | `templates/base.html` with the sandbox banner, the fonts and the color tokens. Sketch S3 (board) and S4 (pledge) on paper or in a design tool. |
| Everyone | Register on the hackathon's Devpost page, then accept the team invite. |

**Git (D22):** Emmanuel pushes directly to `main` only during the docs and planning phase. Once coding starts, everyone works on branches and merges through pull requests; Emmanuel reviews and merges Samuel's and Malama's. Run `pytest` before merging into `main`, because Render deploys `main` to the live URL. Malama reviews any pull request that touches capture or `lock_and_charge`. `main` is never locked (changed Oct 26). After the Nov 5 freeze (D51), only bug fixes, docs (README, Devpost text) and judge test logins merge into `main`.

**Done when:** the live Render URL shows the base page with the sandbox banner, `/health` returns ok with the database connected, `pytest` runs (even with zero tests), and `.env` is not in the repo.

## M1: Walking skeleton, the MVP (Oct 26–28; step 5b and the live runs, 2.6, on Sat Oct 31)

Simplification for M1 only: there is **no last call yet**. At the hard deadline, the event either locks and charges (goal reached) or expires (goal missed). Everyone is counted (no conditions yet). Use demo-mode timers (minutes) so you can test it quickly. A failed capture marks the pledge `FAILED` and the event `NEEDS_ATTENTION`, with no retry yet (M2 adds the retry and the treasurer's buttons). The M1 lock still goes through `LAST_CALL → LOCKING` (rule 6): reaching the goal opens a last call that runs until the hard deadline (D25, an M1 shortcut; M2 restores the 1-hour window). D24–D27 were approved Oct 26 (Malama delegated D24 to Emmanuel).

| Who | Task |
|---|---|
| Emmanuel | `paypal_client.py` (token, client token, create order, authorize, get authorization, capture, get capture, void). `lifecycle.py`: create pledge (at confirm, D31) + order, authorize result, `settle_due_events` with compare-and-set, `lock_and_charge`, `expire_event`. Startup sandbox guard. |
| Emmanuel + Samuel | **Card fields with intent authorize in a real browser** (S4, S5), together: Emmanuel builds a bare `templates/pledge.html` and `static/js/pledge_paypal.js` (the v6 card fields from the B1 spike), and Samuel restyles the page. |
| Malama | `money.py` (`estimate_fee_cents`, `fee_adjusted_goal_cents`, `compute_shares_cents`) + `tests/test_money.py` (C1–C8). `db.py` with a one-time retry on a failed connection (D33). Choose the AI model (D15) before Oct 29: research only. `ai_parser.py` may start early, as a parallel lane (D48, Oct 30). |
| Samuel | S1 create event, S2 treasurer view (share link + open button), S3 board with the 10-second refresh: a plain status word per person (Pledged, Held or Declined), and a total that counts only held money. |

**Done when** (all on the live Render URL, sandbox):
- [ ] B1: a guest card hold works in a real browser, and the auth ID is in our database
- [ ] B2: the decline test card shows "Card declined" and nothing is voided
- [ ] B5: create event → 3 pledgers hold → deadline passes → next page visit charges each share once → board shows the real net from PayPal
- [ ] E5: a missed goal voids every hold
- [ ] E7, E8, E10, F1 pass with the fake PayPal
- [ ] C1–C8 pass
- [ ] `docs/TEST_PLAN.md` statuses updated for everything that ran

## M2: Last call, leaving and failures (Sun Nov 1 – Mon Nov 2)

| Who | Task |
|---|---|
| Emmanuel | First step: write tests E11 and F14 (agreed Oct 30). `LAST_CALL` state with `last_call_ends = min(now + 1h, hard_deadline)`. `pledging_is_open` must compare `LAST_CALL` events against `last_call_ends`, not `hard_deadline`. Leave rules. Cleanup sweep. Capture retry → `NEEDS_ATTENTION`. D27 resume: finish a lock stuck in `LOCKING` or `CHARGING` longer than `STUCK_LOCK_AFTER` (D50). Refund-all action. Finding a lost capture (F5/F6) and the new pay link (F8) moved to `docs/LATER.md` (D49). |
| Samuel | S6 I'm out page, last call banner + countdown, needs-attention panel, refund-all confirmation. |
| Malama | Keep building `conditions.py` (parallel lane). `ai_parser.py` may start now, as a parallel lane (D48). |

**Done when:** E1–E6, E11, F2, F4, F7, F11–F14 pass, and a sandbox run on the live URL shows last call → a late joiner → shares drop → lock → charges.

## M3: Conditional pledges and the circle rule (Mon Nov 2 – Tue Nov 3)

| Who | Task |
|---|---|
| Malama | `conditions.py` (`counted_pledges`) + D1–D7 (written in the parallel lane, wired in now). |
| Emmanuel | Use `counted_pledges` in the goal check and at lock. Void uncounted holds at lock. F9. |
| Samuel | "Only if ___ is in" on the pledge form. "Waiting on Jay" chips. The circle turns green together. |

**Done when:** D1–D7 and F9 pass, and a sandbox run shows Ana ↔ Jay counted together.

## M4: AI reader and the own-words pledge flow (Mon Nov 2 – Tue Nov 3)

| Who | Task |
|---|---|
| Malama | `ai_parser.py` + validator + G1–G3 (the 50 messages frozen by Grok Bot **before** any tuning). Wire it into S4, the pledge page: one friend's message at a time. The validator rule that enforces G1 (`docs/TEAM.md`). D31 #6: the held-only board total in `money.py` (rule 2: no money math in routes or templates). All D31. |
| Samuel | S4: the own-words box, privacy note, quick-amount buttons (D31 #3) and the editable confirm step (amount, cap, condition). D31 #4 and U12: the share button with a copy-link fallback, and static Open Graph tags (`UI_DESIGN.md` §9). D31 #6: the Pledged / Hold pending / Held chips. D31 #7: the declined-card text on the friend's own link. The S7 chat paste is deferred (`docs/LATER.md`). All D31. |
| Emmanuel | The parse and confirm routes, and creating the pledge row at confirm (`SYSTEM_DESIGN.md` §5A). The card step stays the B1 flow. D31 #3: `QUICK_AMOUNTS_CENTS` in `config.py` (values OPEN). D31 #6: each row's state in `board.json`, with "hold pending" worked out from `holds`. All D31. |

**Done when** (each manual check is a sandbox run, recorded in the `TEST_PLAN.md` run log):
- [ ] G1–G3 pass, and the real X/50 score is recorded in `TEST_PLAN.md` and `CLAIMS.md`
- [ ] Manual check, D31 #3: tapping a quick-amount button fills in the confirm step without typing, and nothing is saved until the friend confirms
- [ ] Manual check, D31 #4: Share opens the phone's share sheet; in a browser without the Web Share API, the copy-link fallback copies the link; the link preview shows the static Open Graph text, which says sandbox (wake the server first)
- [ ] Manual check, D31 #6: a pledge shows Pledged before the card step and Held after it, and the board total changes only at Held. Hold pending shows for a hold whose authorize answer hasn't come back (check with the fake PayPal)
- [ ] Manual check, D31 #7: the decline test card shows the declined-card text on the friend's own link

## M5: Demo polish → FREEZE (Wed Nov 4 – Thu Nov 5, D51)

Demo mode badge (E9), the three video moments, the slow-load screen, README draft, `CLAIMS.md` synced with `TEST_PLAN.md`, final project name. **Freeze at the end of Nov 5 (D51): after this, no new features and no new APIs.** After the freeze, only bug fixes, docs (README, Devpost text) and judge test logins merge into `main` (D22); `main` is never locked.

## After the freeze (Nov 6–10)

Record the video (under 3 minutes, see `docs/DEMO_SCRIPT.md`), write the README, add judge test logins, submit by **Nov 10**. Then check the live link once a week until **Dec 15**.

---

## If you're behind on Oct 31, cut in this order

One list, including D31's cut order (D31: its #6 and #7 go before #4).

1. PayPal-button pledgers (already a stretch goal), unless B1 failed and it became the main path.
2. D31 #6: the three visible states (the board total still counts only held money).
3. D31 #7: the declined-card text on the friend's own link (S5's "Card declined" stays).
4. D31 #4: the share button and the Open Graph tags (S2's copy button stays).
5. AI follow-up questions (keep "please retype").
6. The polished needs-attention screen (keep a plain message and the refund-all button; the new pay link moved to `docs/LATER.md`, D49).

**Never cut:** hold → charge → void, settle-on-wake, the cleanup sweep, compare-and-set, the D27 resume of a lock that died halfway (D50), the tests, and D31 #5 (D04's 48-hour window inside the 3-day honor period).

## Other dates that land in this window

- Internship applications closing this week: block an hour or two so the build doesn't swallow them.
