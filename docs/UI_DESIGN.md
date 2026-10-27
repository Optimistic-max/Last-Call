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
| S2 | Treasurer view | `/admin/<token>` | M1 | the share link (copy button), "Open pledging", the board, needs-attention actions (M2) |
| S3 | Board (public) | `/e/<id>` | M1 | goal, progress bar, who's in, time left, status banner |
| S4 | Pledge | `/e/<id>/pledge` | M1 | name, max, the promise text, PayPal card fields, "Hold my max" |
| S5 | Pledge result | same page | M1 | "Held", "Card declined", "Pledging closed", or an error |
| S6 | I'm out | `/p/<token>` | M2 | "Cancel my pledge" or the "can't leave during last call" message |
| S7 | Paste chat + confirm cards | `/admin/<token>/setup` | M4 | paste box, privacy note, editable cards, follow-up questions |

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
| S3 goal line | **Goal $[goal] so the club gets a full $[deposit] after fees** |
| S3 last call banner | **Last call! Goal reached. Join in the next [mm:ss] and everyone's share drops.** |
| S6 during last call | **You're counted, so you can't leave during last call.** |
| After lock | **Charged once. PayPal closes the rest of each hold.** |
| Missed goal | **Goal not reached. Every hold was cancelled. Nobody paid.** |
| Needs attention (treasurer) | **[Name]'s charge didn't go through. The others were charged. Choose what to do:** [Send [Name] a new pay link] [Refund everyone] |
| Refund-all confirm | **Refunding returns everyone's money, but PayPal keeps its fees ($[fees]). This can't be undone.** |
| Slow first load | **Waking up the app… (free hosting can take up to a minute)** |
| Demo mode badge | **Demo mode: timers are minutes, not hours** |
| AI paste screen | **AI reads. You confirm. Plain code handles the money.** and **This text is sent to [provider] to read it. Don't paste anything private.** |

The [Send [Name] a new pay link] button in the "Needs attention" wording waits on D28.

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

Each pledger row shows: name · status chip (Held / Counted / Waiting on [name] / Declined / Charged $[share]) · max. Conditions show as "if Jay's in".

## 6. The three moments the video needs (simple CSS only)

1. **Circle turns green together:** when Ana ("if Jay's in") and Jay ("if Ana's in") both become counted, their two rows flash to the accent color at the same time.
2. **Share drops:** during last call, when someone joins, each share number counts down from the old value to the new one (about 600ms).
3. **Goal reached:** the progress bar fills and the last call banner slides in.

Keep animations under about 0.8 seconds and respect `prefers-reduced-motion`.

## 7. Basics

- Text contrast meets WCAG AA. Status is never shown by color alone (always a word too).
- Buttons are at least 44px tall on phones.
- The board refreshes every 10 seconds with a simple `fetch` to `GET /e/<id>/board.json` (no websockets).
- Show money as `$1,234.56` using one template filter. The JSON endpoint sends amounts already formatted, so JavaScript never does money math or formatting. For the share-drop animation, it also sends the old and new values in cents.

## 8. Final palette and fonts

_Samuel fills this in._
