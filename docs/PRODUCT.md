# Product

## One sentence

A group-payment app where everyone pledges what they'd pay, PayPal holds that money without taking it, and nobody is charged unless the group reaches its goal.

## The problem

A club needs a $300 cabin deposit. The group chat fills with "I'm in if Jay goes", "up to $40 maybe?", "wait are we still doing this?". One person, the treasurer, pays the deposit out of pocket and then chases everyone for weeks. When people back out, the treasurer eats the loss.

## Who it's for

- **Treasurer:** the one person in a small club (hiking club, study group, friend group) who usually fronts the money. Sets the goal, shares the link, watches the board. Under D31, the group-chat paste is deferred and the link gets a share button.
- **Pledgers:** club members. They tap a link in the group chat on their phone, pledge a maximum, and pay by card. No account needed (once the browser card test passes). Under D31, they type the pledge in their own words and confirm what the AI read before the card step.
- **No account to pledge: a friend gives a name, and an email only if they want to (D31).**

## The promise (use exactly this wording)

> **Nobody pays unless the goal is reached.**

The app guards the money, not the trip. It does not book the cabin or pay the venue. The treasurer's PayPal account receives the money and the treasurer decides what to do next.

## User stories (MVP first)

| # | As a... | I want to... | So that... | Milestone |
|---|---|---|---|---|
| U1 | treasurer | create an event with a deposit and a deadline | I can collect money for one plan | M1 |
| U2 | pledger | open a link and pledge a maximum with my card | I'm in without paying yet | M1 |
| U3 | anyone | see a live board with the goal, who's in, and progress | I know where things stand | M1 |
| U4 | treasurer | have everyone charged only their share once the goal is reached | the club gets the full deposit | M1 |
| U5 | pledger | have my hold cancelled if the goal is missed | I never pay for a plan that didn't happen | M1 |
| U6 | pledger | see my share drop when more people join during last call | bigger groups cost me less | M2 |
| U7 | pledger | say "actually I'm out" before last call | my hold is cancelled | M2 |
| U8 | treasurer | see "needs attention" if a charge fails, and choose what to do (the new pay link option waits on D28) | I'm never surprised by an automatic refund | M2 |
| U9 | pledger | pledge "only if Jay's in" | I only pay if my friend comes | M3 |
| U10 | pledger | type my pledge in my own words, then fix what the AI read before anything is saved (D31; replaces the treasurer chat paste) | I can say it the way I would in the chat, and nothing is saved until I confirm | M4 |
| U11 | judge | run a demo with short timers | I can see the whole flow in minutes | M5 |
| U12 | treasurer | share the event link with a share button, or copy it (D31) | friends get the link in the group chat | M4 |

## In scope

**MVP and must-haves:** everything in the table above.

**Stretch goals, cut items and future work** are listed in `docs/LATER.md`. Nothing there may be claimed as built.

## What we never claim

- That money goes to the cabin or venue.
- That a hold is "released instantly". Say "PayPal closes the rest of the hold."
- That a real capture decline was tested. Say "simulated".
- Any number, quote or user that isn't real.
