# AI pledge reader

Owner: **Malama**. Lives in `ai_parser.py`. Milestone **M4**. No parser code before M4; first, Malama chooses the model (D15) before Oct 29.

> **D31 (APPROVED, Oct 26): own-words pledge flow.** This page describes it. Each friend types their own pledge on the event link page, and the AI reads that one message. The treasurer chat paste is deferred (`docs/LATER.md`).

## 1. Job

Turn one friend's own-words message into a **suggested** pledge: amount, cap and condition. The friend sees an editable confirm step, can fix any of the three, and **nothing is saved until they confirm**: the parse result stays only in the page, and the pledge row is created at confirm. The AI never creates a hold, never charges, never decides a share. After the friend confirms, the card step is the B1 flow, unchanged.

Amount is the minimum (`min_dollars`, shown only, D12) and cap is the maximum held (`max_dollars`). Approved with D31.

On screen: **"AI reads. You confirm. Plain code handles the money."**

## 2. Input

The text one friend types into the pledge box on the event link page. One message per request, for example:

```
down if Jay goes, max 40
im in if ana is lol
$20 i guess
actually im out sorry
maybe??
```

The friend's name (required) and email (optional) come from the form fields, never from the AI, so nobody is asked for the same thing twice. Quick-amount buttons (D31) fill in an amount without typing; the friend still confirms.

## 3. Output (the model must return exactly this JSON)

For "down if Jay goes, max 40":

```json
{
  "status": "in",
  "max_dollars": 40,
  "min_dollars": null,
  "conditions": ["Jay"],
  "follow_up_question": null
}
```

For "maybe??":

```json
{
  "status": "unclear",
  "max_dollars": null,
  "min_dollars": null,
  "conditions": [],
  "follow_up_question": "Are you in? What's the most you'd pay?"
}
```

| Field | Allowed values |
|---|---|
| `status` | `"in"`, `"out"`, `"unclear"` |
| `max_dollars`, `min_dollars` | a number or `null` |
| `conditions` | list of names that must also be in (can be empty) |
| `follow_up_question` | text when `status` is `"unclear"` or the max is missing, otherwise `null` |

## 4. Plain-code validation (after the model answers)

Never trust the model's JSON directly. `ai_parser.validate_pledge(raw)` must:

1. Parse the JSON. If it doesn't parse, return a "please retype" result.
2. Drop unknown fields. Reject wrong types.
3. Convert dollars to cents with plain code and **no floats**: `int(Decimal(str(dollars)) * 100)`, only after checking the value is a number between 5 and 10,000 (TODO: source needed) with at most two decimals.
4. Any max under $5 means the card becomes `unclear` with "The minimum is $5. What's your max?".
5. Keep each condition as a name. It doesn't have to match anyone yet: the circle rule decides who is counted (D06), and the board shows "Waiting on [name]". (With one message there are no chat lines to check names or source lines against.)

If the model call fails or times out, show: **"Couldn't read that. Please retype it, or fill in the amount, cap and condition yourself."** The friend can always fill in the confirm step by hand.

## 5. Prompt rules (write in `ai_parser.py`)

- Say the output must be the JSON above and nothing else.
- Say: never guess an amount. If no number is stated, `max_dollars` is `null` and the card is `unclear`.
- Say: "I'm out", "can't make it", "nvm" mean `out`.
- Say: "if X goes", "only if X's in", "down if X" mean a condition on X.
- Say: "in for 20, up to 40 if we're short" means `min_dollars` 20, `max_dollars` 40.
- Say: if the message isn't about joining or paying, the status is `unclear`, with a follow-up question.
- Use a low temperature (or the model's most deterministic setting).

## 6. Privacy

Typing a pledge sends that text to a third-party AI service. The pledge page must say: **"What you type here is sent to [model provider] to read it. Don't type anything private."** For the demo, use only made-up pledges.

## 7. The 50-message accuracy test

- **Written and frozen by Grok Bot before Malama tunes the prompt**, so the person tuning isn't writing the exam. Saved as `tests/ai_test_messages.json` and never edited after it's frozen (record the freeze date in `docs/DECISIONS.md`).
- All messages are made up. The README says so.
- Under D31 each test message is read as one friend's own-words pledge. The categories and scoring stay the same; non-pledge chatter is expected back as `unclear` with a follow-up.

| Category | Count |
|---|---|
| Plain pledges ("I'm in, $30") | 10 |
| Slang ("bet, down for 25") | 8 |
| Named conditions ("only if Jay and Maya go") | 8 |
| Ranges ("in for 20, up to 40 if we're short") | 6 |
| Pull-outs ("actually I'm out") | 6 |
| Unclear, needs a follow-up ("maybe??") | 6 |
| Non-pledge chatter | 6 |
| **Total** | **50** |

**Scoring:** a message is right only if `status`, max, min and conditions all match exactly. For an unclear message, asking a follow-up counts as right. Report the score as **"X/50 on 50 made-up test messages"**.

**Honesty rule:** if the prompt changes after the first scored run, report **both** scores (before and after).

## 8. Model choice (OPEN, Malama decides)

Pick one free model. Record in `docs/DECISIONS.md`: model name, provider, free-tier limits (requests per minute and per day), whether typed text is used for training, and the date you checked.
