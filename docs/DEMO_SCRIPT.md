# Demo video script (about 2:30)

From the project plan (section 10), with the agreed corrections. Samuel edits the video. **A beat is filmed only after the tests in its "needs" column pass.** If a test doesn't pass, cut or change the beat. Never fake it.

## Rules for the whole video

- Under 3 minutes (judges don't have to watch past 3:00). Aim for 2:30.
- Uploaded to YouTube, **public**, link on the Devpost form.
- **SANDBOX DEMO** banner at the top of every screen. It scrolls away with the page (D87), so open each screen at the top.
- Fictional brands and people ("Ridgeline Hiking Club", "Pinecrest Cabins", Ana, Jay, Kofi, Bo, Mia, Dee). PayPal and Venmo marks only from PayPal's official brand assets, following their guidelines. Faces only from licensed stock photos or AI-generated people who don't exist, credited in the README. No other real logos, no real or famous people, no chat-app screenshots (D101, Emmanuel to confirm).
- No copyrighted music. Use no music, or a track you have permission to use.
- Open the live link a minute before recording, so the free server is awake.
- Shows the app running in a real browser on the device it was built for.

## Beats

| Time | Beat | On screen | Needs |
|---|---|---|---|
| 0:00–0:15 | **The problem** | A fictional group chat, labeled "fictional", where everyone says "I'm in" and nobody pays. Voiceover: "Group plans die when one person fronts the money. Last Call fixes that: nobody pays unless the goal is reached." | — |
| 0:15–0:45 | **Own words** (D31; the chat-paste beat is deferred) | The treasurer taps Share and sends the link (only if D31 must-have 4 shipped). A friend opens it and types "down if Jay goes, max 40". The AI shows amount, cap and condition; the friend fixes one and confirms. Caption: "AI reads. You confirm. Plain code handles the money." On screen: **"Accuracy on 50 made-up test messages: X/50"** (the real number only). | G1–G3 |
| 0:45–1:20 | **Pledging** | The pledge screen says "If the goal is met, you're in" **before** any hold. A pledger holds by card with no account. ⚠️ A second pledger pays with a PayPal account only if B4 passed. Otherwise film only card pledgers. The board shows the goal it calculated ("Goal $[x] so the club gets a full $300"). A decline test card shows "Card declined". Ana and Jay turn green together. If D31 must-have 6 shipped, a row goes Pledged → Hold pending → Held, and only held money moves the total. | B1, B2, D2 (B4 for the PayPal-account part) |
| 1:20–1:50 | **Last call** | The goal is reached and the last call countdown starts ("Demo mode: timers are minutes" badge visible). A late joiner gets in and the shares drop on screen. A counted person tries to leave and sees "You're counted, so you can't leave during last call." | E1, E3, E4 |
| 1:50–2:15 | **The money** | Shares lock and each person is charged once. "PayPal closes the rest of each hold." The board shows the club's **real net from PayPal's numbers**. Quick cut: a refused charge (labeled "simulated") marks the event "needs attention" and the treasurer chooses what happens. Quick cut: a missed goal, where every hold is cancelled and nobody pays. | B5, E5, F4 |
| 2:15–2:30 | **Close** | Three seconds of passing tests. "Everything shown runs in PayPal's sandbox. Untested parts are labeled in the README." Repo link. | — |

## What the judges will see (check the video against this list)

1. The sandbox banner on every screen.
2. The treasurer creates "Ridgeline Hiking Club cabin" ($300, demo mode) and copies the pledge link. S2's own address is never shown (it holds the `admin_token`, D59).
3. A friend types "down if Jay goes, max 40"; the AI fills in max $40 and the condition "Jay"; the friend confirms.
4. The card goes into PayPal's card fields, then "Held".
5. A decline test card shows "Card declined".
6. The board: the goal line (the goal that covers fees), progress bar, held total, "Waiting on Jay".
7. Jay pledges "in if Ana is"; both rows turn "Counted" together and the goal is reached.
8. The last-call banner with a 3-minute countdown; a late joiner pledges and every estimated share drops.
9. Last call ends, "Charging…", then the club's real net from PayPal and "Charged $x" per person.
10. A missed-goal event: every hold cancelled, nobody paid.
11. Only if E3, F7 and the D31 manual checks pass by Nov 8: the "can't leave during last call" message, a simulated refused charge with the refund-all confirm, quick-amount buttons, the Share button. Anything that doesn't pass is cut, not faked.

## Lines we never say

- "Sent to the cabin" or "pays the venue" (Payouts is cut).
- "Released instantly" (say "PayPal closes the rest of the hold").
- "We tested real capture declines" (they are simulated).
- "No signup needed", unless B1 passed.
- Any number, quote or user that isn't real.
