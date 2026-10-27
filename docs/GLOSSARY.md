# Glossary (plain words)

| Word | What it means here | Everyday example |
|---|---|---|
| **Hold** / **authorization** | PayPal sets money aside on someone's card without taking it | A hotel holding $100 on your card at check-in |
| **Capture** | Actually taking money from a hold. We capture only the person's share | Checkout: the hotel charges what you really spent |
| **`final_capture: true`** | "This is the last charge on this hold", so PayPal closes the rest | The hotel releases the unused part of the $100 |
| **Void** | Cancel a hold completely. Nothing is charged | You cancel the booking and the hold disappears |
| **Refund** | Give back money that was already charged. PayPal keeps its fee | A store refund that doesn't return the card fee |
| **Honor period** | The first 3 days of a hold, when capturing is most reliable | — |
| **Sandbox** | PayPal's practice system with fake money and test accounts | A flight simulator |
| **Order** | PayPal's container for one payment. We create one per pledge with intent `AUTHORIZE` | A shopping cart |
| **`PayPal-Request-Id`** | A unique ID we send with a request so a retry isn't treated as a new request | Writing a check number so the bank won't cash the same check twice |
| **Idempotent** | Doing it twice has the same effect as doing it once | Pressing a lift button twice |
| **Compare-and-set** | "Change the status to X only if it's still Y". Only one request can win | Two people grabbing the last slice: only one gets it |
| **Settle-on-wake** | Checking deadlines whenever a request arrives, because the free server sleeps | Checking the mailbox whenever you get home |
| **Counted** | A pledge that counts toward the goal: held and its conditions are met | — |
| **Circle** | Two or more people who each said "in if the other is in" | Ana: "if Jay goes". Jay: "if Ana goes" |
| **Fee-adjusted goal** | The goal raised just enough that the club still gets the full deposit after PayPal's fees | Adding the delivery fee so the restaurant still gets full price |
| **Cents (integer)** | We store $25.00 as `2500`, a whole number, to avoid rounding errors | — |
| **ACDC** | Advanced Credit and Debit Card Payments, the PayPal feature that enables card fields | — |
| **Webhook** | PayPal calling our server to tell us something happened. Not used in this project (see `docs/LATER.md`) | A delivery notification text |
| **Cold start** | The slow first load after the free server has been asleep | Starting a car on a cold morning |
