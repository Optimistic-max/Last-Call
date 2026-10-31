# UI design

Owner: **Samuel**. Lives in `templates/` and `static/`. Plain HTML (Jinja), plain CSS, plain JS. No frameworks, no build step.

## 1. Who looks at what

- **Pledgers** open the link from a group chat **on their phone**. Design every pledger screen for a 375px-wide phone first.
- **The treasurer** is often on a laptop, but their screens must still work on a phone.
- **Judges** see it in a 2.5-minute video and may click the live link once. The board must explain itself in about 5 seconds.

## 2. Visual direction

- **Mood:** a friendly "last call" at a bar or campfire: warm, confident, a little playful. Not a bank.
- Pick **one** strong accent color for "counted / goal reached" and one warning color for "declined / needs attention". Everything else is neutral.
- One display font for numbers and headings, one plain font for text. Money amounts should be big and easy to read.
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
| S4 name left blank | **Type your name.** |
| S4 max under $5 | **The smallest max is $5.00.** |
| S4 the same name already holds (D26) | **[Name] has already pledged.** |
| Declined card, on the friend's own link (D31) | **Your card was declined, so nothing is held and you're not counted yet. Try another card.** |
| S3 goal line | **Goal $[goal] so the club gets a full $[deposit] after fees** |
| S3 last call banner | **Last call! Goal reached. Join in the next [mm:ss] and everyone's share drops.** |
| S6 during last call | **You're counted, so you can't leave during last call.** |
| After lock | **Charged once. PayPal closes the rest of each hold.** |
| Missed goal | **Goal not reached. Every hold was cancelled. Nobody paid.** |
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

Each pledger row shows (never the email, which never appears on the public board or in `board.json`, D31): name · status chip (Held / Counted / Waiting on [name] / Declined / Charged $[share]) · max. Conditions show as "if Jay's in".

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

_Samuel fills this in._

## 9. Sharing the link (D31)

- **Share button** on S2: uses the Web Share API where the browser has it, with a copy-link button as the fallback.
- **Static Open Graph tags** on the event link page (`og:title`, `og:description`, `og:image`): the same for every event, with no names or amounts. The description says it's a sandbox demo.
- **Wake the Render server before sharing the link.** Open the link once yourself first: the free server sleeps, and otherwise the link preview or the first friend may reach it asleep.
