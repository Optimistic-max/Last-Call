# UI design

Owner: **Samuel**. Lives in `templates/` and `static/`. Plain HTML (Jinja), plain CSS, plain JS. No frameworks, no build step.

## 1. Who looks at what

- **Pledgers** open the link from a group chat **on their phone**. Design every pledger screen for a 375px-wide phone first.
- **The treasurer** is often on a laptop, but their screens must still work on a phone.
- **Judges** see it in a 2.5-minute video and may click the live link once. The board must explain itself in about 5 seconds.

## 2. Visual direction

- **Mood:** a friendly "last call" at a bar or campfire: warm, confident, a little playful. Not a bank.
- Black means "counted / goal reached", and one warning color means "declined / needs attention". Everything else is grey (D87).
- One font, Inter, for everything (D84, replaces D53's Geist Serif). Money amounts should be big and easy to read.
- Avoid the default look of a template: no generic hero gradient, no stock illustrations. Gradients are light, not paint, and follow the rules in §8 (D87).
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
| Who's in summary (D102) | **[n] in**, then one line: **[Name] just pledged**, **[Name] is counted** (or **[Name] and [Name] are counted**), **Everyone's in**, **[n] charged once** after the lock, and at page load **[Name] pledged most recently** |
| Who's in groups (D102) | **Counted (n)**, **Waiting on someone (n)**, **Pledged (n)**, **Charged (n)**, **Refunded (n)**, **Needs attention (n)**, **Not in (n)**. Empty groups are left out |
| Who's in row note and chip (D102) | the note: **Max $40.00** · **share now $31.05** · **Waiting on Bo** or **if Jay's in** (**if Jay and Kim are in**). The chip: **Counted**, **Waiting**, **Pledged**, **Held**, **Charged $x**, **Charge failed**, **Declined**, **Refunded** |
| Who's in, an opened row (D102) | **Jay's in** or **Waiting on Bo**, and **1 person is waiting on Ana** / **2 people are waiting on Ana** |
| Hold to confirm (D102) | under the button: **Press and hold to confirm**, **Hold to confirm** while held, **Confirmed**. Screen readers hear the label then **, press and hold to confirm** |
| Board and header buttons | **Pledge**, or **Join last call** during last call, and **Invite** |
| How it works card (S2, S3) | **Pledge the most you'd pay** · **PayPal holds it, nothing is charged** · **If the goal is reached, you pay only your share. If not, every hold is cancelled.** |
| S4 link to the board | **← Back to board** |
| S4 steps | **Say it your way**, **Check it**, **Hold it** |
| S4 box the AI filled | **Filled by AI, edit if wrong** |
| Landing headline | **Nobody pays** / **unless the goal is met.** (D85) |
| Landing button | **Start a pledge** |
| Landing "How it works" | **Pledge your max** · **You say the most you'd pay, even 'only if Jay's in'.** **PayPal holds it** · **Nothing is charged while the group fills up.** **Pay your share, once** · **If the goal is reached, you pay your part. If not, every hold is cancelled.** |
| Landing footer | **Built for the PayPal AI Hackathon. Sandbox only.** |
| S1 intro | **Start a pledge**, then **Get your group to actually chip in.** then **Friends pledge with their card. Nobody is charged unless the group reaches the goal; if it doesn't, every hold is cancelled.** then **PayPal holds each friend's max. AI turns 'I'm in for $40 if Jay's in' into a pledge, and they confirm it.** |
| S1 amount field | **How much does the group need? ($)** with the hint **$20 to $2,000** |
| S1 title example | **Ridgeline cabin weekend** |
| S1 demo-mode checkbox | **Demo mode: timers in minutes, not hours** |
| S2 share button | **Copy link**, or **Share** on a phone. It opens the share panel (D87) |
| Share panel title and note | **Invite friends**, then **They pledge with this link. Nobody pays unless the goal is reached.** |
| Share panel buttons | **Copy link**, then **Copied ✓**. **Send with**, then **Messages**, **WhatsApp**, **Telegram** and **Email**. Then **More apps** |
| Share panel tile names for screen readers | **Share on Messages**, **Share on WhatsApp**, **Share on Telegram**, **Share by email** |
| Share message, intro (Samuel's wording) | **Join our pledge for [event title]. Nobody pays unless we reach the goal.** |
| Share message, in full (Samuel's wording) | the intro, a space, then the link |
| Share email subject (Samuel's wording) | **Pledge for [event title]** |
| S2 share link | **Open in new tab** |
| Board, before pledging opens | **Invite opens when pledging starts** (not shown after an event ends, when it would be untrue) |
| Share buttons, if the browser can't copy | **Press and hold to copy**, above the link in a small field |
| 404 page | **This page doesn't exist.** and **Back to start** |
| 500 page | **Something went wrong on our side.** then **Nothing was charged.** and **Back to start** (the second line is for Emmanuel to confirm before it's wired up) |
| S2 private address warning | **This page's address is private. Share only the link above.** |
| S6 during last call | **You're counted, so you can't leave during last call.** |
| After lock | **Charged once. PayPal closes the rest of each hold.** |
| Missed goal | **Goal not reached. Every hold was cancelled. Nobody paid.** |
| Missed goal, while any hold of that event is still CREATED (D45) | **Cancelling holds…** (shown instead of the missed-goal line until no hold is CREATED) |
| Needs attention (treasurer, D92) | **Needs the treasurer's attention.** [Review refunds]. A failed local charge does not prove that PayPal captured nothing. |
| Refund-all confirm (D92; Samuel review pending) | **Each full refund returns that captured payment to its participant. PayPal keeps the original processing fees; they are not deducted from the participant's refund.** Show recorded fees or **Fee information unavailable.** Explain one new refund per explicit action. |
| Slow first load | **Waking up the app… (free hosting can take up to a minute)** |
| Demo mode badge | **Demo mode: timers are minutes, not hours**, in the countdown card on S2 and S3, only where `board.demo_mode` is true |
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

1. **The circle turns black together:** when Ana ("if Jay's in") and Jay ("if Ana's in") both become counted, their chips and avatars turn black at the same moment, 200ms, no stagger (D87).
2. **Share drops:** during last call, when someone joins, the old share slides up and fades as the new one slides in from below, 300ms. Both are the server's text, so JavaScript does no money math (D83, D84).
3. **Goal reached:** the half ring fills, the status card turns black with soft light, the countdown card starts its gentle pulse and its light drifts, and the main button becomes "Join last call".

Keep one-time animations under about 0.8 seconds and respect `prefers-reduced-motion`. The countdown's 2-second pulse and 8-second light drift are loops, and they stop under reduced motion.

The hero's idle float and scroll zoom are extra to these three moments, and they are off under reduced motion too (D85).

## 7. Basics

- Text contrast meets WCAG AA. Status is never shown by color alone (always a word too).
- Buttons are at least 44px tall on phones.
- **Never ask a friend for the same info twice (D31):** the name (and the email, if given) once, the pledge once. A retry after "Card declined" keeps everything they typed.
- The board refreshes every 10 seconds with a simple `fetch` to `GET /e/<id>/board.json` (no websockets).
- Show money as `$1,234.56` using one template filter. That filter must reuse `dollars()` from `app.py`, so the pages and the JSON messages always format money the same way. The JSON endpoint sends amounts already formatted, so JavaScript never does money math or formatting.

## 8. Final palette and fonts

**Look (D87, D100):** the clean black-and-white dashboard of D84 and D85, with light falling across it so it isn't flat. Greys, plus amber used as light (D100, below), and `--danger`. The copy stays warm and plain, so it never feels like a bank. The variables live on `:root` in `static/style.css`. A teal palette was tried and dropped on Nov 5.

| Variable | Value | Job |
|---|---|---|
| `--page` | `#F3F3F1` | Page background |
| `--card` | `#FFFFFF` | Cards |
| `--ink` | `#0B0B0B` | Main text, counted |
| `--ink-2` | `#5C5C5C` | Secondary text, captions, placeholders |
| `--ink-3` | `#8A8A8A` | Reserved. No text uses it, because it is too faint for small text |
| `--line` | `#E5E5E2` | Borders and dividers |
| `--held` | `#9A9A9A` | Held but not counted in the half ring, and the EXPIRED ring |
| `--on-ink` | `#FFFFFF` | Text on black |
| `--on-ink-2` | `#BDBDBD` | Quieter text on black |
| `--danger` / `--danger-bg` | `#B42318` / `#FDECEA` | Only Declined, Charge failed and Needs attention, always with a word |
| `--grey-50` to `--grey-300` | `#FAFAF9`, `#F3F3F1`, `#E8E8E5`, `#D9D9D5` | The light steps of the gradients |
| `--grey-800` / `--grey-900` | `#2A2A2A` / `#161616` | The dark steps of the gradients |

**Font:** Inter from Google Fonts, weights 400, 500, 600 and 800, with system-ui as the fallback. `tabular-nums` is on for the whole page, so money and times never jump.

| Style | Phone / laptop | Used for |
|---|---|---|
| Display | 40 / 56px, 600, -0.03em | Big numbers. In stat cards they shrink with the card (`cqi` units), so `$50,000.00` always fits |
| Title | 28 / 36px, 600, -0.02em | `h1` |
| Card title | 16 / 18px, 500 | Card headings |
| Body | 15 / 16px, 400, line height 1.5 | Text |
| Caption | 13px, 500 | Captions and chips |

Two sizes sit outside that scale on purpose: form labels (14px) and the status card's banner (24px, 600). The landing headline is the only style heavier than 600: 800, -0.045em, both lines in `--ink`, at most 72px (D87).

**Spacing and shape:** a 4px scale (4, 8, 12, 16, 20, 24, 32, 48, 64). Gutter 16 / 32px, card padding 20 / 24px, card gap 12 / 20px, content max-width 1280px. Cards are 24px round. Fields are 48px tall, 14px round, with 16px text so iPhones don't zoom. Buttons and chips are pills: 48px tall on phones, 44px on laptops. The 40px icon buttons have an invisible ring that makes the tap target 46px. Layout breakpoints are 768, 1024 and 1200px.

**Gradients (D87):** they are light, not paint.

- Greys, or amber as light (D100). Amber gradients have two stops, are radial and off-centre, and always have grain on top. No gradient text.
- Big, soft, off-center radial light. The two exceptions run straight down: a white card's very slight fade, and the primary button.
- Grain on every gradient, so it doesn't band: a noise SVG in `--grain`, at 3.5%. A white card fades by only five steps of grey, too little to band, so it skips the grain.
- No small text on the bright part of a gradient.
- **The page:** `--grey-100` with a white bloom from the top left, a light grey bloom toward the bottom right, and grain. All of it sits on one fixed layer, `body::before`, on every screen. iPhones ignore `background-attachment: fixed`, and one layer means one thing to get right.
- **Black cards** (the wallet's hero, and the status card in last call): `--grey-800` at the top left to `#0B0B0B` at the bottom right, with white light at 7% and grain.
- **No grid or line textures on the page (D87):** no dot grid and no ribbed lines on the page background or the hero. The blooms and the grain keep the background from looking flat. The half ring's still-needed stripes stay, because they carry meaning.
- **Ribbed black cards (D98):** the black cards (`.light-card`: the wallet's hero, plus the status card during last call) show `static/images/ribbed-dark.jpg` under a 60% dark layer (white text 6:1, quieter text `#E5E5E5` 4.7:1). With a mouse or trackpad, the ribs slide up to 14px against the pointer (a transform, 700ms ease-out) and a faint light follows it. `static/js/ribs.js` only reports where the pointer is. The light sits on the card's hover layer, above the picture and under the words, so it fades in and out with the hover shadow. Nothing moves on touch screens or with reduced motion.
- **Liquid glass header (D99):** only the landing page's sticky header bends what scrolls under it (SVG noise and displacement inside `backdrop-filter`), in Chrome-family browsers only. Safari and Firefox keep the frosted glass. Never on buttons, cards or anything with text behind it that must stay readable.

The black cards' light sits on `.card-bloom`, an empty element inside the card. It is a separate layer, so it can move without repainting the card.

**Depth (D85):** shadows are layered, soft and black only, never a colored glow. White cards have a 1px `--line` border, a white highlight along the top edge and `--shadow-rest`. Raised surfaces use `--shadow-raised`, the hero's pieces `--shadow-floating`, and hovered cards `--shadow-hover`, which sits on a layer that only fades, because animating `box-shadow` would repaint every frame.

**Buttons:** greyscale glass. The primary is a pill with a `#3A3A3A` to `#0B0B0B` gradient, a 1px border of white at 10%, a highlight along the top, white text and a soft dark shadow. Hover brightens it one step, and a press is `scale(0.97)`. Secondary buttons, icon buttons and the current menu item are frosted white: white at 65%, `blur(12px)`, a 1px border of black at 8%, a highlight along the top and black text. Hover takes them to white at 85%. The leave button is the same glass with `--danger` text. On a black card, the small round button is dark glass.

**Glass elsewhere (used sparingly):** the landing header and the phone's bottom action bar. Without `backdrop-filter`, or under `prefers-reduced-transparency`, glass becomes solid.

**Chips:** Counted and Charged are black with white text. Held is `--line` with black text. Pledged is a `--line` outline. Hold pending is a dashed outline. Waiting on is a black outline. Declined and Charge failed are `--danger-bg` with `--danger` text.

**Half ring:** the counted arc is `#0B0B0B`, and still-needed stripes are `#BDBDBD`. A held arc in `--held` waits for `held_percent`.

**Icons:** Lucide (ISC license, copyright notice in `templates/icons.html`), inline SVG, 20px, 1.5px line. **Logo:** `static/img/logo.svg` on light surfaces, and `logo-white.svg` on black cards. Both are Samuel's files, used as they are. **Favicon:** `static/img/favicon.svg` follows the browser's light or dark setting. A mask widens the mark's gaps slightly, because its thin lines blur at 16px. The two PNG icons were drawn from the logo.

**Hover, press and wiggle (D85):** hover effects apply only under `@media (hover: hover) and (pointer: fine)`. Cards lift 2px, buttons lift 1px, "Who's in" rows lighten and the avatar grows slightly, arrows lean 2px the way they point, and `.text-link` underlines slide in from the left. A press is `scale(0.97)` over 120ms. The wiggle (rotate -3, 3, -2, 1, 0 degrees over 450ms) is for the logo on hover, "Copied ✓", "Just pledged", and Invite once, 8 seconds after an empty board loads. A refused field shakes instead. Money, the countdown and status chips never wiggle.

**Sandbox banner (D87):** the one sandbox notice, at the very top of every page: 28px tall, `--grey-100`, 12px `--ink-2`, weight 500. It isn't sticky, so it scrolls away with the page, and only the landing's glass header stays at the top. There is no second notice under the hero button or in the sidebar. The browser's `theme-color` matches the banner.

**Demo mode badge (D87, D100):** an outlined label under the wallet's Time bar, the time it explains: white at 20% for the border, 12px `--ink-2`, weight 500. Its corners are 12px, not a pill, because the words can wrap to two lines. It appears from `board.demo_mode` in the template. That value never changes once an event exists, so `board.js` doesn't touch it.

**Amber light (D100):** amber is our third colour, used as light, as if a warm lamp lit a dark room. `--amber` `#F5B300`, `--amber-deep` `#B86E00`, `--amber-soft` (18%) and `--amber-glow` (35%).

- **Where it goes:** glows behind and under cards, a soft rim along a top edge, a vignette at the far edges of the dark pages (about 11%), the highlight on the one active thing, and the main action.
- **Where it never goes:** it is never the only way to show a status, because status stays a word plus black and white. It is never a flat fill on a large area, and never behind small text.
- **Primary buttons** keep their glass shape, with an amber rim light along the top edge and an amber glow under them on hover. The glow is on the layer that already fades in, so only opacity animates.
- **The one most important action** on each page is a solid amber pill with black words (`.button-amber`): Hold my max on the pledge page, Create on S1. On the board it is the wallet's Pledge card.
- **The menu:** on a phone, the page you're on keeps white words and gets an amber line that glows. On a laptop it is a white pill.
- **The half ring:** the counted arc goes from white to amber along the stroke. The still-needed stripes stay grey, and the legend words stay.
- **Landing page:** its own look, with a warm amber glow under the logo tile.

**Dark pages (D100):** S2, S3 and the pledge page are near-black `#0A0A0A` with the amber vignette and grain (`body.page-dark`). The tokens turn around there, so cards, chips and lines follow: cards `#141414` with 32px corners, `--ink` `#F5F5F3`, `--ink-2` `#A6A6A2`, `--danger` `#FF8A7A` on a solid `#3A1F1B`. The Counted chip becomes white with black words. The pledge form stays a light card, because PayPal draws its card fields in its own frames with dark text. The sandbox banner is `#121212`, and the browser's `theme-color` matches it.

**The wallet (D100):** the top of the board on S2 and S3. On a phone:

- **The hero card** is black, with 32px corners, the ribbed picture under its 60% dark layer, and amber light from its bottom edge. It shows a small "Held so far" label ("Charged" after the lock, D97), then the amount, 56px at most, 600, tabular, centred, with a small "USD". Under that come the caption and a "Goal $310.01" pill, which shows only when `goal_amount_text` arrives.
- **The time** is a small pill at the top right ("Time left 0:08:59", "Last call 2:58", or "Closed"). In last call an amber ring pulses gently around it.
- **The people row** sits at the bottom of the hero: a 56px white round "+" (Invite, which opens the share panel), then up to four overlapping 48px faces and "+N". The faces show initials, because there are no photos yet (D101). Counted people get a thin amber ring and waiting people are dimmed. The row links to Who's in.
- **The Pledge card** peeks out 56px under the hero, wallet-style: an amber gradient with grain and the words "+ Pledge" in black. It is the real Pledge link (`pledge_link`), hidden while pledging is closed.
- **Under the stack**, amber light spreads onto the page. It breathes on an 8-second loop during last call only.
- **Two thin bars** with their words under them. Counted is `progress_percent`, with "$counted of $goal" when both texts arrive, else the percent. Time is `seconds_left` out of `window_seconds`, which shows only when the server sends that key.

On a laptop the menu is a row of pills across the top, and the header's share buttons are round icon buttons. The wallet sits on the left at 440px at most, with the three totals and Progress to its right. The status card and How it works come next, then Who's in at full width.

**Who's in (D102):** the card is laid out like a guest list. Behind it: the dark base, two big soft blobs (amber and warm grey) drifting on a 20-second loop, and grain. Inside, a column 560px wide at most.

- **The summary** is a glass card: white at 8%, `blur(20px)`, 28px corners and a 1px border of white at 10%. It holds "[n] in", the faces in different sizes with the newest pledger biggest in the middle (up to eleven, then "+N"), and one line with the newest news. The line is `role="status"`, so it announces "Everyone's in" and new pledgers. The faces show initials until photos are allowed (D101).
- **The groups** are sentence case, never tiny capitals: Counted, Waiting on someone, Pledged, Charged, Refunded, Needs attention, Not in, each with its count. Empty groups are left out.
- **Each row** is its own pill: white at 7%, 18px corners, 64px tall at least, 8px apart, with no dividers. It shows the avatar (40px), the name (16px, 500), an italic grey note, the chip (an icon and a word), and a chevron when it opens. Counted is a white chip with black words and a thin amber ring. A failed charge is "counted" on the server, but it never gets the ring or the words "is counted".
- **Opening a row:** a row with dependencies (`board.links`, D96) is a button with `aria-expanded`. It opens in place to "Jay's in" or "Waiting on Bo", plus how many people wait on this person. This replaces Emmanuel's bare list of links, with the same data. The rows open stay open across refreshes.
- **Every refresh** rebuilds the groups in one step. A new face pops into the cluster (scale 0.6 to 1, 300ms) and a new row slides into its group. Rows that became Counted together slide there together (FLIP: 350ms, `cubic-bezier(0.23, 1, 0.32, 1)`), and their chips turn white at the same moment. When everyone is counted, the cluster glows amber for 1.2 seconds. With reduced motion nothing moves: the changes just appear.
- **Reduced transparency:** the summary and the rows become solid.

**Hold to confirm (D102):** a money button only acts after it is held for 800ms, so a stray tap can't send. It is used on Confirm refund everyone, Cancel this authorization and Hold my max. While the button is held, an amber ring beside the label fills, and letting go early drains it back and does nothing. Holding Enter or Space works the same. When the ring is full, a check shows, the action runs exactly once (a form is submitted, any other button gets one confirmed click), and the button switches off. It comes back only if the page turns it off and on again, as Hold my max does after a failed card. A line under the button says "Press and hold to confirm", "Hold to confirm" or "Confirmed". Without JavaScript the buttons work as normal buttons. With reduced motion the ring still fills, because it shows progress, but nothing bounces. Built in `static/js/hold.js` and the `hold_contents` macro.

**Wave hover (D102):** on secondary buttons and button-links (`.btn`), a wave rises from the bottom on hover or keyboard focus, and the words change colour. `--bink` is the wave and `--bsurf` the words on it: a dark wave on light pages, a light wave on dark pages and on dark pills, and amber on the white Join last call pill. Timing is `0.45s cubic-bezier(0.22, 1, 0.36, 1)`, transform and colour only. Hover only applies where a device can hover, and keyboard focus always raises the wave, with a 2px amber ring 4px out. It is never on the amber main action or on hold buttons. Disabled buttons get no wave. With reduced motion the wave appears at once.

**Motion (D100):** the hero lifts and the Pledge card slides 6px further out on hover. The amount crossfades when it changes, and a new face pops in (scale 0.9 to 1). Each is under 0.8 seconds, the breathing light excepted, and all of it is off with reduced motion.

**Landing page (D85):** it sits at the top of S1, on `GET /`. A sticky glass header, then a hero canvas with soft grey light, the logo tile, the headline, one button 32px under it, and six floating pieces (four on tablets, two on phones). Then `#how`, `#create` (the form) and the footer. The pieces are aria-hidden drawings of our own components, and every name and amount in them is made up. Scrolling the first 600px zooms past them. The tile reaches the header at 280px, because any later and the headline would scroll through it.

**Share panel (D87):** every Share, Invite and Copy link button opens one native `<dialog>`, so focus stays inside, Esc closes it, and focus returns to the button that opened it. It only ever holds `share_link` or the public pledge link, never the admin page's own address. On a phone it is a bottom sheet: it slides up in 300ms with a grab handle, and a drag down, a tap on the dim area or the close button closes it. From 768px it is a centered 420px dialog that rises 8px and fades in over 200ms. The dim area is black at 35% with a 2px blur. The tiles are 56px frosted circles with a line icon and a word, never a brand's logo or color, and they fade in 30ms apart. Messages shows only on touch screens, and More apps only where the browser has `navigator.share`. WhatsApp, Telegram and Email open in a new tab, so a web service can't replace the page. Messages doesn't, because it only hands over to a phone's app. Under reduced motion the panel fades instead of sliding. The page behind it stays still while it is open.

**Contrast** (AA needs 4.5:1 for text and 3:1 for large text). Measured Nov 5 in Chrome, at 1440 and 390px, from rendered pixels, against the worst background pixel behind each piece of text:

| Text on background | Lowest ratio | Used for |
|---|---|---|
| White on a black card's lightest part | 11.37 | Titles and numbers on black cards, last call status |
| `--on-ink-2` on a black card | 7.64 | Captions on black cards, the demo mode badge |
| White on the primary button | 13.77 | Primary buttons |
| `--ink` on frosted glass | 18.53 | Secondary buttons, also with a black card under the phone's action bar |
| `--ink-2` on the page's darkest part | 5.86 | The line under the page title |
| `--ink-2` on `--grey-100` | 6.02 | The sandbox banner |
| `--ink-2` on a white card | 6.40 | Captions, placeholders |
| `--ink-2` on the share panel | 6.57 | The panel's note |
| `--danger` on `--danger-bg` | 5.75 | Declined, Charge failed |
| `--ink` or white on a chip | 19.68 | The black and outlined chips |

Worked out from the values, not measured, and below the 3:1 for graphics: `--line` on white is 1.26:1 and `--held` on white 2.81:1, so a field's label and the ring's words and number carry the meaning.

## 9. Sharing the link (D31)

- **Share panel** on S2 and S3 (D87, §8): copies the link, or sends it with Messages, WhatsApp, Telegram or Email. **More apps** uses the Web Share API where the browser has it.
- **Static Open Graph tags** on the event link page (`og:title`, `og:description`, `og:image`): the same for every event, with no names or amounts. The description says it's a sandbox demo.
- **Wake the Render server before sharing the link.** Open the link once yourself first: the free server sleeps, and otherwise the link preview or the first friend may reach it asleep.

## 10. What each page receives (step 5b contract)

Added by Emmanuel on Oct 31 for step 5b (D54–D58). `app.py` passes exactly these values, and tests check that `board.json` has exactly these keys.

- Money and times arrive as finished text, so templates and JavaScript never format or add up money (§7, rule 2). The `dollars` filter (`{{ 4000|dollars }}` shows `$40.00`) is for a template that is given cents. No 5b page needs it.
- No page and no JSON ever gets an email or a `pledger_token`, except the friend's own S6 page and the link on their own pledge page (D82), which carry their own token. Only S2 gets anything that contains the `admin_token`.
- Later milestones may add keys. They never rename one.
- Files: `create_event.html` (S1), `admin.html` (S2), `board.html` (S3) and `board_panel.html` (the board). `board_panel.html` is included by S2 and S3; the others extend `base.html` (D76). `macros.html` holds shared pieces and `icons.html` the icons. `create_event.html` replaces `base.html`'s whole `shell` block and keeps the banner (D85). `404.html` and `500.html` are ready for `app.errorhandler`.
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
| `charged_total_text` | finished money text (D97): from the lock on (`SETTLED`, `NEEDS_ATTENTION`, `REFUNDING`, `REFUNDED`) the sum of the event's saved charges, counting `COMPLETED` and `REFUNDED` captures. `"Total being checked"` (placeholder) when any capture or payment record is unresolved: never `$0.00` for that. `""` at every other status, where the first card stays "Held so far" | `"$32.33"` |
| `refunded_total_text` | finished money text (D97): the sum of refunds PayPal has confirmed, or `""` when there are none (or while the total is being checked) | `"$21.55"` |
| `progress_percent` | a whole number from 0 to 100. It is 100 only when the goal is reached (D54), and 100 from `LAST_CALL` on (§5) | `39` |
| `demo_mode` | true while the event runs on minute timers. Shows the demo mode badge | `true` |
| `window_seconds` | **Not sent yet (wanted for the wallet's Time bar, D100).** The length of the window `seconds_left` counts down: the pledging window during OPEN, the last call during LAST_CALL. Without it the Time bar shows only its words | `600` |
| `pledging_open` | true or false: whether to show the link to `/e/<id>/pledge` | `true` |
| `links` | a list of who depends on whom (D96), one per saved condition, at most `MAX_CONDITIONS` (3) per pledger, in join order then saved order; `[]` when nobody has a condition. Sent in every status. DROPPED pledges are never a `from` (D56) | |
| `links[].from` | text: the pledger's name as the board shows it | `"Ana"` |
| `links[].to` | text: the person they need. Spelled as the board shows them if they have a row, otherwise the saved name tidied (the same name "Waiting on …" uses). A name nobody pledged, or who left, is just a target | `"Jay"` |
| `links[].met` | true or false: `to` has a row the board marks counted (the rows' `counted`), so it follows the rows. A circle (Ana ⇄ Jay) is two links, one each way; if one of them is not counted, both are false | `true` |
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


## F7 Stage 3 private refund interface (D92)

Emmanuel implemented the approved security flow; Samuel's visual and wording review is pending. Existing shared styles are reused. D93 adds one small script, `static/js/refund_preflight.js`; board.js is unchanged.

S2 links to /admin/<admin_token>/refund-access only for NEEDS_ATTENTION, REFUNDING or REFUNDED. That link alone grants no refund permission. The independent club key unlocks a 15-minute event-scoped session. Subsequent private pages use /admin/events/<event_id>/refunds (progress) and /refunds/confirm (confirmation). They display recorded captured payments, never held maximums or estimated shares. Known original fees are displayed; missing fees say "Fee information unavailable."

The confirmation explains full participant refunds, retained original processing fees, authorization verification/cancellation, irreversibility and one new refund per action. POST /refunds/start confirms. Each subsequent POST /refunds/continue needs an explicit Continue refunding action. GET/refresh never sends, reconciles or resumes a payment. POST /refunds/<refund_id>/check permits PayPal GET only for a known eligible pending refund. No retry or maintenance controls exist.

Per-payment words distinguish Not sent yet, Request started/result not confirmed, PayPal processing, PayPal-confirmed Refunded, failed/cancelled requiring review, Result unknown, and Maintenance status check required. Per-person completion requires all recorded payments to agree and no local accounting blockers. D47 captured money, missing records and unresolved authorizations get investigation messages; no missing payment amount is invented. A resolved zero-capture event explicitly says no captured payments required refunds. Public board additions are only generic Refunding/Refunded status words; private request IDs and recovery diagnostics are excluded.

The new templates are refund_access.html, refund_confirm.html, refund_status.html and the private refund_people.html partial. The only automatic action is the read-only preflight (D93); no money command is ever sent automatically. Double-click correctness comes from database claims, rather than JavaScript. Keyboard/mobile layout and actual browser behavior remain NOT RUN.

### D93 changes to the refund review (Samuel review pending)

- The confirm page now works in three steps: (1) **Checked N of M authorizations**, where a small script (or the "Check next authorization" button without JavaScript) reads one authorization per request; (2) an **Open authorizations** list, each with a "Review and cancel" link to its own page, "Cancel this authorization", which names the person and amount and cancels only that hold; (3) "Confirm refund everyone", which appears only when every hold is checked and none is open. Placeholder wording (D57) until Samuel approves it.
- The captured-payments line reads "Recorded captured payments: incomplete records, total unknown" when any payment record is missing or unresolved. It never shows $0.00 for that case.
- New template `refund_cancel.html`. Real browser, keyboard and phone behaviour is NOT RUN.

### D94 changes to the refund review (Samuel review pending)

- A payment whose refund is frozen (no final result, sender gone, PayPal refund id saved) shows a **Check with PayPal** button and one line: "This only asks PayPal what happened to this refund. It never sends money and never starts a new refund."
- If PayPal has no final answer the page says so and nothing changes; if it reports failed or cancelled it says "review required".
- A frozen payment with no saved PayPal refund id shows: "No PayPal refund id was saved, so this cannot be checked here. Nothing was changed: a developer must investigate." No button.
- Placeholder wording (D57) until Samuel approves it. Real browser and phone behaviour is NOT RUN.

### S6 receipt (D95, Samuel review pending)

Once the event is charging or finished, S6's `leave-message` is the friend's receipt, and there is no leave button. Placeholder texts (D57), from `RECEIPT_TEXTS` in `app.py`:

| What happened | Text |
|---|---|
| paid (also shows the money trail) | "You paid $X (your max was $Y). Nobody paid more than their max." |
| refunded | "You were charged $X, and it was refunded in full." |
| refund in progress | "You were charged $X. Your refund is in progress." |
| refund failed or cancelled | "You were charged $X. The treasurer is looking into your refund." |
| card couldn't be charged | "Your card couldn't be charged, so you paid nothing. The treasurer has been told." |
| not charged, hold cancelled / being cancelled / never held | "You weren't charged. Your hold was cancelled." / "... Your hold is being cancelled." / "You weren't charged." |
| goal not reached (the same three) | "The goal wasn't reached, so nobody paid. Your hold was cancelled." / "... Your hold is being cancelled." / "The goal wasn't reached, so nobody paid." |
| locking or charging | "Shares are being charged now. Check back in a minute." |
| anything the records can't prove | "We're checking what happened to your payment. The treasurer has been told." |

**Money trail (paid only):** an `<ol class="money-trail">` with three `money-trail-step` items, "Held $max", "→ Charged $paid", "→ Released $released" (the arrows are `money-trail-arrow`, hidden from screen readers). Bare markup, no styling yet: stack the steps vertically on phones.

**Back link:** every S6 page now ends with "← Back to board" (`back-to-board-link`) to `/e/<id>`. Real browser and phone look: NOT RUN.

#### `links` and the fallback list (D96, Samuel to draw and style)

`links` is names and a flag only, with no ids or tokens. The end of a chain matches "Waiting on …" (D79): follow the links from an uncounted held person through held-but-uncounted people to names nobody holds for. Placeholder fallback in `board_panel.html` (inside the "Who's in" card, shown only when `links` is not empty): `<ul class="board-links">` with one `<li class="board-link" data-met="true|false">` per link, "Ana → Jay ✓" or "Bo → Cy (waiting)". Keep the data the same when you restyle or replace it. It is drawn at page load only, so redraw a diagram from `board.json` on each 10-second refresh; names are user text, so always use `textContent`, never `innerHTML`. On phones a list (or stacked chips) is the fallback for the diagram.

#### The first card after the lock (D97, Samuel to restyle)

While `charged_total_text` is `""` the first card is "Held so far" with `held_total_text`, as before. Once it is not empty, the card's label becomes "Charged", the value is `charged_total_text`, and the caption is "Refunded $X" when `refunded_total_text` is not empty, otherwise "Charged once." (placeholders, D57). `held_total_text` keeps meaning HELD money only (so it is `$0.00` after the lock). The same choice is made in `templates/board_panel.html` (page load) and `static/js/board.js` `showStats` (every refresh, `textContent` only). Hooks to keep: `board-held-title`, `board-held-total`, `board-held-caption`. "Total being checked" is a value, not a number: do not format it as money.
