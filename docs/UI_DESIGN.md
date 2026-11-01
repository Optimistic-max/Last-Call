# UI design

Owner: **Samuel**. Lives in `templates/` and `static/`. Plain HTML (Jinja), plain CSS, plain JS. No frameworks, no build step.

## 1. Who looks at what

- **Pledgers** open the link from a group chat **on their phone**. Design every pledger screen for a 375px-wide phone first.
- **The treasurer** is often on a laptop, but their screens must still work on a phone.
- **Judges** see it in a 2.5-minute video and may click the live link once. The board must explain itself in about 5 seconds.

## 2. Visual direction

- **Mood:** a friendly "last call" at a bar or campfire: warm, confident, a little playful. Not a bank.
- Pick **one** strong accent color for "counted / goal reached" and one warning color for "declined / needs attention". Everything else is neutral.
- One font, Geist Serif, for everything (D53, replaces "one display font plus one text font"). It has one weight, so headings and money amounts stand out by size. Money amounts should be big and easy to read.
- Avoid the default look of a template: no generic hero gradient, no stock illustrations.
- Record the final palette and fonts at the bottom of this file so the video and README match.

## 3. Screens

| # | Screen | Route | Milestone | Must show |
|---|---|---|---|---|
| S1 | Create event | `/` | M1 | title, deposit ($), demo-mode checkbox, "Create" |
| S2 | Treasurer view | `/admin/<token>` | M1 | the share link (copy button), "Open pledging", the board, needs-attention actions (M2). D31: a Share button, see §9 |
| S3 | Board (public) | `/e/<id>` | M1 | goal, progress bar, who's in, time left, status banner |
| S4 | Pledge | `/e/<id>/pledge` | M1 | name, max, the promise text, PayPal card fields, "Hold my max". D31 (M4): name (required) and email (optional), a box to type the pledge in your own words, quick-amount buttons, the privacy note, and an editable confirm step before the card fields: amount (the minimum, shown only, D12), cap (the maximum held) and condition. Nothing is saved until the friend confirms: the AI's result stays only in the page. The card fields part stays the B1 flow |
| S5 | Pledge result | same page | M1 | "Held", "Card declined", "Pledging closed", or an error |
| S6 | I'm out | `/p/<token>` | M2 | "Cancel my pledge" or the "can't leave during last call" message |
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
| S6 during last call | **You're counted, so you can't leave during last call.** |
| After lock | **Charged once. PayPal closes the rest of each hold.** |
| Missed goal | **Goal not reached. Every hold was cancelled. Nobody paid.** |
| Missed goal, while any hold of that event is still CREATED (D45) | **Cancelling holds…** (shown instead of the missed-goal line until no hold is CREATED) |
| Needs attention (treasurer) | **[Name]'s charge didn't go through. The others were charged. Choose what to do:** [Refund everyone] |
| Refund-all confirm | **Refunding returns everyone's money, but PayPal keeps its fees ($[fees]). This can't be undone.** |
| Slow first load | **Waking up the app… (free hosting can take up to a minute)** |
| Demo mode badge | **Demo mode: timers are minutes, not hours** |
| S4 own-words box (D31) | **AI reads. You confirm. Plain code handles the money.** and **What you type here is sent to [provider] to read it. Don't type anything private.** |

The [Send [Name] a new pay link] button moved to `docs/LATER.md` (D49), so [Refund everyone] is the only button in the "Needs attention" wording.

Never write "released instantly", "sent to the cabin", or "no signup needed" (the last one only after the browser card test passes).

## 5. Board states

| Event status | Banner | Progress bar |
|---|---|---|
| `OPEN` | "Pledging open: [time] left" | sum of counted maxes / goal |
| `LAST_CALL` | the last call banner + countdown | full, accent color |
| `LOCKING` / `CHARGING` | "Locking shares…" | full |
| `SETTLED` | "Done! Club receives $[real net]" | full |
| `NEEDS_ATTENTION` | "Needs the treasurer's attention" | full, warning color |
| `EXPIRED` | the missed-goal message | grey |

Each pledger row shows (never the email, which never appears on the public board or in `board.json`, D31): name · status chip (Pledged / Hold pending / Held / Counted / Waiting on [name] / Declined / Charged $[share]; Pledged and Hold pending from M4, D31) · max. Conditions show as "if Jay's in".

