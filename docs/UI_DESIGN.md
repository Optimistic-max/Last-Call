# UI design

Owner: **Samuel**. Lives in `templates/` and `static/`. Plain HTML (Jinja), plain CSS, plain JS. No frameworks, no build step.

## 1. Who looks at what

- **Pledgers** open the link from a group chat **on their phone**. Design every pledger screen for a 375px-wide phone first.
- **The treasurer** is often on a laptop, but their screens must still work on a phone.
- **Judges** see it in a 2.5-minute video and may click the live link once. The board must explain itself in about 5 seconds.

## 2. Visual direction

- **Mood:** a friendly "last call" at a bar or campfire: warm, confident, a little playful. Not a bank.
- Black means "counted / goal reached", and one warning color means "declined / needs attention". Everything else is neutral (D84).
- One font, Inter, for everything (D84, replaces D53's Geist Serif). Money amounts should be big and easy to read.
- Avoid the default look of a template: no generic hero gradient, no stock illustrations. The ribbed picture behind the black cards is the one texture on the app pages.
- Record the final palette and fonts at the bottom of this file so the video and README match.

## 3. Screens

| # | Screen | Route | Milestone | Must show |
|---|---|---|---|---|
| S1 | Landing page and create event | `/` | M1 | the landing hero, "How it works", then the form at `#create`: the three lines of intro text, title, how much the group needs ($), demo-mode checkbox (ticked by default), "Create" (D85) |
| S2 | Treasurer view | `/admin/<token>` | M1 | the share link (copy button), "Open pledging", the board, needs-attention actions (M2). D31: a Share button, see §9 |
| S3 | Board (public) | `/e/<id>` | M1 | goal, progress bar, who's in, time left, status banner |
| S4 | Pledge | `/e/<id>/pledge` | M1 | name, max, the promise text, PayPal card fields, "Hold my max". D31 (M4): name (required) and email (optional), a box to type the pledge in your own words, quick-amount buttons, the privacy note, and an editable confirm step before the card fields: amount (the minimum, shown only, D12), cap (the maximum held) and condition. Nothing is saved until the friend confirms: the AI's result stays only in the page. The card fields part stays the B1 flow |
| S5 | Pledge result | same page | M1 | "Held", "Card declined", "Pledging closed", or an error |
| S6 | I'm out | `/p/<token>` | M2 | "Cancel my pledge" or the "can't leave during last call" message (the leave itself is `POST /p/<token>/leave`, D82) |
| S7 | Paste chat + confirm cards | `/admin/<token>/setup` | — | Deferred to `docs/LATER.md` (D31). Was: paste box, privacy note, editable cards, follow-up questions |

## 4. Exact wording (use these strings; they were checked for honesty)

| Where | Text |
|---|---|
| Top of every page | **SANDBOX DEMO: fake money, no real charges** |
| Promise, on S3 and S4 | **Nobody pays unless the goal is reached.** |
| S4, above the card fields, before any hold | **If the goal is met, you're in. We'll hold up to $[max] now and charge only your share.** |
| S5 success | **Held. You'll pay only your share, at most $[max], and only if the goal is reached.** |
| S5 decline | **Card declined. Nothing was held. Try another card.** |
| S5 pledging closed | **Pledging closed before your hold went through. We're cancelling the hold, and nothing will be charged.** |
| S5 error | **Something went wrong. Nothing was charged. Please try again.** |
| S4/S5 pledging closed before any hold was placed | **Pledging is closed for this event. Nothing was held.** |
| S4 name field label | **Your name** |
| S4 max field label | **Your max ($)** |
| S4 button before the card fields | **Continue** |
| S4 card name field label | **Name on card** |
| S4 name left blank | **Type your name.** |
| S4 max under $5 | **The smallest max is $5.00.** |
| S4 the same name already holds (D26) | **[Name] has already pledged.** |
| Declined card, on the friend's own link (D31) | **Your card was declined, so nothing is held and you're not counted yet. Try another card.** |
| S3 goal line | **Goal $[goal] so the club gets a full $[deposit] after fees** |
| S3 last call banner | **Last call! Goal reached. Join in the next [mm:ss] and everyone's share drops.** |
| Board held card (S2, S3) | **Held so far**, then $[held], then **PayPal is holding this. Nobody is charged yet.** After SETTLED: **Charged once.** No caption in the other ended states, because it would no longer be true (D84) |
| Board stat cards (S2, S3) | **Counted** · **Counts toward the goal**. **People in** · **[n] waiting on someone**. **Goal** · **So the club gets the full amount after PayPal's fees** |
| Board row, on screen (S2, S3) | **[Name]**, then **Max $[max]**, plus **share now $[share]** during last call and the waiting text, and a status chip: **Counted**, "Waiting on [name]", or the status word (D84) |
| Board row, for screen readers | **[Name]: [status word], max $[max]**, plus **, share now $[share]**, the waiting text and **, Counted** when they apply |
| Board status card | **Right now**, then the banner text |
| Board countdown card | **Time left**, or **Last call** during last call, and **Closed** when there's nothing to count down |
| Board progress card | **Progress**, **of the goal counted**, and the legend **Counted**, **Held, waiting on someone** and **Still needed** |
| Board, under the half ring | **Held money counts once everyone it depends on is in.** (meanwhile wording, Samuel to pick) |
| Board, nobody yet | **Nobody has pledged yet. Share the link to start.** (not shown after a missed goal, which drops its pledges from the list) |
| Board, a new name in a refresh | **Just pledged** |
| Board and header buttons | **Pledge**, or **Join last call** during last call, and **Invite** |
| How it works card (S2, S3) | **Pledge the most you'd pay** · **PayPal holds it, nothing is charged** · **If the goal is reached, you pay only your share. If not, every hold is cancelled.** |
| S4 link to the board | **← Back to board** |
| S4 steps | **Say it your way**, **Check it**, **Hold it** |
| S4 box the AI filled | **Filled by AI, edit if wrong** |
| Landing headline | **Nobody pays** / **unless the goal is met.** (D85) |
| Landing supporting line | **Friends pledge the most they'd pay. PayPal holds it. If the group reaches the goal, everyone pays their share once. If not, every hold is cancelled.** |
| Landing button and note | **Start a pledge**, then **Sandbox demo. Fake money, no real charges.** |
| Landing "How it works" | **Pledge your max** · **You say the most you'd pay, even 'only if Jay's in'.** **PayPal holds it** · **Nothing is charged while the group fills up.** **Pay your share, once** · **If the goal is reached, you pay your part. If not, every hold is cancelled.** |
| Landing footer | **Built for the PayPal AI Hackathon. Sandbox only.** |
| S1 intro | **Start a pledge**, then **Get your group to actually chip in.** then **Friends pledge with their card. Nobody is charged unless the group reaches the goal; if it doesn't, every hold is cancelled.** then **PayPal holds each friend's max. AI turns 'I'm in for $40 if Jay's in' into a pledge, and they confirm it.** |
| S1 amount field | **How much does the group need? ($)** with the hint **$20 to $2,000** |
| S1 title example | **Ridgeline cabin weekend** |
| S1 demo-mode checkbox | **Demo mode: timers in minutes, not hours** |
| S2 share button | **Copy link**, then **Copied ✓**. On a phone with a share menu: **Share** |
| S2 share link | **Open in new tab** |
| S2 private address warning | **This page's address is private. Share only the link above.** |
| S6 during last call | **You're counted, so you can't leave during last call.** |
| After lock | **Charged once. PayPal closes the rest of each hold.** |
| Missed goal | **Goal not reached. Every hold was cancelled. Nobody paid.** |
| Missed goal, while any hold of that event is still CREATED (D45) | **Cancelling holds…** (shown instead of the missed-goal line until no hold is CREATED) |
| Needs attention (treasurer, D91) | **Needs the treasurer's attention.** [Review refunds]. A failed local charge does not prove that PayPal captured nothing. |
| Refund-all confirm (D91; Samuel review pending) | **Each full refund returns that captured payment to its participant. PayPal keeps the original processing fees; they are not deducted from the participant's refund.** Show recorded fees or **Fee information unavailable.** Explain one new refund per explicit action. |
| Slow first load | **Waking up the app… (free hosting can take up to a minute)** |
| Demo mode badge | **Demo mode: timers are minutes, not hours** |
| S4 own-words box (D31) | **AI reads. You confirm. Plain code handles the money.** and **What you type here is sent to Groq to read it. Don't type anything private.** (D75) |

The [Send [Name] a new pay link] button moved to `docs/LATER.md` (D49), so [Refund everyone] is the only button in the "Needs attention" wording.

Never write "released instantly", "sent to the cabin", or "no signup needed" (the last one only after the browser card test passes).

## 5. Board states

| Event status | Banner | Progress bar |
|---|---|---|
| `OPEN` | "Pledging open: [time] left" | sum of counted maxes / goal |
| `LAST_CALL` | the last call banner + countdown | full, black |
| `LOCKING` / `CHARGING` | "Locking shares…" | full |
| `SETTLED` | "Done! Club receives $[real net]" | full |
| `NEEDS_ATTENTION` | "Needs the treasurer's attention" | full, warning color, with the word |
| `EXPIRED` | the missed-goal message | grey |

Each pledger row shows (never the email, which never appears on the public board or in `board.json`, D31): name · status chip (Pledged / Hold pending / Held / Counted / Waiting on [name] / Declined / Charged $[share] / Charge failed; Pledged and Hold pending from M4, D31) · max · during last call, the share now. A hold the circle rule counts shows **Counted**. A hold still waiting shows its `waiting_on_text`. **Hold pending** needs a server value that doesn't exist yet, so it can't appear yet. Conditions show as "if Jay's in".

**D31:** three visible states, each a word, not only a color: **Pledged** (confirmed, no card yet), **Hold pending** (card sent, PayPal's answer not back yet), **Held**. Board totals count only held money: pledged and hold-pending rows add $0.

**M1:** a plain status word per person, **Pledged**, **Held** or **Declined**, and the total counts only held money. The styled chips, and **Hold pending**, come in M4 (D31).

**Note:** progress bar = counted pledges; board total = held money.

## 6. The three moments the video needs (simple CSS only)

1. **The circle turns black together:** when Ana ("if Jay's in") and Jay ("if Ana's in") both become counted, their chips and avatars turn black at the same moment, 200ms, no stagger (D84).
2. **Share drops:** during last call, when someone joins, the old share slides up and fades as the new one slides in from below, 300ms. Both are the server's text, so JavaScript does no money math (D83, D84).
3. **Goal reached:** the half ring fills, the status card turns black, the countdown card starts its gentle pulse, and the main button becomes "Join last call".

Keep one-time animations under about 0.8 seconds and respect `prefers-reduced-motion`. The countdown's 2-second pulse is a loop, and it stops under reduced motion.

The hero's idle float and scroll zoom are extra to these three moments, and they are off under reduced motion too (D85).

## 7. Basics

- Text contrast meets WCAG AA. Status is never shown by color alone (always a word too).
- Buttons are at least 44px tall on phones.
- **Never ask a friend for the same info twice (D31):** the name (and the email, if given) once, the pledge once. A retry after "Card declined" keeps everything they typed.
- The board refreshes every 10 seconds with a simple `fetch` to `GET /e/<id>/board.json` (no websockets).
- Show money as `$1,234.56` using one template filter. That filter must reuse `dollars()` from `app.py`, so the pages and the JSON messages always format money the same way. The JSON endpoint sends amounts already formatted, so JavaScript never does money math or formatting.

## 8. Final palette and fonts

**Look (D84, D85):** a clean light dashboard in black and white. A calm grey page, white cards, black for anything important. The copy stays warm and plain, so it never feels like a bank. The variables live on `:root` in `static/style.css`.

| Variable | Value | Job |
|---|---|---|
| `--page` | `#F3F3F1` | Page background, with a faint dot grid |
| `--card` | `#FFFFFF` | Cards |
| `--ink` | `#0B0B0B` | Main text, primary buttons, counted |
| `--ink-2` | `#5C5C5C` | Secondary text, captions, placeholders |
| `--ink-3` | `#8A8A8A` | The hero's second headline line only. 3.45:1 on white is too faint for smaller text |
| `--line` | `#E5E5E2` | Borders and dividers |
| `--held` | `#9A9A9A` | Held but not counted in the gauge, and the EXPIRED ring |
| `--on-ink` | `#FFFFFF` | Text on black |
| `--on-ink-2` | `#BDBDBD` on plain black, `#E5E5E5` on a photo card | Quieter text on black |
| `--danger` / `--danger-bg` | `#B42318` / `#FDECEA` | Only Declined, Charge failed and Needs attention, always with a word |

**Font:** Inter from Google Fonts, weights 400, 500 and 600, with system-ui as the fallback. `tabular-nums` is on for the whole page, so money and times never jump.

| Style | Phone / laptop | Used for |
|---|---|---|
| Display | 40 / 56px, 600, -0.03em | Big numbers. In stat cards they shrink with the card (`cqi` units), so `$50,000.00` always fits |
| Title | 28 / 36px, 600, -0.02em | `h1` |
| Card title | 16 / 18px, 500 | Card headings |
| Body | 15 / 16px, 400, line height 1.5 | Text |
| Caption | 13px, 500 | Captions and chips |

Two sizes sit outside that scale on purpose: form labels (14px) and the status card's banner (24px, 600).

**Spacing and shape:** a 4px scale (4, 8, 12, 16, 20, 24, 32, 48, 64). Gutter 16 / 32px, card padding 20 / 24px, card gap 12 / 20px, content max-width 1280px. Cards are 24px round. Fields are 48px tall, 14px round, with 16px text so iPhones don't zoom. Buttons and chips are pills: 48px tall on phones, 44px on laptops. The 40px icon buttons have an invisible ring that makes the tap target 46px. Layout breakpoints are 768, 1024 and 1200px.

**Icons:** Lucide (ISC license, copyright notice in `templates/icons.html`), inline SVG, 20px, 1.5px line. **Logo:** `static/img/logo.svg` and `logo-white.svg`, Samuel's files, used as they are. **Picture:** `static/images/ribbed-dark.jpg`, Samuel's, behind the black cards under a 60% dark layer, so text passes AA over its brightest pixel.

**Shadows (D85):** layered, soft and black only, never a colored glow.

| Variable | Used on |
|---|---|
| `--shadow-rest` | Every card |
| `--shadow-raised` | The featured "Held so far" card, the countdown card, the logo tile |
| `--shadow-floating` | The hero's floating pieces |
| `--shadow-hover` | Hovered cards. It sits on a layer that only fades, because animating `box-shadow` would repaint every frame |

Raised surfaces also get a 1px highlight along the top edge. Primary buttons get a small shadow so they look pressable. Inputs stay flat.

**Glass (D85), used sparingly:** the landing header, the phone's bottom action bar and the hero's floating pieces on screens from 768px, and nowhere else. Phones skip it on the pieces, because blur behind moving cards is heavy there. Without `backdrop-filter`, the header and bar are solid white.

**Hover, press and wiggle (D85):** hover effects apply only under `@media (hover: hover) and (pointer: fine)`. Cards lift 2px, buttons lift 1px, "Who's in" rows fill with `--page` and the avatar grows slightly, arrows lean 2px the way they point, and `.text-link` underlines slide in from the left. A press is `scale(0.97)` over 120ms. The wiggle (rotate -3, 3, -2, 1, 0 degrees over 450ms) is for the logo on hover, "Copied ✓", "Just pledged", and Invite once, 8 seconds after an empty board loads. A refused field shakes instead. Money, the countdown and status chips never wiggle.

**Landing page (D85):** it sits at the top of S1, on `GET /`. A sticky glass header, then a dotted hero canvas with the logo tile, the headline, the supporting line, one button, and six floating pieces (four on tablets, two on phones). Then `#how`, `#create` (the form) and the footer. The pieces are aria-hidden drawings of our own components, and every name and amount in them is made up. Scrolling the first 600px zooms past them. The tile reaches the header at 280px, because any later and the headline would scroll through it.

**Contrast** (WCAG 2 formula, worked out Nov 5; AA needs 4.5:1 for text and 3:1 for large text):

| Foreground on background | Ratio | Used for |
|---|---|---|
| `--ink` on `--card` / `--page` | 19.68 / 17.72 | Main text |
| `--ink-2` on `--card` / `--page` | 6.69 / 6.02 | Secondary text, captions, placeholders |
| `--ink-3` on `--page` | 3.11 | The hero's second line: large text only |
| White on `--ink` | 19.68 | Buttons, black chips |
| White on a photo card's brightest pixel | 6.0 | Numbers and titles |
| `#E5E5E5` on a photo card's brightest pixel | 4.7 | Captions on photo cards |
| `#BDBDBD` on `--ink` | 10.48 | Quieter text on plain black |
| `--danger` on `--danger-bg` / `--card` | 5.75 / 6.57 | Declined, Charge failed, Needs attention |
| `--ink` on `--line` | 15.59 | Held chip |
| `--ink-2` on `--line` | 5.30 | Disabled button |

Not text, but worth knowing: `--line` on white is 1.26:1, below the 3:1 WCAG asks for a field's edge, and `--held` on white is 2.81:1, below 3:1 for a graphic. A field's label and the ring's legend words carry the meaning. `--ink-3` (3.45:1) would clear the bar for field borders if the team wants that.

## 9. Sharing the link (D31)

- **Share button** on S2: uses the Web Share API where the browser has it, with a copy-link button as the fallback.
- **Static Open Graph tags** on the event link page (`og:title`, `og:description`, `og:image`): the same for every event, with no names or amounts. The description says it's a sandbox demo.
- **Wake the Render server before sharing the link.** Open the link once yourself first: the free server sleeps, and otherwise the link preview or the first friend may reach it asleep.

## 10. What each page receives (step 5b contract)

Added by Emmanuel on Oct 31 for step 5b (D54–D58). `app.py` passes exactly these values, and tests check that `board.json` has exactly these keys.

- Money and times arrive as finished text, so templates and JavaScript never format or add up money (§7, rule 2). The `dollars` filter (`{{ 4000|dollars }}` shows `$40.00`) is for a template that is given cents. No 5b page needs it.
- No page and no JSON ever gets an email or a `pledger_token`, except the friend's own S6 page and the link on their own pledge page (D82), which carry their own token. Only S2 gets anything that contains the `admin_token`.
- Later milestones may add keys. They never rename one.
- Files: `create_event.html` (S1), `admin.html` (S2), `board.html` (S3) and `board_panel.html` (the board). `board_panel.html` is included by S2 and S3; the others extend `base.html` (D76). `macros.html` holds shared pieces and `icons.html` the icons. `create_event.html` replaces `base.html`'s whole `shell` block and keeps the banner (D85).
- *Placeholder* marks D57's texts, used until Samuel approves or replaces them in §4.

### S1 `create_event.html` (`GET /`, and `POST /events` when it refuses)

| Value | Type | Example |
|---|---|---|
| `error_text` | text, `""` when there is none | `"Type a title."` |
| `title_value` | what the treasurer typed, kept after a refusal | `"Cabin deposit"` |
| `deposit_value` | what the treasurer typed, kept after a refusal | `"300"` |
| `demo_mode_checked` | true or false | `false` |

The form posts to `/events` with the fields **`title`**, **`deposit`** and **`demo_mode`** (a checkbox with the value `yes`). `app.py` reads these names, so keep them. Success goes to S2.

S1 refusals: `"Type a title."` *(placeholder)*, `money.py`'s `"Type an amount like 40 or 40.50."`, `"The smallest deposit is $20.00."` *(placeholder, D61)*, `"The largest deposit is $2,000.00."` *(placeholder, D58)*, and the S5 error text if the database is down.

### S2 `admin.html` (`GET /admin/<admin_token>`)

| Value | Type | Example |
|---|---|---|
| `title` | text | `"Cabin deposit"` |
| `share_link` | text: the pledge page (D55) | `"https://last-call-cr7n.onrender.com/e/7/pledge"` |
| `can_open` | true while the event is DRAFT | `true` |
| `open_url` | text: the action of the "Open pledging" form (POST). It holds the treasurer's token, so never put it on another page | `"/admin/<admin_token>/open"` |
| `board` | the S3 object below. Arrives with step C (D54) | |

### S3 `board.html` (`GET /e/<id>`) and `board.json` (`GET /e/<id>/board.json`)

Both get the same `board` object, and `board.json` is exactly this object, so the 10-second refresh can update the page key by key. Arrives with step C (D54).

| Key | Type | Example |
|---|---|---|
| `event_id` | number | `7` |
| `title` | text | `"Ridgeline Hiking Club cabin"` |
| `status` | text, for styling only: `DRAFT`, `OPEN`, `LAST_CALL`, `LOCKING`, `CHARGING`, `SETTLED`, `NEEDS_ATTENTION`, `EXPIRED` | `"OPEN"` |
| `banner_text` | text, from the table below | `"Pledging open: 0:09:00 left"` |
| `seconds_left` | whole number of seconds until `last_call_ends` during `LAST_CALL`, until `hard_deadline` while `OPEN` (never below 0); `null` for every other status. Lets `board.js` tick the countdown live between refreshes. Added Nov 2 (D76), approved by Samuel Nov 3 | `299` |
| `goal_text` | text | `"Goal $310.01 so the club gets a full $300.00 after fees"` |
| `held_total_text` | text: HELD money only (D31, D43). It is `$0.00` after lock, because holds become charges | `"$120.00"` |
| `counted_total_text` | finished money text: the sum of eligible counted held maximums during OPEN and LAST_CALL (D86). Waiting, unpaid, declined, dropped and ineligible holds add nothing. `""` at every other status, preserving the existing people-count fallback; it is not a confirmed-payment total | `"$45.00"` |
| `progress_percent` | a whole number from 0 to 100. It is 100 only when the goal is reached (D54), and 100 from `LAST_CALL` on (§5) | `39` |
| `pledging_open` | true or false: whether to show the link to `/e/<id>/pledge` | `true` |
| `rows` | a list in join order, with DROPPED pledges left out (D56) | |
| `rows[].name` | text | `"Ana"` |
| `rows[].status` | text, for styling only: `PENDING_PAY`, `HELD`, `DECLINED`, `CHARGED`, `FAILED` | `"HELD"` |
| `rows[].status_word` | text: `"Pledged"`, `"Held"`, `"Declined"`, `"Charged $28.33"`, or `"Charge failed"` *(placeholder)* | `"Held"` |
| `rows[].max_text` | text | `"$40.00"` |
| `rows[].estimated_share_text` | text: during `LAST_CALL`, what this person would pay if last call ended now (from `money.py`, the same numbers the lock charges), so a late joiner visibly lowers everyone's number; `""` at every other time. Added Nov 2 (D76), approved by Samuel Nov 3 | `"$8.21"` |
| `rows[].counted` | true or false: true for a held pledge the circle rule counts, and for a pledge already `CHARGED` or `FAILED` at lock; false for Pledged, Declined and held pledges that are still waiting. For styling ("the circle turns green together"). Added Nov 3 (D79), Samuel to approve | `true` |
| `rows[].waiting_on_text` | text: `"Waiting on Jay"`, `"Waiting on Jay and Maya"` or `"Waiting on Jay, Maya and Kim"` *(placeholder)* for a held pledge that isn't counted yet, naming the people nobody has a hold for (it follows the chain: if Ana waits on Bo and Bo waits on Cy, both say Cy); `""` for everyone else and whenever the event is no longer OPEN or LAST_CALL. Added Nov 3 (D79), Samuel to approve | `"Waiting on Jay"` |

| Event `status` | `banner_text` |
|---|---|
| `DRAFT` | "This event isn't open yet." *(placeholder)* |
| `OPEN` | "Pledging open: [time] left", with [time] always `h:mm:ss`, such as `0:09:00` or `47:59:59` (D86). The banner and countdown card tick together from server `seconds_left`; only the server decides when pledging ends |
| `LAST_CALL` | "Last call! Goal reached. Join in the next [mm:ss] and everyone's share drops.", with [mm:ss] like "4:59", or "1:02:03" from one hour up *(placeholder format)* |
| `LOCKING`, `CHARGING` | "Locking shares…" |
| `SETTLED` | "Done! Club receives $[real net]". If PayPal's net is missing for any charge: "Charged once. PayPal closes the rest of each hold." (D54, D57) |
| `NEEDS_ATTENTION` | "Needs the treasurer's attention" |
| `EXPIRED` | "Cancelling holds…" while any hold of the event is still CREATED (D45), then "Goal not reached. Every hold was cancelled. Nobody paid." |

### S4 `POST /api/pledges/parse` (M4, D31, D73)

Added by Emmanuel on Nov 3. The pledge page's JavaScript sends `{"event_id": 7, "text": "down if Jay goes, max 40"}` and gets the AI's **suggestion** back. Nothing is saved (D31, D62): the friend fixes it in the boxes and confirms with `POST /api/pledges`.

| Key | Type | Example |
|---|---|---|
| `status` | text: `in`, `out` or `unclear` | `"in"` |
| `max` | plain amount text with no `$` and no commas, ready to put back in the "Your max ($)" box; `null` when there is none | `"40.00"` |
| `min` | the same, for "in for $20" (D12); `null` when there is none | `null` |
| `conditions` | a list of names that must also be in (can be empty) | `["Jay"]` |
| `follow_up_question` | text to show when `status` is `unclear`, otherwise `null`. If the AI fails or times out it is "Couldn't read that. Please retype it, or fill in the amount, cap and condition yourself.", and every box stays editable | `null` |

Refusals come back as `{"message": "..."}`, like the other routes: `"Type your pledge."` *(placeholder)* for an empty box (400), `"Keep it to 280 characters or fewer."` *(placeholder, D73)* for longer text (400), the S4/S5 closed text (409), and the S5 error text for an unknown event (404) or a database error (503).

### S4 `POST /api/pledges` (D31, D77)

Updated by Emmanuel on Nov 3. The page sends what the friend confirmed: `{"event_id": 7, "name": "Ana", "max": "40", "min": "20", "conditions": ["Jay"]}`. Only `event_id`, `name` and `max` are required.

| Key | Type | Notes |
|---|---|---|
| `max`, `min` | plain amount text like `"40"` or `"40.50"` | `min` is optional: missing, `null` or `""` mean none. `min` is shown only and never changes the share (D12) |
| `conditions` | a list of names, optional (missing or `null` mean none) | At most 3 names, each at most 40 characters. Blanks, repeats and the friend's own name are dropped. Saved in the same transaction as the pledge. A retry replaces the old `min` and conditions |
| `name` | text, at most 40 characters | The same 40-character limit as a condition name |

The answer is `{"pledger_token": "...", "hold_text": "..."}`, as before. Refusals are `{"message": "..."}` with status 400: `"Your amount can't be more than your max."`, `"You can name up to 3 people."`, `"Keep your name to 40 characters or fewer."` and `"Keep each name to 40 characters or fewer."`, all *(placeholders, D57)*, plus the existing ones.

### S4 `pledge.html`: the Check button and the new boxes (M4, D31, D77)

Added by Emmanuel on Nov 3 as bare elements for Samuel to style. **Every older id is unchanged** (`pledge`, `pledge-name`, `pledge-max`, `confirm-button`, `hold-text`, `hold-button`, `message`, `paypal-card-fields-name`, `-number`, `-expiry`, `-cvv`). A test checks that the page has all of them and that every id `static/js/pledge_paypal.js` looks up exists. Style by these ids; don't rename them.

| New id | Element | What it is | Labels are placeholders (D57) |
|---|---|---|---|
| `pledge-message` | `textarea`, `maxlength="280"` | The friend's pledge in their own words (optional). 280 is `config.MAX_PLEDGE_TEXT_CHARS` (D73); the server counts the real limit | "Say it in your own words (optional)" |
| `check-button` | `button` | Sends the words to `POST /api/pledges/parse` | "Check" |
| `check-message` | `p role="status"` | The AI's follow-up question, "Check the boxes below…", or an error from the Check | (filled by the script) |
| `pledge-min` | `input` | The minimum, as typed text (optional, shown only, D12) | "Your minimum ($, optional)" |
| `pledge-conditions` | `input` | Names separated by commas (optional, at most 3 names of at most 40 characters, D77) | "Only if these people are in (optional, separate names with commas)" |

How it behaves (for the design, not for restyling away):
- **Check fills three boxes as a suggestion**: `pledge-max`, `pledge-min` and `pledge-conditions`. Nothing is saved until the friend presses Continue. The boxes stay editable, and the friend can skip Check and type them by hand.
- **Continue sends what is in the boxes**, never the AI's answer: `name`, `max`, `min` and `conditions` (the box split on commas). The server checks everything again and answers in the S4 `POST /api/pledges` table above.
- **An "in" answer sets all three boxes** (empty where the AI gave nothing). **An "unclear" answer sets only what the AI gave** and shows its question. **An "out" answer fills nothing** and shows a short line.
- **Buttons are off while a request runs**, so a double click sends one request. While a Check runs the four suggestion boxes are off too. After Continue succeeds, the name and all the boxes are locked, so the hold is for exactly what was saved.
- **A Check that fails** (a 400, 409 or 503 answer, a network error, or no answer in 20 seconds) shows the server's message, or the general error text, and leaves every box editable.
- **Two placeholder texts are in `static/js/pledge_paypal.js`**, not in the page: `REVIEW_TEXT` = "Check the boxes below. Nothing is saved until you press Continue." and `OUT_TEXT` = "That sounds like a no, so nothing was filled in." Samuel may move them into `pledge.html`; ask Emmanuel to read them from `data-` attributes like `data-error-text`.
- **Still Samuel's:** the line "AI reads. You confirm. Plain code handles the money." and the privacy note (§4, `AI_PARSER.md` §6), which must name the AI provider that is really used.

### S6 `leave.html` (`GET /p/<pledger_token>`, `POST /p/<pledger_token>/leave`, D82)

A bare page from Emmanuel (Nov 4), for Samuel to restyle. It extends `base.html`. The page receives `title` (the event's title), `message` (one line of text), `can_leave` (true only when the button shows), `button_text` and `leave_url`. The texts are placeholders until Samuel approves them (D57), except the counted line, which is copied from §4.

| State | `message` | Button |
|---|---|---|
| can leave | "Cancel your pledge? Your hold will be cancelled and nothing will be charged." | `leave-button`, "Cancel my pledge" |
| counted, in last call | "You're counted, so you can't leave during last call." | none |
| left, hold cancelled (or none) | "You're out. Your hold is cancelled, and nothing will be charged." | none |
| left, hold still being cancelled | "You're out. Cancelling your hold…" | none |
| too late (locking, charged, settled, expired, time up) | "It's too late to cancel here: pledging has ended for this event." | none |

Ids to keep: `leave-message` and `leave-button`. An unknown token (including the `admin_token`) is a 404 with the general error text. The POST always redirects (303) to the page.

**On the pledge page (S4/S5):** after "Held", a hidden line `leave-link-line` is shown with the friend's own S6 address in `leave-link`, and the placeholder text "Keep this link to cancel before last call." (D57). The script sets the address with `textContent`.


## F7 Stage 3 private refund interface (D91)

Emmanuel implemented the approved security flow; Samuel's visual and wording review is pending. Existing shared styles are reused, without new JavaScript or changes to board.js.

S2 links to /admin/<admin_token>/refund-access only for NEEDS_ATTENTION, REFUNDING or REFUNDED. That link alone grants no refund permission. The independent club key unlocks a 15-minute event-scoped session. Subsequent private pages use /admin/events/<event_id>/refunds (progress) and /refunds/confirm (confirmation). They display recorded captured payments, never held maximums or estimated shares. Known original fees are displayed; missing fees say "Fee information unavailable."

The confirmation explains full participant refunds, retained original processing fees, authorization verification/cancellation, irreversibility and one new refund per action. POST /refunds/start confirms. Each subsequent POST /refunds/continue needs an explicit Continue refunding action. GET/refresh never sends, reconciles or resumes a payment. POST /refunds/<refund_id>/check permits PayPal GET only for a known eligible pending refund. No retry or maintenance controls exist.

Per-payment words distinguish Not sent yet, Request started/result not confirmed, PayPal processing, PayPal-confirmed Refunded, failed/cancelled requiring review, Result unknown, and Maintenance status check required. Per-person completion requires all recorded payments to agree and no local accounting blockers. D47 captured money, missing records and unresolved authorizations get investigation messages; no missing payment amount is invented. A resolved zero-capture event explicitly says no captured payments required refunds. Public board additions are only generic Refunding/Refunded status words; private request IDs and recovery diagnostics are excluded.

The new templates are refund_access.html, refund_confirm.html, refund_status.html and the private refund_people.html partial. No auto-submit, automatic status check, or automatic continuation exists. Double-click correctness comes from database claims, rather than JavaScript. Keyboard/mobile layout and actual browser behavior remain NOT RUN.