**D31:** three visible states, each a word, not only a color: **Pledged** (confirmed, no card yet), **Hold pending** (card sent, PayPal's answer not back yet), **Held**. Board totals count only held money: pledged and hold-pending rows add $0.

**M1:** a plain status word per person, **Pledged**, **Held** or **Declined**, and the total counts only held money. The styled chips, and **Hold pending**, come in M4 (D31).

**Note:** progress bar = counted pledges; board total = held money.

## 6. The three moments the video needs (simple CSS only)

1. **Circle turns green together:** when Ana ("if Jay's in") and Jay ("if Ana's in") both become counted, their two rows flash to the accent color at the same time.
2. **Share drops:** during last call, when someone joins, each share number counts down from the old value to the new one (about 600ms).
3. **Goal reached:** the progress bar fills and the last call banner slides in.

Keep animations under about 0.8 seconds and respect `prefers-reduced-motion`.

## 7. Basics

- Text contrast meets WCAG AA. Status is never shown by color alone (always a word too).
- Buttons are at least 44px tall on phones.
- **Never ask a friend for the same info twice (D31):** the name (and the email, if given) once, the pledge once. A retry after "Card declined" keeps everything they typed.
- The board refreshes every 10 seconds with a simple `fetch` to `GET /e/<id>/board.json` (no websockets).
- Show money as `$1,234.56` using one template filter. That filter must reuse `dollars()` from `app.py`, so the pages and the JSON messages always format money the same way. The JSON endpoint sends amounts already formatted, so JavaScript never does money math or formatting. For the share-drop animation, it also sends the old and new values in cents.

## 8. Final palette and fonts

Direction: **"Bar sign"**, a dark room with a lit sign: warm off-white text, one green for "counted", one coral for "needs attention", and a yellow banner that is used only for the sandbox notice. The variables live on `:root` in `static/style.css`.

| Variable | Hex | Job |
|---|---|---|
| `--bg` | `#17161E` | Page background |
| `--surface` | `#212130` | Cards |
| `--line` | `#2C2A36` | Borders, empty progress bar track, disabled buttons (decorative only: 1.27:1 on `--bg`, so never the only edge of an input) |
| `--ink` | `#F4EFE6` | Main text |
| `--ink-soft` | `#B3ADA3` | Secondary text, input borders |
| `--accent` | `#5FD69C` | Counted / goal reached, main button |
| `--accent-soft` | `#1E3D2D` | Background behind `--accent-ink` text |
| `--accent-ink` | `#9BF0C3` | Text on `--accent-soft`, links, focus outline, button hover |
| `--warn` | `#FF7A66` | Declined / needs attention |
| `--warn-soft` | `#45201B` | Background behind `--warn-ink` text |
| `--warn-ink` | `#FFB3A7` | Text on `--warn-soft` |
| `--banner` | `#FFD76A` | Sandbox banner background, nothing else |
| `--banner-ink` | `#2A2100` | Sandbox banner text, nothing else |

**Font (D53):** **Geist Serif** (Vercel, OFL-1.1), weight 400 only, for all text. Fallbacks: Georgia, Times New Roman, serif. It isn't on Google Fonts yet, so `style.css` loads it with `@font-face` from jsDelivr, pinned to commit `d33068f` of [vercel/geist-font](https://github.com/vercel/geist-font) (`fonts/GeistSerif/webfonts/GeistSerif-Regular.woff2`, checked Oct 31: HTTP 200, `font/woff2`). Headings use size, not weight. Money amounts use the `.money` class (40px on a phone, 48px on a laptop).

**Contrast** (WCAG 2 formula, worked out Oct 31; AA needs 4.5:1 for text, 3:1 for a field's edge or a focus ring):

| Foreground on background | Ratio | Used for |
|---|---|---|
| `--ink` on `--bg` / `--surface` | 15.67 / 13.84 | Main text |
| `--ink-soft` on `--bg` / `--surface` | 8.05 / 7.11 | Secondary text, input borders |
| `--accent` on `--bg` / `--surface` | 9.90 / 8.74 | Accent text |
| `--accent-ink` on `--accent-soft` | 8.89 | "Counted" status word |
| `--accent-ink` on `--bg` / `--surface` | 13.37 / 11.81 | Links, focus outline |
| `--warn` on `--bg` / `--surface` | 7.03 / 6.21 | Warning text |
| `--warn-ink` on `--warn-soft` | 8.31 | "Declined" status word |
| `--banner-ink` on `--banner` | 11.54 | Sandbox banner |
| `--bg` on `--accent` / `--accent-ink` | 9.90 / 13.37 | Main button text, normal / hover |
| `--ink` on `--line` | 12.29 | Plain status word |
| `--ink-soft` on `--line` | 6.32 | Disabled button text |
| `--accent` on `--line` | 7.77 | Filled progress bar against the empty track |
| `--line` on `--bg` / `--surface` | 1.27 / 1.13 | Decorative borders only |

Every text pair passes AA, and every one except `--warn` on `--surface` (6.21) also passes AAA (7:1).

## 9. Sharing the link (D31)

- **Share button** on S2: uses the Web Share API where the browser has it, with a copy-link button as the fallback.
- **Static Open Graph tags** on the event link page (`og:title`, `og:description`, `og:image`): the same for every event, with no names or amounts. The description says it's a sandbox demo.
- **Wake the Render server before sharing the link.** Open the link once yourself first: the free server sleeps, and otherwise the link preview or the first friend may reach it asleep.

## 10. What each page receives (step 5b contract)

Added by Emmanuel on Oct 31 for step 5b (D54–D58). `app.py` passes exactly these values, and tests check that `board.json` has exactly these keys.

- Money and times arrive as finished text, so templates and JavaScript never format or add up money (§7, rule 2). The `dollars` filter (`{{ 4000|dollars }}` shows `$40.00`) is for a template that is given cents. No 5b page needs it.
- No page and no JSON ever gets an email or a `pledger_token`. Only S2 gets anything that contains the `admin_token`.
- Later milestones may add keys. They never rename one.
- Files: `create_event.html` (S1), `admin.html` (S2), `board.html` (S3) and `board_panel.html` (the board, shown on S2 and S3). All of them extend `base.html`. The bare versions are Emmanuel's, for Samuel to restyle.
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
| `banner_text` | text, from the table below | `"Pledging open: 9 min left"` |
| `goal_text` | text | `"Goal $310.01 so the club gets a full $300.00 after fees"` |
| `held_total_text` | text: HELD money only (D31, D43). It is `$0.00` after lock, because holds become charges | `"$120.00"` |
| `progress_percent` | a whole number from 0 to 100. It is 100 only when the goal is reached (D54), and 100 from `LAST_CALL` on (§5) | `39` |
| `pledging_open` | true or false: whether to show the link to `/e/<id>/pledge` | `true` |
| `rows` | a list in join order, with DROPPED pledges left out (D56) | |
| `rows[].name` | text | `"Ana"` |
| `rows[].status` | text, for styling only: `PENDING_PAY`, `HELD`, `DECLINED`, `CHARGED`, `FAILED` | `"HELD"` |
| `rows[].status_word` | text: `"Pledged"`, `"Held"`, `"Declined"`, `"Charged $28.33"`, or `"Charge failed"` *(placeholder)* | `"Held"` |
| `rows[].max_text` | text | `"$40.00"` |

| Event `status` | `banner_text` |
|---|---|
| `DRAFT` | "This event isn't open yet." *(placeholder)* |
| `OPEN` | "Pledging open: [time] left", with [time] like "1 h 5 min", "9 min" or "less than a minute" *(placeholder formats)* |
| `LAST_CALL` | "Last call! Goal reached. Join in the next [mm:ss] and everyone's share drops.", with [mm:ss] like "4:59", or "1:02:03" from one hour up *(placeholder format)* |
| `LOCKING`, `CHARGING` | "Locking shares…" |
| `SETTLED` | "Done! Club receives $[real net]". If PayPal's net is missing for any charge: "Charged once. PayPal closes the rest of each hold." (D54, D57) |
| `NEEDS_ATTENTION` | "Needs the treasurer's attention" |
| `EXPIRED` | "Cancelling holds…" while any hold of the event is still CREATED (D45), then "Goal not reached. Every hold was cancelled. Nobody paid." |
